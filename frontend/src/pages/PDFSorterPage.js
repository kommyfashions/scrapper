import { useCallback, useEffect, useMemo, useState } from "react";
import {
  ArrowsClockwiseIcon,
  DownloadSimpleIcon,
  FileArrowUpIcon,
  PrinterIcon,
  TrashIcon,
  UploadSimpleIcon,
  WarningCircleIcon,
  XIcon,
  GearIcon,
} from "@phosphor-icons/react";
import api, { API, formatApiError } from "@/lib/api";

const TABS = [
  { k: "process", label: "Process PDFs" },
  { k: "runs", label: "Run History" },
  { k: "config", label: "Config" },
];

// ---------- Process tab ----------
function ProcessTab({ accounts }) {
  const [files, setFiles] = useState([]);
  const [accountId, setAccountId] = useState("");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);
  const [err, setErr] = useState("");

  const process = async () => {
    if (!files.length) return;
    setBusy(true); setErr(""); setResult(null);
    try {
      const fd = new FormData();
      files.forEach((f) => fd.append("files", f));
      const qs = accountId ? `?account_id=${accountId}` : "";
      const { data } = await api.post(`/pdf-sorter/process${qs}`, fd, {
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
    <div className="space-y-4" data-testid="ps-process-tab">
      <div className="panel p-5 space-y-4">
        <div className="flex flex-wrap items-end gap-3">
          <div>
            <div className="section-label mb-1">/ account (optional)</div>
            <select
              value={accountId}
              onChange={(e) => setAccountId(e.target.value)}
              className="input-shell font-mono text-sm min-w-[200px]"
              data-testid="ps-account"
            >
              <option value="">— unattributed —</option>
              {accounts.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.alias ? `${a.alias} (${a.name})` : a.name}
                </option>
              ))}
            </select>
          </div>
          <label className="btn-secondary text-xs flex items-center gap-2 cursor-pointer">
            <FileArrowUpIcon size={14} weight="bold" />
            <span>{files.length ? `${files.length} file(s) chosen` : "Choose PDFs"}</span>
            <input
              type="file"
              accept="application/pdf"
              multiple
              className="hidden"
              onChange={(e) => setFiles(Array.from(e.target.files || []))}
              data-testid="ps-file-input"
            />
          </label>
          <button
            disabled={!files.length || busy}
            onClick={process}
            className="btn-primary text-xs flex items-center gap-1"
            data-testid="ps-process-btn"
          >
            <PrinterIcon size={12} weight="bold" />
            {busy ? "Processing…" : "Process"}
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
  return (
    <div className="space-y-4" data-testid="ps-result">
      <div className="grid grid-cols-5 gap-2">
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
            <a
              key={f}
              href={`${API}/pdf-sorter/runs/${result.run_id}/files/${f}?token=${localStorage.getItem("md_token")}`}
              onClick={async (e) => {
                // token has to be sent via header; use fetch fallback
                e.preventDefault();
                const r = await api.get(
                  `/pdf-sorter/runs/${result.run_id}/files/${f}`,
                  { responseType: "blob" }
                );
                const url = URL.createObjectURL(new Blob([r.data]));
                const a = document.createElement("a");
                a.href = url;
                a.download = f;
                a.click();
                URL.revokeObjectURL(url);
              }}
              className="btn-primary text-xs flex items-center gap-1"
              data-testid={`ps-download-${f}`}
            >
              <DownloadSimpleIcon size={12} weight="bold" /> {f}
            </a>
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
          title="Courier Order Summary"
          rows={Object.entries(result.courier_totals || {})
            .sort((a, b) => b[1] - a[1])
            .map(([k, v]) => ({ key: k, count: v }))}
        />
        <MiniTable
          title="SKU Order Summary (Today's run)"
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

// ---------- Runs tab ----------
function RunsTab() {
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const load = useCallback(async () => {
    setLoading(true);
    try {
      const { data } = await api.get("/pdf-sorter/runs");
      setRows(data.items || []);
    } catch (_) { /* best effort */ }
    setLoading(false);
  }, []);
  useEffect(() => { load(); }, [load]);
  return (
    <div className="space-y-3" data-testid="ps-runs-tab">
      <div className="flex justify-end">
        <button onClick={load} className="btn-ghost text-xs flex items-center gap-1">
          <ArrowsClockwiseIcon size={12} weight="bold" /> Refresh
        </button>
      </div>
      <div className="table-wrap">
        <table className="dense">
          <thead>
            <tr>
              <th>Run</th>
              <th>When</th>
              <th className="num">Pages</th>
              <th className="num">Orders</th>
              <th className="num">Dups</th>
              <th className="num">Unknown SKU</th>
              <th>Downloads</th>
            </tr>
          </thead>
          <tbody>
            {loading && (
              <tr><td colSpan={7} className="text-center py-6 text-[var(--text-muted)]">Loading…</td></tr>
            )}
            {!loading && rows.length === 0 && (
              <tr><td colSpan={7} className="text-center py-6 text-[var(--text-muted)]">No runs yet.</td></tr>
            )}
            {rows.map((r) => (
              <tr key={r.run_id}>
                <td className="font-mono text-[11px]">{r.run_id}</td>
                <td className="text-xs">{r.created_at ? new Date(r.created_at).toLocaleString() : "—"}</td>
                <td className="num">{r.total_pages}</td>
                <td className="num">{r.unique_orders}</td>
                <td className="num">{r.duplicates_skipped}</td>
                <td className="num">{r.unknown_sku}</td>
                <td>
                  <div className="flex gap-1">
                    {(r.files || []).map((f) => (
                      <button
                        key={f}
                        onClick={async () => {
                          const rr = await api.get(
                            `/pdf-sorter/runs/${r.run_id}/files/${f}`,
                            { responseType: "blob" }
                          );
                          const url = URL.createObjectURL(new Blob([rr.data]));
                          const a = document.createElement("a");
                          a.href = url; a.download = f; a.click();
                          URL.revokeObjectURL(url);
                        }}
                        className="btn-ghost text-[10px] flex items-center gap-1"
                      >
                        <DownloadSimpleIcon size={10} weight="bold" /> {f.replace(".pdf", "")}
                      </button>
                    ))}
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

// ---------- Config tab ----------
function ConfigTab() {
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
    if (!window.confirm(`Delete SKU mapping for ${raw}?`)) return;
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
    <div className="space-y-6" data-testid="ps-config-tab">
      {err && <div className="border border-[rgba(239,68,68,0.35)] bg-[rgba(239,68,68,0.1)] px-3 py-2 font-mono text-xs text-[#FCA5A5]">{err}</div>}

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div className="panel p-4 space-y-3">
          <h3 className="font-display text-sm">SKU Normalisation</h3>
          <div className="text-xs text-[var(--text-muted)]">
            Map raw SKU strings printed on Meesho labels to your canonical SKU codes.
          </div>
          <div className="flex flex-wrap items-end gap-2">
            <input
              placeholder="Raw SKU (as printed)"
              value={skuDraft.raw_sku}
              onChange={(e) => setSkuDraft({ ...skuDraft, raw_sku: e.target.value })}
              className="input-shell font-mono text-xs flex-1"
              data-testid="ps-sku-raw"
            />
            <input
              placeholder="Normalized SKU"
              value={skuDraft.normalized_sku}
              onChange={(e) => setSkuDraft({ ...skuDraft, normalized_sku: e.target.value })}
              className="input-shell font-mono text-xs flex-1"
              data-testid="ps-sku-norm"
            />
            <button onClick={addSku} className="btn-primary text-xs" data-testid="ps-sku-add">Add</button>
          </div>
          <div className="table-wrap max-h-96">
            <table className="dense">
              <thead>
                <tr><th>Raw SKU</th><th>Normalized</th><th></th></tr>
              </thead>
              <tbody>
                {loading && <tr><td colSpan={3} className="text-center py-4 text-[var(--text-muted)]">Loading…</td></tr>}
                {!loading && cfg.sku_normalization.length === 0 && (
                  <tr><td colSpan={3} className="text-center py-4 text-[var(--text-muted)]">No mappings yet.</td></tr>
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
          <div className="text-xs text-[var(--text-muted)]">
            Detect courier from label text. First matching rule wins.
          </div>
          <div className="flex flex-wrap items-end gap-2">
            <input
              placeholder="Courier name"
              value={courierDraft.courier_name}
              onChange={(e) => setCourierDraft({ ...courierDraft, courier_name: e.target.value })}
              className="input-shell font-mono text-xs flex-1"
              data-testid="ps-courier-name"
            />
            <input
              placeholder="Match text (word appearing on label)"
              value={courierDraft.match_text}
              onChange={(e) => setCourierDraft({ ...courierDraft, match_text: e.target.value })}
              className="input-shell font-mono text-xs flex-1"
              data-testid="ps-courier-match"
            />
            <button onClick={addCourier} className="btn-primary text-xs" data-testid="ps-courier-add">Add</button>
          </div>
          <div className="table-wrap max-h-96">
            <table className="dense">
              <thead>
                <tr><th>Courier</th><th>Match Text</th><th></th></tr>
              </thead>
              <tbody>
                {loading && <tr><td colSpan={3} className="text-center py-4 text-[var(--text-muted)]">Loading…</td></tr>}
                {!loading && cfg.courier_rules.length === 0 && (
                  <tr><td colSpan={3} className="text-center py-4 text-[var(--text-muted)]">No rules yet.</td></tr>
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

// ---------- Page ----------
export default function PDFSorterPage() {
  const [tab, setTab] = useState("process");
  const [accounts, setAccounts] = useState([]);

  useEffect(() => {
    api.get("/accounts").then((r) => setAccounts(r.data.items || [])).catch(() => {});
  }, []);

  return (
    <div className="px-8 py-6 space-y-5" data-testid="pdf-sorter-page">
      <div className="flex items-center gap-2">
        <PrinterIcon size={22} weight="bold" color="#10B981" />
        <div className="flex-1">
          <h2 className="font-display text-xl">PDF Label Sorter</h2>
          <div className="text-xs text-[var(--text-muted)]">
            Sort Meesho label PDFs by SKU. TIER-1 high-volume gets an upside-down separator.
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
            data-testid={`ps-tab-${t.k}`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {tab === "process" && <ProcessTab accounts={accounts} />}
      {tab === "runs" && <RunsTab />}
      {tab === "config" && <ConfigTab />}
    </div>
  );
}
