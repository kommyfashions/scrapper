import { format, formatDistanceToNow, parseISO } from "date-fns";

export function fmtDate(value) {
  if (!value) return "—";
  try {
    const d = typeof value === "string" ? parseISO(value) : new Date(value);
    if (Number.isNaN(d.getTime())) return String(value);
    return format(d, "yyyy-MM-dd HH:mm");
  } catch {
    return String(value);
  }
}

export function fmtRelative(value) {
  if (!value) return "—";
  try {
    const d = typeof value === "string" ? parseISO(value) : new Date(value);
    if (Number.isNaN(d.getTime())) return String(value);
    return formatDistanceToNow(d, { addSuffix: true });
  } catch {
    return String(value);
  }
}

export function fmtNumber(n) {
  if (n === null || n === undefined) return "—";
  return new Intl.NumberFormat("en-US").format(n);
}

export function StatusPill({ status }) {
  const map = {
    pending:    { color: "#F5A623", label: "PENDING" },
    processing: { color: "#007AFF", label: "PROCESSING" },
    done:       { color: "#00E676", label: "DONE" },
    failed:     { color: "#FF3B30", label: "FAILED" },
    stuck:      { color: "#FF3B30", label: "STUCK" },
  };
  const cfg = map[status] || { color: "#71717A", label: String(status || "—").toUpperCase() };
  const animate = status === "processing" ? " dot-pulse" : "";
  return (
    <span
      className="tactical-pill"
      style={{
        background: `${cfg.color}1a`,
        border: `1px solid ${cfg.color}55`,
        color: cfg.color,
      }}
      data-testid={`status-pill-${status}`}
    >
      <span className={`dot${animate}`} style={{ background: cfg.color }}></span>
      {cfg.label}
    </span>
  );
}

export function StarRow({ rating }) {
  const r = Math.max(0, Math.min(5, Math.round(Number(rating) || 0)));
  const color =
    r >= 4 ? "#00E676" : r >= 3 ? "#F5A623" : r >= 1 ? "#FF3B30" : "#71717A";
  return (
    <span className="font-mono text-xs" style={{ color }}>
      {"★".repeat(r)}
      <span style={{ color: "#2A2A2A" }}>{"★".repeat(5 - r)}</span>
    </span>
  );
}
