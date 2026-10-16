"use client";

import { useEffect, useRef, useState } from "react";
import { forecastTrends, ForecastResult, ForecastSeries, LogRow, SensorInput } from "@/lib/api";

const STORAGE_KEY = "autoguard_reading_log";
const MIN_POINTS = 5;
const TIME_KEYS = ["timestamp", "date", "time", "datetime", "recorded_at"];

const STATUS: Record<ForecastSeries["status"], { label: string; cls: string }> = {
  out_of_range: { label: "Past limit", cls: "border-danger text-danger" },
  drifting: { label: "Drifting", cls: "border-warn text-warn" },
  slow_drift: { label: "Slow drift", cls: "border-warn/60 text-warn" },
  improving: { label: "Improving", cls: "border-ok text-ok" },
  stable: { label: "Stable", cls: "border-white/20 text-steel" },
  insufficient: { label: "Need data", cls: "border-white/20 text-steel" },
};

const fmt = (v: number) => String(Number(v.toPrecision(3)));

/* ---------- helpers ---------- */

function parseCsv(text: string): LogRow[] {
  const lines = text.trim().split(/\r?\n/).filter(Boolean);
  if (lines.length < 2) return [];
  const head = lines[0].split(",").map((h) => h.trim().toLowerCase().replace(/^"|"$/g, ""));
  return lines
    .slice(1)
    .map((line) => {
      const cells = line.split(",");
      const row: LogRow = {};
      head.forEach((h, i) => {
        const c = (cells[i] ?? "").trim().replace(/^"|"$/g, "");
        if (!c) return;
        const n = Number(c);
        row[h] = TIME_KEYS.includes(h) || Number.isNaN(n) ? c : n;
      });
      return row;
    })
    .filter((r) => Object.keys(r).length > 0)
    .slice(-2000);
}

// 30 days of a gradually degrading vehicle, so the feature can be demoed instantly
function demoLog(): LogRow[] {
  const days = 30;
  const now = Date.now();
  let seed = 7;
  const rnd = () => {
    seed = (seed * 16807) % 2147483647;
    return seed / 2147483647 - 0.5;
  };
  return Array.from({ length: days }, (_, i) => {
    const t = i / (days - 1);
    return {
      timestamp: new Date(now - (days - 1 - i) * 86400000).toISOString(),
      mileage_km: Math.round(62000 + i * 55),
      engine_temp_c: +(88 + t * 9 + rnd() * 3).toFixed(1),
      rpm: Math.round(2200 + rnd() * 300),
      vibration_level: +(0.05 + t * 0.07 + rnd() * 0.01).toFixed(3),
      oil_quality_pct: +(68 - t * 20 + rnd() * 2).toFixed(1),
      brake_pad_mm: +(7.5 - t * 3.6 + rnd() * 0.2).toFixed(2),
      battery_voltage: +(12.7 - t * 0.45 + rnd() * 0.05).toFixed(2),
      coolant_level_pct: +(85 - t * 28 + rnd() * 1.5).toFixed(1),
    };
  });
}

/* ---------- chart ---------- */

function Chart({ s }: { s: ForecastSeries }) {
  const W = 320, H = 92, P = 6;
  const proj = s.projection;
  const xs = [...s.points.map((p) => p[0]), ...(proj ? proj.map((p) => p[0]) : [])];
  const ys = [...s.points.map((p) => p[1]), s.limit, ...(proj ? proj.map((p) => p[1]) : [])];
  const x0 = Math.min(...xs);
  const x1 = Math.max(...xs);
  let y0 = Math.min(...ys);
  let y1 = Math.max(...ys);
  if (y0 === y1) { y0 -= 1; y1 += 1; }
  const pad = (y1 - y0) * 0.1;
  y0 -= pad; y1 += pad;
  const X = (x: number) => P + ((x - x0) / (x1 - x0 || 1)) * (W - 2 * P);
  const Y = (y: number) => H - P - ((y - y0) / (y1 - y0)) * (H - 2 * P);
  const line = (pts: [number, number][]) => pts.map((p) => `${X(p[0])},${Y(p[1])}`).join(" ");

  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full h-24" role="img"
         aria-label={`${s.label} trend chart. ${s.message}`}>
      <line x1={P} x2={W - P} y1={Y(s.limit)} y2={Y(s.limit)} stroke="#ff5d6c" strokeWidth={1}
            strokeDasharray="4 3" opacity={0.8} />
      <text x={W - P} y={Y(s.limit) - 3} textAnchor="end" fontSize={8} fill="#ff5d6c">limit</text>
      <polyline points={line(s.points)} fill="none" stroke="#5ad1ff" strokeWidth={1.6} strokeLinejoin="round" />
      {s.fit && <polyline points={line(s.fit)} fill="none" stroke="#8fa5b6" strokeWidth={1} opacity={0.7} />}
      {proj && (
        <>
          <polyline points={line(proj)} fill="none" stroke="#ffb547" strokeWidth={1.6} strokeDasharray="5 3" />
          <circle cx={X(proj[1][0])} cy={Y(proj[1][1])} r={3} fill="#ffb547" />
        </>
      )}
    </svg>
  );
}

/* ---------- component ---------- */

export default function TrendForecast({ current }: { current: SensorInput }) {
  const [log, setLog] = useState<LogRow[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [data, setData] = useState<ForecastResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const reqId = useRef(0);

  // restore saved log
  useEffect(() => {
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      if (raw) setLog(JSON.parse(raw));
    } catch {}
    setLoaded(true);
  }, []);

  // persist
  useEffect(() => {
    if (!loaded) return;
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(log));
    } catch {}
  }, [log, loaded]);

  // re-forecast whenever the log changes (debounced)
  useEffect(() => {
    if (!loaded) return;
    if (log.length < MIN_POINTS) {
      setData(null);
      setErr(null);
      return;
    }
    const id = ++reqId.current;
    setLoading(true);
    const timer = setTimeout(() => {
      forecastTrends(log)
        .then((r) => { if (id === reqId.current) { setData(r); setErr(null); } })
        .catch(() => { if (id === reqId.current) setErr("Couldn't reach the forecast service."); })
        .finally(() => { if (id === reqId.current) setLoading(false); });
    }, 300);
    return () => clearTimeout(timer);
  }, [log, loaded]);

  const logCurrent = () =>
    setLog((l) => [...l, { timestamp: new Date().toISOString(), ...current }].slice(-2000));

  const onFile = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;
    const rows = parseCsv(await file.text());
    if (rows.length === 0) setErr("Couldn't read any rows from that CSV (needs a header row).");
    else { setErr(null); setLog(rows); }
  };

  const unitWord = data?.x_unit === "days" ? "days" : data?.x_unit === "km" ? "km" : "readings";

  return (
    <div className="flex flex-col gap-4 pb-1">
      <p className="text-sm text-steel leading-relaxed">
        Log readings over time or upload a CSV; each sensor is checked for real drift.
      </p>

      <div className="flex flex-wrap items-center gap-2">
        <button onClick={logCurrent}
                className="rounded-lg border border-accent px-3 py-1.5 text-sm text-accent hover:bg-accent/10 transition-colors">
          Log current reading
        </button>
        <button onClick={() => fileRef.current?.click()}
                className="rounded-lg border border-white/15 px-3 py-1.5 text-sm hover:border-accent hover:text-accent transition-colors">
          Upload CSV
        </button>
        <button onClick={() => { setErr(null); setLog(demoLog()); }}
                className="rounded-lg border border-white/15 px-3 py-1.5 text-sm hover:border-accent hover:text-accent transition-colors">
          Load demo data
        </button>
        {log.length > 0 && (
          <button onClick={() => setLog([])}
                  className="rounded-lg px-3 py-1.5 text-sm text-steel hover:text-danger transition-colors">
            Clear
          </button>
        )}
        <input ref={fileRef} type="file" accept=".csv,text/csv" onChange={onFile} className="hidden" />
        <span className="readout ml-auto text-xs text-steel">{log.length} readings</span>
      </div>

      <p className="text-xs text-steel/70">
        CSV columns: an optional <span className="readout">timestamp</span> plus any of the sensor names
        (engine_temp_c, rpm, vibration_level, mileage_km, oil_quality_pct, brake_pad_mm, battery_voltage,
        coolant_level_pct).
      </p>

      {err && <p role="alert" className="text-sm text-danger">{err}</p>}
      {log.length > 0 && log.length < MIN_POINTS && (
        <p className="text-sm text-warn">
          {MIN_POINTS - log.length} more reading{MIN_POINTS - log.length === 1 ? "" : "s"} needed before a trend can be detected.
        </p>
      )}
      {loading && <p className="text-xs text-steel">Analyzing trends…</p>}

      {data && data.series.length > 0 && (
        <>
          <div className="rounded-lg border border-white/10 bg-white/5 px-4 py-3">
            <h4 className="text-sm text-steel mb-2">Forecast summary</h4>
            <ul className="space-y-1.5 text-sm leading-relaxed list-disc pl-4">
              {data.summary.map((m, i) => <li key={i}>{m}</li>)}
            </ul>
          </div>

          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {data.series.map((s) => (
              <div key={s.feature} className="rounded-lg border border-white/10 p-3">
                <div className="flex items-center justify-between gap-2 mb-1">
                  <span className="text-sm font-medium">{s.label}</span>
                  <span className={`rounded-full border px-2 py-0.5 text-[11px] ${STATUS[s.status].cls}`}>
                    {STATUS[s.status].label}
                  </span>
                </div>
                <p className="readout text-xs text-steel mb-1">
                  latest {fmt(s.latest * s.scale)} {s.unit}
                  {s.eta !== null && s.eta_range && (
                    <>
                      {" · "}ETA {fmt(s.eta)} {unitWord}
                      {s.eta_range[0] !== null && ` (${fmt(s.eta_range[0])}–${s.eta_range[1] !== null ? fmt(s.eta_range[1]) : "later"})`}
                    </>
                  )}
                </p>
                <Chart s={s} />
                <p className="text-xs text-steel leading-relaxed">{s.message}</p>
              </div>
            ))}
          </div>

          <p className="text-xs text-steel/70">
            Team 18
          </p>
        </>
      )}
    </div>
  );
}