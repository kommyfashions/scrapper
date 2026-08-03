import { useCallback, useEffect, useMemo, useState } from "react";
import {
  ArrowsClockwiseIcon,
  DownloadSimpleIcon,
  FileArrowUpIcon,
  MagnifyingGlassIcon,
  PrinterIcon,
  TrashIcon,
  WarningCircleIcon,
  XIcon,
  ChartBarIcon,
} from "@phosphor-icons/react";
import api, { formatApiError } from "@/lib/api";

const TABS = [
  { k: "process", label: "Sort & Print" },
  { k: "analytics", label: "Analytics" },
  { k: "overrides", label: "Overrides" },
];

// ============================================================================
// Sort & Print tab
// ============================================================================
function ProcessTab() {
  const [files, setFiles] = useState([]);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);
  const [err, setErr] = useState("");

  const process = async () => {
    if (!files.length) return;
    setBusy(true); setErr(""); setResult(null);
    try {
      const fd = new FormData();
      files.forEach((f) => fd.append("files", f));
      const { data } = await api.post("/pdf-sorter/process", fd, {
        headers: { "Content-Type": "multipart/form-data" },
        timeout: 300000,
      });
      setResult(data);
    } catch (e) {
      setErr(formatApiError(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-4" data-testid="pl-process-tab">
      <div className="panel p-5 space-y-4">
        <div className="text-xs text-[var(--text-secondary)]">
          Upload one or many Meesho label PDFs from <b>any account</b>. Labels
          are grouped by their SKU using the <span className="code-tag">Product Master</span> mapping so
          the same product across accounts prints together. High-volume groups
          (≥10 pages) get an upside-down separator on the last page.
        </div>
        <div className="flex flex-wrap items-end gap-3">
          <label className="btn-secondary text-xs flex items-center gap-2 cursor-pointer">
            <FileArrowUpIcon size={14} weight="bold" />
            <span>{files.length ? `${files.length} file(s) chosen` : "Choose PDFs"}</span>
            <input
              type="file"
              accept="application/pdf"
              multiple
              className="hidden"
              onChange={(e) => setFiles(Array.from(e.target.files || []))}
              data-testid="pl-file-input"
            />
          </label>
          <button
            disabled={!files.length || busy}
            onClick={process}
            className="btn-primary text-xs flex items-center gap-1"
            data-testid="pl-process-btn"
          >
            <PrinterIcon size={12} weight="bold" />
            {busy ? "Processing…" : "Sort & Generate Printouts"}
          </button>
        </div>
        {files.length > 0 && (
          <div className="flex flex-wrap gap-1">
            {files.map((f, i) => (
              <span key={i} className="chip">
                {f.name}{" "}
                <button
                  onClick={() =>
                    setFiles(files.filter((_, idx) => idx !== i))
                  }
                >
                  <XIcon size={10} weight="bold" />
                </button>
              </span>
            ))}
          </div>
        )}
        {err && (
          <div className="border border-[rgba(239,68,68,0.35)] bg-[rgba(239,68,68,0.1)] px-3 py-2 font-mono text-xs text-[#FCA5A5]">
            {err}
          </div>
        )}
      </div>

      {result && <ResultPanel result={result} />}
    </div>
  );
}

function ResultPanel({ result }) {
  const stats = [
    { label: "Pages", value: result.total_pages },
    { label: "Unique Orders", value: result.unique_orders },
    { label: "Duplicates Skipped", value: result.duplicates_skipped },
    { label: "Unknown SKUs", value: result.unknown_sku },
    { label: "Unknown Couriers", value: result.unknown_courier },
  ];
  const download = async (fname) => {
    const rr = await api.get(
      `/pdf-sorter/runs/${result.run_id}/files/${fname}`,
      { responseType: "blob" }
    );
    const url = URL.createObjectURL(new Blob([rr.data]));
    const a = document.createElement("a");
    a.href = url; a.download = fname; a.click();
    URL.revokeObjectURL(url);
  };
  return (
    <div className="space-y-4" data-testid="pl-result">
      <div className="grid grid-cols-2 md:grid-cols-5 gap-2">
        {stats.map((s) => (
          <div key={s.label} className="kpi-card">
            <div className="font-display text-2xl">{s.value}</div>
            <div className="section-label mt-1">{s.label}</div>
          </div>
        ))}
      </div>
      <div className="panel p-4 space-y-3">
        <h3 className="font-display text-sm">
          Downloads — <span className="font-mono text-xs">{result.run_id}</span>
        </h3>
        <div className="flex flex-wrap gap-2">
          {result.files.map((f) => (
            <button
              key={f}
              onClick={() => download(f)}
              className="btn-primary text-xs flex items-center gap-1"
              data-testid={`pl-download-${f}`}
            >
              <DownloadSimpleIcon size={12} weight="bold" /> {f}
            </button>
          ))}
        </div>
      </div>

      {result.warnings?.length > 0 && (
        <div className="border border-[rgba(245,158,11,0.35)] bg-[rgba(245,158,11,0.1)] p-3 rounded text-xs">
          <div className="font-semibold text-[#FCD34D] mb-1 flex items-center gap-1">
            <WarningCircleIcon size={12} weight="bold" /> Warnings:
            orders already CANCELLED / RTO in P&amp;L
          </div>
          <div className="space-y-0.5 max-h-40 overflow-y-auto">
            {result.warnings.map((w, i) => (
              <div key={i} className="font-mono text-[11px]">
                {w.order_no} — <span className="text-[#FCA5A5]">{w.status}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        <MiniTable
          title="Courier — this run"
          rows={Object.entries(result.courier_totals || {})
            .sort((a, b) => b[1] - a[1])
            .map(([k, v]) => ({ key: k, count: v }))}
        />
        <MiniTable
          title="Products / SKUs — this run"
          rows={Object.entries(result.sku_totals || {})
            .sort((a, b) => b[1] - a[1])
            .map(([k, v]) => ({ key: k, count: v }))}
          max={40}
        />
      </div>
    </div>
  );
}

function MiniTable({ title, rows, max = 20 }) {
  return (
    <div className="panel p-4">
      <h3 className="font-display text-sm mb-2">{title}</h3>
      <div className="table-wrap max-h-96">
        <table className="dense">
          <thead>
            <tr>
              <th>Name</th>
              <th className="num">Count</th>
            </tr>
          </thead>
          <tbody>
            {rows.slice(0, max).map((r) => (
              <tr key={r.key}>
                <td className="font-mono text-[11px]">{r.key}</td>
                <td className="num font-mono">{r.count}</td>
              </tr>
            ))}
            {!rows.length && (
              <tr>
                <td colSpan={2} className="text-center py-3 text-[var(--text-muted)]">
                  no data
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ============================================================================
// Analytics tab — courier + SKU historical totals with filters
// ============================================================================
function AnalyticsTab() {
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [q, setQ] = useState("");
  const [qLive, setQLive] = useState("");
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState("");

  useEffect(() => {
    const t = setTimeout(() => setQ(qLive), 350);
    return () => clearTimeout(t);
  }, [qLive]);

  const load = useCallback(async () => {
    setLoading(true); setErr("");
    try {
      const p = new URLSearchParams();
      if (start) p.append("start_date", start);
      if (end) p.append("end_date", end);
      if (q) p.append("q", q);
      const { data } = await api.get(`/pdf-sorter/analytics?${p.toString()}`);
      setData(data);
    } catch (e) {
      setErr(formatApiError(e));
    } finally {
      setLoading(false);
    }
  }, [start, end, q]);

  useEffect(() => { load(); }, [load]);

  const stats = data ? [
    { label: "Total Runs", value: data.total_runs },
    { label: "Pages Sorted", value: data.total_pages },
    { label: "Unique Orders", value: data.unique_orders },
    { label: "Duplicates Skipped", value: data.duplicates_skipped },
  ] : [];

  return (
    <div className="space-y-4" data-testid="pl-analytics-tab">
      <div className="panel p-4 flex flex-wrap items-end gap-3">
        <div className="flex-1 min-w-[220px]">
          <div className="section-label mb-1">/ search</div>
          <div className="relative">
            <MagnifyingGlassIcon
              size={14}
              weight="bold"
              className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--text-muted)]"
            />
            <input
              value={qLive}
              onChange={(e) => setQLive(e.target.value)}
              placeholder="Filter SKUs or couriers…"
              className="input-shell font-mono text-sm pl-8"
              data-testid="pl-analytics-search"
            />
          </div>
        </div>
        <div>
          <div className="section-label mb-1">/ from</div>
          <input
            type="date"
            value={start}
            onChange={(e) => setStart(e.target.value)}
            className="input-shell font-mono text-xs"
            data-testid="pl-analytics-start"
          />
        </div>
        <div>
          <div className="section-label mb-1">/ to</div>
          <input
            type="date"
            value={end}
            onChange={(e) => setEnd(e.target.value)}
            className="input-shell font-mono text-xs"
            data-testid="pl-analytics-end"
          />
        </div>
        <button
          onClick={() => { setStart(""); setEnd(""); setQLive(""); }}
          className="btn-ghost text-xs"
        >
          Clear
        </button>
        <button
          onClick={load}
          className="btn-ghost text-xs flex items-center gap-1"
          data-testid="pl-analytics-refresh"
        >
          <ArrowsClockwiseIcon size={12} weight="bold" /> Refresh
        </button>
      </div>

      {err && (
        <div className="border border-[rgba(239,68,68,0.35)] bg-[rgba(239,68,68,0.1)] px-3 py-2 font-mono text-xs text-[#FCA5A5]">
          {err}
        </div>
      )}

      {loading ? (
        <div className="text-center text-[var(--text-muted)] py-8">
          <span className="cursor-blink">LOADING</span>
        </div>
      ) : !data || !data.total_runs ? (
        <div className="panel p-10 text-center text-[var(--text-muted)] text-sm">
          No printouts yet in this window. Head to <span className="code-tag">Sort &amp; Print</span> to make one.
        </div>
      ) : (
        <>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
            {stats.map((s) => (
              <div key={s.label} className="kpi-card">
                <div className="font-display text-2xl">{s.value}</div>
                <div className="section-label mt-1">{s.label}</div>
              </div>
            ))}
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            <div className="panel p-4">
              <h3 className="font-display text-sm mb-2 flex items-center gap-1">
                <PrinterIcon size={14} weight="bold" /> Courier Partner Orders
              </h3>
              <div className="table-wrap max-h-[480px]">
                <table className="dense">
                  <thead>
                    <tr>
                      <th>Courier</th>
                      <th className="num">Orders</th>
                      <th className="num">%</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(data.courier_totals || []).map((c) => {
                      const totalC = (data.courier_totals || []).reduce((a, b) => a + b.count, 0) || 1;
                      return (
                        <tr key={c.name} data-testid={`pl-cr-${c.name}`}>
                          <td className="font-mono text-[11px]">{c.name}</td>
                          <td className="num font-mono">{c.count}</td>
                          <td className="num font-mono text-[var(--text-muted)]">
                            {((c.count / totalC) * 100).toFixed(1)}%
                          </td>
                        </tr>
                      );
                    })}
                    {!data.courier_totals?.length && (
                      <tr><td colSpan={3} className="text-center py-4 text-[var(--text-muted)]">no data</td></tr>
                    )}
                  </tbody>
                </table>
              </div>
            </div>

            <div className="panel p-4">
              <h3 className="font-display text-sm mb-2 flex items-center gap-1">
                <ChartBarIcon size={14} weight="bold" /> Product / SKU Orders
                <span className="text-[var(--text-muted)] font-mono text-[10px] ml-1">
                  ({(data.sku_totals || []).length} unique)
                </span>
              </h3>
              <div className="table-wrap max-h-[480px]">
                <table className="dense">
                  <thead>
                    <tr>
                      <th>SKU / Product</th>
                      <th className="num">Orders</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(data.sku_totals || []).map((c) => (
                      <tr key={c.name} data-testid={`pl-sku-${c.name}`}>
                        <td className="font-mono text-[11px]">{c.name}</td>
                        <td className="num font-mono">{c.count}</td>
                      </tr>
                    ))}
                    {!data.sku_totals?.length && (
                      <tr><td colSpan={2} className="text-center py-4 text-[var(--text-muted)]">no data</td></tr>
                    )}
                  </tbody>
                </table>
              </div>
            </div>
          </div>

          {data.daily_series?.length > 0 && (
            <div className="panel p-4">
              <h3 className="font-display text-sm mb-3">Daily Volume</h3>
              <DailyBars data={data.daily_series} />
            </div>
          )}
        </>
      )}
    </div>
  );
}

function DailyBars({ data }) {
  const max = Math.max(...data.map((d) => d.count), 1);
  return (
    <div className="space-y-1">
      {data.map((d) => (
        <div key={d.date} className="flex items-center gap-2 text-xs">
          <div className="w-24 font-mono text-[10px] text-[var(--text-muted)]">{d.date}</div>
          <div className="flex-1 bar-track">
            <div
              className="bar-fill"
              style={{
                width: `${(d.count / max) * 100}%`,
                background: "var(--accent)",
              }}
            />
          </div>
          <div className="w-16 text-right font-mono">{d.count}</div>
        </div>
      ))}
    </div>
  );
}

// ============================================================================
// Overrides tab — optional SKU normalization + courier rules
// ============================================================================
function OverridesTab() {
  const [cfg, setCfg] = useState({ sku_normalization: [], courier_rules: [] });
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState("");
  const [skuDraft, setSkuDraft] = useState({ raw_sku: "", normalized_sku: "" });
  const [courierDraft, setCourierDraft] = useState({ courier_name: "", match_text: "" });

  const load = useCallback(async () => {
    setLoading(true); setErr("");
    try {
      const { data } = await api.get("/pdf-sorter/config");
      setCfg(data);
    } catch (e) { setErr(formatApiError(e)); }
    setLoading(false);
  }, []);
  useEffect(() => { load(); }, [load]);

  const addSku = async () => {
    if (!skuDraft.raw_sku || !skuDraft.normalized_sku) return;
    try {
      await api.post("/pdf-sorter/config/sku", skuDraft);
      setSkuDraft({ raw_sku: "", normalized_sku: "" });
      await load();
    } catch (e) { setErr(formatApiError(e)); }
  };
  const delSku = async (raw) => {
    if (!window.confirm(`Delete override for ${raw}?`)) return;
    try { await api.delete(`/pdf-sorter/config/sku/${encodeURIComponent(raw)}`); await load(); }
    catch (e) { setErr(formatApiError(e)); }
  };
  const addCourier = async () => {
    if (!courierDraft.courier_name || !courierDraft.match_text) return;
    try {
      await api.post("/pdf-sorter/config/courier", courierDraft);
      setCourierDraft({ courier_name: "", match_text: "" });
      await load();
    } catch (e) { setErr(formatApiError(e)); }
  };
  const delCourier = async (nm) => {
    if (!window.confirm(`Delete courier rule for ${nm}?`)) return;
    try { await api.delete(`/pdf-sorter/config/courier/${encodeURIComponent(nm)}`); await load(); }
    catch (e) { setErr(formatApiError(e)); }
  };

  return (
    <div className="space-y-4" data-testid="pl-overrides-tab">
      <div className="text-xs text-[var(--text-secondary)]">
        Product Master is the primary source for SKU grouping. Add entries here <b>only</b> for
        raw SKUs that aren&apos;t in Product Master or need a special override, or to teach the
        app which text on a label identifies each courier partner.
      </div>
      {err && <div className="border border-[rgba(239,68,68,0.35)] bg-[rgba(239,68,68,0.1)] px-3 py-2 font-mono text-xs text-[#FCA5A5]">{err}</div>}

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div className="panel p-4 space-y-3">
          <h3 className="font-display text-sm">SKU Overrides (optional)</h3>
          <div className="flex flex-wrap items-end gap-2">
            <input
              placeholder="Raw SKU (as printed)"
              value={skuDraft.raw_sku}
              onChange={(e) => setSkuDraft({ ...skuDraft, raw_sku: e.target.value })}
              className="input-shell font-mono text-xs flex-1"
              data-testid="pl-sku-raw"
            />
            <input
              placeholder="Group label"
              value={skuDraft.normalized_sku}
              onChange={(e) => setSkuDraft({ ...skuDraft, normalized_sku: e.target.value })}
              className="input-shell font-mono text-xs flex-1"
              data-testid="pl-sku-norm"
            />
            <button onClick={addSku} className="btn-primary text-xs" data-testid="pl-sku-add">Add</button>
          </div>
          <div className="table-wrap max-h-96">
            <table className="dense">
              <thead><tr><th>Raw SKU</th><th>Group</th><th></th></tr></thead>
              <tbody>
                {loading && <tr><td colSpan={3} className="text-center py-4 text-[var(--text-muted)]">Loading…</td></tr>}
                {!loading && cfg.sku_normalization.length === 0 && (
                  <tr><td colSpan={3} className="text-center py-4 text-[var(--text-muted)]">No overrides.</td></tr>
                )}
                {cfg.sku_normalization.map((r) => (
                  <tr key={r.raw_sku}>
                    <td className="font-mono text-[11px]">{r.raw_sku}</td>
                    <td className="font-mono text-[11px] text-[#6EE7B7]">{r.normalized_sku}</td>
                    <td className="text-right">
                      <button onClick={() => delSku(r.raw_sku)} className="btn-ghost hover:text-[var(--status-failed)]">
                        <TrashIcon size={12} weight="bold" />
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        <div className="panel p-4 space-y-3">
          <h3 className="font-display text-sm">Courier Rules</h3>
          <div className="flex flex-wrap items-end gap-2">
            <input
              placeholder="Courier name"
              value={courierDraft.courier_name}
              onChange={(e) => setCourierDraft({ ...courierDraft, courier_name: e.target.value })}
              className="input-shell font-mono text-xs flex-1"
              data-testid="pl-courier-name"
            />
            <input
              placeholder="Match text on label"
              value={courierDraft.match_text}
              onChange={(e) => setCourierDraft({ ...courierDraft, match_text: e.target.value })}
              className="input-shell font-mono text-xs flex-1"
              data-testid="pl-courier-match"
            />
            <button onClick={addCourier} className="btn-primary text-xs" data-testid="pl-courier-add">Add</button>
          </div>
          <div className="table-wrap max-h-96">
            <table className="dense">
              <thead><tr><th>Courier</th><th>Match</th><th></th></tr></thead>
              <tbody>
                {loading && <tr><td colSpan={3} className="text-center py-4 text-[var(--text-muted)]">Loading…</td></tr>}
                {!loading && cfg.courier_rules.length === 0 && (
                  <tr><td colSpan={3} className="text-center py-4 text-[var(--text-muted)]">No rules.</td></tr>
                )}
                {cfg.courier_rules.map((r) => (
                  <tr key={r.courier_name}>
                    <td className="font-mono text-[11px]">{r.courier_name}</td>
                    <td className="font-mono text-[11px]">{r.match_text}</td>
                    <td className="text-right">
                      <button onClick={() => delCourier(r.courier_name)} className="btn-ghost hover:text-[var(--status-failed)]">
                        <TrashIcon size={12} weight="bold" />
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
  );
}

// ============================================================================
// Page
// ============================================================================
export default function PrintoutLabelsPage() {
  const [tab, setTab] = useState("process");
  return (
    <div className="px-8 py-6 space-y-5" data-testid="printout-labels-page">
      <div className="flex items-center gap-2">
        <PrinterIcon size={22} weight="bold" color="#10B981" />
        <div className="flex-1">
          <h2 className="font-display text-xl">Printout Labels</h2>
          <div className="text-xs text-[var(--text-muted)]">
            Upload PDFs from any/multiple accounts. Sorted by Product Master SKUs and delivered
            as TIER-1 / TIER-2 / MASTER printouts, plus courier and SKU analytics.
          </div>
        </div>
      </div>

      <div className="flex gap-1 border-b border-[var(--border)]">
        {TABS.map((t) => (
          <button
            key={t.k}
            onClick={() => setTab(t.k)}
            className={
              "px-4 py-2 font-mono text-[11px] uppercase tracking-wider border-b-2 transition-colors " +
              (tab === t.k
                ? "border-[var(--accent)] text-[var(--text-primary)]"
                : "border-transparent text-[var(--text-muted)] hover:text-[var(--text-secondary)]")
            }
            data-testid={`pl-tab-${t.k}`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {tab === "process" && <ProcessTab />}
      {tab === "analytics" && <AnalyticsTab />}
      {tab === "overrides" && <OverridesTab />}
    </div>
  );
}
