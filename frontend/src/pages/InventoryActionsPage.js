import { useCallback, useEffect, useState } from "react";
import {
  PauseCircleIcon,
  ArrowsClockwiseIcon,
  CheckCircleIcon,
  XCircleIcon,
  ClockIcon,
  CaretRightIcon,
  CaretDownIcon,
} from "@phosphor-icons/react";
import api, { formatApiError } from "@/lib/api";
import PageHeader from "@/components/PageHeader";
import { fmtRelative } from "@/lib/format";

/* -------------- helpers -------------- */
const STATUS_COLORS = {
  pending: "bg-amber-500/15 text-amber-300 border-amber-500/30",
  processing: "bg-sky-500/15 text-sky-300 border-sky-500/30",
  done: "bg-emerald-500/15 text-emerald-300 border-emerald-500/30",
  failed: "bg-rose-500/15 text-rose-300 border-rose-500/30",
};

function StatusPill({ status, testid }) {
  const cls = STATUS_COLORS[status] || "bg-white/5 text-white/70 border-white/10";
  return (
    <span
      data-testid={testid}
      className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] uppercase tracking-widest ${cls}`}
    >
      {status}
    </span>
  );
}

/* -------------- main page -------------- */
export default function InventoryActionsPage() {
  const [accounts, setAccounts] = useState([]);
  const [accountId, setAccountId] = useState("");
  const [categories, setCategories] = useState([]);
  const [category, setCategory] = useState("");
  const [colors, setColors] = useState([]);
  const [color, setColor] = useState("");
  const [allSizes, setAllSizes] = useState([]);
  const [styleIds, setStyleIds] = useState([]);
  const [selectedSizes, setSelectedSizes] = useState([]);
  const [wholeProduct, setWholeProduct] = useState(true);

  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [pausing, setPausing] = useState(false);
  const [lastJobId, setLastJobId] = useState(null);
  const [history, setHistory] = useState([]);

  /* --------- load accounts once --------- */
  useEffect(() => {
    api.get("/inventory-actions/options")
      .then((r) => setAccounts(r.data.accounts || []))
      .catch((e) => setErr(formatApiError(e)));
    refreshHistory();
  }, []);

  const refreshHistory = useCallback(async () => {
    try {
      const r = await api.get("/inventory-actions/history", { params: { limit: 30 } });
      setHistory(r.data.items || []);
    } catch (e) {
      /* silent */
    }
  }, []);

  /* --------- cascade: account → categories --------- */
  useEffect(() => {
    setCategory(""); setColor(""); setColors([]);
    setAllSizes([]); setStyleIds([]); setSelectedSizes([]);
    setCategories([]);
    if (!accountId) return;
    setBusy(true); setErr("");
    api.get("/inventory-actions/options", { params: { account_id: accountId } })
      .then((r) => setCategories(r.data.main_categories || []))
      .catch((e) => setErr(formatApiError(e)))
      .finally(() => setBusy(false));
  }, [accountId]);

  /* --------- cascade: category → colors --------- */
  useEffect(() => {
    setColor(""); setAllSizes([]); setStyleIds([]); setSelectedSizes([]);
    setColors([]);
    if (!accountId || !category) return;
    setBusy(true); setErr("");
    api.get("/inventory-actions/options", {
      params: { account_id: accountId, main_category: category },
    })
      .then((r) => setColors(r.data.colors || []))
      .catch((e) => setErr(formatApiError(e)))
      .finally(() => setBusy(false));
  }, [accountId, category]);

  /* --------- cascade: color → sizes + style_ids --------- */
  useEffect(() => {
    setAllSizes([]); setStyleIds([]); setSelectedSizes([]); setWholeProduct(true);
    if (!accountId || !category || !color) return;
    setBusy(true); setErr("");
    api.get("/inventory-actions/options", {
      params: { account_id: accountId, main_category: category, color },
    })
      .then((r) => {
        setAllSizes(r.data.sizes || []);
        setStyleIds(r.data.style_ids || []);
      })
      .catch((e) => setErr(formatApiError(e)))
      .finally(() => setBusy(false));
  }, [accountId, category, color]);

  const toggleSize = (s) => {
    setWholeProduct(false);
    setSelectedSizes((prev) =>
      prev.includes(s) ? prev.filter((x) => x !== s) : [...prev, s]
    );
  };

  const targetSizes = wholeProduct ? allSizes : selectedSizes;
  const estimatedSkus = styleIds.length * targetSizes.length;
  const canPause = accountId && category && color && styleIds.length > 0 && targetSizes.length > 0 && !pausing;

  /* --------- pause action --------- */
  const doPause = async () => {
    setPausing(true); setErr(""); setLastJobId(null);
    try {
      const body = {
        account_id: accountId,
        main_category: category,
        color,
        sizes: wholeProduct ? [] : selectedSizes,
      };
      const r = await api.post("/inventory-actions/pause", body);
      setLastJobId(r.data.job_id);
      await refreshHistory();
    } catch (e) {
      setErr(formatApiError(e));
    } finally {
      setPausing(false);
    }
  };

  /* --------- poll last job until finished --------- */
  useEffect(() => {
    if (!lastJobId) return;
    const t = setInterval(async () => {
      try {
        const r = await api.get(`/inventory-actions/${lastJobId}`);
        setHistory((prev) => {
          const idx = prev.findIndex((x) => x.id === r.data.id);
          if (idx === -1) return [r.data, ...prev];
          const next = [...prev];
          next[idx] = r.data;
          return next;
        });
        if (r.data.status === "done" || r.data.status === "failed") {
          clearInterval(t);
        }
      } catch (e) {
        /* silent */
      }
    }, 3000);
    return () => clearInterval(t);
  }, [lastJobId]);

  return (
    <div className="min-h-screen" data-testid="inventory-actions-page">
      <PageHeader
        title="AUTOMATION / BULK PAUSE"
        subtitle="Pause Meesho SKUs by Product Master"
        right={
          <button
            data-testid="refresh-history-btn"
            onClick={refreshHistory}
            className="btn-ghost text-xs"
          >
            <ArrowsClockwiseIcon size={14} weight="bold" />
            <span className="ml-1">Refresh history</span>
          </button>
        }
      />

      <div className="grid gap-6 px-8 py-6 lg:grid-cols-[minmax(0,1fr)_360px]">
        {/* ---------- Left: builder ---------- */}
        <div className="space-y-6">
          {/* Cascading pickers */}
          <div className="rounded-lg border border-[var(--border)] bg-[var(--bg-card)] p-6">
            <div className="section-label mb-4">1 · Choose product</div>
            <div className="grid gap-4 sm:grid-cols-3">
              <Field label="Account">
                <select
                  data-testid="account-select"
                  className="input"
                  value={accountId}
                  onChange={(e) => setAccountId(e.target.value)}
                  disabled={busy}
                >
                  <option value="">— Select account —</option>
                  {accounts.map((a) => (
                    <option
                      key={a.id}
                      value={a.id}
                      disabled={!a.enabled}
                    >
                      {a.alias || a.name}{a.enabled ? "" : " (disabled)"}
                    </option>
                  ))}
                </select>
              </Field>
              <Field label="Main Category">
                <select
                  data-testid="category-select"
                  className="input"
                  value={category}
                  onChange={(e) => setCategory(e.target.value)}
                  disabled={!accountId || busy}
                >
                  <option value="">— Select category —</option>
                  {categories.map((c) => (
                    <option key={c} value={c}>{c}</option>
                  ))}
                </select>
              </Field>
              <Field label="Color">
                <select
                  data-testid="color-select"
                  className="input"
                  value={color}
                  onChange={(e) => setColor(e.target.value)}
                  disabled={!category || busy}
                >
                  <option value="">— Select color —</option>
                  {colors.map((c) => (
                    <option key={c} value={c}>{c}</option>
                  ))}
                </select>
              </Field>
            </div>
          </div>

          {/* Sizes / style IDs */}
          <div className="rounded-lg border border-[var(--border)] bg-[var(--bg-card)] p-6">
            <div className="section-label mb-4">2 · Choose what to pause</div>
            {!color ? (
              <div
                data-testid="picker-empty"
                className="rounded-md border border-dashed border-[var(--border)] px-4 py-8 text-center text-sm text-[var(--text-muted)]"
              >
                Pick account, category and color to see available sizes.
              </div>
            ) : (
              <div className="space-y-5">
                <div className="flex flex-wrap items-center gap-4">
                  <label
                    className="flex cursor-pointer items-center gap-2 text-sm"
                    data-testid="whole-product-toggle"
                  >
                    <input
                      type="checkbox"
                      className="h-4 w-4 accent-[var(--accent)]"
                      checked={wholeProduct}
                      onChange={(e) => {
                        setWholeProduct(e.target.checked);
                        if (e.target.checked) setSelectedSizes([]);
                      }}
                    />
                    <span className="font-medium">Pause whole product</span>
                    <span className="text-xs text-[var(--text-muted)]">
                      (all {allSizes.length} sizes)
                    </span>
                  </label>
                </div>

                <div>
                  <div className="text-xs uppercase tracking-widest text-[var(--text-muted)] mb-2">
                    …or pick specific sizes
                  </div>
                  <div className="flex flex-wrap gap-2" data-testid="size-checkboxes">
                    {allSizes.map((s) => {
                      const on = wholeProduct || selectedSizes.includes(s);
                      return (
                        <button
                          key={s}
                          data-testid={`size-chip-${s}`}
                          type="button"
                          onClick={() => toggleSize(s)}
                          className={`rounded-full border px-3 py-1.5 text-xs font-medium transition ${
                            on
                              ? "border-emerald-500/50 bg-emerald-500/15 text-emerald-200"
                              : "border-[var(--border)] bg-transparent text-[var(--text-secondary)] hover:border-white/30"
                          }`}
                        >
                          {s}
                        </button>
                      );
                    })}
                    {allSizes.length === 0 && (
                      <span className="text-sm text-[var(--text-muted)]">
                        No sizes on file for this product.
                      </span>
                    )}
                  </div>
                </div>

                <details className="rounded border border-[var(--border)] px-4 py-3">
                  <summary className="cursor-pointer text-xs uppercase tracking-widest text-[var(--text-muted)]">
                    Style IDs in this product ({styleIds.length})
                  </summary>
                  <div className="mt-3 flex flex-wrap gap-1.5" data-testid="style-ids-list">
                    {styleIds.map((s) => (
                      <span
                        key={s}
                        className="rounded bg-white/5 px-2 py-1 font-mono text-[11px] text-[var(--text-secondary)]"
                      >
                        {s}
                      </span>
                    ))}
                  </div>
                </details>
              </div>
            )}
          </div>

          {/* Summary + execute */}
          <div className="rounded-lg border border-[var(--border)] bg-[var(--bg-card)] p-6">
            <div className="section-label mb-4">3 · Execute</div>
            <div className="flex flex-wrap items-center gap-6 mb-5">
              <SummaryStat
                label="Style IDs"
                value={styleIds.length}
                testid="summary-style-ids"
              />
              <SummaryStat
                label="Sizes"
                value={targetSizes.length}
                testid="summary-sizes"
              />
              <SummaryStat
                label="Meesho SKUs (est.)"
                value={estimatedSkus}
                testid="summary-est-skus"
                highlight
              />
            </div>
            {err && (
              <div
                data-testid="error-banner"
                className="mb-4 rounded border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-sm text-rose-200"
              >
                {err}
              </div>
            )}
            <button
              data-testid="pause-now-btn"
              disabled={!canPause}
              onClick={doPause}
              className="inline-flex items-center gap-2 rounded-md bg-rose-500 px-5 py-2.5 text-sm font-semibold text-white shadow-lg shadow-rose-500/20 transition hover:bg-rose-400 disabled:cursor-not-allowed disabled:opacity-40"
            >
              <PauseCircleIcon size={18} weight="fill" />
              {pausing ? "Queuing…" : `Pause ${estimatedSkus || ""} SKU${estimatedSkus === 1 ? "" : "s"} now`}
            </button>
            {lastJobId && (
              <div
                data-testid="last-job-hint"
                className="mt-3 text-xs text-[var(--text-muted)]"
              >
                Job queued (id <span className="font-mono">{lastJobId}</span>). Progress
                appears in the history panel →
              </div>
            )}
          </div>
        </div>

        {/* ---------- Right: history ---------- */}
        <aside className="rounded-lg border border-[var(--border)] bg-[var(--bg-card)] p-4">
          <div className="mb-3 flex items-center justify-between">
            <div className="section-label">Recent actions</div>
            <span className="text-[10px] uppercase tracking-widest text-[var(--text-muted)]">
              {history.length}
            </span>
          </div>
          <div className="max-h-[70vh] space-y-2 overflow-auto pr-1" data-testid="history-list">
            {history.length === 0 && (
              <div className="rounded border border-dashed border-[var(--border)] p-6 text-center text-xs text-[var(--text-muted)]">
                No pause actions yet.
              </div>
            )}
            {history.map((j) => (
              <HistoryRow key={j.id} job={j} />
            ))}
          </div>
        </aside>
      </div>
    </div>
  );
}

/* --------- small building blocks --------- */
function Field({ label, children }) {
  return (
    <label className="block">
      <div className="mb-1 text-[10px] font-semibold uppercase tracking-widest text-[var(--text-muted)]">
        {label}
      </div>
      {children}
    </label>
  );
}

function SummaryStat({ label, value, testid, highlight }) {
  return (
    <div data-testid={testid}>
      <div className="text-[10px] uppercase tracking-widest text-[var(--text-muted)]">
        {label}
      </div>
      <div
        className={`font-display text-2xl font-semibold ${
          highlight ? "text-emerald-300" : "text-white"
        }`}
      >
        {value}
      </div>
    </div>
  );
}

function HistoryRow({ job }) {
  const [open, setOpen] = useState(false);
  const r = job.result || {};
  const finished = job.status === "done" || job.status === "failed";
  const Icon = finished ? (job.status === "done" ? CheckCircleIcon : XCircleIcon) : ClockIcon;
  return (
    <div
      data-testid={`history-item-${job.id}`}
      className="rounded border border-[var(--border)] bg-black/20 p-3"
    >
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-start gap-3 text-left"
      >
        <Icon
          size={16}
          weight="fill"
          className={
            job.status === "done"
              ? "mt-0.5 text-emerald-400"
              : job.status === "failed"
              ? "mt-0.5 text-rose-400"
              : "mt-0.5 text-sky-400"
          }
        />
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span className="truncate text-sm font-medium text-white">
              {job.main_category} · {job.color}
            </span>
            <StatusPill status={job.status} testid={`history-status-${job.id}`} />
          </div>
          <div className="mt-1 text-[11px] text-[var(--text-muted)]">
            {job.account_name} · {job.target_sizes.length} size(s) · {job.style_ids.length} style ID(s)
          </div>
          <div className="mt-0.5 text-[10px] text-[var(--text-muted)]">
            {fmtRelative(job.created_at)}
          </div>
          {finished && (
            <div className="mt-1 flex flex-wrap gap-3 text-[11px]">
              <span className="text-emerald-300">Paused: {r.paused_count}</span>
              <span className="text-amber-300">Already: {r.already_paused_count}</span>
              <span className="text-rose-300">Failed: {r.failed_count}</span>
            </div>
          )}
          {job.error && (
            <div className="mt-1 text-[11px] text-rose-300 truncate" title={job.error}>
              {job.error}
            </div>
          )}
        </div>
        {open ? (
          <CaretDownIcon size={12} className="mt-1 text-[var(--text-muted)]" />
        ) : (
          <CaretRightIcon size={12} className="mt-1 text-[var(--text-muted)]" />
        )}
      </button>
      {open && (
        <div className="mt-3 border-t border-[var(--border)] pt-2">
          <div className="mb-1 text-[10px] uppercase tracking-widest text-[var(--text-muted)]">
            Per Style ID
          </div>
          <div className="space-y-1 text-[11px]">
            {(r.per_sku || []).length === 0 && (
              <div className="text-[var(--text-muted)]">Waiting for scraper…</div>
            )}
            {(r.per_sku || []).map((row, i) => (
              <div
                key={i}
                className="flex items-center justify-between gap-2 rounded bg-white/5 px-2 py-1"
              >
                <span className="font-mono truncate">{row.style_id}</span>
                <span
                  className={
                    row.status === "paused"
                      ? "text-emerald-300"
                      : row.status === "already_paused"
                      ? "text-amber-300"
                      : "text-rose-300"
                  }
                >
                  {row.status}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
