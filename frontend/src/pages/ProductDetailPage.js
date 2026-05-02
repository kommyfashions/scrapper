import { useEffect, useState, useMemo } from "react";
import { Link, useParams } from "react-router-dom";
import {
  ArrowLeftIcon,
  ArrowSquareOutIcon,
  StorefrontIcon,
  ThumbsUpIcon,
  ImageSquareIcon,
  TrendUpIcon,
} from "@phosphor-icons/react";
import {
  ResponsiveContainer, LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip,
} from "recharts";
import api from "@/lib/api";
import PageHeader from "@/components/PageHeader";
import { fmtDate, fmtNumber, StarRow } from "@/lib/format";

const STAR_COLORS = {
  5: "#00E676", 4: "#7FE15A", 3: "#F5A623", 2: "#FF8C42", 1: "#FF3B30",
};
const tooltipStyle = {
  background: "#0F0F0F", border: "1px solid #2A2A2A", borderRadius: 2,
  color: "#fff", fontFamily: "JetBrains Mono, monospace", fontSize: 12,
};

export default function ProductDetailPage() {
  const { productId } = useParams();
  const [product, setProduct] = useState(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState("");
  const [starFilter, setStarFilter] = useState("all");
  const [sortBy, setSortBy] = useState("date");
  const [history, setHistory] = useState([]);
  const [historyRange, setHistoryRange] = useState(30);
  const [trackBusy, setTrackBusy] = useState(false);
  const [compareA, setCompareA] = useState("");
  const [compareB, setCompareB] = useState("");

  const loadProduct = () => {
    setLoading(true);
    api.get(`/products/${productId}`)
      .then((r) => setProduct(r.data))
      .catch((e) => setErr(e?.response?.data?.detail || "Not found"))
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    document.title = `Product ${productId} · Seller Central`;
    loadProduct();
  }, [productId]);

  useEffect(() => {
    api.get(`/products/${productId}/history`, { params: { days: historyRange } })
      .then((r) => {
        const items = r.data.items || [];
        setHistory(items);
        // default compare: oldest ↔ latest inside the visible range
        if (items.length >= 2) {
          setCompareA(items[0].snapshot_at);
          setCompareB(items[items.length - 1].snapshot_at);
        } else {
          setCompareA("");
          setCompareB("");
        }
      })
      .catch(() => setHistory([]));
  }, [productId, historyRange]);

  const dist = product?.rating_distribution || {};
  const totalReviews = product?.total_reviews || 0;
  const maxBar = useMemo(() => Math.max(1, ...Object.values(dist).map(Number)), [dist]);

  const reviews = useMemo(() => {
    if (!product?.reviews) return [];
    let out = [...product.reviews];
    if (starFilter !== "all") out = out.filter((r) => Number(r.rating) === parseInt(starFilter, 10));
    if (sortBy === "date") out.sort((a, b) => String(b.created_at).localeCompare(String(a.created_at)));
    else if (sortBy === "helpful") out.sort((a, b) => (Number(b.helpful) || 0) - (Number(a.helpful) || 0));
    else if (sortBy === "rating_high") out.sort((a, b) => (Number(b.rating) || 0) - (Number(a.rating) || 0));
    else if (sortBy === "rating_low") out.sort((a, b) => (Number(a.rating) || 0) - (Number(b.rating) || 0));
    return out;
  }, [product, starFilter, sortBy]);

  const historyChartData = useMemo(() => {
    return history.map((h) => ({
      date: (h.snapshot_at || "").slice(0, 10),
      reviews: h.total_reviews ?? 0,
      rating: h.avg_rating ?? null,
    }));
  }, [history]);

  const delta = useMemo(() => {
    if (history.length < 2) return null;
    const first = history[0];
    const last = history[history.length - 1];
    return {
      reviews: (last.total_reviews ?? 0) - (first.total_reviews ?? 0),
      rating: (last.avg_rating ?? 0) - (first.avg_rating ?? 0),
    };
  }, [history]);

  const compareRows = useMemo(() => {
    const a = history.find((h) => h.snapshot_at === compareA);
    const b = history.find((h) => h.snapshot_at === compareB);
    if (!a || !b) return null;
    const aDist = a.rating_distribution || {};
    const bDist = b.rating_distribution || {};
    const star = (s) => ({
      label: `${s}★`,
      a: Number(aDist[s] ?? aDist[String(s)] ?? 0),
      b: Number(bDist[s] ?? bDist[String(s)] ?? 0),
      // for stars: going DOWN on 1★/2★ is "good"; going UP on 4★/5★ is "good"
      goodWhenUp: s >= 4,
    });
    return {
      dateA: (a.snapshot_at || "").slice(0, 10),
      dateB: (b.snapshot_at || "").slice(0, 10),
      rows: [
        { label: "Total reviews", a: a.total_reviews ?? 0, b: b.total_reviews ?? 0, goodWhenUp: true, kind: "int" },
        { label: "Avg rating",    a: a.avg_rating ?? 0,    b: b.avg_rating ?? 0,    goodWhenUp: true, kind: "rating" },
        star(5), star(4), star(3), star(2), star(1),
      ],
    };
  }, [history, compareA, compareB]);

  const toggleTrack = async () => {
    if (!product) return;
    setTrackBusy(true);
    try {
      await api.post(`/products/${productId}/track`, { tracked: !product.tracked });
      setProduct({ ...product, tracked: !product.tracked });
    } finally {
      setTrackBusy(false);
    }
  };

  if (loading) {
    return (
      <div data-testid="product-detail-loading" className="flex h-full items-center justify-center">
        <div className="font-mono text-xs uppercase tracking-widest text-[#71717A] cursor-blink">
          LOADING PRODUCT
        </div>
      </div>
    );
  }

  if (err || !product) {
    return (
      <div className="px-8 py-10">
        <Link to="/products" className="btn-secondary text-xs">
          <ArrowLeftIcon size={12} weight="bold" /> Back
        </Link>
        <div className="mt-6 panel p-6 text-sm text-[#FF3B30]">{err || "Not found"}</div>
      </div>
    );
  }

  return (
    <div data-testid="product-detail-page">
      <PageHeader
        title={`product / ${product.product_id}`}
        subtitle={product.product_name || "Product Detail"}
        right={
          <>
            <Link to="/products" className="btn-secondary text-xs flex items-center gap-1">
              <ArrowLeftIcon size={12} weight="bold" /> Back
            </Link>
            <button
              onClick={toggleTrack}
              disabled={trackBusy}
              className={
                "text-xs flex items-center gap-1 px-3 py-1.5 rounded-sm font-mono uppercase tracking-wider border " +
                (product.tracked
                  ? "bg-[#00E676]/10 border-[#00E676]/40 text-[#00E676]"
                  : "bg-[#141414] border-[#2A2A2A] text-[#71717A] hover:text-white")
              }
              data-testid="detail-track-toggle"
            >
              {product.tracked ? "Tracking" : "Track"}
            </button>
            <a href={product.product_url} target="_blank" rel="noreferrer"
              className="btn-secondary text-xs flex items-center gap-1" data-testid="open-meesho-link">
              Open on Meesho <ArrowSquareOutIcon size={12} weight="bold" />
            </a>
          </>
        }
      />

      <div className="px-8 py-6 space-y-6">
        {/* HERO: image + seller + summary */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
          <a
            href={product.product_url}
            target="_blank"
            rel="noreferrer"
            className="panel lg:col-span-1 block overflow-hidden"
            data-testid="product-hero-image"
          >
            <div className="aspect-square bg-[#0F0F0F] flex items-center justify-center">
              {product.image ? (
                <img src={product.image} alt={product.product_name || ""} className="h-full w-full object-cover" />
              ) : (
                <ImageSquareIcon size={48} color="#3a3a3a" />
              )}
            </div>
          </a>

          <div className="panel lg:col-span-2 p-5 space-y-4">
            <div className="flex items-center gap-2 text-[#A1A1AA]">
              <StorefrontIcon size={16} weight="bold" />
              <div className="section-label">/ seller</div>
            </div>
            <div className="font-display text-xl">{product.seller?.name || "—"}</div>

            {product.product_description && (
              <div className="text-xs text-[#A1A1AA] whitespace-pre-line max-h-28 overflow-auto">
                {product.product_description}
              </div>
            )}

            <div className="grid grid-cols-3 gap-4 border-t border-[#2A2A2A] pt-4">
              <div>
                <div className="font-mono text-xs text-[#71717A]">REVIEWS</div>
                <div className="font-mono text-2xl">{fmtNumber(totalReviews)}</div>
              </div>
              <div>
                <div className="font-mono text-xs text-[#71717A]">AVG RATING</div>
                <div className="font-mono text-2xl">{product.avg_rating ?? "—"}</div>
                <StarRow rating={product.avg_rating} />
              </div>
              <div>
                <div className="font-mono text-xs text-[#71717A]">LAST UPDATED</div>
                <div className="font-mono text-xs text-[#A1A1AA] mt-2">{fmtDate(product.updated_at)}</div>
              </div>
            </div>
          </div>
        </div>

        {/* TREND */}
        <div className="panel">
          <div className="flex flex-wrap items-center justify-between gap-2 border-b border-[#2A2A2A] px-5 py-3">
            <div className="flex items-center gap-2">
              <TrendUpIcon size={16} weight="bold" color="#007AFF" />
              <div className="font-display text-sm font-medium">Trend</div>
              {delta && (
                <div className="flex gap-3 ml-4 font-mono text-[11px]">
                  <span className="text-[#71717A]">
                    Δ reviews:{" "}
                    <span className={delta.reviews >= 0 ? "text-[#00E676]" : "text-[#FF3B30]"}>
                      {delta.reviews >= 0 ? "+" : ""}{delta.reviews}
                    </span>
                  </span>
                  <span className="text-[#71717A]">
                    Δ rating:{" "}
                    <span className={delta.rating >= 0 ? "text-[#00E676]" : "text-[#FF3B30]"}>
                      {delta.rating >= 0 ? "+" : ""}{delta.rating.toFixed(2)}
                    </span>
                  </span>
                </div>
              )}
            </div>
            <div className="flex items-center gap-1">
              {[7, 30, 90].map((d) => (
                <button
                  key={d}
                  onClick={() => setHistoryRange(d)}
                  className={
                    "px-2 py-1 font-mono text-[10px] uppercase tracking-wider rounded-sm border " +
                    (historyRange === d
                      ? "bg-[#007AFF] border-[#007AFF] text-white"
                      : "bg-[#141414] border-[#2A2A2A] text-[#A1A1AA] hover:bg-[#1F1F1F]")
                  }
                  data-testid={`history-range-${d}`}
                >
                  {d}D
                </button>
              ))}
            </div>
          </div>
          <div className="px-5 py-4">
            {historyChartData.length < 2 ? (
              <div className="text-center py-8 text-xs text-[#71717A]">
                Not enough history yet — snapshots are captured by the worker on every successful scrape.
                Run daily scrapes for a few days to see trends.
              </div>
            ) : (
              <>
                {/* COMPARE SUBSECTION */}
                <div className="mb-6 pb-6 border-b border-[#2A2A2A]" data-testid="compare-section">
                  <div className="flex flex-wrap items-center gap-3 mb-3">
                    <div className="section-label">/ compare</div>
                    <select
                      value={compareA}
                      onChange={(e) => setCompareA(e.target.value)}
                      className="input-shell font-mono text-xs py-1 w-auto"
                      data-testid="compare-date-a"
                    >
                      {history.map((h) => (
                        <option key={`a-${h.snapshot_at}`} value={h.snapshot_at}>
                          {(h.snapshot_at || "").slice(0, 16).replace("T", " ")}
                        </option>
                      ))}
                    </select>
                    <span className="font-mono text-xs text-[#71717A]">→</span>
                    <select
                      value={compareB}
                      onChange={(e) => setCompareB(e.target.value)}
                      className="input-shell font-mono text-xs py-1 w-auto"
                      data-testid="compare-date-b"
                    >
                      {history.map((h) => (
                        <option key={`b-${h.snapshot_at}`} value={h.snapshot_at}>
                          {(h.snapshot_at || "").slice(0, 16).replace("T", " ")}
                        </option>
                      ))}
                    </select>
                    <div className="flex items-center gap-1 ml-auto">
                      {[
                        { key: "oldest_latest", label: "oldest ↔ latest" },
                        { key: "last_two", label: "last vs prev" },
                      ].map((p) => (
                        <button
                          key={p.key}
                          onClick={() => {
                            if (history.length < 2) return;
                            if (p.key === "oldest_latest") {
                              setCompareA(history[0].snapshot_at);
                              setCompareB(history[history.length - 1].snapshot_at);
                            } else {
                              setCompareA(history[history.length - 2].snapshot_at);
                              setCompareB(history[history.length - 1].snapshot_at);
                            }
                          }}
                          className="btn-secondary text-[10px] px-2 py-1"
                          data-testid={`compare-preset-${p.key}`}
                        >
                          {p.label}
                        </button>
                      ))}
                    </div>
                  </div>

                  {compareRows ? (
                    <div className="overflow-x-auto">
                      <table className="dense w-full" data-testid="compare-table">
                        <thead>
                          <tr>
                            <th className="w-40">Metric</th>
                            <th className="num w-28">{compareRows.dateA}</th>
                            <th className="num w-28">{compareRows.dateB}</th>
                            <th className="num">Δ</th>
                          </tr>
                        </thead>
                        <tbody>
                          {compareRows.rows.map((row) => {
                            const delta = (row.b - row.a);
                            const isStar = row.label.endsWith("★");
                            const isRating = row.kind === "rating";
                            const isZero = Math.abs(delta) < (isRating ? 0.005 : 0.5);
                            const good = isZero
                              ? null
                              : (row.goodWhenUp ? delta > 0 : delta < 0);
                            const color = isZero ? "#71717A" : (good ? "#00E676" : "#FF3B30");
                            const fmt = (v) =>
                              isRating ? (Number(v) || 0).toFixed(2) : Math.round(Number(v) || 0);
                            const sign = delta > 0 ? "+" : "";
                            return (
                              <tr key={row.label} data-testid={`compare-row-${row.label}`}>
                                <td className={"font-mono text-xs " + (isStar ? "text-[#A1A1AA]" : "text-white")}>
                                  {row.label}
                                </td>
                                <td className="num font-mono text-xs text-[#E5E5E5]">{fmt(row.a)}</td>
                                <td className="num font-mono text-xs text-[#E5E5E5]">{fmt(row.b)}</td>
                                <td className="num font-mono text-xs" style={{ color }}>
                                  {isZero ? "—" : `${sign}${fmt(delta)}`}
                                </td>
                              </tr>
                            );
                          })}
                        </tbody>
                      </table>
                    </div>
                  ) : (
                    <div className="text-xs text-[#71717A] font-mono py-3">
                      Pick two snapshots to compare.
                    </div>
                  )}
                </div>

                {/* TIMELINE CHART */}
                <div style={{ width: "100%", height: 260 }}>
                <ResponsiveContainer>
                  <LineChart data={historyChartData} margin={{ top: 10, right: 20, left: 0, bottom: 0 }}>
                    <CartesianGrid stroke="#2A2A2A" strokeDasharray="2 4" />
                    <XAxis dataKey="date" stroke="#71717A" fontSize={10} fontFamily="JetBrains Mono" />
                    <YAxis yAxisId="left" stroke="#71717A" fontSize={10} fontFamily="JetBrains Mono" />
                    <YAxis yAxisId="right" orientation="right" domain={[0, 5]} stroke="#F5A623"
                      fontSize={10} fontFamily="JetBrains Mono" />
                    <Tooltip contentStyle={tooltipStyle} />
                    <Line yAxisId="left" type="monotone" dataKey="reviews" stroke="#007AFF"
                      strokeWidth={2} dot={{ r: 3, fill: "#007AFF" }} activeDot={{ r: 5 }} name="Total Reviews" />
                    <Line yAxisId="right" type="monotone" dataKey="rating" stroke="#F5A623"
                      strokeWidth={2} dot={{ r: 3, fill: "#F5A623" }} activeDot={{ r: 5 }} name="Avg Rating" />
                  </LineChart>
                </ResponsiveContainer>
                </div>
              </>
            )}
          </div>
        </div>

        {/* RATING DISTRIBUTION */}
        <div className="panel p-5">
          <div className="section-label mb-4">/ rating distribution</div>
          <div className="space-y-2.5">
            {[5, 4, 3, 2, 1].map((star) => {
              const c = Number(dist[star] ?? dist[String(star)] ?? 0);
              const pct = (c / maxBar) * 100;
              const totalPct = totalReviews ? ((c / totalReviews) * 100).toFixed(1) : "0.0";
              return (
                <div key={star} className="flex items-center gap-3" data-testid={`dist-row-${star}`}>
                  <div className="flex w-12 items-center gap-1 font-mono text-xs">
                    <span style={{ color: STAR_COLORS[star] }}>{star}★</span>
                  </div>
                  <div className="flex-1 bar-track">
                    <div className="bar-fill" style={{ width: `${pct}%`, background: STAR_COLORS[star] }} />
                  </div>
                  <div className="w-24 text-right font-mono text-xs text-[#A1A1AA]">
                    {fmtNumber(c)} <span className="text-[#71717A]">({totalPct}%)</span>
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        {/* REVIEWS */}
        <div className="panel">
          <div className="flex flex-wrap items-center justify-between gap-3 border-b border-[#2A2A2A] px-5 py-3">
            <div className="flex items-center gap-2">
              <div className="font-display text-sm font-medium">Reviews</div>
              <span className="code-tag">{reviews.length}</span>
            </div>
            <div className="flex items-center gap-2">
              {["all", "5", "4", "3", "2", "1"].map((s) => (
                <button key={s} onClick={() => setStarFilter(s)}
                  className={"px-2 py-1 font-mono text-[10px] uppercase tracking-wider rounded-sm border " +
                    (starFilter === s
                      ? "bg-[#007AFF] border-[#007AFF] text-white"
                      : "bg-[#141414] border-[#2A2A2A] text-[#A1A1AA] hover:bg-[#1F1F1F]")}
                  data-testid={`star-filter-${s}`}>
                  {s === "all" ? "ALL" : `${s}★`}
                </button>
              ))}
              <select value={sortBy} onChange={(e) => setSortBy(e.target.value)}
                className="input-shell font-mono text-xs py-1 ml-2 w-auto"
                data-testid="review-sort-select">
                <option value="date">Newest</option>
                <option value="helpful">Most Helpful</option>
                <option value="rating_high">Rating ↓</option>
                <option value="rating_low">Rating ↑</option>
              </select>
            </div>
          </div>

          <div className="divide-y divide-[#2A2A2A]">
            {reviews.length === 0 && (
              <div className="px-6 py-10 text-center text-sm text-[#71717A]">
                No reviews match this filter.
              </div>
            )}
            {reviews.map((r) => (
              <article key={r.review_id || `${r.customer}-${r.created_at}`}
                className="px-5 py-4" data-testid={`review-${r.review_id}`}>
                <div className="flex items-start justify-between gap-3">
                  <div className="flex-1">
                    <div className="flex items-center gap-2">
                      <StarRow rating={r.rating} />
                      <span className="text-sm text-white">{r.customer || "Anonymous"}</span>
                      <span className="font-mono text-[11px] text-[#71717A]">· {r.created_at || ""}</span>
                    </div>
                    {r.text && (
                      <p className="mt-2 text-sm text-[#E5E5E5] leading-relaxed whitespace-pre-line">{r.text}</p>
                    )}
                    {Array.isArray(r.media) && r.media.length > 0 && (
                      <div className="mt-3 flex flex-wrap gap-2">
                        {r.media.map((m, i) => {
                          const url = typeof m === "string" ? m : m?.url || m?.image_url;
                          if (!url) return null;
                          return (
                            <a key={i} href={url} target="_blank" rel="noreferrer"
                              className="media-thumb block h-16 w-16">
                              <img src={url} alt="" className="h-full w-full object-cover" loading="lazy" />
                            </a>
                          );
                        })}
                      </div>
                    )}
                  </div>
                  {Number(r.helpful) > 0 && (
                    <div className="flex items-center gap-1 font-mono text-xs text-[#A1A1AA]">
                      <ThumbsUpIcon size={12} weight="bold" />
                      {r.helpful}
                    </div>
                  )}
                </div>
              </article>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
