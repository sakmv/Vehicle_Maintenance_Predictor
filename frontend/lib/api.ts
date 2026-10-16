const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8811";

export type SensorInput = {
  mileage_km: number;
  engine_temp_c: number;
  rpm: number;
  vibration_level: number;
  oil_quality_pct?: number;
  brake_pad_mm?: number;
  battery_voltage?: number;
  coolant_level_pct?: number;
};

export type PredictionResult = {
  failure_probability: number;
  risk_level: "Low" | "Moderate" | "High";
  anomaly_detected: boolean;
  anomaly_score: number;
  feature_contributions: {
    feature: string;
    value: number;
    healthy_range: [number, number];
    out_of_range: boolean;
    contribution_score: number;
  }[];
  recommendation: string;
};

export type ParsedIssue = {
  values: Partial<SensorInput>;
  matches: { label: string; severity: string }[];
  explanation?: string;
  source?: "ai" | "rules";
};

export async function predictFailure(input: SensorInput): Promise<PredictionResult> {
  const res = await fetch(`${API_BASE}/predict`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
  if (!res.ok) throw new Error(`Prediction request failed: ${res.status}`);
  return res.json();
}

export async function parseIssue(query: string): Promise<ParsedIssue> {
  const res = await fetch(`${API_BASE}/parse-issue`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ query }),
  });
  if (!res.ok) throw new Error(`Issue parsing failed: ${res.status}`);
  return res.json();
}

export type AIAction = { title: string; detail: string; timeframe: string };
export type AIExplanation = {
  summary: string;
  urgency: "Routine" | "Soon" | "Urgent" | "Stop driving";
  actions: AIAction[];
  source: string;
};
export type ChatTurn = { role: "user" | "assistant"; text: string };

export async function aiExplain(
  sensors: SensorInput,
  prediction: PredictionResult
): Promise<AIExplanation> {
  const res = await fetch(`${API_BASE}/ai/explain`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ sensors, prediction }),
  });
  if (!res.ok) throw new Error(`AI explain failed: ${res.status}`);
  return res.json();
}

export async function aiChat(
  sensors: SensorInput,
  prediction: PredictionResult,
  history: ChatTurn[],
  message: string
): Promise<{ reply: string; source: string }> {
  const res = await fetch(`${API_BASE}/ai/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ sensors, prediction, history, message }),
  });
  if (!res.ok) throw new Error(`AI chat failed: ${res.status}`);
  return res.json();
}

export type ForecastSeries = {
  feature: string;
  label: string;
  unit: string;
  scale: number; // multiply values by this for display (risk is 0..1 -> %)
  limit: number;
  bad_direction: "high" | "low";
  latest: number;
  points: [number, number][];
  status: "out_of_range" | "drifting" | "slow_drift" | "improving" | "stable" | "insufficient";
  slope: number | null;
  p_value: number | null;
  eta: number | null;
  eta_range: [number | null, number | null] | null;
  eta_date: string | null;
  fit: [number, number][] | null;
  projection: [number, number][] | null;
  message: string;
};

export type ForecastResult = {
  n: number;
  x_unit: "days" | "km" | "readings" | null;
  series: ForecastSeries[];
  summary: string[];
  message: string;
};

export type LogRow = Record<string, number | string>;

export async function forecastTrends(readings: LogRow[]): Promise<ForecastResult> {
  const res = await fetch(`${API_BASE}/forecast`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ readings }),
  });
  if (!res.ok) throw new Error(`Forecast failed: ${res.status}`);
  return res.json();
}