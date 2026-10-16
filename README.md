# AutoGuard — AI-Powered Predictive Vehicle Maintenance

A predictive maintenance dashboard that estimates vehicle failure risk from live
sensor readings, explains *why* it made that prediction, and recommends what to
inspect — built on a real trained ML model, not a static form.

## Architecture

```
autoguard/
├── backend/          FastAPI service + ML models
│   ├── generate_data.py     synthetic sensor dataset generator
│   ├── train_model.py       trains classifier + anomaly detector
│   ├── app.py                API: POST /predict, GET /metrics
│   └── requirements.txt
└── frontend/          Next.js + TypeScript + Tailwind dashboard
    ├── app/page.tsx          main dashboard
    ├── components/
    │   ├── RiskGauge.tsx           automotive-style semicircular gauge
    │   └── FeatureContributions.tsx  bar chart of contributing sensors
    └── lib/api.ts             typed API client
```

## ML approach

**Features:** mileage, engine temperature, RPM, vibration, oil quality, brake
pad thickness, battery voltage, coolant level, vehicle age.

**Models:**
- `XGBClassifier` predicts failure probability (handles class imbalance via
  `scale_pos_weight`, since real failures are rare events)
- `IsolationForest` trained only on healthy examples flags sensor patterns
  that don't resemble any known-healthy vehicle, even if the classifier isn't
  confident about failure

**Explainability:** each prediction returns a per-feature contribution score
combining the model's global feature importance with how far *this specific
reading* deviates from a healthy reference range — so the dashboard can say
*why*, not just *what*.

**Current test performance:** ROC-AUC ≈ 0.83, recall ≈ 0.58 at the default
threshold (tuned to catch more true failures at the cost of some false alarms,
which is the right tradeoff for maintenance alerts).

## Running it

**Backend**
```bash
cd backend
pip install -r requirements.txt
python generate_data.py
python train_model.py
uvicorn app:app --reload --port 8811
```

**Frontend**
```bash
cd frontend
npm install
npm run dev
```

Set `NEXT_PUBLIC_API_BASE` if the backend isn't on `localhost:8811`.

## Future enhancements

- Real IoT sensor stream ingestion instead of manual entry
- SHAP values for per-prediction explainability instead of the current
  heuristic contribution score
- Historical trend view per vehicle (time-series of past readings)
- Model retraining pipeline as new labeled failure data comes in

## Author

Poja Shri J M — B.Tech Artificial Intelligence & Data Science
