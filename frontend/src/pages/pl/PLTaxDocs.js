import { useEffect, useState, useCallback } from "react";
import {
  ArrowsClockwiseIcon, TrashIcon, FileXlsIcon, FileZipIcon,
  CloudArrowDownIcon, ShareNetworkIcon, CopyIcon, CheckCircleIcon, XCircleIcon,
} from "@phosphor-icons/react";
import api, { formatApiError } from "@/lib/api";
import { usePL } from "./PLLayout";

const MONTHS = [
  { v: 1, n: "January" }, { v: 2, n: "February" }, { v: 3, n: "March" },
  { v: 4, n: "April" }, { v: 5, n: "May" }, { v: 6, n: "June" },
  { v: 7, n: "July" }, { v: 8, n: "August" }, { v: 9, n: "September" },
  { v: 10, n: "October" }, { v: 11, n: "November" }, { v: 12, n: "December" },
];

const YEARS = (() => {
  const y = new Date().getFullYear();
  return [y - 2, y - 1, y, y + 1];
})();

function ShareLinkButton({ kind, recId }) {
  const [busy, setBusy] = useState(false);
  const [url, setUrl] = useState("");
  const [exp, setExp] = useState("");
  const [copied, setCopied] = useState(false);
  const onShare = async () => {
    setBusy(true);
    try {
      const { data } = await api.post(`/pl/${kind}/${recId}/share`);
      setUrl(data.url); setExp(data.expires_at);
    } catch (e) { alert(formatApiError(e)); }
    finally { setBusy(false); }
  };
  const onCopy = async () => {
    try { await navigator.clipboard.writeText(url); setCopied(true); setTimeout(() => setCopied(false), 1800); } catch {}
  };
  if (!url) {
    return (
      <button onClick={onShare} disabled={busy}
        className="btn-ghost text-xs flex items-center gap-1"
        data-testid={`share-${kind}-${recId}`}>
        <ShareNetworkIcon size={12} weight="bold" />
        {busy ? "…" : "Share"}
      </button>
    );
  }
  return (
    <div className="flex items-center gap-1 max-w-[260px]">
      <input readOnly value={url}
        className="input-shell text-[10px] font-mono flex-1 truncate"
        title={`expires ${exp}`} />
      <button onClick={onCopy} className="btn-ghost text-xs flex items-center gap-1">
        {copied ? <CheckCircleIcon size={12} color="#00E676" weight="bold" /> : <CopyIcon size={12} weight="bold" />}
      </button>
    </div>
  );
}

function DocPanel({ title, kind, accentColor }) {
  const { accountId, accounts, reloadAccounts } = usePL();
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [picked, setPicked] = useState(accountId !== "all" ? accountId : "");
  const [year, setYear] = useState(new Date().getFullYear());
  const [month, setMonth] = useState(new Date().getMonth() || 12); // default to current-month-ish; user must pick explicitly
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(""); const [msg, setMsg] = useState("");

  useEffect(() => {
    if (accountId !== "all") setPicked(accountId);
  }, [accountId]);

  const load = useCallback(async () => {
    setLoading(true); setErr("");
    try {
      const url = `/pl/${kind}${accountId && accountId !== "all" ? `?account_id=${accountId}` : ""}`;
      const { data } = await api.get(url);
      setItems(data.items || []);
    } catch (e) { setErr(formatApiError(e)); }
    finally { setLoading(false); }
  }, [accountId, kind]);

  useEffect(() => { reloadAccounts(); load(); }, [load, reloadAccounts]);

  const fetchNow = async () => {
    if (!picked) { setErr("Select an account first."); return; }
    if (!year || !month) { setErr("Pick year and month."); return; }
    setBusy(true); setErr(""); setMsg("");
    try {
      const ep = kind === "gst-report" ? "/pl/gst-report/fetch-now" : "/pl/tax-invoice/fetch-now";
      const { data } = await api.post(ep, { account_id: picked, year: Number(year), month: Number(month) });
      const dup = data.duplicate ? " (already pending)" : "";
      setMsg(`Job queued${dup}: ${data.job_id}. Watch the Jobs page for progress.`);
      setTimeout(() => setMsg(""), 6000);
    } catch (e) { setErr(formatApiError(e)); }
    finally { setBusy(false); }
  };

  const onDelete = async (id) => {
    if (!window.confirm("Delete this record (and its file)? This cannot be undone.")) return;
    try {
      await api.delete(`/pl/${kind}/${id}`);
      await load();
    } catch (e) { setErr(formatApiError(e)); }
  };

  const download = async (rec) => {
    try {
      const resp = await api.get(`/pl/${kind}/${rec.id}/download`, { responseType: "blob" });
      const url = window.URL.createObjectURL(new Blob([resp.data]));
      const a = document.createElement("a");
      a.href = url;
      a.download = rec.stored_filename || `${kind}_${rec.id}`;
      document.body.appendChild(a); a.click(); a.remove();
      setTimeout(() => window.URL.revokeObjectURL(url), 1000);
    } catch (e) { setErr(formatApiError(e)); }
  };

  const accLabel = (a) => a.alias ? `${a.alias} (${a.name})` : a.name;
  const fmtDt = (s) => s ? new Date(s).toLocaleString() : "—";

  return (
    <div className="panel p-5 space-y-4" data-testid={`${kind}-panel`}>
      <div className="flex items-center justify-between">
        <div className="font-display text-base">{title}</div>
        <span className={`code-tag border-[${accentColor}]/40 text-[${accentColor}]`}>{items.length}</span>
      </div>
      <div className="text-[11px] text-[#A1A1AA]">
        On-demand fetch from Meesho. Cron auto-runs every day <span className="code-tag">7th–15th 02:00 IST</span> for the previous month
        and keeps retrying daily until a file is generated. Files are stored on the dashboard and a 7-day signed URL can be created
        for sharing with your CA.
      </div>

      <div className="flex flex-wrap gap-3 items-end">
        <div className="min-w-[180px]">
          <div className="section-label mb-1">/ account</div>
          <select value={picked} onChange={(e) => setPicked(e.target.value)}
            className="input-shell font-mono text-xs w-full" data-testid={`${kind}-account`}>
            <option value="">Select account…</option>
            {accounts.map((a) => <option key={a.id} value={a.id}>{accLabel(a)}</option>)}
          </select>
        </div>
        <div className="min-w-[110px]">
          <div className="section-label mb-1">/ year</div>
          <select value={year} onChange={(e) => setYear(e.target.value)}
            className="input-shell font-mono text-xs w-full" data-testid={`${kind}-year`}>
            {YEARS.map((y) => <option key={y} value={y}>{y}</option>)}
          </select>
        </div>
        <div className="min-w-[140px]">
          <div className="section-label mb-1">/ month</div>
          <select value={month} onChange={(e) => setMonth(e.target.value)}
            className="input-shell font-mono text-xs w-full" data-testid={`${kind}-month`}>
            {MONTHS.map((m) => <option key={m.v} value={m.v}>{m.n}</option>)}
          </select>
        </div>
        <button onClick={fetchNow} disabled={!picked || busy}
          className={`btn-primary text-xs flex items-center gap-2 ${(!picked || busy) ? "opacity-50 pointer-events-none" : ""}`}
          data-testid={`${kind}-fetch-btn`}>
          <CloudArrowDownIcon size={14} weight="bold" />
          {busy ? "Queueing…" : `Fetch ${title}`}
        </button>
      </div>

      {msg && <div className="border border-[#00E676]/30 bg-[#00E676]/10 px-3 py-2 font-mono text-xs text-[#00E676]">{msg}</div>}
      {err && <div className="border border-[#FF3B30]/30 bg-[#FF3B30]/10 px-3 py-2 font-mono text-xs text-[#FF3B30]">{err}</div>}

      <div className="overflow-x-auto -mx-5 -mb-5 border-t border-[#2A2A2A]">
        <table className="dense">
          <thead>
            <tr>
              <th>Status</th>
              <th>Account</th>
              <th>Period</th>
              <th>File</th>
              <th>Fetched</th>
              <th className="text-right">Actions</th>
            </tr>
          </thead>
          <tbody>
            {loading && <tr><td colSpan={6} className="text-center py-8 text-[#71717A] font-mono text-xs"><span className="cursor-blink">LOADING</span></td></tr>}
            {!loading && items.length === 0 && (
              <tr><td colSpan={6} className="text-center py-10 text-[#71717A] text-sm">
                No {title.toLowerCase()} fetched yet.
              </td></tr>
            )}
            {items.map((r) => (
              <tr key={r.id} data-testid={`${kind}-row-${r.id}`}>
                <td>
                  {r.available ? (
                    <span className="inline-flex items-center gap-1 text-[#00E676] font-mono text-[10px]">
                      <CheckCircleIcon size={12} weight="bold" /> AVAILABLE
                    </span>
                  ) : (
                    <span className="inline-flex items-center gap-1 text-[#F5A623] font-mono text-[10px]" title={r.reason || ""}>
                      <XCircleIcon size={12} weight="bold" /> NO DATA
                    </span>
                  )}
                </td>
                <td className="font-mono text-[11px] text-[#A1A1AA]">{r.account_name}</td>
                <td className="font-mono text-[11px]">{r.period}</td>
                <td className="font-mono text-[10px] text-white">
                  {r.available ? (
                    <div className="flex items-center gap-1">
                      {r.stored_filename?.endsWith(".zip") ? <FileZipIcon size={12} color="#F5A623" weight="bold" /> : <FileXlsIcon size={12} color="#00E676" weight="bold" />}
                      <span className="truncate max-w-[260px]" title={r.stored_filename}>{r.stored_filename}</span>
                    </div>
                  ) : (
                    <span className="text-[#71717A] truncate max-w-[260px]" title={r.reason}>{r.reason || "—"}</span>
                  )}
                </td>
                <td className="font-mono text-[10px] text-[#71717A]">{fmtDt(r.fetched_at)}</td>
                <td className="text-right">
                  <div className="flex items-center justify-end gap-1">
                    {r.available && (
                      <>
                        <button onClick={() => download(r)}
                          className="btn-ghost text-xs flex items-center gap-1"
                          data-testid={`download-${kind}-${r.id}`}>
                          <CloudArrowDownIcon size={12} weight="bold" /> Download
                        </button>
                        <ShareLinkButton kind={kind} recId={r.id} />
                      </>
                    )}
                    <button onClick={() => onDelete(r.id)}
                      className="btn-ghost text-xs flex items-center gap-1 hover:text-[#FF3B30]"
                      data-testid={`del-${kind}-${r.id}`}>
                      <TrashIcon size={12} weight="bold" />
                    </button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export default function PLTaxDocs() {
  const { reloadAccounts } = usePL();
  return (
    <div className="px-8 py-6 space-y-6" data-testid="pl-tax-docs-page">
      <div className="flex items-center justify-between">
        <div className="text-[11px] text-[#A1A1AA] max-w-3xl">
          Auto-fetch monthly <span className="code-tag text-[#00E676]">GST Report</span> and{" "}
          <span className="code-tag text-[#A78BFA]">Tax Invoice</span> ZIPs/Excels from Meesho's supplier panel and share them
          with your CA via expiring 7-day links.
        </div>
        <button onClick={reloadAccounts} className="btn-ghost text-xs flex items-center gap-1">
          <ArrowsClockwiseIcon size={12} weight="bold" /> Refresh
        </button>
      </div>
      <DocPanel title="GST Report" kind="gst-report" accentColor="#00E676" />
      <DocPanel title="Tax Invoice" kind="tax-invoice" accentColor="#A78BFA" />
    </div>
  );
}
