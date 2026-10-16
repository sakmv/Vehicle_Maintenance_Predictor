"""
Turns a rough free-text description of a vehicle problem into sensor values.

Two passes:
1. Symptom rules  - "overheating", "brakes grinding", "won't start" ... map to faulty
   sensor values. Words like "slightly" / "severely" pick mild / moderate / severe.
2. Explicit numbers - "temp 120", "battery 11.2v", "150k km", "brake pad 2mm" ...
   override whatever the symptom rules chose.
"""
import json
import logging
import os
import re
import time
import urllib.error
import urllib.request

try:
    from dotenv import load_dotenv
    load_dotenv()  # reads backend/.env if present
except ImportError:
    pass

try:
    import anthropic
except ImportError:  # AI mode simply stays off
    anthropic = None

log = logging.getLogger("diagnose")

# Sliders in the UI go 0..max, so clamp to these
LIMITS = {
    "engine_temp_c": 140, "rpm": 7000, "vibration_level": 1.0,
    "mileage_km": 300000, "oil_quality_pct": 100, "coolant_level_pct": 100,
    "brake_pad_mm": 20, "battery_voltage": 15,
}
# For these, a LOWER value is worse. For the rest, higher is worse.
BAD_LOW = {"oil_quality_pct", "coolant_level_pct", "brake_pad_mm", "battery_voltage"}

# set = {feature: (mild, moderate, severe)}
RULES = [
    {"label": "Overheating",
     "pattern": r"overheat\w*|running hot|runs? hot|too hot|temp(?:erature)?(?: gauge)? (?:is )?(?:high|spik\w+|rising|red)|steam\w*|boiling",
     "set": {"engine_temp_c": (104, 118, 132), "coolant_level_pct": (70, 50, 35)}},
    {"label": "Low coolant / leak",
     "pattern": r"coolant (?:is )?(?:low|leak\w*|empty|gone)|leak\w* coolant|coolant leak|radiator leak\w*|low on coolant",
     "set": {"coolant_level_pct": (40, 25, 10)}},
    {"label": "Vibration / shaking",
     "pattern": r"vibrat\w*|shak\w*|shudder\w*|rattl\w*|wobbl\w*|judder\w*|rough (?:idle|running)",
     "set": {"vibration_level": (0.2, 0.4, 0.7)}},
    {"label": "Engine stalling / misfire",
     "pattern": r"stall\w*|cuts? out|sputter\w*|misfir\w*",
     "set": {"vibration_level": (0.2, 0.3, 0.5)}},
    {"label": "Worn brakes",
     "pattern": r"brakes?\b.{0,25}?(?:squeal\w*|squeak\w*|grind\w*|worn|spongy|weak|soft|noisy|bad|failing)|(?:squeal\w*|squeak\w*|grind\w*).{0,25}?brake\w*|worn (?:out )?(?:brake|pads)|brake pads? (?:are |is )?(?:low|thin|gone)",
     "set": {"brake_pad_mm": (2.8, 1.8, 0.8)}},
    {"label": "Degraded oil",
     "pattern": r"oil (?:is )?(?:dirty|old|black|sludg\w*|degraded|low|burnt|burning|overdue)|(?:dirty|old|burning|burnt|low) oil|oil leak\w*|sludge|oil change (?:is )?(?:overdue|due)",
     "set": {"oil_quality_pct": (25, 15, 5)}},
    {"label": "Weak battery / won't start",
     "pattern": r"battery (?:is )?(?:dead|weak|low|failing|drain\w*|bad|old|flat)|(?:dead|weak|flat|bad) battery|slow crank\w*|(?:won'?t|wont|doesn'?t|does not|not) (?:start|crank)|dim (?:head)?lights?|hard (?:to )?start\w*",
     "set": {"battery_voltage": (11.9, 11.4, 10.6)}},
    {"label": "High RPM",
     "pattern": r"high rpm|revving|revs? (?:too )?high|rpm (?:is )?(?:high|spik\w+)|racing|engine races|over-?rev\w*|redlin\w*",
     "set": {"rpm": (4600, 5400, 6400)}},
    {"label": "High mileage",
     "pattern": r"high[- ]mileage|high[- ]km|well[- ]used|lots? of (?:km|miles|kilometers)|(?:very )?old (?:car|vehicle)|(?:car|vehicle) is (?:very )?old|ancient",
     "set": {"mileage_km": (110000, 160000, 230000)}},
]

SEVERE = r"very|severe\w*|extreme\w*|bad(?:ly)?|completely|totally|heavy|heavily|really|dangerously|critical\w*"
MILD = r"slight\w*|a bit|a little|little|mild\w*|somewhat|minor|occasional\w*"
NEGATION = r"\b(?:no|not|without|never|isn'?t|aren'?t|doesn'?t|don'?t)\b"

_N = r"(\d[\d,]*(?:\.\d+)?)"


def _f(s):
    return float(s.replace(",", ""))


def _level(text, start, end):
    window = text[max(0, start - 30):end + 30]
    if re.search(SEVERE, window):
        return 2
    if re.search(MILD, window):
        return 0
    return 1


def _merge(values, feat, val):
    """Keep the worse value if two symptoms touch the same sensor."""
    if feat not in values:
        values[feat] = val
    elif feat in BAD_LOW:
        values[feat] = min(values[feat], val)
    else:
        values[feat] = max(values[feat], val)


def _explicit_numbers(text):
    out = {}

    def grab(feat, pattern, conv=_f):
        m = re.search(pattern, text)
        if m:
            out[feat] = conv(m)

    grab("engine_temp_c", r"temp(?:erature)?\s*(?:is|at|of|reads?|=|:)?\s*" + _N + r"\b",
         lambda m: _f(m.group(1)))
    if "engine_temp_c" not in out:
        grab("engine_temp_c", _N + r"\s*(?:°|degrees?)\s*c?", lambda m: _f(m.group(1)))

    grab("rpm", _N + r"\s*rpm", lambda m: _f(m.group(1)))
    grab("battery_voltage", _N + r"\s*v(?:olts?)?\b", lambda m: _f(m.group(1)))
    grab("brake_pad_mm", r"(?:brake|pads?)[^.,;]{0,20}?" + _N + r"\s*mm", lambda m: _f(m.group(1)))
    grab("oil_quality_pct", r"oil[^.,;]{0,20}?" + _N + r"\s*%", lambda m: _f(m.group(1)))
    grab("coolant_level_pct", r"coolant[^.,;]{0,20}?" + _N + r"\s*%", lambda m: _f(m.group(1)))
    grab("vibration_level", r"vibration\w*\s*(?:is|at|of|=|:)?\s*(\d*\.\d+)", lambda m: _f(m.group(1)))

    m = re.search(r"(?:mileage|odometer)\s*(?:is|at|of|=|:)?\s*" + _N + r"\s*(k\b)?", text)
    if m:
        out["mileage_km"] = _f(m.group(1)) * (1000 if m.group(2) else 1)
    else:
        m = re.search(_N + r"\s*(k\b|kms?\b|kilomet\w+|miles?\b|mi\b)", text)
        if m:
            n, unit = _f(m.group(1)), m.group(2)
            if unit == "k":
                n *= 1000
            elif unit.startswith(("mile", "mi")):
                n *= 1.609
            out["mileage_km"] = n
    return out


def parse_issue_rules(query: str):
    text = query.lower().strip()
    values, matches = {}, []

    for rule in RULES:
        for m in re.finditer(rule["pattern"], text):
            if re.search(NEGATION, text[max(0, m.start() - 14):m.start()]):
                continue  # e.g. "no overheating"
            lvl = _level(text, m.start(), m.end())
            for feat, tiers in rule["set"].items():
                _merge(values, feat, tiers[lvl])
            matches.append({"label": rule["label"], "severity": ["mild", "moderate", "severe"][lvl]})
            break  # one hit per rule is enough

    explicit = _explicit_numbers(text)
    for feat, val in explicit.items():
        values[feat] = val
    if explicit:
        matches.append({"label": "Explicit values: " + ", ".join(explicit), "severity": "exact"})

    values = {k: round(max(0, min(LIMITS[k], v)), 2) for k, v in values.items()}
    return {"values": values, "matches": matches, "explanation": "", "source": "rules"}


# ----------------------------------------------------------------------------
# AI parser: understands any plain-English description of a vehicle problem.
# Needs ANTHROPIC_API_KEY in the backend environment; falls back to rules if
# the key is missing or the call fails.
# ----------------------------------------------------------------------------
MODEL = os.getenv("ANTHROPIC_MODEL", "claude-haiku-5-5")

SYSTEM_PROMPT = """You are a vehicle diagnostics assistant. The user describes a car problem in everyday English. Decide which sensor readings would most plausibly look abnormal given that description, and call set_sensors.

Sensors (unit, healthy range, hard limits):
- engine_temp_c (C, healthy 70-100, 0-140): higher is worse
- rpm (rpm, healthy 700-3500, 0-7000): higher is worse
- vibration_level (g, healthy 0-0.15, 0-1): higher is worse
- mileage_km (km, healthy 0-100000, 0-300000): higher is worse
- oil_quality_pct (%, healthy 40-100, 0-100): lower is worse
- coolant_level_pct (%, healthy 50-100, 0-100): lower is worse
- brake_pad_mm (mm, healthy 3-12, 0-20): lower is worse
- battery_voltage (V, healthy 12.0-14.5, 0-15): lower is worse

Rules:
- Only include sensors the description actually implicates. Leave all others out; they will stay at healthy defaults.
- Choose values that match the severity implied (slight/occasional = just outside healthy range, severe/dangerous = far outside). If the user gives an exact number or unit, use it exactly (convert miles to km, F to C).
- Use everyday-symptom reasoning, e.g. sweet smell or white smoke from the hood -> coolant low and/or temp high; pulls to one side or squeals when braking -> brake pad low; ticking or knocking with dark oil -> oil quality low; lights flicker, slow crank, clicking on start -> battery voltage low; steering wheel shakes or rough idle -> vibration high; engine races or revs by itself -> rpm high; "old car", "been driven a lot" -> mileage high. A symptom can implicate several sensors.
- If the description is not about a vehicle problem, or is too vague to implicate any sensor, return empty values and matches, and say so in the explanation.
- matches: one short label per diagnosed problem (e.g. "Worn brake pads") with severity mild, moderate, severe, or exact.
- explanation: one or two plain sentences on why you chose these readings."""

_SENSOR_PROPS = {k: {"type": "number"} for k in LIMITS}

TOOL = {
    "name": "set_sensors",
    "description": "Set the sensor readings that best represent the described vehicle problem.",
    "input_schema": {
        "type": "object",
        "properties": {
            "values": {"type": "object", "properties": _SENSOR_PROPS, "additionalProperties": False},
            "matches": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "label": {"type": "string"},
                        "severity": {"type": "string", "enum": ["mild", "moderate", "severe", "exact"]},
                    },
                    "required": ["label", "severity"],
                },
            },
            "explanation": {"type": "string"},
        },
        "required": ["values", "matches", "explanation"],
    },
}


def _finalize(query, data, source):
    """Validate/clamp whatever the model returned and shape the API response."""
    values = {}
    for k, v in (data.get("values") or {}).items():
        if k in LIMITS and isinstance(v, (int, float)) and not isinstance(v, bool):
            values[k] = v
    # Exact numbers the user typed always win over the model's guess
    values.update(_explicit_numbers(query.lower()))
    values = {k: round(max(0, min(LIMITS[k], v)), 2) for k, v in values.items()}

    matches = [m for m in (data.get("matches") or []) if isinstance(m, dict) and m.get("label")]
    if values and not matches:
        matches = [{"label": "Inferred from description", "severity": "moderate"}]
    if not values:
        matches = []
    return {"values": values, "matches": matches,
            "explanation": str(data.get("explanation", ""))[:400], "source": source}


def parse_issue_claude(query: str):
    client = anthropic.Anthropic(timeout=20.0, max_retries=1)
    resp = client.messages.create(
        model=MODEL,
        max_tokens=800,
        system=SYSTEM_PROMPT,
        tools=[TOOL],
        tool_choice={"type": "tool", "name": "set_sensors"},
        messages=[{"role": "user", "content": query}],
    )
    block = next(b for b in resp.content if b.type == "tool_use")
    return _finalize(query, block.input, "claude")


# ---- Gemini (free tier via Google AI Studio) -------------------------------

GEMINI_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "values": {"type": "OBJECT", "properties": {k: {"type": "NUMBER"} for k in LIMITS}},
        "matches": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "label": {"type": "STRING"},
                    "severity": {"type": "STRING", "enum": ["mild", "moderate", "severe", "exact"]},
                },
                "required": ["label", "severity"],
            },
        },
        "explanation": {"type": "STRING"},
    },
    "required": ["values", "matches", "explanation"],
}


_GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta"
_gemini_model_cache = {"name": None, "list": None}


def _gemini_headers():
    return {"Content-Type": "application/json", "x-goog-api-key": os.environ["GEMINI_API_KEY"]}


def _discover_gemini_models():
    """Ask Google which models this key can call; return Flash models, best first."""
    req = urllib.request.Request(f"{_GEMINI_BASE}/models?pageSize=200", headers=_gemini_headers())
    with urllib.request.urlopen(req, timeout=15) as r:
        models = json.load(r).get("models", [])
    cands = []
    for m in models:
        name = m.get("name", "").replace("models/", "")
        if "generateContent" not in m.get("supportedGenerationMethods", []):
            continue
        if "flash" not in name or any(x in name for x in ("image", "tts", "live", "audio", "exp", "robotics", "computer")):
            continue
        ver = re.search(r"(\d+(?:\.\d+)?)", name)
        cands.append((("preview" in name), ("lite" in name), -(float(ver.group(1)) if ver else 0), name))
    if not cands:
        raise RuntimeError("no Gemini flash model available to this key; available: "
                           + ", ".join(m.get("name", "") for m in models[:15]))
    cands.sort()
    return [c[3] for c in cands]


def _gemini_call(model, query):
    def build(with_thinking):
        cfg = {
            "responseMimeType": "application/json",
            "responseSchema": GEMINI_SCHEMA,
            "maxOutputTokens": 4096,   # thinking tokens count toward this, so leave headroom
            "temperature": 0.2,
        }
        if with_thinking and "argon" in model:
            cfg["thinkingConfig"] = {"thinkingLevel": "LOW"}  # simple task: keep it fast/cheap
        body = {
            "systemInstruction": {"parts": [{"text": SYSTEM_PROMPT.replace("call set_sensors", "return JSON")}]},
            "contents": [{"role": "user", "parts": [{"text": query}]}],
            "generationConfig": cfg,
        }
        return urllib.request.Request(f"{_GEMINI_BASE}/models/{model}:generateContent",
                                      data=json.dumps(body).encode(), headers=_gemini_headers(), method="POST")

    try:
        with urllib.request.urlopen(build(True), timeout=30) as r:
            payload = json.load(r)
    except urllib.error.HTTPError as e:
        if e.code != 400 or "argon" not in model:
            raise
        with urllib.request.urlopen(build(False), timeout=30) as r:   # thinking setting rejected
            payload = json.load(r)
    parts = payload["candidates"][0]["content"]["parts"]
    text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
    return json.loads(text)


_RETRYABLE = {429, 500, 502, 503, 504}  # busy / overloaded: worth retrying or trying another model


DEFAULT_GEMINI_MODEL = "gemini-3-flash"
_SKIP_TO_NEXT = _RETRYABLE | {400, 403, 404}  # model busy / not allowed for this key / not found


def gemini_model_order():
    """Models to try, best first (cached choice, env override, then discovered Flash models)."""
    if _gemini_model_cache.get("list") is None:
        try:
            _gemini_model_cache["list"] = _discover_gemini_models()
        except Exception as e:
            log.warning("Couldn't list Gemini models: %s", e)
            _gemini_model_cache["list"] = []
    preferred = _gemini_model_cache["name"] or os.getenv("GEMINI_MODEL") or DEFAULT_GEMINI_MODEL
    known = _gemini_model_cache["list"]
    if known and preferred not in known:
        # Allow short names: "gemini-3-flash" -> "gemini-3-flash-preview" if that's what Google lists
        match = [m for m in known if m.startswith(preferred) and "lite" not in m]
        preferred = match[0] if match else preferred
    order = [preferred] + [m for m in known if m != preferred]
    return order


def parse_issue_gemini(query: str):
    order = gemini_model_order()

    last_err = None
    for model in order[:4]:                     # at most 4 different models
        for attempt in range(2):                # 2 tries each if overloaded
            try:
                data = _gemini_call(model, query)
                _gemini_model_cache["name"] = model
                return _finalize(query, data, "gemini:" + model)
            except urllib.error.HTTPError as e:
                last_err = e
                if e.code in _RETRYABLE and attempt == 0:
                    time.sleep(1.0)
                    continue
                if e.code in _SKIP_TO_NEXT:
                    log.warning("Gemini model '%s' failed (HTTP %s); trying next", model, e.code)
                    break
                raise
    raise last_err or RuntimeError("Gemini unavailable")


def parse_issue(query: str):
    """Gemini (free) if GEMINI_API_KEY is set, else Claude if ANTHROPIC_API_KEY is set,
    else (or on any failure) the built-in keyword rules."""
    query = (query or "").strip()[:1000]
    attempts = []
    if os.getenv("GEMINI_API_KEY"):
        attempts.append(parse_issue_gemini)
    if anthropic is not None and os.getenv("ANTHROPIC_API_KEY"):
        attempts.append(parse_issue_claude)
    for fn in attempts:
        try:
            return fn(query)
        except Exception as e:  # network, auth, quota, bad output...
            log.warning("%s failed, trying next option: %s", fn.__name__, e)
    return parse_issue_rules(query)