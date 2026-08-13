import { useCallback, useEffect, useMemo, useState } from "react";
import {
  ArrowsClockwiseIcon,
  CheckCircleIcon,
  ClockIcon,
  DownloadSimpleIcon,
  FileArrowUpIcon,
  FilePdfIcon,
  MagnifyingGlassIcon,
  PackageIcon,
  PrinterIcon,
  SlidersIcon,
  TrashIcon,
  UploadSimpleIcon,
  WarningCircleIcon,
  XIcon,
} from "@phosphor-icons/react";
import api, { formatApiError } from "@/lib/api";

// ---------------- Reusable pieces ----------------
function KPI({ icon: Icon, label, value, sub, tint = "" }) {
  return (
    <div className="kpi-card">
      <div className="flex items-start gap-3">
        <div
          className={
            "p-2 rounded-lg " +
            (tint === "green" ? "bg-[rgba(16,185,129,0.10)] text-[#6EE7B7]"
             : tint === "amber" ? "bg-[rgba(245,158,11,0.10)] text-[#FCD34D]"
             : tint === "red" ? "bg-[rgba(239,68,68,0.10)] text-[#FCA5A5]"
             : tint === "blue" ? "bg-[rgba(56,189,248,0.10)] text-[#7DD3FC]"
             : tint === "violet" ? "bg-[rgba(139,92,246,0.10)] text-[#C4B5FD]"
             : "bg-[var(--bg-surface-2)] text-[var(--text-secondary)]")
          }
        >
          {Icon && <Icon size={18} weight="bold" />}
        </div>
        <div className="flex-1 min-w-0">
          <div className="section-label truncate">{label}</div>
          <div className="font-display text-3xl mt-1">{value}</div>
          {sub && <div className="text-[11px] text-[var(--text-muted)] mt-0.5">{sub}</div>}
        </div>
      </div>
    </div>
  );
}

function StaticStepper({ steps, current }) {
  return (
    <div className="flex items-start justify-between gap-2">
      {steps.map((s, i) => {
        const done = i < current;
        const active = i === current;
        return (
          <div key={s.label} className="flex-1 flex flex-col items-center relative">
            {i > 0 && (
              <div
                className="absolute top-3 -left-1/2 w-full h-[2px]"
                style={{
                  background: i <= current
                    ? "var(--accent)"
                    : "var(--border)",
                }}
              />
            )}
            <div
              className={
                "relative z-10 w-6 h-6 rounded-full flex items-center justify-center text-[10px] font-bold " +
                (done ? "bg-[var(--accent)] text-[#052E1F]"
                 : active ? "bg-[var(--accent)] text-[#052E1F] ring-4 ring-[rgba(16,185,129,0.25)]"
                 : "bg-[var(--bg-surface-2)] text-[var(--text-muted)] border border-[var(--border)]")
              }
            >
              {done ? <CheckCircleIcon size={12} weight="fill" /> : i + 1}
            </div>
            <div className="mt-2 text-[10px] font-mono uppercase tracking-wider text-center text-[var(--text-secondary)]">
              {s.label}
            </div>
            <div className="text-[10px] text-[var(--text-muted)] font-mono">{s.time || ""}</div>
          </div>
        );
      })}
    </div>
  );
}

// ---------------- Upload zone ----------------
function UploadZone({ onFilesReady, processing }) {
  const [files, setFiles] = useState([]);
  const [drag, setDrag] = useState(false);

  const add = (list) => {
    const arr = Array.from(list || []).filter(
      (f) => f && f.name && f.name.toLowerCase().endsWith(".pdf")
    );
    setFiles((prev) => [...prev, ...arr]);
  };

  const remove = (i) => setFiles((prev) => prev.filter((_, idx) => idx !== i));

  const submit = () => {
    if (!files.length || processing) return;
    onFilesReady(files, () => setFiles([]));
  };

  return (
    <div className="panel p-5" data-testid="pl-upload-zone">
      <div className="flex items-center gap-2 mb-3">
        <UploadSimpleIcon size={16} weight="bold" color="#10B981" />
        <h3 className="font-display text-base">Upload Meesho Label PDFs</h3>
        <div className="text-[11px] text-[var(--text-muted)] ml-auto">
          Any mix of accounts • Grouped by Product Master SKUs
        </div>
      </div>
      <label
        onDragEnter={(e) => { e.preventDefault(); setDrag(true); }}
        onDragOver={(e) => { e.preventDefault(); setDrag(true); }}
        onDragLeave={() => setDrag(false)}
        onDrop={(e) => {
          e.preventDefault(); setDrag(false);
          add(e.dataTransfer?.files);
        }}
        className={
          "flex flex-col items-center justify-center border-2 border-dashed rounded-lg p-8 cursor-pointer transition-colors " +
          (drag
            ? "border-[var(--accent)] bg-[rgba(16,185,129,0.06)]"
            : "border-[var(--border)] hover:border-[#475569] hover:bg-[var(--bg-surface-2)]")
        }
      >
        <FileArrowUpIcon size={36} weight="light" className="text-[var(--accent)]" />
        <div className="mt-2 text-sm">
          <span className="text-[var(--accent)] font-medium">Click to browse</span>
          <span className="text-[var(--text-secondary)]"> or drag &amp; drop PDF files here</span>
        </div>
        <div className="text-[11px] text-[var(--text-muted)] mt-1">
          Multiple files supported • Only .pdf accepted
        </div>
        <input
          type="file"
          accept="application/pdf"
          multiple
          className="hidden"
          onChange={(e) => add(e.target.files)}
          data-testid="pl-file-input"
        />
      </label>
      {files.length > 0 && (
        <div className="mt-3 flex flex-wrap gap-1" data-testid="pl-file-list">
          {files.map((f, i) => (
            <span key={`${f.name}-${i}`} className="chip chip-info">
              <FilePdfIcon size={10} weight="bold" />
              {f.name}
              <button onClick={() => remove(i)}>
                <XIcon size={10} weight="bold" />
              </button>
            </span>
          ))}
        </div>
      )}
      <div className="mt-4 flex items-center justify-between">
        <div className="text-xs text-[var(--text-muted)] font-mono">
          {files.length} file{files.length !== 1 ? "s" : ""} selected
        </div>
        <button
          disabled={!files.length || processing}
          onClick={submit}
          className="btn-primary text-sm flex items-center gap-2"
          data-testid="pl-process-btn"
        >
          <PrinterIcon size={14} weight="bold" />
          {processing ? "Processing…" : "Sort & Generate Printouts"}
        </button>
      </div>
    </div>
  );
}

// ---------------- Last-run downloads (right under upload) ----------------
function LastRunDownloads({ run }) {
  if (!run || !run.files || !run.files.length) return null;
  const download = async (fname) => {
    const r = await api.get(
      `/pdf-sorter/runs/${run.run_id}/files/${fname}`,
      {
        responseType: "blob",
        // Force fresh request every click so a re-download always works,
        // even after the browser cached the first hit.
        params: { _ts: Date.now() },
        headers: { "Cache-Control": "no-cache", Pragma: "no-cache" },
      }
    );
    const cd = r.headers?.["content-disposition"] || "";
    const match = /filename="?([^"]+)"?/i.exec(cd);
    const name = (match && match[1]) || fname;
    const url = URL.createObjectURL(new Blob([r.data]));
    const a = document.createElement("a");
    a.href = url;
    a.download = name;
    a.rel = "noopener";
    document.body.appendChild(a);
    a.click();
    // Delay revoke until the browser had a chance to consume the URL.
    setTimeout(() => {
      URL.revokeObjectURL(url);
      a.remove();
    }, 4000);
  };
  const stats = [
    { label: "Files", value: run.input_files_count ?? run.total_files ?? "—" },
    { label: "Labels", value: run.total_pages ?? "—" },
    { label: "Orders", value: run.unique_orders ?? "—" },
    { label: "Matched", value: (run.total_pages ?? 0) - (run.unmatched ?? run.unknown_sku ?? 0), color: "text-[#6EE7B7]" },
    { label: "Unmatched", value: run.unmatched ?? run.unknown_sku ?? 0, color: "text-[#FCD34D]" },
  ];
  const files = ["MASTER_PRINT.pdf", "TIER1_HIGH_VOLUME.pdf", "TIER2_LOW_VOLUME.pdf"]
    .filter((f) => run.files.includes(f));
  const labels = {
    "MASTER_PRINT.pdf": "Master Print",
    "TIER1_HIGH_VOLUME.pdf": "Tier 1 · High Volume",
    "TIER2_LOW_VOLUME.pdf": "Tier 2 · Low Volume",
  };
  return (
    <div
      className="panel p-4"
      style={{
        background: "linear-gradient(180deg, rgba(16,185,129,0.06) 0%, var(--bg-surface) 100%)",
        borderColor: "rgba(16,185,129,0.35)",
      }}
      data-testid="pl-last-run"
    >
      <div className="flex items-center gap-2 mb-3">
        <CheckCircleIcon size={16} weight="fill" color="#10B981" />
        <h3 className="font-display text-sm text-[#6EE7B7]">Latest Run — ready to download</h3>
        {run.created_at && (
          <span className="text-[10px] text-[var(--text-muted)] font-mono">
            {new Date(run.created_at).toLocaleString()}
          </span>
        )}
        <span className="text-[10px] text-[var(--text-muted)] font-mono ml-auto">
          {run.run_id}
        </span>
      </div>
      <div className="flex flex-wrap items-center gap-3 mb-3">
        {stats.map((s) => (
          <div key={s.label} className="flex flex-col">
            <span className={"font-display text-lg " + (s.color || "")}>{s.value}</span>
            <span className="section-label">{s.label}</span>
          </div>
        ))}
      </div>
      <div className="flex flex-wrap gap-2">
        {files.map((f) => (
          <button
            key={f}
            onClick={() => download(f)}
            className="btn-primary text-xs flex items-center gap-2"
            data-testid={`pl-latest-dl-${f}`}
          >
            <DownloadSimpleIcon size={12} weight="bold" />
            {labels[f] || f}
          </button>
        ))}
      </div>
    </div>
  );
}

// ---------------- Downloads history strip ----------------
function DownloadsPanel({ items, onRefresh, onReset }) {
  const download = async (runId, fname) => {
    const r = await api.get(
      `/pdf-sorter/runs/${runId}/files/${fname}`,
      {
        responseType: "blob",
        params: { _ts: Date.now() },
        headers: { "Cache-Control": "no-cache", Pragma: "no-cache" },
      }
    );
    // Backend already appends timestamp to Content-Disposition. Just use the
    // filename it sends back.
    const cd = r.headers?.["content-disposition"] || "";
    const match = /filename="?([^"]+)"?/i.exec(cd);
    const name = (match && match[1]) || fname;
    const url = URL.createObjectURL(new Blob([r.data]));
    const a = document.createElement("a");
    a.href = url;
    a.download = name;
    a.rel = "noopener";
    document.body.appendChild(a);
    a.click();
    setTimeout(() => { URL.revokeObjectURL(url); a.remove(); }, 4000);
  };
  return (
    <div className="panel p-4" data-testid="pl-downloads-panel">
      <div className="flex items-center gap-2 mb-3">
        <DownloadSimpleIcon size={14} weight="bold" color="#10B981" />
        <h3 className="font-display text-sm">Recent Downloads · Last 7 days</h3>
        <div className="ml-auto flex items-center gap-2">
          <button onClick={onRefresh} className="btn-ghost text-xs flex items-center gap-1">
            <ArrowsClockwiseIcon size={11} weight="bold" /> Refresh
          </button>
          <button
            onClick={onReset}
            className="btn-danger text-xs flex items-center gap-1"
            data-testid="pl-reset-btn"
            title="Wipe all past runs — files and history"
          >
            <TrashIcon size={11} weight="bold" /> Reset all runs
          </button>
        </div>
      </div>
      {items.length === 0 ? (
        <div className="text-center py-4 text-[var(--text-muted)] text-xs">
          No printouts in the last 7 days.
        </div>
      ) : (
        <div className="table-wrap">
          <table className="dense">
            <thead>
              <tr>
                <th>When</th>
                <th className="num">Files</th>
                <th className="num">Labels</th>
                <th className="num">Orders</th>
                <th className="num">Unmatched</th>
                <th>Download</th>
              </tr>
            </thead>
            <tbody>
              {items.map((r) => (
                <tr key={r.run_id} data-testid={`pl-recent-${r.run_id}`}>
                  <td className="text-xs">
                    {r.created_at ? new Date(r.created_at).toLocaleString() : "—"}
                  </td>
                  <td className="num">{r.total_files || 0}</td>
                  <td className="num">{r.total_pages || 0}</td>
                  <td className="num">{r.unique_orders || 0}</td>
                  <td className="num">
                    {r.unknown_sku ? (
                      <span className="chip chip-warn">{r.unknown_sku}</span>
                    ) : (
                      <span className="text-[var(--text-muted)]">0</span>
                    )}
                  </td>
                  <td>
                    <div className="flex gap-1 flex-wrap">
                      {(r.files || []).map((f) => (
                        <button
                          key={f}
                          onClick={() => download(r.run_id, f)}
                          className="btn-ghost text-[10px] flex items-center gap-1"
                          data-testid={`pl-dl-${r.run_id}-${f}`}
                        >
                          <DownloadSimpleIcon size={10} weight="bold" />
                          {f.replace(".pdf", "").replace(/_/g, " ")}
                        </button>
                      ))}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <div className="text-[10px] text-[var(--text-muted)] mt-2 font-mono">
        Files older than 7 days are auto-purged. Download filenames include the local timestamp.
      </div>
    </div>
  );
}

// ---------------- Overrides collapsible ----------------
function OverridesPanel() {
  const [open, setOpen] = useState(false);
  const [cfg, setCfg] = useState({ sku_normalization: [], courier_rules: [] });
  const [err, setErr] = useState("");
  const [skuDraft, setSkuDraft] = useState({ raw_sku: "", normalized_sku: "" });
  const [courierDraft, setCourierDraft] = useState({ courier_name: "", match_text: "" });

  const load = useCallback(async () => {
    try {
      const { data } = await api.get("/pdf-sorter/config");
      setCfg(data);
    } catch (e) { setErr(formatApiError(e)); }
  }, []);
  useEffect(() => { if (open) load(); }, [open, load]);

  const addSku = async () => {
    if (!skuDraft.raw_sku || !skuDraft.normalized_sku) return;
    try { await api.post("/pdf-sorter/config/sku", skuDraft); setSkuDraft({ raw_sku: "", normalized_sku: "" }); await load(); }
    catch (e) { setErr(formatApiError(e)); }
  };
  const delSku = async (raw) => {
    if (!window.confirm(`Delete override for ${raw}?`)) return;
    try { await api.delete(`/pdf-sorter/config/sku/${encodeURIComponent(raw)}`); await load(); }
    catch (e) { setErr(formatApiError(e)); }
  };
  const addCourier = async () => {
    if (!courierDraft.courier_name || !courierDraft.match_text) return;
    try { await api.post("/pdf-sorter/config/courier", courierDraft); setCourierDraft({ courier_name: "", match_text: "" }); await load(); }
    catch (e) { setErr(formatApiError(e)); }
  };
  const delCourier = async (nm) => {
    if (!window.confirm(`Delete rule for ${nm}?`)) return;
    try { await api.delete(`/pdf-sorter/config/courier/${encodeURIComponent(nm)}`); await load(); }
    catch (e) { setErr(formatApiError(e)); }
  };

  return (
    <div className="panel" data-testid="pl-overrides-panel">
      <button
        onClick={() => setOpen((o) => !o)}
        className="w-full flex items-center gap-2 p-4 text-left"
        data-testid="pl-overrides-toggle"
      >
        <SlidersIcon size={14} weight="bold" color="#10B981" />
        <h3 className="font-display text-sm">Overrides &amp; Courier Rules</h3>
        <span className="text-[11px] text-[var(--text-muted)] ml-2">
          Optional — for SKUs not in Product Master and courier text matching
        </span>
        <span className="ml-auto text-xs text-[var(--text-muted)]">
          {open ? "Hide" : "Show"}
        </span>
      </button>
      {open && (
        <div className="p-4 pt-0 space-y-4">
          {err && (
            <div className="border border-[rgba(239,68,68,0.35)] bg-[rgba(239,68,68,0.1)] px-3 py-2 font-mono text-xs text-[#FCA5A5]">
              {err}
            </div>
          )}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div className="space-y-2">
              <div className="section-label">/ sku overrides</div>
              <div className="flex items-end gap-2">
                <input placeholder="Raw SKU" value={skuDraft.raw_sku}
                  onChange={(e) => setSkuDraft({ ...skuDraft, raw_sku: e.target.value })}
                  className="input-shell font-mono text-xs flex-1" data-testid="pl-ovr-sku-raw" />
                <input placeholder="Group label" value={skuDraft.normalized_sku}
                  onChange={(e) => setSkuDraft({ ...skuDraft, normalized_sku: e.target.value })}
                  className="input-shell font-mono text-xs flex-1" data-testid="pl-ovr-sku-norm" />
                <button onClick={addSku} className="btn-primary text-xs" data-testid="pl-ovr-sku-add">Add</button>
              </div>
              <div className="table-wrap max-h-56">
                <table className="dense">
                  <thead><tr><th>Raw</th><th>Group</th><th></th></tr></thead>
                  <tbody>
                    {cfg.sku_normalization.length === 0 && (
                      <tr><td colSpan={3} className="text-center py-3 text-[var(--text-muted)]">None</td></tr>
                    )}
                    {cfg.sku_normalization.map((r) => (
                      <tr key={r.raw_sku}>
                        <td className="font-mono text-[11px]">{r.raw_sku}</td>
                        <td className="font-mono text-[11px] text-[#6EE7B7]">{r.normalized_sku}</td>
                        <td className="text-right">
                          <button onClick={() => delSku(r.raw_sku)} className="btn-ghost hover:text-[var(--status-failed)]">
                            <TrashIcon size={11} weight="bold" />
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
            <div className="space-y-2">
              <div className="section-label">/ courier rules</div>
              <div className="flex items-end gap-2">
                <input placeholder="Courier" value={courierDraft.courier_name}
                  onChange={(e) => setCourierDraft({ ...courierDraft, courier_name: e.target.value })}
                  className="input-shell font-mono text-xs flex-1" data-testid="pl-ovr-cr-name" />
                <input placeholder="Match text" value={courierDraft.match_text}
                  onChange={(e) => setCourierDraft({ ...courierDraft, match_text: e.target.value })}
                  className="input-shell font-mono text-xs flex-1" data-testid="pl-ovr-cr-match" />
                <button onClick={addCourier} className="btn-primary text-xs" data-testid="pl-ovr-cr-add">Add</button>
              </div>
              <div className="table-wrap max-h-56">
                <table className="dense">
                  <thead><tr><th>Courier</th><th>Match</th><th></th></tr></thead>
                  <tbody>
                    {cfg.courier_rules.length === 0 && (
                      <tr><td colSpan={3} className="text-center py-3 text-[var(--text-muted)]">None</td></tr>
                    )}
                    {cfg.courier_rules.map((r) => (
                      <tr key={r.courier_name}>
                        <td className="font-mono text-[11px]">{r.courier_name}</td>
                        <td className="font-mono text-[11px]">{r.match_text}</td>
                        <td className="text-right">
                          <button onClick={() => delCourier(r.courier_name)} className="btn-ghost hover:text-[var(--status-failed)]">
                            <TrashIcon size={11} weight="bold" />
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

// ---------------- Main page ----------------
export default function PrintoutLabelsPage() {
  const [analytics, setAnalytics] = useState(null);
  const [recent, setRecent] = useState([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState("");
  const [processing, setProcessing] = useState(false);
  const [runResult, setRunResult] = useState(null);
  const [q, setQ] = useState("");
  const [qLive, setQLive] = useState("");
  const [showUnmatched, setShowUnmatched] = useState(false);
  // Date range filter — default TODAY so the KPIs reflect the latest batch,
  // not everything ever uploaded.
  const today = new Date().toISOString().slice(0, 10);
  const [startDate, setStartDate] = useState(today);
  const [endDate, setEndDate] = useState(today);

  useEffect(() => {
    const t = setTimeout(() => setQ(qLive), 300);
    return () => clearTimeout(t);
  }, [qLive]);

  const setPreset = (kind) => {
    const d = new Date();
    const iso = (n) => new Date(d.getTime() - n * 86400000).toISOString().slice(0, 10);
    if (kind === "today") { setStartDate(iso(0)); setEndDate(iso(0)); }
    else if (kind === "yesterday") { setStartDate(iso(1)); setEndDate(iso(1)); }
    else if (kind === "7d") { setStartDate(iso(6)); setEndDate(iso(0)); }
    else if (kind === "30d") { setStartDate(iso(29)); setEndDate(iso(0)); }
    else if (kind === "all") { setStartDate(""); setEndDate(""); }
  };

  const loadAll = useCallback(async () => {
    setLoading(true); setErr("");
    try {
      const p = new URLSearchParams();
      if (q) p.append("q", q);
      if (startDate) p.append("start_date", startDate);
      if (endDate) p.append("end_date", endDate);
      const [a, r] = await Promise.all([
        api.get(`/pdf-sorter/analytics?${p.toString()}`),
        api.get("/pdf-sorter/recent-runs"),
      ]);
      setAnalytics(a.data);
      setRecent(r.data.items || []);
    } catch (e) {
      setErr(formatApiError(e));
    } finally {
      setLoading(false);
    }
  }, [q, startDate, endDate]);

  useEffect(() => { loadAll(); }, [loadAll]);

  const resetAll = async () => {
    if (!window.confirm("Delete ALL past runs, files and history? This cannot be undone.")) return;
    try {
      await api.post("/pdf-sorter/admin/reset");
      setRunResult(null);
      await loadAll();
    } catch (e) { setErr(formatApiError(e)); }
  };

  const process = async (files, clearFiles) => {
    setProcessing(true); setErr(""); setRunResult(null);
    try {
      const fd = new FormData();
      files.forEach((f) => fd.append("files", f));
      const { data } = await api.post("/pdf-sorter/process", fd, {
        headers: { "Content-Type": "multipart/form-data" },
        timeout: 600000,
      });
      setRunResult(data);
      clearFiles();
      // Ensure "today" is in the filter window so the fresh run shows up
      const t = new Date().toISOString().slice(0, 10);
      if (endDate && endDate < t) setEndDate(t);
      await loadAll();
    } catch (e) {
      setErr(formatApiError(e));
    } finally {
      setProcessing(false);
    }
  };

  // KPIs and tables ALWAYS reflect the current date window (default: today).
  // A fresh runResult only exposes download buttons + warnings; it does not
  // override the window numbers, so cumulative math stays consistent.
  const total_files = analytics?.total_files ?? 0;
  const total_pages = analytics?.total_pages ?? 0;
  const unknown = analytics?.unknown_sku_total ?? 0;
  const sorted = Math.max(0, total_pages - unknown);
  const groups_filled = analytics?.groups_filled ?? 0;
  const groups_total = analytics?.groups_total ?? 0;
  const unique_orders = analytics?.unique_orders ?? 0;

  // Tables: analytics endpoint aggregates within the window.
  const courierRows = analytics?.courier_totals || [];
  const skuRows = analytics?.sku_totals || [];

  const courierTotal = courierRows.reduce((s, r) => s + r.count, 0) || 1;
  const skuTotal = skuRows.reduce((s, r) => s + r.count, 0) || 1;

  const unmatchedRows = runResult?.unmatched_skus
    || analytics?.latest_run?.unmatched_skus
    || [];

  const stepper = [
    { label: "Uploaded" }, { label: "Read" },
    { label: "Matched" }, { label: "Sorted" }, { label: "Done" },
  ];
  const step = runResult ? 5 : (analytics?.latest_run ? 5 : 0);

  return (
    <div className="px-8 py-6 space-y-5" data-testid="printout-labels-page">
      <div className="flex items-start justify-between gap-4">
        <div className="flex items-center gap-2">
          <PrinterIcon size={22} weight="bold" color="#10B981" />
          <div>
            <h2 className="font-display text-xl">Printout Labels</h2>
            <div className="text-xs text-[var(--text-muted)]">
              Upload Meesho label PDFs, sort by Product Master SKUs, download TIER1 / TIER2 / MASTER printouts.
            </div>
          </div>
        </div>
        <div className="relative w-72">
          <MagnifyingGlassIcon size={13} weight="bold"
            className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--text-muted)]" />
          <input
            value={qLive}
            onChange={(e) => setQLive(e.target.value)}
            placeholder="Search SKUs or couriers…"
            className="input-shell font-mono text-xs pl-8"
            data-testid="pl-search"
          />
        </div>
      </div>

      {err && (
        <div className="border border-[rgba(239,68,68,0.35)] bg-[rgba(239,68,68,0.1)] px-3 py-2 font-mono text-xs text-[#FCA5A5]">
          {err}
        </div>
      )}

      {/* Upload zone — always visible on top */}
      <UploadZone onFilesReady={process} processing={processing} />

      {/* Downloads directly under upload (per user request) — from LATEST run */}
      {(runResult || analytics?.latest_run) && (
        <LastRunDownloads
          run={runResult ? {
            run_id: runResult.run_id,
            created_at: null,
            total_pages: runResult.total_pages,
            unknown_sku: runResult.unknown_sku,
            unique_orders: runResult.unique_orders,
            files: runResult.files,
          } : analytics.latest_run}
        />
      )}

      {/* Date range filter — controls all KPIs and tables below */}
      <div className="panel p-3 flex flex-wrap items-center gap-2" data-testid="pl-date-filter">
        <SlidersIcon size={13} weight="bold" color="#10B981" />
        <span className="section-label">/ date range</span>
        <input
          type="date"
          value={startDate}
          onChange={(e) => setStartDate(e.target.value)}
          className="input-shell font-mono text-xs w-40"
          data-testid="pl-date-start"
        />
        <span className="text-[var(--text-muted)] text-xs">→</span>
        <input
          type="date"
          value={endDate}
          onChange={(e) => setEndDate(e.target.value)}
          className="input-shell font-mono text-xs w-40"
          data-testid="pl-date-end"
        />
        <div className="flex gap-1 ml-2">
          {[
            ["today", "Today"], ["yesterday", "Yesterday"],
            ["7d", "7d"], ["30d", "30d"], ["all", "All time"],
          ].map(([k, l]) => (
            <button
              key={k}
              onClick={() => setPreset(k)}
              className="btn-ghost text-[10px] font-mono uppercase"
              data-testid={`pl-preset-${k}`}
            >
              {l}
            </button>
          ))}
        </div>
        <div className="ml-auto text-[10px] text-[var(--text-muted)] font-mono">
          {loading ? "loading…" : `${analytics?.total_runs || 0} run${analytics?.total_runs === 1 ? "" : "s"} in window`}
        </div>
      </div>

      {/* Sorting stepper (static, always visible after any run exists) */}
      {step > 0 && (
        <div className="panel p-4" data-testid="pl-stepper">
          <div className="section-label mb-3">/ sorting progress</div>
          <StaticStepper steps={stepper} current={step} />
        </div>
      )}

      {/* KPIs */}
      <div className="grid grid-cols-2 md:grid-cols-6 gap-3">
        <KPI icon={FilePdfIcon} label="Total Files" value={total_files}
             sub="Uploaded" tint="blue" />
        <KPI icon={PrinterIcon} label="Total Labels" value={total_pages}
             sub="All Files Combined" tint="green" />
        <KPI icon={CheckCircleIcon} label="Sorted Labels" value={sorted}
             sub={total_pages > 0 ? `${((sorted / total_pages) * 100).toFixed(1)}% of Total` : "—"}
             tint="green" />
        <KPI icon={WarningCircleIcon} label="Unmatched" value={unknown}
             sub={total_pages > 0 ? `${((unknown / total_pages) * 100).toFixed(1)}% of Total` : "—"}
             tint="amber" />
        <KPI icon={PackageIcon} label="Groups Filled" value={`${groups_filled} / ${groups_total}`}
             sub={groups_total > 0
               ? `${((groups_filled / groups_total) * 100).toFixed(0)}% Completed`
               : "No products yet"}
             tint="violet" />
        <KPI icon={PackageIcon} label="Total Packages" value={unique_orders}
             sub="Shippable" tint="blue" />
      </div>

      {/* Tables */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        <div className="panel p-4">
          <div className="flex items-center gap-2 mb-3">
            <PrinterIcon size={13} weight="bold" color="#10B981" />
            <h3 className="font-display text-sm">Courier Partner Orders</h3>
            <span className="text-[10px] text-[var(--text-muted)] font-mono ml-1">
              ({courierRows.length})
            </span>
          </div>
          <div className="table-wrap max-h-[420px]">
            <table className="dense">
              <thead>
                <tr><th>Courier</th><th className="num">Orders</th><th className="num">%</th></tr>
              </thead>
              <tbody>
                {courierRows.length === 0 && (
                  <tr><td colSpan={3} className="text-center py-6 text-[var(--text-muted)]">no data</td></tr>
                )}
                {courierRows.map((c) => (
                  <tr key={c.name} data-testid={`pl-cr-${c.name}`}>
                    <td className="font-mono text-[11px]">{c.name}</td>
                    <td className="num font-mono">{c.count}</td>
                    <td className="num font-mono text-[var(--text-muted)]">
                      {((c.count / courierTotal) * 100).toFixed(1)}%
                    </td>
                  </tr>
                ))}
                {courierRows.length > 1 && (
                  <tr>
                    <td className="font-mono text-[11px] text-[var(--accent)]">Total</td>
                    <td className="num font-mono text-[var(--accent)]">{courierTotal}</td>
                    <td className="num font-mono text-[var(--accent)]">100%</td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>

        <div className="panel p-4">
          <div className="flex items-center gap-2 mb-3">
            <PackageIcon size={13} weight="bold" color="#10B981" />
            <h3 className="font-display text-sm">Product / SKU Orders</h3>
            <span className="text-[10px] text-[var(--text-muted)] font-mono ml-1">
              ({skuRows.length} unique)
            </span>
          </div>
          <div className="table-wrap max-h-[420px]">
            <table className="dense">
              <thead>
                <tr><th>SKU / Product</th><th className="num">Orders</th></tr>
              </thead>
              <tbody>
                {skuRows.length === 0 && (
                  <tr><td colSpan={2} className="text-center py-6 text-[var(--text-muted)]">no data</td></tr>
                )}
                {skuRows.map((c) => (
                  <tr key={c.name} data-testid={`pl-sku-${c.name}`}>
                    <td className="font-mono text-[11px]">{c.name}</td>
                    <td className="num font-mono">{c.count}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>

      {/* Unmatched alert */}
      {unmatchedRows.length > 0 && (
        <div
          className="panel p-4 border-[rgba(245,158,11,0.35)]"
          style={{ background: "rgba(245,158,11,0.06)" }}
          data-testid="pl-unmatched"
        >
          <div className="flex items-center gap-2">
            <WarningCircleIcon size={16} weight="bold" color="#FCD34D" />
            <h3 className="font-display text-sm text-[#FCD34D]">
              Unmatched Labels ({unmatchedRows.length})
            </h3>
            <button
              onClick={() => setShowUnmatched((o) => !o)}
              className="btn-secondary text-xs ml-auto"
              data-testid="pl-unmatched-toggle"
            >
              {showUnmatched ? "Hide list" : "View list"}
            </button>
          </div>
          <div className="text-[11px] text-[var(--text-secondary)] mt-1">
            These raw SKUs could not be matched to any product in Master. Add them in <span className="code-tag">Product Master</span>.
          </div>
          {showUnmatched && (
            <div className="mt-3 flex flex-wrap gap-1 max-h-40 overflow-y-auto">
              {unmatchedRows.slice(0, 500).map((u) => (
                <span key={u.sku} className="chip chip-warn">
                  {u.sku}{u.count > 1 && (
                    <span className="opacity-70 font-mono text-[9px]">×{u.count}</span>
                  )}
                </span>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Warnings — CANCELLED / RTO from most recent run */}
      {(runResult?.warnings || []).length > 0 && (
        <div className="border border-[rgba(245,158,11,0.35)] bg-[rgba(245,158,11,0.1)] p-3 rounded text-xs">
          <div className="font-semibold text-[#FCD34D] mb-1 flex items-center gap-1">
            <WarningCircleIcon size={12} weight="bold" /> Warnings — orders already CANCELLED / RTO in P&amp;L
          </div>
          <div className="space-y-0.5 max-h-40 overflow-y-auto">
            {runResult.warnings.map((w, i) => (
              <div key={i} className="font-mono text-[11px]">
                {w.order_no} — <span className="text-[#FCA5A5]">{w.status}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Downloads history */}
      <DownloadsPanel items={recent} onRefresh={loadAll} onReset={resetAll} />

      {/* Overrides */}
      <OverridesPanel />
    </div>
  );
}
