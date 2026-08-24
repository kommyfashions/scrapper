import { useCallback, useEffect, useMemo, useState } from "react";
import {
  ArrowsClockwiseIcon,
  DownloadSimpleIcon,
  MagnifyingGlassIcon,
  CheckCircleIcon,
  XCircleIcon,
  ClockIcon,
  StorefrontIcon,
} from "@phosphor-icons/react";
import api, { formatApiError } from "@/lib/api";
import PageHeader from "@/components/PageHeader";
import WorkerDriftBanner from "@/components/WorkerDriftBanner";
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

export default function LiveInventoryPage() {
  const [accounts, setAccounts] = useState([]);
  const [accountId, setAccountId] = useState("all");
  const [pages, setPages] = useState(20);
  const [tab, setTab] = useState("live");
  const [search, setSearch] = useState("");
  const [category, setCategory] = useState("");
  const [live, setLive] = useState({ items: [], total: 0, facets: {} });
  const [missing, setMissing] = useState({ items: [], total: 0, facets: {} });
  const [history, setHistory] = useState([]);
  const [lastSync, setLastSync] = useState({});
  const [loading, setLoading] = useState(false);
  const [runningJobs, setRunningJobs] = useState([]); // job ids
  const [err, setErr] = useState("");
  const [info, setInfo] = useState("");

  const loadAccounts = useCallback(async () => {
    try {
      const r = await api.get("/inventory-actions/options");
      setAccounts(r.data.accounts || []);
    } catch (e) { setErr(formatApiError(e)); }
  }, []);

  const loadLive = useCallback(async () => {
    setLoading(true); setErr("");
    try {
      const params = { limit: 1000 };
      if (accountId && accountId !== "all") params.account_id = accountId;
      if (category) params.category = category;
      if (search.trim()) params.search = search.trim();
      const r = await api.get("/inventory-sync/live", { params });
      setLive(r.data);
    } catch (e) { setErr(formatApiError(e)); }
    finally { setLoading(false); }
  }, [accountId, category, search]);

  const loadMissing = useCallback(async () => {
    setLoading(true); setErr("");
    try {
      const params = { limit: 1000 };
      if (accountId && accountId !== "all") params.account_id = accountId;
      if (search.trim()) params.search = search.trim();
      const r = await api.get("/inventory-sync/missing", { params });
      setMissing(r.data);
    } catch (e) { setErr(formatApiError(e)); }
    finally { setLoading(false); }
  }, [accountId, search]);

  const loadHistory = useCallback(async () => {
    try {
      const r = await api.get("/inventory-sync/history", { params: { limit: 30 } });
      setHistory(r.data.items || []);
    } catch (e) { /* silent */ }
  }, []);

  const loadLastSync = useCallback(async () => {
    try {
      const r = await api.get("/inventory-sync/last-sync");
      const map = {};
      (r.data.items || []).forEach((it) => { map[it.account_id] = it; });
      setLastSync(map);
    } catch (e) { /* silent */ }
  }, []);

  useEffect(() => { loadAccounts(); loadHistory(); loadLastSync(); }, [loadAccounts, loadHistory, loadLastSync]);
  useEffect(() => { if (tab === "live") loadLive(); }, [tab, loadLive]);
  useEffect(() => { if (tab === "missing") loadMissing(); }, [tab, loadMissing]);

  const runSync = async () => {
    setErr(""); setInfo("");
    try {
      const r = await api.post("/inventory-sync/run", {
        account_id: accountId,
        pages: Number(pages) || 20,
      });
      const ids = r.data.fanned_out
        ? (r.data.jobs || []).map((j) => j.job_id).filter(Boolean)
        : [r.data.job_id].filter(Boolean);
      setRunningJobs(ids);
      if (r.data.fanned_out) {
        setInfo(`Queued ${ids.length} sync job(s) — one per account. Runs sequentially on EC2.`);
      } else {
        setInfo(r.data.already_queued
          ? "A sync for this account is already queued or running."
          : `Sync queued (${pages} pages).`);
      }
      await loadHistory();
    } catch (e) {
      setErr(formatApiError(e));
      setRunningJobs([]);
    }
  };

  // Poll running jobs until every one is done/failed
  useEffect(() => {
    if (!runningJobs.length) return;
    const t = setInterval(async () => {
      try {
        const r = await api.get("/inventory-sync/history", { params: { limit: 50 } });
        setHistory(r.data.items || []);
        const outstanding = runningJobs.filter((id) => {
          const j = (r.data.items || []).find((x) => x.id === id);
          return !j || (j.status !== "done" && j.status !== "failed");
        });
        if (outstanding.length === 0) {
          clearInterval(t);
          setRunningJobs([]);
          loadLastSync();
          if (tab === "live") loadLive();
          if (tab === "missing") loadMissing();
        } else {
          setRunningJobs(outstanding);
        }
      } catch (e) { /* silent */ }
    }, 3000);
    return () => clearInterval(t);
  }, [runningJobs, tab, loadLive, loadMissing, loadLastSync]);

  const triggerDownload = (r, defaultName) => {
    const cd = r.headers?.["content-disposition"] || "";
    const m = /filename="?([^"]+)"?/i.exec(cd);
    const name = (m && m[1]) || defaultName;
    const url = URL.createObjectURL(new Blob([r.data]));
    const a = document.createElement("a");
    a.href = url; a.download = name;
    document.body.appendChild(a); a.click();
    setTimeout(() => { URL.revokeObjectURL(url); a.remove(); }, 4000);
  };

  const exportLive = async () => {
    const params = new URLSearchParams();
    if (accountId && accountId !== "all") params.set("account_id", accountId);
    if (category) params.set("category", category);
    if (search.trim()) params.set("search", search.trim());
    const r = await api.get(`/inventory-sync/live/export?${params.toString()}`, {
      responseType: "blob",
    });
    triggerDownload(r, "live_skus.xlsx");
  };

  const exportMissing = async () => {
    const params = new URLSearchParams();
    if (accountId && accountId !== "all") params.set("account_id", accountId);
    if (search.trim()) params.set("search", search.trim());
    const r = await api.get(`/inventory-sync/missing/export?${params.toString()}`, {
      responseType: "blob",
    });
    triggerDownload(r, "missing_live_skus.xlsx");
  };

  const categoriesForAccount = useMemo(
    () => (live.facets?.by_category || []).map((c) => c.category).filter(Boolean),
    [live.facets]
  );

  const lastForAcc = accountId !== "all" ? lastSync[accountId] : null;
  const isSyncing = runningJobs.length > 0;
  const missingCount = missing.total || 0;

  return (
    <div className="min-h-screen" data-testid="live-inventory-page">
      <PageHeader
        title="INVENTORY / LIVE ON MEESHO"
        subtitle="Currently active SKUs scraped from the seller panel"
        right={
          <div className="flex items-center gap-2">
            <button
              onClick={() => { loadHistory(); loadLastSync(); if (tab === "live") loadLive(); if (tab === "missing") loadMissing(); }}
              className="btn-ghost text-xs"
              data-testid="refresh-btn"
            >
              <ArrowsClockwiseIcon size={12} weight="bold" />
              <span className="ml-1">Refresh</span>
            </button>
          </div>
        }
      />

      <div className="px-8 py-6 space-y-6">
        <WorkerDriftBanner neededTypes={["inventory_sync"]} />

        {/* controls */}
        <div className="rounded-lg border border-[var(--border)] bg-[var(--bg-card)] p-4 flex flex-wrap items-end gap-3">
          <label className="block">
            <div className="mb-1 text-[10px] font-semibold uppercase tracking-widest text-[var(--text-muted)]">Account</div>
            <select
              data-testid="account-select"
              className="input-shell text-sm"
              value={accountId}
              onChange={(e) => setAccountId(e.target.value)}
            >
              <option value="all">All accounts</option>
              {accounts.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.alias || a.name}
                </option>
              ))}
            </select>
          </label>
          <label className="block">
            <div className="mb-1 text-[10px] font-semibold uppercase tracking-widest text-[var(--text-muted)]">Pages to scrape</div>
            <input
              data-testid="pages-input"
              type="number"
              min={1}
              max={200}
              className="input-shell text-sm w-24"
              value={pages}
              onChange={(e) => setPages(e.target.value)}
            />
          </label>
          <label className="block flex-1 min-w-[240px]">
            <div className="mb-1 text-[10px] font-semibold uppercase tracking-widest text-[var(--text-muted)]">Search Style ID</div>
            <div className="relative">
              <MagnifyingGlassIcon size={14} weight="bold"
                className="absolute left-2 top-1/2 -translate-y-1/2 text-[var(--text-muted)]" />
              <input
                data-testid="search-input"
                className="input-shell pl-7 text-sm w-full"
                placeholder="RM-LEOO-5-NAVY BLUE-123…"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                onKeyDown={(e) => { if (e.key === "Enter") { if (tab === "live") loadLive(); else if (tab === "missing") loadMissing(); } }}
              />
            </div>
          </label>
          {tab === "live" && categoriesForAccount.length > 0 && (
            <label className="block">
              <div className="mb-1 text-[10px] font-semibold uppercase tracking-widest text-[var(--text-muted)]">Main Category</div>
              <select
                data-testid="category-select"
                className="input-shell text-sm"
                value={category}
                onChange={(e) => setCategory(e.target.value)}
              >
                <option value="">All</option>
                {categoriesForAccount.map((c) => (
                  <option key={c} value={c}>{c}</option>
                ))}
              </select>
            </label>
          )}
          <button
            data-testid="run-sync-btn"
            onClick={runSync}
            disabled={isSyncing}
            className="inline-flex items-center gap-2 rounded-md bg-emerald-500 px-4 py-2 text-xs font-semibold text-white shadow-lg shadow-emerald-500/20 transition hover:bg-emerald-400 disabled:cursor-not-allowed disabled:opacity-40"
          >
            <StorefrontIcon size={14} weight="fill" />
            {isSyncing ? `Syncing… (${runningJobs.length})` : "Sync from Meesho"}
          </button>
          <button
            data-testid="export-live-btn"
            onClick={exportLive}
            className="btn-ghost text-xs flex items-center gap-1"
          >
            <DownloadSimpleIcon size={12} weight="bold" />
            Export live SKUs
          </button>
          <button
            data-testid="export-missing-btn"
            onClick={exportMissing}
            className="btn-ghost text-xs flex items-center gap-1"
          >
            <DownloadSimpleIcon size={12} weight="bold" />
            Export missing
          </button>
        </div>

        {lastForAcc && (
          <div className="rounded border border-[var(--border)] bg-black/20 px-3 py-2 text-xs text-[var(--text-muted)]" data-testid="last-sync-info">
            Last sync for <span className="text-white">{lastForAcc.account_name}</span>{" "}
            · {fmtRelative(lastForAcc.finished_at)} · captured{" "}
            <span className="text-emerald-300">{lastForAcc.result.skus_captured}</span> SKUs
            across <span className="text-emerald-300">{lastForAcc.result.catalogs_scanned}</span> catalogs
            ({lastForAcc.result.pages_visited} pages)
          </div>
        )}

        {info && (
          <div data-testid="info-banner" className="rounded border border-emerald-500/40 bg-emerald-500/10 px-3 py-2 text-sm text-emerald-200">
            {info}
          </div>
        )}
        {err && (
          <div data-testid="error-banner" className="rounded border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-sm text-rose-200">
            {err}
          </div>
        )}

        {/* tabs */}
        <div className="flex gap-1" data-testid="tabs">
          {[
            { k: "live", label: `Live SKUs ${live.total ? `(${live.total})` : ""}` },
            { k: "missing", label: `Missing ${missingCount ? `(${missingCount})` : ""}` },
            { k: "history", label: "Sync history" },
          ].map(({ k, label }) => (
            <button
              key={k}
              data-testid={`tab-${k}`}
              onClick={() => setTab(k)}
              className={`rounded-t border border-b-0 px-3 py-1.5 text-xs uppercase tracking-widest transition ${
                tab === k
                  ? "border-[var(--border)] bg-[var(--bg-card)] text-emerald-200"
                  : "border-transparent text-[var(--text-muted)] hover:text-white"
              }`}
            >
              {label}
            </button>
          ))}
        </div>

        <div className="rounded-lg border border-[var(--border)] bg-[var(--bg-card)] overflow-hidden">
          {tab === "live" && (
            <RowTable
              rows={live.items}
              loading={loading}
              emptyMsg={<>No live SKUs yet. Click <b>Sync from Meesho</b> to fetch.</>}
              testid="live-table"
            />
          )}
          {tab === "missing" && (
            <RowTable
              rows={missing.items}
              loading={loading}
              emptyMsg={<>Nothing missing — every scraped Style ID is in Master Inventory.</>}
              testid="missing-table"
            />
          )}
          {tab === "history" && (
            <HistoryList items={history} />
          )}
        </div>
      </div>
    </div>
  );
}

function RowTable({ rows, loading, emptyMsg, testid }) {
  if (loading) return <div className="p-6 text-sm text-[var(--text-muted)]">Loading…</div>;
  if (!rows || rows.length === 0) {
    return (
      <div className="p-8 text-center text-sm text-[var(--text-muted)]" data-testid={`${testid}-empty`}>
        {emptyMsg}
      </div>
    );
  }
  return (
    <div className="overflow-auto max-h-[65vh]" data-testid={testid}>
      <table className="dense w-full">
        <thead>
          <tr>
            <th>Account</th>
            <th>Main Category</th>
            <th>Style ID</th>
            <th>Last Synced</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i}>
              <td className="text-xs">{r.account}</td>
              <td className="text-xs">
                {r.main_category === "Unmapped"
                  ? <span className="rounded bg-amber-500/15 text-amber-300 px-1.5 py-0.5 text-[10px] uppercase tracking-widest">Unmapped</span>
                  : r.main_category}
              </td>
              <td className="font-mono text-[11px]">{r.style_id}</td>
              <td className="text-xs text-[var(--text-muted)]">{r.last_synced ? new Date(r.last_synced).toLocaleString() : "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function HistoryList({ items }) {
  if (!items || items.length === 0) {
    return <div className="p-8 text-center text-sm text-[var(--text-muted)]" data-testid="history-empty">No sync runs yet.</div>;
  }
  return (
    <div className="max-h-[70vh] overflow-auto" data-testid="history-list">
      {items.map((j) => {
        const Icon = j.status === "done" ? CheckCircleIcon : j.status === "failed" ? XCircleIcon : ClockIcon;
        return (
          <div key={j.id} className="border-b border-[var(--border)] px-4 py-3 flex items-start gap-3" data-testid={`history-item-${j.id}`}>
            <Icon size={16} weight="fill" className={
              j.status === "done" ? "text-emerald-400" :
              j.status === "failed" ? "text-rose-400" : "text-sky-400"
            } />
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2">
                <span className="text-sm">{j.account_name}</span>
                <StatusPill status={j.status} />
                <span className="text-[10px] text-[var(--text-muted)]">
                  {j.pages_requested ? `${j.pages_requested} pages requested` : ""}
                </span>
              </div>
              <div className="mt-1 text-[11px] text-[var(--text-muted)]">
                {fmtRelative(j.created_at)} · captured <span className="text-emerald-300">{j.result.skus_captured}</span> Style IDs across <span className="text-emerald-300">{j.result.catalogs_scanned}</span> catalogs ({j.result.pages_visited} pages visited)
              </div>
              {j.error && <div className="mt-1 text-[11px] text-rose-300 truncate" title={j.error}>{j.error}</div>}
              {j.result.note && (
                <div className="mt-1 text-[11px] text-amber-300 whitespace-pre-wrap break-all" data-testid={`sync-note-${j.id}`}>
                  {j.result.note}
                </div>
              )}
              {j.result.debug_dir && (
                <div className="mt-1 text-[10px] text-[var(--text-muted)]" data-testid={`sync-debug-${j.id}`}>
                  Screenshots on scraper box: <code className="font-mono">{j.result.debug_dir}</code>
                </div>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}
