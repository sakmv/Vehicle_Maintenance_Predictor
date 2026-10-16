"""
Trains:
1. An XGBoost classifier for failure-risk probability
2. An Isolation Forest for anomaly detection on raw sensor patterns

Saves both models + feature list + metrics to disk for the FastAPI app to load.
"""
import json
import joblib
import numpy as np
import pandas as pd
from sklearn.model_selection import train_test_split
from sklearn.ensemble import IsolationForest
from sklearn.metrics import roc_auc_score, precision_score, recall_score, f1_score
from xgboost import XGBClassifier

df = pd.read_csv("sensor_data.csv")
FEATURES = [
    "mileage_km", "engine_temp_c", "rpm", "vibration_level",
    "oil_quality_pct", "brake_pad_mm", "battery_voltage",
    "coolant_level_pct", "vehicle_age_years",
]
X = df[FEATURES]
y = df["failure_risk"]

X_train, X_test, y_train, y_test = train_test_split(
    X, y, test_size=0.2, random_state=42, stratify=y
)

scale_pos_weight = (y_train == 0).sum() / (y_train == 1).sum()

clf = XGBClassifier(
    n_estimators=250,
    max_depth=4,
    learning_rate=0.05,
    subsample=0.9,
    colsample_bytree=0.9,
    scale_pos_weight=scale_pos_weight,
    eval_metric="auc",
    random_state=42,
)
clf.fit(X_train, y_train)

probs = clf.predict_proba(X_test)[:, 1]
preds = (probs >= 0.5).astype(int)

metrics = {
    "roc_auc": round(roc_auc_score(y_test, probs), 4),
    "precision": round(precision_score(y_test, preds), 4),
    "recall": round(recall_score(y_test, preds), 4),
    "f1": round(f1_score(y_test, preds), 4),
}
print("Classifier metrics:", metrics)

# Anomaly detector trained only on healthy (non-failure) examples
healthy = X_train[y_train == 0]
iso = IsolationForest(n_estimators=200, contamination=0.05, random_state=42)
iso.fit(healthy)

importances = dict(zip(FEATURES, clf.feature_importances_.tolist()))
importances = dict(sorted(importances.items(), key=lambda x: -x[1]))

joblib.dump(clf, "model_classifier.joblib")
joblib.dump(iso, "model_anomaly.joblib")
with open("feature_importance.json", "w") as f:
    json.dump(importances, f, indent=2)
with open("metrics.json", "w") as f:
    json.dump(metrics, f, indent=2)
with open("features.json", "w") as f:
    json.dump(FEATURES, f, indent=2)

print("Feature importances:", importances)
print("Saved model_classifier.joblib, model_anomaly.joblib, feature_importance.json")
