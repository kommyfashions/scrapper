import { useEffect, useState, useCallback } from "react";
import {
  ArrowsClockwiseIcon,
  TrashIcon,
  WarningCircleIcon,
  MagnifyingGlassIcon,
} from "@phosphor-icons/react";
import api, { formatApiError } from "@/lib/api";
import PageHeader from "@/components/PageHeader";
import { fmtDate, fmtRelative, StatusPill } from "@/lib/format";

const FILTERS = ["all", "pending", "processing", "done", "failed"];
const TYPES = [
  { k: "all", label: "ALL TYPES" },
  { k: "product_scrape", label: "SCRAPE" },
  { k: "label_download", label: "LABEL" },
];

export default function JobsPage() {
  const [items, setItems] = useState([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [status, setStatus] = useState("all");
  const [jobType, setJobType] = useState("all");
  const [q, setQ] = useState("");
  const [stats, setStats] = useState(null);
  const [error, setError] = useState("");
  const [busyId, setBusyId] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [jobs, st] = await Promise.all([
        api.get("/jobs", { params: { status, type: jobType, q: q || undefined, limit: 100 } }),
        api.get("/jobs/stats"),
      ]);
      setItems(jobs.data.items);
      setTotal(jobs.data.total);
      setStats(st.data);
    } catch (e) {
      setError(formatApiError(e));
    } finally {
      setLoading(false);
    }
  }, [status, jobType, q]);

  useEffect(() => {
    document.title = "Jobs · Seller Central";
    load();
  }, [load]);

  // auto refresh every 8s if there are processing jobs
  useEffect(() => {
    if (!stats) return;
    if ((stats.processing || 0) + (stats.pending || 0) === 0) return;
    const t = setInterval(load, 8000);
    return () => clearInterval(t);
  }, [stats, load]);

  const retry = async (id) => {
    setBusyId(id);
    try {
      await api.post(`/jobs/${id}/retry`);
      await load();
    } catch (e) {
      setError(formatApiError(e));
    } finally {
      setBusyId(null);
    }
  };

  const remove = async (id) => {
    if (!window.confirm("Delete this job? This cannot be undone.")) return;
    setBusyId(id);
    try {
      await api.delete(`/jobs/${id}`);
      await load();
    } catch (e) {
      setError(formatApiError(e));
    } finally {
      setBusyId(null);
    }
  };

  const resetStuck = async () => {
    if (!window.confirm("Reset all stuck 'processing' jobs back to 'pending'?")) return;
    try {
      const { data } = await api.post("/jobs/reset-stuck");
      await load();
      alert(`Reset ${data.reset} job(s).`);
    } catch (e) {
      setError(formatApiError(e));
    }
  };

  return (
    <div data-testid="jobs-page">
      <PageHeader
        title="queue"
        subtitle="Jobs"
        right={
          <>
            <button
              onClick={load}
              className="btn-secondary text-sm flex items-center gap-2"
              data-testid="refresh-jobs-button"
            >
              <ArrowsClockwiseIcon size={14} weight="bold" />
              Refresh
            </button>
            {stats?.stuck > 0 && (
              <button
                onClick={resetStuck}
                className="btn-danger text-sm flex items-center gap-2"
                data-testid="reset-stuck-button"
              >
                <WarningCircleIcon size={14} weight="bold" />
                Reset {stats.stuck} stuck
              </button>
            )}
          </>
        }
      />

      <div className="px-8 py-6 space-y-4">
        <div className="flex flex-wrap items-center gap-2">
          {FILTERS.map((f) => {
            const count =
              f === "all"
                ? (stats ? stats.pending + stats.processing + stats.done + stats.failed : null)
                : stats?.[f];
            const active = status === f;
            return (
              <button
                key={f}
                onClick={() => setStatus(f)}
                className={
                  "px-3 py-1.5 text-xs font-mono uppercase tracking-wider rounded-sm transition-colors " +
                  (active
                    ? "bg-[#007AFF] text-white"
                    : "bg-[#141414] text-[#A1A1AA] border border-[#2A2A2A] hover:bg-[#1F1F1F]")
                }
                data-testid={`filter-${f}`}
              >
                {f}
                {count !== null && count !== undefined && (
                  <span className="ml-2 opacity-70">{count}</span>
                )}
              </button>
            );
          })}
          <div className="mx-3 h-6 w-px bg-[#2A2A2A]" />
          {TYPES.map((t) => (
            <button
              key={t.k}
              onClick={() => setJobType(t.k)}
              className={
                "px-3 py-1.5 text-xs font-mono uppercase tracking-wider rounded-sm transition-colors " +
                (jobType === t.k
                  ? "bg-[#F5A623] text-black"
                  : "bg-[#141414] text-[#A1A1AA] border border-[#2A2A2A] hover:bg-[#1F1F1F]")
              }
              data-testid={`type-filter-${t.k}`}
            >
              {t.label}
            </button>
          ))}
          <div className="flex-1" />
          <div className="relative w-full sm:w-72">
            <MagnifyingGlassIcon
              size={14}
              weight="bold"
              color="#71717A"
              className="absolute left-3 top-1/2 -translate-y-1/2 pointer-events-none"
            />
            <input
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="Search by URL…"
              className="input-shell pl-8 text-sm"
              data-testid="jobs-search-input"
            />
          </div>
        </div>

        {error && (
          <div className="border border-[#FF3B30]/30 bg-[#FF3B30]/10 px-3 py-2 font-mono text-xs text-[#FF3B30]">
            {error}
          </div>
        )}

        <div className="table-wrap">
          <table className="dense">
            <thead>
              <tr>
                <th>Status</th>
                <th>Product URL</th>
                <th className="num">Created</th>
                <th className="num">Started</th>
                <th className="num">Finished</th>
                <th className="num">Actions</th>
              </tr>
            </thead>
            <tbody>
              {loading && (
                <tr>
                  <td colSpan={6} className="text-center py-8 text-[#71717A] font-mono text-xs">
                    <span className="cursor-blink">LOADING JOBS</span>
                  </td>
                </tr>
              )}
              {!loading && items.length === 0 && (
                <tr>
                  <td colSpan={6} className="text-center py-8 text-[#71717A] text-sm">
                    No jobs match.
                  </td>
                </tr>
              )}
              {items.map((j) => {
                const pid = j.product_id || (j.product_url || "").split("/p/")[1]?.split(/[/?#]/)[0];
                return (
                  <tr key={j.id} data-testid={`job-row-${j.id}`}>
                    <td>
                      <StatusPill status={j.status} />
                      {j.type === "label_download" && (
                        <span className="ml-2 code-tag text-[#F5A623] border-[#F5A623]/40">LABEL</span>
                      )}
                      {j.error && (
                        <div
                          className="mt-1 max-w-[260px] truncate font-mono text-[10px] text-[#FF3B30]"
                          title={j.error}
                        >
                          {j.error}
                        </div>
                      )}
                    </td>
                    <td className="max-w-md">
                      {j.type === "label_download" ? (
                        <div className="font-mono text-xs text-[#F5A623]">Label Download job</div>
                      ) : (
                        <>
                          <div className="font-mono text-xs text-white truncate">{j.product_url}</div>
                          {pid && (
                            <span className="code-tag mt-1 inline-block">id: {pid}</span>
                          )}
                        </>
                      )}
                    </td>
                    <td className="num text-xs text-[#A1A1AA]" title={fmtDate(j.created_at)}>
                      {fmtRelative(j.created_at)}
                    </td>
                    <td className="num text-xs text-[#A1A1AA]">{fmtRelative(j.started_at)}</td>
                    <td className="num text-xs text-[#A1A1AA]">{fmtRelative(j.finished_at)}</td>
                    <td className="num">
                      <div className="flex items-center justify-end gap-1">
                        <button
                          onClick={() => retry(j.id)}
                          disabled={busyId === j.id}
                          className="btn-ghost flex items-center gap-1 text-xs"
                          title="Reset to pending"
                          data-testid={`retry-${j.id}`}
                        >
                          <ArrowsClockwiseIcon size={12} weight="bold" />
                          Retry
                        </button>
                        <button
                          onClick={() => remove(j.id)}
                          disabled={busyId === j.id}
                          className="btn-ghost flex items-center gap-1 text-xs text-[#FF3B30]/80 hover:text-[#FF3B30]"
                          title="Delete"
                          data-testid={`delete-${j.id}`}
                        >
                          <TrashIcon size={12} weight="bold" />
                        </button>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>

        <div className="font-mono text-[11px] text-[#71717A]">
          Showing {items.length} of {total}
        </div>
      </div>
    </div>
  );
}
