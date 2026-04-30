import { useEffect, useState, useCallback } from "react";
import { PrinterIcon, PlayIcon, ArrowsClockwiseIcon } from "@phosphor-icons/react";
import api, { formatApiError } from "@/lib/api";
import PageHeader from "@/components/PageHeader";
import { fmtDate, fmtRelative, StatusPill } from "@/lib/format";

export default function LabelsPage() {
  const [runs, setRuns] = useState([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const [queuedMsg, setQueuedMsg] = useState("");

  const load = useCallback(async () => {
    setLoading(true); setErr("");
    try {
      const { data } = await api.get("/labels/runs", { params: { limit: 100 } });
      setRuns(data.items);
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

  const runNow = async () => {
    setBusy(true); setErr(""); setQueuedMsg("");
    try {
      const { data } = await api.post("/labels/run-now");
      setQueuedMsg(data.already_queued ? "A label job is already queued/running." : "Label job queued.");
      await load();
      setTimeout(() => setQueuedMsg(""), 3500);
    } catch (e) {
      setErr(formatApiError(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div data-testid="labels-page">
      <PageHeader
        title="automation"
        subtitle="Label Download"
        right={
          <>
            <button onClick={load} className="btn-secondary text-sm flex items-center gap-2"
              data-testid="labels-refresh">
              <ArrowsClockwiseIcon size={14} weight="bold" /> Refresh
            </button>
            <button onClick={runNow} disabled={busy} className="btn-primary text-sm flex items-center gap-2"
              data-testid="labels-run-now">
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
              Clicking <span className="code-tag">Run Now</span> queues a <span className="code-tag">label_download</span> job in
              MongoDB. When your local worker is running (with Chrome open on the supplier portal at
              <span className="code-tag"> supplier.meesho.com</span> via port 9222), it will:
            </p>
            <ul className="list-disc ml-5 text-xs text-[#A1A1AA] space-y-1">
              <li>Open the Pending tab and accept all pending orders</li>
              <li>Switch to Ready-to-Ship and click the Label button to download PDFs</li>
              <li>Mark the job <span className="code-tag">done</span> (or <span className="code-tag">failed</span> with error)</li>
            </ul>
            <p className="text-xs text-[#A1A1AA] leading-relaxed">
              The PDF files are saved to your local machine's default Chrome download folder — nothing is uploaded back here.
            </p>
          </div>
        </div>

        {queuedMsg && (
          <div className="border border-[#00E676]/30 bg-[#00E676]/10 px-3 py-2 font-mono text-xs text-[#00E676]"
            data-testid="labels-msg">{queuedMsg}</div>
        )}
        {err && (
          <div className="border border-[#FF3B30]/30 bg-[#FF3B30]/10 px-3 py-2 font-mono text-xs text-[#FF3B30]">
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
                  <th className="num">Created</th>
                  <th className="num">Started</th>
                  <th className="num">Finished</th>
                  <th>Submitted By</th>
                  <th>Notes</th>
                </tr>
              </thead>
              <tbody>
                {loading && (
                  <tr><td colSpan={6} className="text-center py-8 text-[#71717A] font-mono text-xs">
                    <span className="cursor-blink">LOADING</span>
                  </td></tr>
                )}
                {!loading && runs.length === 0 && (
                  <tr><td colSpan={6} className="text-center py-10 text-[#71717A] text-sm">
                    No runs yet. Click "Run Now" to queue the first one.
                  </td></tr>
                )}
                {runs.map((r) => (
                  <tr key={r.id} data-testid={`label-run-${r.id}`}>
                    <td><StatusPill status={r.status} /></td>
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
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  );
}
