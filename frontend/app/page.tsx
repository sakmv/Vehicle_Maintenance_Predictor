"use client";

import { useState } from "react";
import RiskGauge from "@/components/RiskGauge";
import FeatureContributions from "@/components/FeatureContributions";
import AIMechanic from "@/components/AIMechanic";
import TrendForecast from "@/components/TrendForecast";
import { predictFailure, parseIssue, PredictionResult, SensorInput } from "@/lib/api";

const DEFAULTS: SensorInput = {
  mileage_km: 50000,
  engine_temp_c: 90,
  rpm: 2200,
  vibration_level: 0.05,
  oil_quality_pct: 70,
  brake_pad_mm: 8,
  battery_voltage: 12.6,
  coolant_level_pct: 85,
};

type Field = { key: keyof SensorInput; label: string; unit: string; step: number; max: number };

// Column-major: first four fill the left column, last four the right
const FIELDS: Field[] = [
  { key: "engine_temp_c", label: "Engine temperature", unit: "°C", step: 1, max: 140 },
  { key: "rpm", label: "RPM", unit: "rpm", step: 50, max: 7000 },
  { key: "vibration_level", label: "Vibration level", unit: "g", step: 0.01, max: 1 },
  { key: "mileage_km", label: "Mileage", unit: "km", step: 1000, max: 300000 },
  { key: "oil_quality_pct", label: "Oil quality", unit: "%", step: 1, max: 100 },
  { key: "coolant_level_pct", label: "Coolant level", unit: "%", step: 1, max: 100 },
  { key: "brake_pad_mm", label: "Brake pad thickness", unit: "mm", step: 0.5, max: 20 },
  { key: "battery_voltage", label: "Battery voltage", unit: "V", step: 0.1, max: 15 },
];

export default function Home() {
  const [values, setValues] = useState<SensorInput>(DEFAULTS);
  const [result, setResult] = useState<PredictionResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [query, setQuery] = useState("");
  const [describing, setDescribing] = useState(false);
  const [matches, setMatches] = useState<{ label: string; severity: string }[] | null>(null);
  const [explanation, setExplanation] = useState("");
  const [snapshot, setSnapshot] = useState<SensorInput | null>(null); // readings behind the current result
  const [tab, setTab] = useState<"drivers" | "ai">("drivers");
  const [changed, setChanged] = useState<Set<string>>(new Set());

  const update = (key: keyof SensorInput, val: number) => {
    setValues((v) => ({ ...v, [key]: val }));
    setChanged((c) => {
      const n = new Set(c);
      n.delete(key);
      return n;
    });
  };

  // Describe the issue in words -> sliders jump to the probable cause -> run prediction
  const handleDescribe = async () => {
    if (!query.trim()) return;
    setDescribing(true);
    setError(null);
    try {
      const parsed = await parseIssue(query);
      setMatches(parsed.matches);
      setExplanation(parsed.explanation ?? "");
      if (parsed.matches.length === 0) return;
      const next = { ...DEFAULTS, ...parsed.values } as SensorInput;
      setValues(next);
      setChanged(new Set(Object.keys(parsed.values)));
      const r = await predictFailure(next);
      setSnapshot(next);
      setResult(r);
    } catch (e) {
      setError("Couldn't reach the prediction service. Start the backend and try again.");
    } finally {
      setDescribing(false);
    }
  };

  const handlePredict = async () => {
    setLoading(true);
    setError(null);
    try {
      const r = await predictFailure(values);
      setSnapshot(values);
      setResult(r);
    } catch (e) {
      setError("Couldn't reach the prediction service. Start the backend and try again.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <main className="mx-auto flex max-w-[1300px] flex-col gap-10 px-6 py-8 md:px-10">
      <div className="flex flex-col gap-8 lg:h-[calc(100dvh-4rem)]">
      <header className="flex flex-wrap items-end justify-between gap-x-10 gap-y-3">
        <div>
          <p className="text-sm text-accent mb-2">AI Mini Project</p>
          <h1 className="font-title text-5xl md:text-6xl font-semibold leading-none tracking-normal">
            Vehicle Predictive Maintenance
          </h1>
        </div>
        <p className="text-steel text-sm leading-relaxed max-w-sm">
          Set the sensor readings and run the model to get a failure risk score, anomaly
          flag and a specific maintenance call.
        </p>
      </header>

      <div className="grid flex-1 min-h-0 gap-8 lg:grid-cols-2">
        {/* Sensors */}
        <section className="panel flex min-h-0 flex-col p-7 md:p-8">
          <h2 className="font-display text-2xl font-semibold">Sensor readings</h2>

          <div className="mt-4">
            <label htmlFor="issue" className="text-sm text-steel mb-1.5 block">
              Describe the issue
            </label>
            <div className="flex gap-2">
              <input
                id="issue"
                type="text"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && handleDescribe()}
                placeholder="e.g. steering wheel shakes and I smell something sweet from the hood"
                className="flex-1 rounded-lg border border-white/15 bg-white/5 px-3.5 py-2.5 text-sm placeholder:text-steel/60 focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent"
              />
              <button
                onClick={handleDescribe}
                disabled={describing || !query.trim()}
                className="rounded-lg border border-accent px-4 text-sm text-accent hover:bg-accent/10 transition-colors disabled:opacity-40"
              >
                {describing ? "Reading…" : "Set sensors"}
              </button>
            </div>
            {matches && (
              <p className="mt-2 text-xs text-steel leading-relaxed">
                {matches.length === 0
                  ? "Couldn't match that to any sensor. Try words like overheating, vibration, grinding brakes, dead battery, or give numbers (e.g. battery 11.2v)."
                  : "Detected: " + matches.map((m) => `${m.label} (${m.severity})`).join(" · ")}
              </p>
            )}
            {explanation && matches && matches.length > 0 && (
              <p className="mt-1 text-xs text-steel/80 leading-relaxed">{explanation}</p>
            )}
          </div>

          <div className="grid flex-1 min-h-0 content-evenly gap-x-10 gap-y-6 py-6 sm:grid-flow-col sm:grid-rows-4">
            {FIELDS.map((f) => {
              const pct = Math.min(100, (values[f.key] / f.max) * 100);
              return (
                <div key={f.key}>
                  <label htmlFor={f.key} className="flex items-baseline justify-between mb-1">
                    <span className="text-sm flex items-center gap-2">
                      {f.label}
                      {changed.has(f.key) && (
                        <span className="inline-block h-1.5 w-1.5 rounded-full bg-warn" title="Set from your description" />
                      )}
                    </span>
                    <span className="readout text-sm text-accent">
                      {values[f.key]} <span className="text-steel">{f.unit}</span>
                    </span>
                  </label>
                  <input
                    id={f.key}
                    type="range"
                    min={0}
                    max={f.max}
                    step={f.step}
                    value={values[f.key]}
                    onChange={(e) => update(f.key, parseFloat(e.target.value))}
                    className="range"
                    style={{ ["--p" as string]: `${pct}%` }}
                  />
                </div>
              );
            })}
          </div>

          <button
            onClick={handlePredict}
            disabled={loading}
            className="w-full bg-accent hover:bg-accentDim text-ink font-semibold rounded-lg py-3.5 transition-colors disabled:opacity-50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
          >
            {loading ? "Analyzing…" : "Predict failure risk"}
          </button>
          {error && <p role="alert" className="text-danger text-sm mt-3">{error}</p>}
        </section>

        {/* Results */}
        <section className="panel flex min-h-0 flex-col p-7 md:p-8">
          <h2 className="font-display text-2xl font-semibold mb-4">Prediction</h2>

          <div className="grid items-center gap-8 sm:grid-cols-2">
            <RiskGauge
              probability={result ? result.failure_probability : null}
              riskLevel={result ? result.risk_level : null}
            />
            <div className="space-y-4">
              {!result ? (
                <p className="text-steel text-sm leading-relaxed">
                  Adjust the sensors, then select Predict failure risk to see the diagnosis.
                </p>
              ) : (
                <>
                  {result.anomaly_detected && (
                    <div className="border-l-2 border-warn bg-warn/10 px-4 py-3 text-sm leading-relaxed text-warn">
                      Anomaly detected. This sensor pattern is unusual compared with
                      typical healthy vehicles.
                    </div>
                  )}
                  <div>
                    <h3 className="text-sm text-steel mb-1.5">Recommended action</h3>
                    <p className="text-sm leading-relaxed">{result.recommendation}</p>
                  </div>
                </>
              )}
            </div>
          </div>

          <div className="divider mt-7 pt-5 flex min-h-0 flex-1 flex-col">
            <div role="tablist" className="mb-4 flex flex-wrap gap-x-5 gap-y-1 text-sm">
              {([["drivers", "What's driving the score"], ["ai", "AI mechanic"]] as const).map(
                ([id, label]) => (
                  <button
                    key={id}
                    role="tab"
                    aria-selected={tab === id}
                    onClick={() => setTab(id)}
                    className={`pb-1.5 border-b-2 transition-colors ${
                      tab === id ? "border-accent text-accent" : "border-transparent text-steel hover:text-white"
                    }`}
                  >
                    {label}
                  </button>
                )
              )}
            </div>
            <div className="flex-1 min-h-0 overflow-y-auto pr-1">
              <div className={tab === "drivers" ? "" : "hidden"}>
                {result && snapshot ? (
                  <FeatureContributions data={result.feature_contributions} />
                ) : (
                  <p className="text-sm text-steel">Run a prediction to see what's driving the score.</p>
                )}
              </div>
              <div className={tab === "ai" ? "" : "hidden"}>
                {result && snapshot ? (
                  <AIMechanic sensors={snapshot} result={result} active={tab === "ai"} />
                ) : (
                  <p className="text-sm text-steel">Run a prediction to get an AI diagnosis and ask questions about it.</p>
                )}
              </div>
            </div>
          </div>
        </section>
      </div>
      </div>

      {/* Trend forecast: its own full-width section */}
      <section id="trend" className="panel p-7 md:p-8">
        <div className="mb-5">
          <h2 className="font-display text-2xl font-semibold">Trend forecast</h2>
          <p className="mt-1 text-sm text-steel">
            Spot sensors that are drifting toward their limits and see when they're projected to cross.
          </p>
        </div>
        <TrendForecast current={values} />
      </section>
    </main>
  );
}