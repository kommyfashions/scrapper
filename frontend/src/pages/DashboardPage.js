import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
  PackageIcon,
  ChatCircleTextIcon,
  StarIcon,
  ListBulletsIcon,
  ArrowUpRightIcon,
  WarningCircleIcon,
} from "@phosphor-icons/react";
import api from "@/lib/api";
import PageHeader from "@/components/PageHeader";
import { fmtNumber, StatusPill } from "@/lib/format";

function Kpi({ label, value, sub, Icon, testid }) {
  return (
    <div className="kpi-card" data-testid={testid}>
      <div className="flex items-start justify-between">
        <div className="section-label">{label}</div>
        {Icon && <Icon size={16} weight="bold" color="#71717A" />}
      </div>
      <div className="mt-3 font-mono text-3xl font-semibold tracking-tight text-white">
        {value}
      </div>
      {sub && <div className="mt-1 text-xs text-[#A1A1AA]">{sub}</div>}
    </div>
  );
}

export default function DashboardPage() {
  const [overview, setOverview] = useState(null);
  const [jobsStats, setJobsStats] = useState(null);
  const [recentJobs, setRecentJobs] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    document.title = "Dashboard · Seller Central";
    Promise.all([
      api.get("/analytics/overview"),
      api.get("/jobs/stats"),
      api.get("/jobs", { params: { limit: 6 } }),
    ])
      .then(([a, b, c]) => {
        setOverview(a.data);
        setJobsStats(b.data);
        setRecentJobs(c.data.items);
      })
      .finally(() => setLoading(false));
  }, []);

  return (
    <div data-testid="dashboard-page">
      <PageHeader
        title="overview"
        subtitle="Operations Dashboard"
        right={
          <Link to="/jobs/new" className="btn-primary text-sm" data-testid="header-submit-cta">
            + Submit Job
          </Link>
        }
      />

      <div className="px-8 py-6 space-y-6">
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
          <Kpi
            label="Total Products"
            value={loading ? "—" : fmtNumber(overview?.total_products)}
            sub="Tracked in catalog"
            Icon={PackageIcon}
            testid="kpi-total-products"
          />
          <Kpi
            label="Total Reviews"
            value={loading ? "—" : fmtNumber(overview?.total_reviews)}
            sub="Across all products"
            Icon={ChatCircleTextIcon}
            testid="kpi-total-reviews"
          />
          <Kpi
            label="Avg Rating"
            value={loading ? "—" : overview?.avg_rating ?? "—"}
            sub="Weighted by review count"
            Icon={StarIcon}
            testid="kpi-avg-rating"
          />
          <Kpi
            label="Jobs Today"
            value={loading ? "—" : fmtNumber(overview?.jobs_today)}
            sub={
              jobsStats
                ? `${jobsStats.pending} pending · ${jobsStats.processing} running`
                : ""
            }
            Icon={ListBulletsIcon}
            testid="kpi-jobs-today"
          />
        </div>

        {jobsStats?.stuck > 0 && (
          <div
            className="panel flex items-center gap-3 border-[#FF3B30]/40 px-4 py-3"
            style={{ borderColor: "#FF3B3055", background: "rgba(255,59,48,0.06)" }}
            data-testid="stuck-jobs-warning"
          >
            <WarningCircleIcon size={20} weight="bold" color="#FF3B30" />
            <div className="flex-1 text-sm">
              <span className="font-mono text-[#FF3B30]">{jobsStats.stuck}</span>{" "}
              job(s) stuck in <span className="font-mono">processing</span> for over 30
              minutes — worker may be offline.
            </div>
            <Link to="/jobs" className="btn-secondary text-xs" data-testid="stuck-jobs-link">
              Review →
            </Link>
          </div>
        )}

        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
          <div className="panel lg:col-span-2">
            <div className="flex items-center justify-between border-b border-[#2A2A2A] px-5 py-3">
              <div className="font-display text-sm font-medium">Recent Jobs</div>
              <Link
                to="/jobs"
                className="text-xs text-[#A1A1AA] hover:text-white flex items-center gap-1"
                data-testid="recent-jobs-link"
              >
                View all <ArrowUpRightIcon size={12} weight="bold" />
              </Link>
            </div>
            <div className="overflow-x-auto">
              <table className="dense">
                <thead>
                  <tr>
                    <th>Status</th>
                    <th>Product URL</th>
                    <th className="num">Created</th>
                  </tr>
                </thead>
                <tbody>
                  {loading && (
                    <tr>
                      <td colSpan={3} className="text-center py-8 text-[#71717A] font-mono text-xs">
                        <span className="cursor-blink">LOADING</span>
                      </td>
                    </tr>
                  )}
                  {!loading && recentJobs.length === 0 && (
                    <tr>
                      <td colSpan={3} className="text-center py-8 text-[#71717A] text-xs">
                        No jobs yet.
                      </td>
                    </tr>
                  )}
                  {recentJobs.map((j) => (
                    <tr key={j.id} data-testid={`recent-job-row-${j.id}`}>
                      <td>
                        <StatusPill status={j.status} />
                      </td>
                      <td className="max-w-md truncate font-mono text-xs text-[#A1A1AA]">
                        {j.product_url}
                      </td>
                      <td className="num text-xs text-[#A1A1AA]">
                        {j.created_at?.replace("T", " ").slice(0, 16) || "—"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          <div className="panel">
            <div className="border-b border-[#2A2A2A] px-5 py-3 font-display text-sm font-medium">
              Job Queue
            </div>
            <div className="p-5 space-y-3">
              {[
                { k: "pending", color: "#F5A623" },
                { k: "processing", color: "#007AFF" },
                { k: "done", color: "#00E676" },
                { k: "failed", color: "#FF3B30" },
              ].map(({ k, color }) => {
                const v = jobsStats?.[k] ?? 0;
                const total = jobsStats
                  ? Math.max(
                      1,
                      (jobsStats.pending || 0) +
                        (jobsStats.processing || 0) +
                        (jobsStats.done || 0) +
                        (jobsStats.failed || 0)
                    )
                  : 1;
                const pct = (v / total) * 100;
                return (
                  <div key={k} data-testid={`queue-bar-${k}`}>
                    <div className="mb-1 flex items-center justify-between text-xs">
                      <span className="font-mono uppercase text-[#A1A1AA]">{k}</span>
                      <span className="font-mono text-white">{v}</span>
                    </div>
                    <div className="bar-track">
                      <div
                        className="bar-fill"
                        style={{ width: `${pct}%`, background: color }}
                      />
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
