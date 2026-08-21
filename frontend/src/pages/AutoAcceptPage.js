import { useCallback, useEffect, useState } from "react";
import {
  CheckCircleIcon,
  XCircleIcon,
  ClockIcon,
  ArrowsClockwiseIcon,
  PlayCircleIcon,
} from "@phosphor-icons/react";
import api, { formatApiError } from "@/lib/api";
import PageHeader from "@/components/PageHeader";
import { fmtRelative } from "@/lib/format";

const STATUS_COLORS = {
  pending: "bg-amber-500/15 text-amber-300 border-amber-500/30",
  processing: "bg-sky-500/15 text-sky-300 border-sky-500/30",
  done: "bg-emerald-500/15 text-emerald-300 border-emerald-500/30",
  failed: "bg-rose-500/15 text-rose-300 border-rose-500/30",
};
function StatusPill({ status }) {
  const cls = STATUS_COLORS[status] || "bg-white/5 text-white/70 border-white/10";
  return (
    <span className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] uppercase tracking-widest ${cls}`}>
      {status}
    </span>
  );
}

export default function AutoAcceptPage() {
  const [settings, setSettings] = useState([]);
  const [history, setHistory] = useState([]);
  const [err, setErr] = useState("");
  const [savingId, setSavingId] = useState(null);
  const [runningId, setRunningId] = useState(null);

  const loadSettings = useCallback(async () => {
    try {
      const r = await api.get("/auto-accept/settings");
      setSettings(r.data.items || []);
    } catch (e) { setErr(formatApiError(e)); }
  }, []);
  const loadHistory = useCallback(async () => {
    try {
      const r = await api.get("/auto-accept/history", { params: { limit: 30 } });
      setHistory(r.data.items || []);
    } catch (e) { /* silent */ }
  }, []);

  useEffect(() => { loadSettings(); loadHistory(); }, [loadSettings, loadHistory]);

  const toggle = async (row, enabled) => {
    setSavingId(row.account_id); setErr("");
    try {
      await api.put(`/auto-accept/settings/${row.account_id}`, { enabled });
      await loadSettings();
    } catch (e) { setErr(formatApiError(e)); }
    finally { setSavingId(null); }
  };
  const updateInterval = async (row, minutes) => {
    setSavingId(row.account_id); setErr("");
    try {
      await api.put(`/auto-accept/settings/${row.account_id}`, { interval_minutes: Number(minutes) });
      await loadSettings();
    } catch (e) { setErr(formatApiError(e)); }
    finally { setSavingId(null); }
  };
  const runNow = async (row) => {
    setRunningId(row.account_id); setErr("");
    try {
      await api.post(`/auto-accept/run-now/${row.account_id}`);
      await loadHistory();
    } catch (e) { setErr(formatApiError(e)); }
    finally { setRunningId(null); }
  };

  const anyEnabled = settings.some((s) => s.auto_accept_enabled);

  return (
    <div className="min-h-screen" data-testid="auto-accept-page">
      <PageHeader
        title="AUTOMATION / AUTO-ACCEPT ORDERS"
        subtitle="Polling picks up new orders on Meesho and clicks Accept — no PDF download"
        right={
          <button data-testid="refresh-btn" className="btn-ghost text-xs" onClick={() => { loadSettings(); loadHistory(); }}>
            <ArrowsClockwiseIcon size={12} weight="bold" />
            <span className="ml-1">Refresh</span>
          </button>
        }
      />

      <div className="px-8 py-6 space-y-6">
        <div className="rounded border border-[var(--border)] bg-[var(--bg-card)] p-4 text-xs text-[var(--text-muted)]" data-testid="how-it-works">
          <div className="mb-1 text-white text-sm">How it works</div>
          Every 5 minutes the dashboard&apos;s scheduler checks each account you&apos;ve enabled below. If the last successful accept-run
          is older than the account&apos;s interval, we enqueue an <span className="font-mono">accept_labels</span> job for the EC2 scraper.
          The scraper opens Meesho Orders → Ready to Ship and clicks <b>Accept Order</b> on every new one — nothing is downloaded.
          {anyEnabled ? (
            <span className="ml-2 rounded bg-emerald-500/15 text-emerald-300 px-2 py-0.5 text-[10px] uppercase tracking-widest border border-emerald-500/30">
              polling active
            </span>
          ) : (
            <span className="ml-2 rounded bg-white/5 text-[var(--text-muted)] px-2 py-0.5 text-[10px] uppercase tracking-widest border border-[var(--border)]">
              off — no accounts enabled
            </span>
          )}
        </div>

        {err && (
          <div data-testid="error-banner" className="rounded border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-sm text-rose-200">
            {err}
          </div>
        )}

        <div className="rounded-lg border border-[var(--border)] bg-[var(--bg-card)] overflow-hidden">
          <table className="dense w-full" data-testid="settings-table">
            <thead>
              <tr>
                <th>Account</th>
                <th>Auto-accept</th>
                <th>Interval</th>
                <th>Last run</th>
                <th>Run now</th>
              </tr>
            </thead>
            <tbody>
              {settings.map((s) => (
                <tr key={s.account_id} data-testid={`settings-row-${s.account_id}`}>
                  <td className="text-xs">
                    {s.account_alias || s.account_name}
                    {!s.account_enabled && (
                      <span className="ml-2 text-[10px] text-rose-300">(disabled)</span>
                    )}
                  </td>
                  <td>
                    <label className="inline-flex items-center gap-2 cursor-pointer">
                      <input
                        type="checkbox"
                        data-testid={`toggle-${s.account_id}`}
                        checked={s.auto_accept_enabled}
                        disabled={!s.account_enabled || savingId === s.account_id}
                        onChange={(e) => toggle(s, e.target.checked)}
                        className="h-4 w-4 accent-[var(--accent)]"
                      />
                      <span className="text-xs">{s.auto_accept_enabled ? "ON" : "OFF"}</span>
                    </label>
                  </td>
                  <td>
                    <select
                      data-testid={`interval-${s.account_id}`}
                      value={s.interval_minutes}
                      disabled={!s.account_enabled || savingId === s.account_id}
                      onChange={(e) => updateInterval(s, e.target.value)}
                      className="input-shell text-xs"
                    >
                      {[5, 10, 15, 30, 60, 120].map((m) => (
                        <option key={m} value={m}>every {m} min</option>
                      ))}
                    </select>
                  </td>
                  <td className="text-xs">
                    {s.last_run && s.last_run.finished_at ? (
                      <div>
                        <div>
                          {s.last_run.status === "done" ? "✓" : s.last_run.status === "failed" ? "✕" : "…"}{" "}
                          <span className="text-emerald-300">{s.last_run.accepted_count}</span> accepted
                        </div>
                        <div className="text-[10px] text-[var(--text-muted)]">{fmtRelative(s.last_run.finished_at)}</div>
                      </div>
                    ) : <span className="text-[var(--text-muted)]">—</span>}
                  </td>
                  <td>
                    <button
                      data-testid={`run-now-${s.account_id}`}
                      onClick={() => runNow(s)}
                      disabled={!s.account_enabled || runningId === s.account_id}
                      className="btn-ghost text-xs flex items-center gap-1"
                    >
                      <PlayCircleIcon size={12} weight="fill" /> Run now
                    </button>
                  </td>
                </tr>
              ))}
              {settings.length === 0 && (
                <tr><td colSpan={5} className="text-center text-[var(--text-muted)] text-sm py-6">No accounts.</td></tr>
              )}
            </tbody>
          </table>
        </div>

        <div className="rounded-lg border border-[var(--border)] bg-[var(--bg-card)] p-4">
          <div className="section-label mb-3">Recent auto-accept runs</div>
          {history.length === 0 ? (
            <div className="text-sm text-[var(--text-muted)]" data-testid="history-empty">No runs yet.</div>
          ) : (
            <div className="space-y-2" data-testid="history-list">
              {history.map((j) => {
                const Icon = j.status === "done" ? CheckCircleIcon : j.status === "failed" ? XCircleIcon : ClockIcon;
                return (
                  <div key={j.id} data-testid={`history-item-${j.id}`} className="flex items-start gap-3 rounded border border-[var(--border)] px-3 py-2 bg-black/20">
                    <Icon size={14} weight="fill" className={
                      j.status === "done" ? "text-emerald-400" :
                      j.status === "failed" ? "text-rose-400" : "text-sky-400"
                    } />
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <span className="text-sm">{j.account_name}</span>
                        <StatusPill status={j.status} />
                        <span className="text-[10px] text-[var(--text-muted)]">by {j.submitted_by}</span>
                      </div>
                      <div className="text-[11px] text-[var(--text-muted)] mt-0.5">
                        {fmtRelative(j.created_at)} · accepted{" "}
                        <span className="text-emerald-300">{j.result.accepted_count}</span>
                        {j.result.failed_count > 0 && (
                          <span className="ml-2 text-rose-300">failed {j.result.failed_count}</span>
                        )}
                      </div>
                      {j.error && <div className="text-[11px] text-rose-300 truncate mt-0.5" title={j.error}>{j.error}</div>}
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
