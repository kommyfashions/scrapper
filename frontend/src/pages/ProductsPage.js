import { useEffect, useState, useCallback } from "react";
import { Link } from "react-router-dom";
import {
  MagnifyingGlassIcon,
  ImageSquareIcon,
  CopyIcon,
  ArrowSquareOutIcon,
  StorefrontIcon,
  RowsIcon,
  SquaresFourIcon,
  ArrowUpRightIcon,
} from "@phosphor-icons/react";
import api from "@/lib/api";
import PageHeader from "@/components/PageHeader";
import { fmtNumber, fmtRelative, StarRow } from "@/lib/format";

const SORTS = [
  { k: "updated_at", label: "Updated" },
  { k: "total_reviews", label: "Reviews" },
  { k: "product_id", label: "ID" },
];

export default function ProductsPage() {
  const [items, setItems] = useState([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [q, setQ] = useState("");
  const [sort, setSort] = useState("updated_at");
  const [order, setOrder] = useState("desc");
  const [filter, setFilter] = useState("all");
  const [view, setView] = useState(() => localStorage.getItem("md_products_view") || "grid");
  const [busyId, setBusyId] = useState(null);
  const [copied, setCopied] = useState("");

  const load = useCallback(() => {
    setLoading(true);
    const params = { q: q || undefined, sort, order, limit: 100 };
    if (filter === "tracked") params.tracked = true;
    if (filter === "untracked") params.tracked = false;
    api
      .get("/products", { params })
      .then((r) => {
        setItems(r.data.items);
        setTotal(r.data.total);
      })
      .finally(() => setLoading(false));
  }, [q, sort, order, filter]);

  useEffect(() => {
    document.title = "Products · Seller Central";
    load();
  }, [load]);

  useEffect(() => {
    localStorage.setItem("md_products_view", view);
  }, [view]);

  const toggleTrack = async (p) => {
    setBusyId(p.product_id);
    try {
      await api.post(`/products/${p.product_id}/track`, { tracked: !p.tracked });
      setItems((prev) =>
        prev.map((x) =>
          x.product_id === p.product_id ? { ...x, tracked: !p.tracked } : x
        )
      );
    } finally {
      setBusyId(null);
    }
  };

  const copyId = (id) => {
    navigator.clipboard?.writeText(id);
    setCopied(id);
    setTimeout(() => setCopied(""), 1500);
  };

  return (
    <div data-testid="products-page">
      <PageHeader
        title="catalog"
        subtitle="Products"
        right={
          <div className="flex items-center gap-1 panel p-0.5">
            <button
              onClick={() => setView("grid")}
              className={
                "px-2.5 py-1.5 rounded-sm flex items-center gap-1 text-xs font-mono uppercase tracking-wider " +
                (view === "grid" ? "bg-[#1F1F1F] text-white" : "text-[#71717A] hover:text-white")
              }
              data-testid="view-grid"
              title="Grid view"
            >
              <SquaresFourIcon size={14} weight="bold" /> Grid
            </button>
            <button
              onClick={() => setView("table")}
              className={
                "px-2.5 py-1.5 rounded-sm flex items-center gap-1 text-xs font-mono uppercase tracking-wider " +
                (view === "table" ? "bg-[#1F1F1F] text-white" : "text-[#71717A] hover:text-white")
              }
              data-testid="view-table"
              title="Table view"
            >
              <RowsIcon size={14} weight="bold" /> Table
            </button>
          </div>
        }
      />

      <div className="px-8 py-6 space-y-5">
        {/* Controls */}
        <div className="flex flex-wrap items-center gap-3">
          <div className="relative w-full sm:w-[28rem]">
            <MagnifyingGlassIcon
              size={16}
              weight="bold"
              color="#71717A"
              className="absolute left-3 top-1/2 -translate-y-1/2 pointer-events-none"
            />
            <input
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="Search by product id, seller, name, url…"
              className="input-shell pl-9 text-sm font-mono"
              data-testid="products-search-input"
              autoFocus
            />
          </div>

          <div className="flex items-center gap-1">
            {[
              { k: "all", label: "ALL" },
              { k: "tracked", label: "TRACKED" },
              { k: "untracked", label: "UNTRACKED" },
            ].map(({ k, label }) => (
              <button
                key={k}
                onClick={() => setFilter(k)}
                className={
                  "px-3 py-1.5 text-[11px] font-mono uppercase tracking-wider rounded-sm " +
                  (filter === k
                    ? "bg-[#007AFF] text-white"
                    : "bg-[#141414] text-[#A1A1AA] border border-[#2A2A2A] hover:bg-[#1F1F1F]")
                }
                data-testid={`products-filter-${k}`}
              >
                {label}
              </button>
            ))}
          </div>

          {view === "grid" && (
            <div className="flex items-center gap-1 ml-auto">
              <span className="font-mono text-[10px] uppercase tracking-wider text-[#71717A] mr-1">
                Sort
              </span>
              {SORTS.map(({ k, label }) => (
                <button
                  key={k}
                  onClick={() => {
                    if (sort === k) setOrder(order === "desc" ? "asc" : "desc");
                    else { setSort(k); setOrder("desc"); }
                  }}
                  className={
                    "px-2.5 py-1 text-[10px] font-mono uppercase tracking-wider rounded-sm border " +
                    (sort === k
                      ? "bg-[#1F1F1F] border-[#3a3a3a] text-white"
                      : "bg-[#141414] border-[#2A2A2A] text-[#A1A1AA] hover:text-white")
                  }
                  data-testid={`sort-${k}`}
                >
                  {label}
                  {sort === k && (order === "desc" ? " ↓" : " ↑")}
                </button>
              ))}
            </div>
          )}

          <div className="ml-auto font-mono text-xs text-[#71717A]">
            {fmtNumber(total)} product{total === 1 ? "" : "s"}
          </div>
        </div>

        {/* Empty / loading */}
        {loading && (
          <div className="text-center py-16 font-mono text-xs uppercase tracking-widest text-[#71717A] cursor-blink">
            LOADING
          </div>
        )}
        {!loading && items.length === 0 && (
          <div className="panel py-16 text-center text-sm text-[#71717A]">
            No products match. Submit a job to start scraping.
          </div>
        )}

        {/* GRID VIEW */}
        {!loading && view === "grid" && items.length > 0 && (
          <div
            className="grid gap-4 grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 2xl:grid-cols-4"
            data-testid="products-grid"
          >
            {items.map((p) => (
              <div
                key={p.product_id}
                className="panel flex flex-col overflow-hidden group transition-colors hover:border-[#3a3a3a]"
                data-testid={`product-card-${p.product_id}`}
              >
                {/* Image */}
                <Link
                  to={`/products/${p.product_id}`}
                  className="relative aspect-square bg-[#0F0F0F] flex items-center justify-center overflow-hidden"
                  data-testid={`product-image-${p.product_id}`}
                >
                  {p.image ? (
                    <img
                      src={p.image}
                      alt={p.product_name || p.product_id}
                      className="h-full w-full object-cover transition-transform duration-300 group-hover:scale-[1.03]"
                      loading="lazy"
                    />
                  ) : (
                    <ImageSquareIcon size={56} color="#3a3a3a" />
                  )}

                  {/* Track badge overlay */}
                  <div className="absolute top-2 right-2">
                    <span
                      className={
                        "tactical-pill " +
                        (p.tracked
                          ? "bg-[#00E676]/15 text-[#00E676] border border-[#00E676]/40"
                          : "bg-black/60 text-[#71717A] border border-[#2A2A2A]")
                      }
                    >
                      <span
                        className="dot"
                        style={{ background: p.tracked ? "#00E676" : "#71717A" }}
                      />
                      {p.tracked ? "TRACKING" : "UNTRACKED"}
                    </span>
                  </div>

                  {/* Reviews + rating overlay (bottom) */}
                  <div className="absolute bottom-0 inset-x-0 bg-gradient-to-t from-black/80 via-black/40 to-transparent p-3 flex items-end justify-between">
                    <div>
                      <div className="font-mono text-[10px] uppercase tracking-widest text-[#A1A1AA]">
                        Reviews
                      </div>
                      <div className="font-mono text-lg text-white">
                        {fmtNumber(p.total_reviews)}
                      </div>
                    </div>
                    <div className="text-right">
                      <div className="font-mono text-[10px] uppercase tracking-widest text-[#A1A1AA]">
                        Avg
                      </div>
                      <div className="font-mono text-lg text-white">
                        {p.avg_rating ?? "—"}
                      </div>
                      <StarRow rating={p.avg_rating} />
                    </div>
                  </div>
                </Link>

                {/* Body */}
                <div className="flex-1 p-4 space-y-2">
                  {/* Big product ID */}
                  <div className="flex items-center justify-between">
                    <button
                      onClick={() => copyId(p.product_id)}
                      className="flex items-center gap-1.5 group/id"
                      title="Copy product id"
                      data-testid={`copy-id-${p.product_id}`}
                    >
                      <span className="font-mono text-base font-semibold text-white tracking-wide">
                        {p.product_id}
                      </span>
                      {copied === p.product_id ? (
                        <span className="font-mono text-[10px] text-[#00E676]">COPIED</span>
                      ) : (
                        <CopyIcon
                          size={12}
                          weight="bold"
                          className="text-[#3a3a3a] group-hover/id:text-[#A1A1AA] transition-colors"
                        />
                      )}
                    </button>
                    <a
                      href={p.product_url}
                      target="_blank"
                      rel="noreferrer"
                      onClick={(e) => e.stopPropagation()}
                      className="text-[#71717A] hover:text-[#007AFF] transition-colors"
                      title="Open on Meesho"
                      data-testid={`open-meesho-${p.product_id}`}
                    >
                      <ArrowSquareOutIcon size={14} weight="bold" />
                    </a>
                  </div>

                  {p.product_name && (
                    <div className="text-sm text-white/95 line-clamp-2 leading-snug">
                      {p.product_name}
                    </div>
                  )}

                  <div className="flex items-center gap-1.5 text-xs text-[#A1A1AA] truncate">
                    <StorefrontIcon size={12} weight="bold" className="shrink-0" />
                    <span className="truncate">{p.seller?.name || "—"}</span>
                  </div>

                  <div className="flex items-center justify-between pt-2 border-t border-[#2A2A2A]">
                    <span className="font-mono text-[10px] text-[#71717A]">
                      {fmtRelative(p.updated_at)}
                    </span>
                    <div className="flex items-center gap-1.5">
                      <button
                        onClick={() => toggleTrack(p)}
                        disabled={busyId === p.product_id}
                        className={
                          "px-2 py-1 rounded-sm font-mono text-[10px] uppercase tracking-wider border " +
                          (p.tracked
                            ? "bg-[#00E676]/10 border-[#00E676]/40 text-[#00E676] hover:bg-[#00E676]/20"
                            : "bg-[#141414] border-[#2A2A2A] text-[#71717A] hover:text-white")
                        }
                        data-testid={`track-toggle-${p.product_id}`}
                      >
                        {p.tracked ? "ON" : "OFF"}
                      </button>
                      <Link
                        to={`/products/${p.product_id}`}
                        className="btn-primary text-[11px] py-1 px-2.5 flex items-center gap-1"
                        data-testid={`view-product-${p.product_id}`}
                      >
                        Open <ArrowUpRightIcon size={11} weight="bold" />
                      </Link>
                    </div>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}

        {/* TABLE VIEW (compact) */}
        {!loading && view === "table" && items.length > 0 && (
          <div className="table-wrap">
            <table className="dense">
              <thead>
                <tr>
                  <th className="w-16"></th>
                  <th>Product ID / Name</th>
                  <th>Seller</th>
                  <th className="num">Reviews</th>
                  <th>Avg Rating</th>
                  <th className="num">Updated</th>
                  <th>Track</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {items.map((p) => (
                  <tr key={p.product_id} data-testid={`product-row-${p.product_id}`}>
                    <td>
                      <Link
                        to={`/products/${p.product_id}`}
                        className="block h-14 w-14 media-thumb"
                      >
                        {p.image ? (
                          <img
                            src={p.image}
                            alt=""
                            loading="lazy"
                            className="h-full w-full object-cover"
                          />
                        ) : (
                          <div className="h-full w-full flex items-center justify-center">
                            <ImageSquareIcon size={20} color="#3a3a3a" />
                          </div>
                        )}
                      </Link>
                    </td>
                    <td>
                      <button
                        onClick={() => copyId(p.product_id)}
                        className="font-mono text-sm text-white hover:text-[#007AFF] flex items-center gap-1"
                        title="Copy product id"
                      >
                        {p.product_id}
                        {copied === p.product_id ? (
                          <span className="font-mono text-[10px] text-[#00E676]">COPIED</span>
                        ) : (
                          <CopyIcon size={11} className="text-[#3a3a3a]" />
                        )}
                      </button>
                      {p.product_name && (
                        <div className="text-[12px] text-white/85 max-w-md truncate">
                          {p.product_name}
                        </div>
                      )}
                      <div className="text-[11px] text-[#71717A] max-w-md truncate">
                        {p.product_url}
                      </div>
                    </td>
                    <td className="text-sm">{p.seller?.name || "—"}</td>
                    <td className="num font-mono text-sm">{fmtNumber(p.total_reviews)}</td>
                    <td>
                      <div className="flex items-center gap-2">
                        <StarRow rating={p.avg_rating} />
                        <span className="font-mono text-xs text-[#A1A1AA]">
                          {p.avg_rating ?? "—"}
                        </span>
                      </div>
                    </td>
                    <td className="num text-xs text-[#A1A1AA]">
                      {fmtRelative(p.updated_at)}
                    </td>
                    <td>
                      <button
                        onClick={() => toggleTrack(p)}
                        disabled={busyId === p.product_id}
                        className={
                          "px-2 py-1 rounded-sm font-mono text-[10px] uppercase tracking-wider border " +
                          (p.tracked
                            ? "bg-[#00E676]/10 border-[#00E676]/40 text-[#00E676]"
                            : "bg-[#141414] border-[#2A2A2A] text-[#71717A] hover:text-white")
                        }
                        data-testid={`track-toggle-${p.product_id}`}
                      >
                        {p.tracked ? "ON" : "OFF"}
                      </button>
                    </td>
                    <td className="num">
                      <Link
                        to={`/products/${p.product_id}`}
                        className="btn-ghost inline-flex items-center gap-1 text-xs"
                        data-testid={`view-product-${p.product_id}`}
                      >
                        View <ArrowUpRightIcon size={12} weight="bold" />
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
