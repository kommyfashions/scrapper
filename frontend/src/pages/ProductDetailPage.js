import { useEffect, useState, useMemo } from "react";
import { Link, useParams } from "react-router-dom";
import {
  ArrowLeftIcon,
  ArrowSquareOutIcon,
  StorefrontIcon,
  ThumbsUpIcon,
} from "@phosphor-icons/react";
import api from "@/lib/api";
import PageHeader from "@/components/PageHeader";
import { fmtDate, fmtNumber, StarRow } from "@/lib/format";

const STAR_COLORS = {
  5: "#00E676",
  4: "#7FE15A",
  3: "#F5A623",
  2: "#FF8C42",
  1: "#FF3B30",
};

export default function ProductDetailPage() {
  const { productId } = useParams();
  const [product, setProduct] = useState(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState("");
  const [starFilter, setStarFilter] = useState("all");
  const [sortBy, setSortBy] = useState("date");

  useEffect(() => {
    document.title = `Product ${productId} · Seller Central`;
    setLoading(true);
    api
      .get(`/products/${productId}`)
      .then((r) => setProduct(r.data))
      .catch((e) => setErr(e?.response?.data?.detail || "Not found"))
      .finally(() => setLoading(false));
  }, [productId]);

  const dist = product?.rating_distribution || {};
  const totalReviews = product?.total_reviews || 0;
  const maxBar = useMemo(
    () => Math.max(1, ...Object.values(dist).map(Number)),
    [dist]
  );

  const reviews = useMemo(() => {
    if (!product?.reviews) return [];
    let out = [...product.reviews];
    if (starFilter !== "all") {
      const s = parseInt(starFilter, 10);
      out = out.filter((r) => Number(r.rating) === s);
    }
    if (sortBy === "date") {
      out.sort((a, b) => String(b.created_at).localeCompare(String(a.created_at)));
    } else if (sortBy === "helpful") {
      out.sort((a, b) => (Number(b.helpful) || 0) - (Number(a.helpful) || 0));
    } else if (sortBy === "rating_high") {
      out.sort((a, b) => (Number(b.rating) || 0) - (Number(a.rating) || 0));
    } else if (sortBy === "rating_low") {
      out.sort((a, b) => (Number(a.rating) || 0) - (Number(b.rating) || 0));
    }
    return out;
  }, [product, starFilter, sortBy]);

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
        subtitle="Product Detail"
        right={
          <>
            <Link to="/products" className="btn-secondary text-xs flex items-center gap-1">
              <ArrowLeftIcon size={12} weight="bold" /> Back
            </Link>
            <a
              href={product.product_url}
              target="_blank"
              rel="noreferrer"
              className="btn-secondary text-xs flex items-center gap-1"
              data-testid="open-meesho-link"
            >
              Open on Meesho <ArrowSquareOutIcon size={12} weight="bold" />
            </a>
          </>
        }
      />

      <div className="px-8 py-6 space-y-6">
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
          <div className="panel lg:col-span-1 p-5 space-y-4">
            <div className="flex items-center gap-2 text-[#A1A1AA]">
              <StorefrontIcon size={16} weight="bold" />
              <div className="section-label">/ seller</div>
            </div>
            <div className="font-display text-xl">{product.seller?.name || "—"}</div>

            <div className="border-t border-[#2A2A2A] pt-4">
              <div className="section-label mb-2">/ summary</div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <div className="font-mono text-xs text-[#71717A]">REVIEWS</div>
                  <div className="font-mono text-2xl">{fmtNumber(totalReviews)}</div>
                </div>
                <div>
                  <div className="font-mono text-xs text-[#71717A]">AVG</div>
                  <div className="font-mono text-2xl">{product.avg_rating ?? "—"}</div>
                  <StarRow rating={product.avg_rating} />
                </div>
              </div>
            </div>

            <div className="border-t border-[#2A2A2A] pt-4">
              <div className="section-label mb-1">/ last updated</div>
              <div className="font-mono text-xs text-[#A1A1AA]">
                {fmtDate(product.updated_at)}
              </div>
            </div>
          </div>

          <div className="panel lg:col-span-2 p-5">
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
                      <div
                        className="bar-fill"
                        style={{ width: `${pct}%`, background: STAR_COLORS[star] }}
                      />
                    </div>
                    <div className="w-24 text-right font-mono text-xs text-[#A1A1AA]">
                      {fmtNumber(c)} <span className="text-[#71717A]">({totalPct}%)</span>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        </div>

        <div className="panel">
          <div className="flex flex-wrap items-center justify-between gap-3 border-b border-[#2A2A2A] px-5 py-3">
            <div className="flex items-center gap-2">
              <div className="font-display text-sm font-medium">Reviews</div>
              <span className="code-tag">{reviews.length}</span>
            </div>
            <div className="flex items-center gap-2">
              {["all", "5", "4", "3", "2", "1"].map((s) => (
                <button
                  key={s}
                  onClick={() => setStarFilter(s)}
                  className={
                    "px-2 py-1 font-mono text-[10px] uppercase tracking-wider rounded-sm border " +
                    (starFilter === s
                      ? "bg-[#007AFF] border-[#007AFF] text-white"
                      : "bg-[#141414] border-[#2A2A2A] text-[#A1A1AA] hover:bg-[#1F1F1F]")
                  }
                  data-testid={`star-filter-${s}`}
                >
                  {s === "all" ? "ALL" : `${s}★`}
                </button>
              ))}
              <select
                value={sortBy}
                onChange={(e) => setSortBy(e.target.value)}
                className="input-shell font-mono text-xs py-1 ml-2 w-auto"
                data-testid="review-sort-select"
              >
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
              <article
                key={r.review_id || `${r.customer}-${r.created_at}`}
                className="px-5 py-4"
                data-testid={`review-${r.review_id}`}
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="flex-1">
                    <div className="flex items-center gap-2">
                      <StarRow rating={r.rating} />
                      <span className="text-sm text-white">{r.customer || "Anonymous"}</span>
                      <span className="font-mono text-[11px] text-[#71717A]">
                        · {r.created_at || ""}
                      </span>
                    </div>
                    {r.text && (
                      <p className="mt-2 text-sm text-[#E5E5E5] leading-relaxed whitespace-pre-line">
                        {r.text}
                      </p>
                    )}
                    {Array.isArray(r.media) && r.media.length > 0 && (
                      <div className="mt-3 flex flex-wrap gap-2">
                        {r.media.map((m, i) => {
                          const url = typeof m === "string" ? m : m?.url || m?.image_url;
                          if (!url) return null;
                          return (
                            <a
                              key={i}
                              href={url}
                              target="_blank"
                              rel="noreferrer"
                              className="media-thumb block h-16 w-16"
                            >
                              <img
                                src={url}
                                alt="review media"
                                className="h-full w-full object-cover"
                                loading="lazy"
                              />
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
