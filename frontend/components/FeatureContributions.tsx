"use client";

type Contribution = {
  feature: string;
  value: number;
  healthy_range: [number, number];
  out_of_range: boolean;
  contribution_score: number;
};

const LABELS: Record<string, string> = {
  mileage_km: "Mileage",
  engine_temp_c: "Engine temp",
  rpm: "RPM",
  vibration_level: "Vibration",
  oil_quality_pct: "Oil quality",
  brake_pad_mm: "Brake pad",
  battery_voltage: "Battery voltage",
  coolant_level_pct: "Coolant level",
  vehicle_age_years: "Vehicle age",
};

export default function FeatureContributions({ data }: { data: Contribution[] }) {
  const rows = [...data].sort((a, b) => b.contribution_score - a.contribution_score);
  const max = Math.max(...rows.map((d) => d.contribution_score), 0.01);

  return (
    <ul className="grid gap-x-10 gap-y-5 sm:grid-cols-2">
      {rows.map((d) => (
        <li key={d.feature} title={`Healthy range ${d.healthy_range[0]}–${d.healthy_range[1]}`}>
          <div className="flex items-baseline justify-between gap-3 mb-2">
            <span className="text-sm flex items-center gap-2">
              <span
                className={`inline-block h-2 w-2 rounded-full ${d.out_of_range ? "bg-danger" : "bg-ok"}`}
                aria-hidden
              />
              {LABELS[d.feature] ?? d.feature}
            </span>
            <span className="readout text-sm">{d.value}</span>
          </div>
          <div className="h-1.5 rounded-full bg-white/10 overflow-hidden">
            <div
              className="h-full rounded-full transition-all duration-700"
              style={{
                width: `${(d.contribution_score / max) * 100}%`,
                background: d.out_of_range ? "#ff5d6c" : "#5ad1ff",
              }}
            />
          </div>
          {d.out_of_range && (
            <p className="text-xs text-danger mt-1.5">
              Healthy: {d.healthy_range[0]}–{d.healthy_range[1]}
            </p>
          )}
        </li>
      ))}
    </ul>
  );
}