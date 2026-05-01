import { useEffect, useState, useCallback, useMemo } from "react";
import { Link } from "react-router-dom";
import {
  PrinterIcon,
  PlayIcon,
  ArrowsClockwiseIcon,
  UserCircleIcon,
} from "@phosphor-icons/react";
import api, { formatApiError } from "@/lib/api";
import PageHeader from "@/components/PageHeader";
import { fmtDate, fmtRelative, StatusPill } from "@/lib/format";

export default function LabelsPage() {
  const [runs, setRuns] = useState([]);
  const [accounts, setAccounts] = useState([]);
  const [selected, setSelected] = useState("__all__");
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const [queuedMsg, setQueuedMsg] = useState("");

  const load = useCallback(async () => {
    setLoading(true); setErr("");
    try {
      const [runsRes, accRes] = await Promise.all([
        api.get("/labels/runs", { params: { limit: 100 } }),
        api.get("/accounts"),
      ]);
      setRuns(runsRes.data.items);
      setAccounts(accRes.data.items || []);
    } catch (e) {
      setErr(formatApiError(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    document.title = "Label Download · Seller Central";
    load();
  }, [load]);

  // auto-refresh if something is pending/processing
  useEffect(() => {
    const active = runs.some((r) => r.status === "pending" || r.status === "processing");
    if (!active) return;
    const t = setInterval(load, 6000);
    return () => clearInterval(t);
  }, [runs, load]);

  const enabledAccounts = useMemo(() => accounts.filter((a) => a.enabled), [accounts]);

  const runNow = async () => {
    setBusy(true); setErr(""); setQueuedMsg("");
    try {
      let body;
      if (selected === "__all__") {
        body = { all_accounts: true };
      } else {
        body = { account_id: selected };
      }
      const { data } = await api.post("/labels/run-now", body);
      if (data.queued) {
        setQueuedMsg(
          `Queued ${data.queued.length} job(s)` +
          (data.skipped?.length ? ` · ${data.skipped.length} already running` : "")
        );
      } else if (data.already_queued) {
        setQueuedMsg("A label job is already queued/running for this account.");
      } else {
        setQueuedMsg(`Label job queued for ${data.account_name || "account"}.`);
      }
      await load();
      setTimeout(() => setQueuedMsg(""), 4000);
    } catch (e) {
      setErr(formatApiError(e));
    } finally {
      setBusy(false);
    }
  };

  const accNameMap = useMemo(() => {
    const m = {};
    accounts.forEach((a) => { m[a.id] = a.name; });
    return m;
  }, [accounts]);

  return (
    <div data-testid="labels-page">
      <PageHeader
        title="automation"
        subtitle="Label Download"
        right={
          <>
            <select
              value={selected}
              onChange={(e) => setSelected(e.target.value)}
              className="input-shell font-mono text-xs py-1.5 w-auto"
              data-testid="labels-account-select"
            >
              <option value="__all__">▸ All enabled accounts ({enabledAccounts.length})</option>
              {accounts.map((a) => (
                <option key={a.id} value={a.id} disabled={!a.enabled}>
                  {a.name} {a.enabled ? "" : "(disabled)"} · :{a.debug_port}
                </option>
              ))}
            </select>
            <button onClick={load} className="btn-secondary text-sm flex items-center gap-2"
              data-testid="labels-refresh">
              <ArrowsClockwiseIcon size={14} weight="bold" /> Refresh
            </button>
            <button
              onClick={runNow}
              disabled={busy || (selected === "__all__" && enabledAccounts.length === 0)}
              className="btn-primary text-sm flex items-center gap-2"
              data-testid="labels-run-now"
            >
              <PlayIcon size={14} weight="bold" />
              {busy ? "Queuing…" : "Run Now"}
            </button>
          </>
        }
      />

      <div className="px-8 py-6 space-y-4">
        <div className="panel p-5 flex gap-4 items-start">
          <PrinterIcon size={28} weight="bold" color="#007AFF" />
          <div className="flex-1 space-y-2">
            <div className="font-display text-base">How this works</div>
            <p className="text-xs text-[#A1A1AA] leading-relaxed">
              Pick an account (or "All enabled accounts") and click <span className="code-tag">Run Now</span>.
              For each selected account a <span className="code-tag">label_download</span> job is queued
              in MongoDB. The EC2 worker connects to that account's Chrome (on its <span className="code-tag">debug_port</span>)
              and:
            </p>
            <ul className="list-disc ml-5 text-xs text-[#A1A1AA] space-y-1">
              <li>Opens the Pending tab and accepts all pending orders</li>
              <li>Switches to Ready-to-Ship and clicks Label to download PDFs</li>
              <li>Marks the job <span className="code-tag">done</span> (or <span className="code-tag">failed</span> with error)</li>
            </ul>
            {accounts.length === 0 && (
              <p className="text-xs text-[#F5A623] mt-2">
                No accounts configured yet — <Link to="/accounts" className="underline">add one</Link> first.
              </p>
            )}
          </div>
        </div>

        {queuedMsg && (
          <div className="border border-[#00E676]/30 bg-[#00E676]/10 px-3 py-2 font-mono text-xs text-[#00E676]"
            data-testid="labels-msg">{queuedMsg}</div>
        )}
        {err && (
          <div className="border border-[#FF3B30]/30 bg-[#FF3B30]/10 px-3 py-2 font-mono text-xs text-[#FF3B30]"
            data-testid="labels-err">
            {err}
          </div>
        )}

        <div className="panel">
          <div className="border-b border-[#2A2A2A] px-5 py-3 font-display text-sm font-medium">Run History</div>
          <div className="overflow-x-auto">
            <table className="dense">
              <thead>
                <tr>
                  <th>Status</th>
                  <th>Account</th>
                  <th className="num">Created</th>
                  <th className="num">Started</th>
                  <th className="num">Finished</th>
                  <th>Submitted By</th>
                  <th>Notes</th>
                </tr>
              </thead>
              <tbody>
                {loading && (
                  <tr><td colSpan={7} className="text-center py-8 text-[#71717A] font-mono text-xs">
                    <span className="cursor-blink">LOADING</span>
                  </td></tr>
                )}
                {!loading && runs.length === 0 && (
                  <tr><td colSpan={7} className="text-center py-10 text-[#71717A] text-sm">
                    No runs yet. Click "Run Now" to queue the first one.
                  </td></tr>
                )}
                {runs.map((r) => {
                  const accName = r.account_name || accNameMap[r.account_id] || "—";
                  return (
                    <tr key={r.id} data-testid={`label-run-${r.id}`}>
                      <td><StatusPill status={r.status} /></td>
                      <td className="font-mono text-xs text-[#E5E5E5]">
                        <span className="flex items-center gap-1">
                          <UserCircleIcon size={12} weight="bold" color="#71717A" />
                          {accName}
                        </span>
                      </td>
                      <td className="num text-xs text-[#A1A1AA]" title={fmtDate(r.created_at)}>{fmtRelative(r.created_at)}</td>
                      <td className="num text-xs text-[#A1A1AA]">{fmtRelative(r.started_at)}</td>
                      <td className="num text-xs text-[#A1A1AA]">{fmtRelative(r.finished_at)}</td>
                      <td className="text-xs text-[#A1A1AA]">{r.submitted_by || "—"}</td>
                      <td className="text-xs">
                        {r.error ? (
                          <span className="text-[#FF3B30] font-mono">{r.error}</span>
                        ) : r.status === "done" ? (
                          <span className="text-[#71717A]">PDFs downloaded on worker machine</span>
                        ) : (
                          <span className="text-[#71717A]">—</span>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  );
}
