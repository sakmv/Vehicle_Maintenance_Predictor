import json
import joblib
import numpy as np
import pandas as pd
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Any, Literal
from pydantic import Field
from diagnose import parse_issue
import ai_mechanic
import forecast

app = FastAPI(title="AutoGuard Predictive Maintenance API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

clf = joblib.load("model_classifier.joblib")
iso = joblib.load("model_anomaly.joblib")
with open("features.json") as f:
    FEATURES = json.load(f)
with open("feature_importance.json") as f:
    GLOBAL_IMPORTANCE = json.load(f)
with open("metrics.json") as f:
    METRICS = json.load(f)

# Rough "healthy" reference ranges used to flag which sensor(s) look off
REFERENCE = {
    "mileage_km": (0, 100000),
    "engine_temp_c": (70, 100),
    "rpm": (700, 3500),
    "vibration_level": (0.0, 0.15),
    "oil_quality_pct": (40, 100),
    "brake_pad_mm": (3, 12),
    "battery_voltage": (12.0, 14.5),
    "coolant_level_pct": (50, 100),
    "vehicle_age_years": (0, 8),
}


class SensorInput(BaseModel):
    mileage_km: float
    engine_temp_c: float
    rpm: float
    vibration_level: float
    oil_quality_pct: float = 70.0
    brake_pad_mm: float = 8.0
    battery_voltage: float = 12.6
    coolant_level_pct: float = 85.0
    vehicle_age_years: float = None


@app.get("/")
def root():
    return {"status": "ok", "model_metrics": METRICS}


class IssueQuery(BaseModel):
    query: str


@app.post("/parse-issue")
def parse_issue_endpoint(body: IssueQuery):
    return parse_issue(body.query)


class ExplainRequest(BaseModel):
    sensors: dict[str, float]
    prediction: dict


class ChatTurn(BaseModel):
    role: Literal["user", "assistant"]
    text: str = Field(max_length=2000)


class ChatRequest(ExplainRequest):
    history: list[ChatTurn] = Field(default_factory=list, max_length=20)
    message: str = Field(min_length=1, max_length=1000)


@app.post("/ai/explain")
def ai_explain(body: ExplainRequest):
    return ai_mechanic.explain(body.sensors, body.prediction)


@app.post("/ai/chat")
def ai_chat(body: ChatRequest):
    return ai_mechanic.chat(body.sensors, body.prediction,
                            [t.model_dump() for t in body.history], body.message)


# Used to fill sensors missing from logged readings when scoring them with the classifier
RISK_DEFAULTS = {
    "mileage_km": 50000.0, "engine_temp_c": 90.0, "rpm": 2200.0, "vibration_level": 0.05,
    "oil_quality_pct": 70.0, "brake_pad_mm": 8.0, "battery_voltage": 12.6, "coolant_level_pct": 85.0,
}


def _risk_series(rows):
    recs = []
    for r in rows:
        d = {}
        for feat in FEATURES:
            try:
                v = float(r.get(feat))
                if not np.isfinite(v):
                    raise ValueError
            except (TypeError, ValueError):
                v = RISK_DEFAULTS.get(feat)
            d[feat] = v
        if d.get("vehicle_age_years") is None:
            d["vehicle_age_years"] = round(d["mileage_km"] / 15000, 1)
        recs.append(d)
    return clf.predict_proba(pd.DataFrame(recs)[FEATURES])[:, 1].tolist()


class ForecastRequest(BaseModel):
    readings: list[dict[str, Any]] = Field(max_length=2000)


@app.post("/forecast")
def forecast_endpoint(body: ForecastRequest):
    return forecast.run(body.readings, risk_fn=_risk_series)


@app.get("/metrics")
def metrics():
    return {"metrics": METRICS, "global_feature_importance": GLOBAL_IMPORTANCE}


@app.post("/predict")
def predict(sensor: SensorInput):
    data = sensor.dict()
    if data["vehicle_age_years"] is None:
        data["vehicle_age_years"] = round(data["mileage_km"] / 15000, 1)

    row = pd.DataFrame([{k: data[k] for k in FEATURES}])

    failure_prob = float(clf.predict_proba(row)[0, 1])
    anomaly_flag = int(iso.predict(row)[0] == -1)
    anomaly_score = float(-iso.score_samples(row)[0])  # higher = more anomalous

    # Per-request feature contribution: global importance weighted by
    # how far this reading sits outside the healthy reference range
    contributions = []
    for feat in FEATURES:
        lo, hi = REFERENCE[feat]
        val = data[feat]
        if val < lo:
            deviation = (lo - val) / max(lo, 1e-6)
        elif val > hi:
            deviation = (val - hi) / max(hi, 1e-6)
        else:
            deviation = 0.0
        deviation = min(deviation, 1.5)
        contributions.append({
            "feature": feat,
            "value": val,
            "healthy_range": [lo, hi],
            "out_of_range": deviation > 0,
            "contribution_score": round(GLOBAL_IMPORTANCE.get(feat, 0) * (1 + deviation), 4),
        })
    contributions.sort(key=lambda x: -x["contribution_score"])

    if failure_prob >= 0.6:
        risk_level = "High"
    elif failure_prob >= 0.3:
        risk_level = "Moderate"
    else:
        risk_level = "Low"

    top_issues = [c["feature"] for c in contributions if c["out_of_range"]][:3]
    if top_issues:
        recommendation = "Inspect: " + ", ".join(f.replace("_", " ") for f in top_issues)
    elif risk_level == "Low":
        recommendation = "No immediate action needed. Continue routine servicing."
    else:
        recommendation = "Schedule a general inspection; no single sensor is critically out of range."

    return {
        "failure_probability": round(failure_prob, 4),
        "risk_level": risk_level,
        "anomaly_detected": bool(anomaly_flag),
        "anomaly_score": round(anomaly_score, 4),
        "feature_contributions": contributions,
        "recommendation": recommendation,
    }