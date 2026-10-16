"use client";

type Props = {
  probability: number | null; // 0..1, null = no prediction yet
  riskLevel: "Low" | "Moderate" | "High" | null;
};

const COLORS = { Low: "#3ddc97", Moderate: "#ffb547", High: "#ff5d6c" };
const SEGMENTS = [
  { from: 0, to: 0.3, color: COLORS.Low },
  { from: 0.3, to: 0.6, color: COLORS.Moderate },
  { from: 0.6, to: 1, color: COLORS.High },
];

const CX = 120;
const CY = 120;
const R = 96;

// a: 0 (far left) .. 180 (far right) across the top of the dial
const pt = (r: number, a: number) => ({
  x: CX - r * Math.cos((a * Math.PI) / 180),
  y: CY - r * Math.sin((a * Math.PI) / 180),
});

const arc = (from: number, to: number) => {
  const gap = 1.2;
  const s = pt(R, from * 180 + gap);
  const e = pt(R, to * 180 - gap);
  return `M ${s.x} ${s.y} A ${R} ${R} 0 0 1 ${e.x} ${e.y}`;
};

export default function RiskGauge({ probability, riskLevel }: Props) {
  const idle = probability === null || riskLevel === null;
  const pct = idle ? 0 : Math.max(0, Math.min(1, probability));
  const angle = -90 + pct * 180;
  const color = idle ? "#8fa5b6" : COLORS[riskLevel];

  return (
    <div className="flex flex-col items-center" role="img"
         aria-label={idle ? "Risk gauge, no prediction yet" : `Failure risk ${(pct * 100).toFixed(1)} percent, ${riskLevel}`}>
      <svg viewBox="0 0 240 140" className="w-full max-w-[420px] max-h-[28vh]">
        {SEGMENTS.map((s, i) => {
          const active = !idle && pct >= s.from && (pct < s.to || s.to === 1);
          return (
            <path key={i} d={arc(s.from, s.to)} stroke={s.color} strokeWidth={14} fill="none"
                  opacity={active ? 1 : idle ? 0.25 : 0.18}
                  style={{ transition: "opacity 0.4s" }} />
          );
        })}

        {/* Ticks every 5%, long every 25% */}
        {Array.from({ length: 21 }, (_, i) => {
          const long = i % 5 === 0;
          const a = (i / 20) * 180;
          const p1 = pt(R - 14, a);
          const p2 = pt(R - (long ? 24 : 19), a);
          return <line key={i} x1={p1.x} y1={p1.y} x2={p2.x} y2={p2.y}
                       stroke="#8fa5b6" strokeWidth={long ? 1.5 : 1} opacity={long ? 0.9 : 0.4} />;
        })}
        {[0, 25, 50, 75, 100].map((v) => {
          const p = pt(R - 36, (v / 100) * 180);
          return <text key={v} x={p.x} y={p.y + 3} textAnchor="middle" fontSize={8}
                       fill="#8fa5b6" fontFamily="IBM Plex Mono, monospace">{v}</text>;
        })}

        <g style={{ transition: "transform 0.8s cubic-bezier(0.22, 1.2, 0.36, 1)", transformOrigin: `${CX}px ${CY}px` }}
           transform={`rotate(${angle}, ${CX}, ${CY})`}>
          <polygon points={`${CX - 3},${CY} ${CX + 3},${CY} ${CX},${CY - 70}`} fill={color} />
          <circle cx={CX} cy={CY} r={8} fill="#080f16" stroke={color} strokeWidth={3} />
        </g>
      </svg>

      <div className="text-center -mt-1">
        <div className="readout text-5xl font-semibold leading-none" style={{ color }}>
          {idle ? "--.-" : (pct * 100).toFixed(1)}
          <span className="text-2xl opacity-70">%</span>
        </div>
        <div className="text-sm mt-2 text-steel">
          {idle ? "Waiting for a prediction" : `${riskLevel} failure risk`}
        </div>
      </div>
    </div>
  );
}