import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
  ResponsiveContainer,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid,
  LineChart,
  Line,
} from "recharts";
import api from "@/lib/api";
import PageHeader from "@/components/PageHeader";
import { fmtNumber, StarRow } from "@/lib/format";

const STAR_COLORS = {
  5: "#00E676",
  4: "#7FE15A",
  3: "#F5A623",
  2: "#FF8C42",
  1: "#FF3B30",
};

const tooltipStyle = {
  background: "#0F0F0F",
  border: "1px solid #2A2A2A",
  borderRadius: 2,
  color: "#fff",
  fontFamily: "JetBrains Mono, monospace",
  fontSize: 12,
};

export default function AnalyticsPage() {
  const [d, setD] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    document.title = "Analytics · Seller Central";
    api
      .get("/analytics/overview")
      .then((r) => setD(r.data))
      .finally(() => setLoading(false));
  }, []);

  const distData = d
    ? [5, 4, 3, 2, 1].map((s) => ({
        name: `${s}★`,
        value: Number(d.rating_distribution?.[s] ?? d.rating_distribution?.[String(s)] ?? 0),
        color: STAR_COLORS[s],
      }))
    : [];

  return (
    <div data-testid="analytics-page">
      <PageHeader title="insights" subtitle="Analytics" />
      <div className="px-8 py-6 space-y-6">
        {loading && (
          <div className="font-mono text-xs uppercase tracking-widest text-[#71717A] cursor-blink">
            LOADING ANALYTICS
          </div>
        )}
        {d && (
          <>
            <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
              <div className="kpi-card" data-testid="ana-products">
                <div className="section-label">Products</div>
                <div className="mt-3 font-mono text-3xl">{fmtNumber(d.total_products)}</div>
              </div>
              <div className="kpi-card" data-testid="ana-reviews">
                <div className="section-label">Reviews</div>
                <div className="mt-3 font-mono text-3xl">{fmtNumber(d.total_reviews)}</div>
              </div>
              <div className="kpi-card" data-testid="ana-avg">
                <div className="section-label">Avg Rating</div>
                <div className="mt-3 font-mono text-3xl">{d.avg_rating ?? "—"}</div>
                <div className="mt-1"><StarRow rating={d.avg_rating} /></div>
              </div>
              <div className="kpi-card" data-testid="ana-jobs-today">
                <div className="section-label">Jobs Today</div>
                <div className="mt-3 font-mono text-3xl">{fmtNumber(d.jobs_today)}</div>
                <div className="mt-1 text-xs text-[#A1A1AA]">
                  {d.job_status_breakdown.done} done · {d.job_status_breakdown.failed} failed
                </div>
              </div>
            </div>

            <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
              <div className="panel lg:col-span-1 p-5">
                <div className="section-label mb-4">/ overall rating distribution</div>
                <div style={{ width: "100%", height: 220 }}>
                  <ResponsiveContainer>
                    <BarChart data={distData} layout="vertical" margin={{ top: 0, right: 16, left: 0, bottom: 0 }}>
                      <CartesianGrid stroke="#2A2A2A" strokeDasharray="2 4" horizontal={false} />
                      <XAxis type="number" stroke="#71717A" fontSize={11} fontFamily="JetBrains Mono" />
                      <YAxis dataKey="name" type="category" stroke="#71717A" fontSize={11} fontFamily="JetBrains Mono" width={32} />
                      <Tooltip contentStyle={tooltipStyle} cursor={{ fill: "rgba(0,122,255,0.06)" }} />
                      <Bar dataKey="value" radius={[0, 2, 2, 0]}>
                        {distData.map((row, i) => (
                          <rect key={i} fill={row.color} />
                        ))}
                      </Bar>
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              </div>

              <div className="panel lg:col-span-2 p-5">
                <div className="section-label mb-4">/ review volume (last 30 days)</div>
                {d.review_volume.length === 0 ? (
                  <div className="text-xs text-[#71717A] py-10 text-center">
                    No recent reviews to plot.
                  </div>
                ) : (
                  <div style={{ width: "100%", height: 220 }}>
                    <ResponsiveContainer>
                      <LineChart data={d.review_volume} margin={{ top: 8, right: 16, left: -10, bottom: 0 }}>
                        <CartesianGrid stroke="#2A2A2A" strokeDasharray="2 4" />
                        <XAxis dataKey="date" stroke="#71717A" fontSize={10} fontFamily="JetBrains Mono" />
                        <YAxis stroke="#71717A" fontSize={10} fontFamily="JetBrains Mono" />
                        <Tooltip contentStyle={tooltipStyle} />
                        <Line
                          type="monotone"
                          dataKey="count"
                          stroke="#007AFF"
                          strokeWidth={2}
                          dot={{ r: 3, fill: "#007AFF" }}
                          activeDot={{ r: 5 }}
                        />
                      </LineChart>
                    </ResponsiveContainer>
                  </div>
                )}
              </div>
            </div>

            <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
              <div className="panel">
                <div className="border-b border-[#2A2A2A] px-5 py-3 font-display text-sm font-medium">
                  Top Sellers
                </div>
                <div className="overflow-x-auto">
                  <table className="dense">
                    <thead>
                      <tr>
                        <th>Seller</th>
                        <th className="num">Products</th>
                        <th className="num">Reviews</th>
                      </tr>
                    </thead>
                    <tbody>
                      {d.top_sellers.length === 0 && (
                        <tr><td colSpan={3} className="text-center py-6 text-[#71717A] text-xs">No data</td></tr>
                      )}
                      {d.top_sellers.map((s) => (
                        <tr key={s.seller} data-testid={`top-seller-${s.seller}`}>
                          <td className="text-sm">{s.seller}</td>
                          <td className="num font-mono text-sm">{s.products}</td>
                          <td className="num font-mono text-sm">{fmtNumber(s.reviews)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>

              <div className="panel">
                <div className="border-b border-[#2A2A2A] px-5 py-3 font-display text-sm font-medium">
                  Most Helpful Reviews
                </div>
                <div className="divide-y divide-[#2A2A2A]">
                  {d.helpful_reviews.length === 0 && (
                    <div className="px-5 py-6 text-center text-xs text-[#71717A]">
                      No helpful reviews yet.
                    </div>
                  )}
                  {d.helpful_reviews.map((r, i) => (
                    <div key={i} className="px-5 py-3" data-testid={`helpful-${i}`}>
                      <div className="flex items-center justify-between">
                        <div className="flex items-center gap-2">
                          <StarRow rating={r.rating} />
                          <span className="text-xs text-[#A1A1AA]">{r.customer}</span>
                        </div>
                        <Link
                          to={`/products/${r.product_id}`}
                          className="font-mono text-[10px] text-[#007AFF] hover:underline"
                        >
                          {r.product_id} →
                        </Link>
                      </div>
                      {r.text && (
                        <p className="mt-1 text-xs text-[#E5E5E5] line-clamp-2">{r.text}</p>
                      )}
                      <div className="mt-1 font-mono text-[10px] text-[#71717A]">
                        +{r.helpful} helpful · {r.seller}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
