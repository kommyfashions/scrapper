import { useCallback, useEffect, useMemo, useState } from "react";
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
import WorkerDriftBanner from "@/components/WorkerDriftBanner";
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
  const [colors, setColors] = useState([]);            // available for cat
  const [selectedColors, setSelectedColors] = useState([]); // multi-select
  const [colorDetail, setColorDetail] = useState({});  // {color: {sizes, style_ids}}
  const [selectedSizes, setSelectedSizes] = useState([]);
  const [wholeProduct, setWholeProduct] = useState(true);

  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [pausing, setPausing] = useState(false);
  const [lastJobIds, setLastJobIds] = useState([]);
  const [history, setHistory] = useState([]);
  const [counts, setCounts] = useState({ pending: 0, processing: 0, done: 0, failed: 0 });
  const [statusFilter, setStatusFilter] = useState("all");

  /* --------- load accounts once + history --------- */
  useEffect(() => {
    api.get("/inventory-actions/options")
      .then((r) => setAccounts(r.data.accounts || []))
      .catch((e) => setErr(formatApiError(e)));
    refreshHistory();
  }, []);

  const refreshHistory = useCallback(async (filter) => {
    try {
      const params = { limit: 50 };
      const s = filter ?? statusFilter;
      if (s && s !== "all") params.status = s;
      const r = await api.get("/inventory-actions/history", { params });
      setHistory(r.data.items || []);
      setCounts(r.data.counts || { pending: 0, processing: 0, done: 0, failed: 0 });
    } catch (e) {
      /* silent */
    }
  }, [statusFilter]);

  useEffect(() => {
    refreshHistory(statusFilter);
  }, [statusFilter, refreshHistory]);

  /* --------- cascade: account → categories --------- */
  useEffect(() => {
    setCategory(""); setColors([]); setSelectedColors([]);
    setColorDetail({}); setSelectedSizes([]);
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
    setSelectedColors([]); setColorDetail({}); setSelectedSizes([]);
    setWholeProduct(true); setColors([]);
    if (!accountId || !category) return;
    setBusy(true); setErr("");
    api.get("/inventory-actions/options", {
      params: { account_id: accountId, main_category: category },
    })
      .then((r) => setColors(r.data.colors || []))
      .catch((e) => setErr(formatApiError(e)))
      .finally(() => setBusy(false));
  }, [accountId, category]);

  /* --------- when colors change, fetch details for missing colors --------- */
  useEffect(() => {
    if (!accountId || !category) return;
    const missing = selectedColors.filter((c) => !colorDetail[c]);
    if (missing.length === 0) return;
    let cancelled = false;
    (async () => {
      setBusy(true); setErr("");
      try {
        const results = await Promise.all(
          missing.map((c) =>
            api.get("/inventory-actions/options", {
              params: { account_id: accountId, main_category: category, color: c },
            })
          )
        );
        if (cancelled) return;
        setColorDetail((prev) => {
          const next = { ...prev };
          missing.forEach((c, i) => {
            next[c] = {
              sizes: results[i].data.sizes || [],
              style_ids: results[i].data.style_ids || [],
            };
          });
          return next;
        });
      } catch (e) {
        if (!cancelled) setErr(formatApiError(e));
      } finally {
        if (!cancelled) setBusy(false);
      }
    })();
    return () => { cancelled = true; };
  }, [accountId, category, selectedColors, colorDetail]);

  /* --------- derived: union sizes + total style ids --------- */
  const unionSizes = useMemo(() => {
    const set = new Set();
    selectedColors.forEach((c) => {
      (colorDetail[c]?.sizes || []).forEach((s) => set.add(s));
    });
    return Array.from(set).sort((a, b) => (a.length - b.length) || a.localeCompare(b));
  }, [selectedColors, colorDetail]);

  const totalStyleIds = useMemo(
    () => selectedColors.reduce(
      (n, c) => n + (colorDetail[c]?.style_ids?.length || 0), 0),
    [selectedColors, colorDetail]
  );

  const estimatedSkus = useMemo(() => {
    if (selectedColors.length === 0) return 0;
    let est = 0;
    selectedColors.forEach((c) => {
      const detail = colorDetail[c];
      if (!detail) return;
      const target = wholeProduct
        ? detail.sizes
        : selectedSizes.filter((s) => detail.sizes.includes(s));
      est += detail.style_ids.length * target.length;
    });
    return est;
  }, [selectedColors, colorDetail, selectedSizes, wholeProduct]);

  const toggleColor = (c) => {
    setSelectedColors((prev) =>
      prev.includes(c) ? prev.filter((x) => x !== c) : [...prev, c]
    );
  };
  const toggleSize = (s) => {
    setWholeProduct(false);
    setSelectedSizes((prev) =>
      prev.includes(s) ? prev.filter((x) => x !== s) : [...prev, s]
    );
  };

  const canPause = accountId && category && selectedColors.length > 0
    && totalStyleIds > 0 && estimatedSkus > 0 && !pausing;

  /* --------- pause: one job per color --------- */
  const doPause = async () => {
    setPausing(true); setErr(""); setLastJobIds([]);
    const created = [];
    try {
      for (const c of selectedColors) {
        const detail = colorDetail[c];
        if (!detail || detail.style_ids.length === 0) continue;
        // sizes applicable to THIS color
        const targetSizes = wholeProduct
          ? []                                       // "whole product" = all sizes
          : selectedSizes.filter((s) => detail.sizes.includes(s));
        if (!wholeProduct && targetSizes.length === 0) continue;
        try {
          const r = await api.post("/inventory-actions/pause", {
            account_id: accountId,
            main_category: category,
            color: c,
            sizes: targetSizes,
          });
          created.push(r.data.job_id);
        } catch (e) {
          setErr((prev) => prev
            ? `${prev} · ${c}: ${formatApiError(e)}`
            : `${c}: ${formatApiError(e)}`);
        }
      }
      setLastJobIds(created);
      await refreshHistory();
    } finally {
      setPausing(false);
    }
  };

  /* --------- poll all pending jobs --------- */
  useEffect(() => {
    if (lastJobIds.length === 0) return;
    const pending = new Set(lastJobIds);
    const t = setInterval(async () => {
      for (const id of Array.from(pending)) {
        try {
          const r = await api.get(`/inventory-actions/${id}`);
          setHistory((prev) => {
            const idx = prev.findIndex((x) => x.id === r.data.id);
            if (idx === -1) return [r.data, ...prev];
            const next = [...prev];
            next[idx] = r.data;
            return next;
          });
          if (r.data.status === "done" || r.data.status === "failed") {
            pending.delete(id);
          }
        } catch (e) { /* silent */ }
      }
      if (pending.size === 0) clearInterval(t);
    }, 3000);
    return () => clearInterval(t);
  }, [lastJobIds]);

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
          <WorkerDriftBanner neededTypes={["pause_skus"]} />
          {/* Cascading pickers (account + category are single-select) */}
          <div className="rounded-lg border border-[var(--border)] bg-[var(--bg-card)] p-6">
            <div className="section-label mb-4">1 · Choose account &amp; category</div>
            <div className="grid gap-4 sm:grid-cols-2">
              <Field label="Account">
                <select
                  data-testid="account-select"
                  className="input-shell"
                  value={accountId}
                  onChange={(e) => setAccountId(e.target.value)}
                  disabled={busy}
                >
                  <option value="">— Select account —</option>
                  {accounts.map((a) => (
                    <option key={a.id} value={a.id} disabled={!a.enabled}>
                      {a.alias || a.name}{a.enabled ? "" : " (disabled)"}
                    </option>
                  ))}
                </select>
              </Field>
              <Field label="Main Category">
                <select
                  data-testid="category-select"
                  className="input-shell"
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
            </div>
          </div>

          {/* Colors — MULTI-SELECT chips */}
          <div className="rounded-lg border border-[var(--border)] bg-[var(--bg-card)] p-6">
            <div className="section-label mb-4">
              2 · Choose one or more colors
              {selectedColors.length > 0 && (
                <span className="ml-2 text-[10px] text-emerald-300">
                  ({selectedColors.length} selected)
                </span>
              )}
            </div>
            {!category ? (
              <div
                data-testid="colors-empty"
                className="rounded-md border border-dashed border-[var(--border)] px-4 py-6 text-center text-sm text-[var(--text-muted)]"
              >
                Pick account and category first.
              </div>
            ) : colors.length === 0 ? (
              <div
                data-testid="colors-none"
                className="rounded-md border border-dashed border-[var(--border)] px-4 py-6 text-center text-sm text-[var(--text-muted)]"
              >
                No colors in Product Master for this category.
              </div>
            ) : (
              <div className="space-y-3">
                <div className="flex flex-wrap gap-2" data-testid="color-checkboxes">
                  <button
                    type="button"
                    data-testid="color-select-all"
                    onClick={() =>
                      setSelectedColors(
                        selectedColors.length === colors.length ? [] : [...colors]
                      )
                    }
                    className="rounded-full border border-[var(--border)] px-3 py-1.5 text-xs font-medium text-[var(--text-secondary)] hover:border-white/40"
                  >
                    {selectedColors.length === colors.length ? "Clear all" : "Select all"}
                  </button>
                  {colors.map((c) => {
                    const on = selectedColors.includes(c);
                    return (
                      <button
                        key={c}
                        type="button"
                        data-testid={`color-chip-${c}`}
                        onClick={() => toggleColor(c)}
                        className={`rounded-full border px-3 py-1.5 text-xs font-medium transition ${
                          on
                            ? "border-sky-400/60 bg-sky-500/15 text-sky-200"
                            : "border-[var(--border)] bg-transparent text-[var(--text-secondary)] hover:border-white/30"
                        }`}
                      >
                        {c}
                      </button>
                    );
                  })}
                </div>
              </div>
            )}
          </div>

          {/* Sizes — appears once colors chosen */}
          <div className="rounded-lg border border-[var(--border)] bg-[var(--bg-card)] p-6">
            <div className="section-label mb-4">3 · Choose sizes to pause</div>
            {selectedColors.length === 0 ? (
              <div
                data-testid="sizes-empty"
                className="rounded-md border border-dashed border-[var(--border)] px-4 py-6 text-center text-sm text-[var(--text-muted)]"
              >
                Pick one or more colors above to see available sizes.
              </div>
            ) : (
              <div className="space-y-4">
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
                    (all sizes for each selected color)
                  </span>
                </label>

                <div>
                  <div className="text-xs uppercase tracking-widest text-[var(--text-muted)] mb-2">
                    …or pick specific sizes (across selected colors)
                  </div>
                  <div className="flex flex-wrap gap-2" data-testid="size-checkboxes">
                    {unionSizes.length === 0 && (
                      <span className="text-sm text-[var(--text-muted)]">
                        Loading sizes…
                      </span>
                    )}
                    {unionSizes.map((s) => {
                      const on = wholeProduct || selectedSizes.includes(s);
                      // how many of the selected colors have this size?
                      const colorsWithSize = selectedColors.filter(
                        (c) => (colorDetail[c]?.sizes || []).includes(s)
                      );
                      return (
                        <button
                          key={s}
                          data-testid={`size-chip-${s}`}
                          type="button"
                          onClick={() => toggleSize(s)}
                          title={`In ${colorsWithSize.length} / ${selectedColors.length} selected colors`}
                          className={`rounded-full border px-3 py-1.5 text-xs font-medium transition ${
                            on
                              ? "border-emerald-500/50 bg-emerald-500/15 text-emerald-200"
                              : "border-[var(--border)] bg-transparent text-[var(--text-secondary)] hover:border-white/30"
                          }`}
                        >
                          {s}
                          {colorsWithSize.length < selectedColors.length && (
                            <span className="ml-1 text-[9px] opacity-60">
                              ×{colorsWithSize.length}
                            </span>
                          )}
                        </button>
                      );
                    })}
                  </div>
                </div>

                <details className="rounded border border-[var(--border)] px-4 py-3">
                  <summary className="cursor-pointer text-xs uppercase tracking-widest text-[var(--text-muted)]">
                    Style IDs across selected colors ({totalStyleIds})
                  </summary>
                  <div className="mt-3 space-y-2" data-testid="style-ids-list">
                    {selectedColors.map((c) => (
                      <div key={c}>
                        <div className="text-[10px] uppercase tracking-widest text-sky-300 mb-1">
                          {c}
                        </div>
                        <div className="flex flex-wrap gap-1.5">
                          {(colorDetail[c]?.style_ids || []).map((s) => (
                            <span
                              key={s}
                              className="rounded bg-white/5 px-2 py-1 font-mono text-[11px] text-[var(--text-secondary)]"
                            >
                              {s}
                            </span>
                          ))}
                          {(colorDetail[c]?.style_ids || []).length === 0 && (
                            <span className="text-[11px] text-[var(--text-muted)]">
                              (loading…)
                            </span>
                          )}
                        </div>
                      </div>
                    ))}
                  </div>
                </details>
              </div>
            )}
          </div>

          {/* Summary + execute */}
          <div className="rounded-lg border border-[var(--border)] bg-[var(--bg-card)] p-6">
            <div className="section-label mb-4">4 · Execute</div>
            <div className="flex flex-wrap items-center gap-6 mb-5">
              <SummaryStat label="Colors" value={selectedColors.length} testid="summary-colors" />
              <SummaryStat label="Style IDs" value={totalStyleIds} testid="summary-style-ids" />
              <SummaryStat
                label="Sizes"
                value={wholeProduct ? unionSizes.length : selectedSizes.length}
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
              {pausing
                ? "Queuing…"
                : `Pause ${estimatedSkus || ""} SKU${estimatedSkus === 1 ? "" : "s"} across ${selectedColors.length} color${selectedColors.length === 1 ? "" : "s"}`
              }
            </button>
            {lastJobIds.length > 0 && (
              <div data-testid="last-jobs-hint" className="mt-3 text-xs text-[var(--text-muted)]">
                {lastJobIds.length} job(s) queued. Watch the history panel →
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
          <div
            className="mb-3 flex flex-wrap gap-1"
            data-testid="history-filter-tabs"
          >
            {[
              { k: "all",        label: "All",       n: counts.pending + counts.processing + counts.done + counts.failed },
              { k: "pending",    label: "Pending",   n: counts.pending },
              { k: "processing", label: "Running",   n: counts.processing },
              { k: "done",       label: "Done",      n: counts.done },
              { k: "failed",     label: "Failed",    n: counts.failed },
            ].map(({ k, label, n }) => {
              const on = statusFilter === k;
              return (
                <button
                  key={k}
                  type="button"
                  data-testid={`history-filter-${k}`}
                  onClick={() => setStatusFilter(k)}
                  className={`rounded-full border px-2.5 py-1 text-[10px] uppercase tracking-widest transition ${
                    on
                      ? "border-emerald-400/60 bg-emerald-500/15 text-emerald-200"
                      : "border-[var(--border)] bg-transparent text-[var(--text-muted)] hover:border-white/30"
                  }`}
                >
                  {label} <span className="ml-1 font-mono">{n}</span>
                </button>
              );
            })}
          </div>
          <div className="max-h-[70vh] space-y-2 overflow-auto pr-1" data-testid="history-list">
            {history.length === 0 && (
              <div className="rounded border border-dashed border-[var(--border)] p-6 text-center text-xs text-[var(--text-muted)]">
                {statusFilter === "all"
                  ? "No pause actions yet."
                  : `No ${statusFilter} actions.`}
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
