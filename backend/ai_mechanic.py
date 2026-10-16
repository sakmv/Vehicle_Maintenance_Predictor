"""
AI Mechanic: turns a prediction into a plain-English diagnosis + action plan,
and answers follow-up questions about that specific result.

Provider order (same as diagnose.py): Gemini -> Claude -> built-in template.
"""
import json
import logging
import os
import time
import urllib.error
import urllib.request

import diagnose
from diagnose import _GEMINI_BASE, _RETRYABLE, _SKIP_TO_NEXT, _gemini_headers, _gemini_model_cache, gemini_model_order

try:
    import anthropic
except ImportError:
    anthropic = None

log = logging.getLogger("ai_mechanic")

URGENCY = ["Routine", "Soon", "Urgent", "Stop driving"]

PERSONA = """You are an experienced, friendly vehicle mechanic explaining the output of a predictive-maintenance model to a car owner.
Rules:
- Ground every statement in the JSON data provided (sensor readings, healthy ranges, failure probability, anomaly flag). Never invent readings or fault codes.
- The failure probability is an estimate from a machine-learning demo model, not a certainty. Say so plainly when relevant.
- Plain language, no jargon without a short explanation. Be specific about which sensor and why it matters.
- Be honest about uncertainty. If readings look healthy, say so rather than inventing problems.
- Safety first: if brakes, overheating or battery readings are severely out of range, say clearly if driving is risky.
- Stay on vehicle topics. Politely decline anything else."""

EXPLAIN_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "summary": {"type": "STRING"},
        "urgency": {"type": "STRING", "enum": URGENCY},
        "actions": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "title": {"type": "STRING"},
                    "detail": {"type": "STRING"},
                    "timeframe": {"type": "STRING"},
                },
                "required": ["title", "detail", "timeframe"],
            },
        },
    },
    "required": ["summary", "urgency", "actions"],
}

EXPLAIN_TASK = (
    "Explain this result. Return JSON with: summary (2-3 sentences: overall risk, the main reason, what it means for the owner), "
    "urgency (one of Routine, Soon, Urgent, Stop driving), and actions (2-5 items ordered by priority, each with a short title, "
    "a one-sentence detail, and a timeframe such as 'Today', 'This week', 'Next service'). If nothing is out of range, give one or two "
    "routine-maintenance actions."
)

ADVICE = {
    "engine_temp_c": ("Check cooling system", "Inspect thermostat, radiator and fan; high engine temperature can cause serious engine damage."),
    "coolant_level_pct": ("Top up and check for coolant leaks", "Low coolant leads to overheating; look for leaks around hoses and the radiator."),
    "vibration_level": ("Diagnose the vibration", "Check engine mounts, wheel balance, belts and misfires to find the source."),
    "oil_quality_pct": ("Change engine oil and filter", "Degraded oil increases wear and heat inside the engine."),
    "brake_pad_mm": ("Inspect and replace brake pads", "Thin pads reduce stopping power and can damage the discs."),
    "battery_voltage": ("Test battery and alternator", "Low voltage causes hard starts and can leave you stranded."),
    "rpm": ("Check engine speed behaviour", "Abnormally high RPM can point to transmission slip, throttle or sensor faults."),
    "mileage_km": ("Review service history", "High mileage means wear items are due; check the service schedule."),
    "vehicle_age_years": ("Review age-related wear", "Older vehicles need more frequent inspections of rubber parts and fluids."),
}


# ---------------------------------------------------------------- context ---
def _context(sensors: dict, pred: dict) -> str:
    contrib = [c for c in (pred.get("feature_contributions") or []) if isinstance(c, dict)]
    out = [
        {"sensor": c.get("feature"), "value": c.get("value"), "healthy_range": c.get("healthy_range")}
        for c in contrib if c.get("out_of_range")
    ]
    try:
        pct = round(float(pred.get("failure_probability", 0)) * 100, 1)
    except (TypeError, ValueError):
        pct = None
    return json.dumps({
        "sensor_readings": sensors,
        "failure_probability_pct": pct,
        "risk_level": pred.get("risk_level"),
        "anomaly_detected": pred.get("anomaly_detected"),
        "out_of_range_sensors": out,
        "rule_based_recommendation": pred.get("recommendation"),
    })


# ------------------------------------------------------------- providers ----
def _gemini_text(system, turns, schema=None, max_tokens=2048):
    contents = [{"role": "user" if r == "user" else "model", "parts": [{"text": t}]} for r, t in turns]
    cfg = {"maxOutputTokens": max_tokens, "temperature": 0.4}
    if schema:
        cfg.update({"responseMimeType": "application/json", "responseSchema": schema})
    body = json.dumps({"systemInstruction": {"parts": [{"text": system}]}, "contents": contents,
                       "generationConfig": cfg}).encode()

    last_err = None
    for model in gemini_model_order()[:4]:
        for attempt in range(2):
            try:
                req = urllib.request.Request(f"{_GEMINI_BASE}/models/{model}:generateContent",
                                             data=body, headers=_gemini_headers(), method="POST")
                with urllib.request.urlopen(req, timeout=30) as r:
                    payload = json.load(r)
                parts = payload["candidates"][0]["content"]["parts"]
                text = "".join(p.get("text", "") for p in parts if not p.get("thought")).strip()
                if not text:
                    raise RuntimeError("empty Gemini response")
                _gemini_model_cache["name"] = model
                return text
            except urllib.error.HTTPError as e:
                last_err = e
                if e.code in _RETRYABLE and attempt == 0:
                    time.sleep(1.0)
                    continue
                if e.code in _SKIP_TO_NEXT:
                    break
                raise
    raise last_err or RuntimeError("Gemini unavailable")


def _claude_text(system, turns, json_hint=None, max_tokens=1200):
    if json_hint:
        system += "\n\nRespond with ONLY a JSON object, no markdown, shaped like: " + json_hint
    client = anthropic.Anthropic(timeout=25.0, max_retries=1)
    resp = client.messages.create(
        model=diagnose.MODEL, max_tokens=max_tokens, system=system,
        messages=[{"role": r, "content": t} for r, t in turns],
    )
    return "".join(b.text for b in resp.content if b.type == "text").strip()


def _llm(system, turns, schema=None, json_hint=None):
    """Return (text, source). Raises if no provider works."""
    errs = []
    if os.getenv("GEMINI_API_KEY"):
        try:
            return _gemini_text(system, turns, schema), "gemini"
        except Exception as e:
            log.warning("Gemini failed: %s", e)
            errs.append(e)
    if anthropic is not None and os.getenv("ANTHROPIC_API_KEY"):
        try:
            return _claude_text(system, turns, json_hint), "claude"
        except Exception as e:
            log.warning("Claude failed: %s", e)
            errs.append(e)
    raise RuntimeError(f"no AI provider available: {errs}")


def _parse_json(text):
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        text = text[text.find("{"):]
    return json.loads(text[text.find("{"): text.rfind("}") + 1])


# --------------------------------------------------------------- explain ----
def _template_explanation(sensors, pred):
    out = [c for c in (pred.get("feature_contributions") or []) if isinstance(c, dict) and c.get("out_of_range")]
    level = pred.get("risk_level", "Low")
    try:
        pct = float(pred.get("failure_probability", 0)) * 100
    except (TypeError, ValueError):
        pct = 0.0
    names = ", ".join(str(c["feature"]).replace("_", " ") for c in out[:3])
    if out:
        summary = (f"The model estimates a {pct:.0f}% failure risk ({level}). "
                   f"Readings outside the healthy range: {names}.")
    else:
        summary = f"The model estimates a {pct:.0f}% failure risk ({level}). No sensor is outside its healthy range."
    urgency = {"High": "Urgent", "Moderate": "Soon"}.get(level, "Routine")
    actions = []
    for c in out[:4]:
        title, detail = ADVICE.get(c["feature"], ("Inspect " + c["feature"], "Have this sensor checked."))
        actions.append({"title": title, "detail": detail,
                        "timeframe": "Today" if urgency == "Urgent" else "This week"})
    if not actions:
        actions = [{"title": "Continue routine servicing", "detail": "No issues detected; keep to the service schedule.",
                    "timeframe": "Next service"}]
    return {"summary": summary, "urgency": urgency, "actions": actions, "source": "template"}


def explain(sensors: dict, pred: dict):
    ctx = _context(sensors, pred)
    hint = '{"summary": str, "urgency": "Routine|Soon|Urgent|Stop driving", "actions": [{"title": str, "detail": str, "timeframe": str}]}'
    try:
        text, source = _llm(PERSONA, [("user", f"Data:\n{ctx}\n\n{EXPLAIN_TASK}")], EXPLAIN_SCHEMA, hint)
        data = _parse_json(text)
        urgency = data.get("urgency") if data.get("urgency") in URGENCY else "Soon"
        actions = []
        for a in (data.get("actions") or [])[:5]:
            if isinstance(a, dict) and a.get("title"):
                actions.append({k: str(a.get(k, ""))[:300] for k in ("title", "detail", "timeframe")})
        summary = str(data.get("summary", "")).strip()[:800]
        if not summary:
            raise ValueError("empty summary")
        return {"summary": summary, "urgency": urgency, "actions": actions, "source": source}
    except Exception as e:
        log.warning("AI explain failed, using template: %s", e)
        return _template_explanation(sensors, pred)


# ------------------------------------------------------------------ chat ----
def chat(sensors: dict, pred: dict, history: list, message: str):
    ctx = _context(sensors, pred)
    system = (PERSONA + "\n\nThe owner is asking follow-up questions about this specific result. "
              "Answer in under 120 words, plain text, no markdown headings.\n\nCurrent result data:\n" + ctx)
    turns = [(h["role"], h["text"]) for h in history[-8:] if h.get("text")]
    while turns and turns[0][0] != "user":
        turns.pop(0)
    turns.append(("user", message))
    try:
        text, source = _llm(system, turns)
        return {"reply": text, "source": source}
    except Exception as e:
        log.warning("AI chat failed: %s", e)
        return {"reply": "The AI assistant isn't available right now (no working API key, or the free quota is "
                         "used up). The summary above is based on the model's readings; try again in a minute.",
                "source": "unavailable"}