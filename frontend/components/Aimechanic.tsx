"use client";

import { useEffect, useRef, useState } from "react";
import {
  aiChat,
  aiExplain,
  AIExplanation,
  ChatTurn,
  PredictionResult,
  SensorInput,
} from "@/lib/api";

const URGENCY_STYLE: Record<string, string> = {
  Routine: "border-ok text-ok",
  Soon: "border-warn text-warn",
  Urgent: "border-danger text-danger",
  "Stop driving": "border-danger text-danger bg-danger/10",
};

const SUGGESTIONS = [
  "What should I fix first?",
  "Is it safe to keep driving?",
  "What's the likely cause?",
];

type Props = {
  sensors: SensorInput; // readings used for this prediction
  result: PredictionResult;
  active: boolean; // only call the AI once the tab is opened (saves quota)
};

export default function AIMechanic({ sensors, result, active }: Props) {
  const [exp, setExp] = useState<AIExplanation | null>(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [chat, setChat] = useState<ChatTurn[]>([]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const fetchedFor = useRef<PredictionResult | null>(null);
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!active || fetchedFor.current === result) return;
    const mine = result;
    fetchedFor.current = mine;
    setExp(null);
    setChat([]);
    setErr(null);
    setLoading(true);
    aiExplain(sensors, mine)
      .then((e) => fetchedFor.current === mine && setExp(e))
      .catch(() => fetchedFor.current === mine && setErr("Couldn't reach the AI service."))
      .finally(() => fetchedFor.current === mine && setLoading(false));
  }, [active, result, sensors]);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }, [chat, sending]);

  const send = async (text: string) => {
    const msg = text.trim();
    if (!msg || sending) return;
    const history = chat;
    setChat([...history, { role: "user", text: msg }]);
    setInput("");
    setSending(true);
    try {
      const r = await aiChat(sensors, result, history, msg);
      setChat((c) => [...c, { role: "assistant", text: r.reply }]);
    } catch {
      setChat((c) => [...c, { role: "assistant", text: "Couldn't reach the AI service. Try again." }]);
    } finally {
      setSending(false);
    }
  };

  return (
    <div className="flex flex-col gap-5 pb-1">
      {loading && <p className="text-sm text-steel">The AI mechanic is reviewing your readings…</p>}
      {err && <p role="alert" className="text-sm text-danger">{err}</p>}

      {exp && (
        <div className="space-y-4">
          <div className="flex items-start gap-3">
            <span
              className={`shrink-0 rounded-full border px-2.5 py-0.5 text-xs font-medium ${
                URGENCY_STYLE[exp.urgency] ?? "border-warn text-warn"
              }`}
            >
              {exp.urgency}
            </span>
            <p className="text-sm leading-relaxed">{exp.summary}</p>
          </div>

          <ol className="space-y-3">
            {exp.actions.map((a, i) => (
              <li key={i} className="flex gap-3">
                <span className="readout mt-0.5 text-xs text-accent">{i + 1}</span>
                <div className="min-w-0">
                  <p className="text-sm font-medium">
                    {a.title}
                    {a.timeframe && <span className="ml-2 text-xs font-normal text-steel">· {a.timeframe}</span>}
                  </p>
                  <p className="text-sm text-steel leading-relaxed">{a.detail}</p>
                </div>
              </li>
            ))}
          </ol>

          <p className="text-xs text-steel/70">
            {exp.source === "template"
              ? "AI unavailable, showing a standard summary. "
              : "AI-generated from the model's output. "}
            Confirm with a qualified mechanic before making repair decisions.
          </p>
        </div>
      )}

      {exp && (
        <div className="divider pt-4 space-y-3">
          <h4 className="text-sm text-steel">Ask about this result</h4>

          {chat.length === 0 && (
            <div className="flex flex-wrap gap-2">
              {SUGGESTIONS.map((s) => (
                <button
                  key={s}
                  onClick={() => send(s)}
                  className="rounded-full border border-white/15 px-3 py-1 text-xs hover:border-accent hover:text-accent transition-colors"
                >
                  {s}
                </button>
              ))}
            </div>
          )}

          <div className="space-y-2.5">
            {chat.map((m, i) => (
              <div
                key={i}
                className={`max-w-[90%] rounded-lg px-3.5 py-2 text-sm leading-relaxed whitespace-pre-wrap ${
                  m.role === "user" ? "ml-auto bg-accent/15 text-accent" : "bg-white/5"
                }`}
              >
                {m.text}
              </div>
            ))}
            {sending && <p className="text-xs text-steel">Thinking…</p>}
            <div ref={endRef} />
          </div>

          <div className="flex gap-2">
            <input
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && send(input)}
              placeholder="e.g. Can I wait until next month?"
              aria-label="Ask the AI mechanic"
              className="flex-1 rounded-lg border border-white/15 bg-white/5 px-3.5 py-2 text-sm placeholder:text-steel/60 focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent"
            />
            <button
              onClick={() => send(input)}
              disabled={sending || !input.trim()}
              className="rounded-lg border border-accent px-4 text-sm text-accent hover:bg-accent/10 transition-colors disabled:opacity-40"
            >
              Send
            </button>
          </div>
        </div>
      )}
    </div>
  );
}