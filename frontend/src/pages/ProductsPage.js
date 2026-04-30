import { useEffect, useState, useCallback } from "react";
import { Link } from "react-router-dom";
import { MagnifyingGlassIcon, ArrowUpRightIcon, ImageSquareIcon } from "@phosphor-icons/react";
import api from "@/lib/api";
import PageHeader from "@/components/PageHeader";
import { fmtNumber, fmtRelative, StarRow } from "@/lib/format";

export default function ProductsPage() {
  const [items, setItems] = useState([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [q, setQ] = useState("");
  const [sort, setSort] = useState("updated_at");
  const [order, setOrder] = useState("desc");
  const [filter, setFilter] = useState("all"); // all | tracked | untracked
  const [busyId, setBusyId] = useState(null);

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

  const toggleSort = (field) => {
    if (sort === field) setOrder(order === "desc" ? "asc" : "desc");
    else { setSort(field); setOrder("desc"); }
  };
  const sortIndicator = (field) => (sort === field ? (order === "desc" ? " ↓" : " ↑") : "");

  const toggleTrack = async (p) => {
    setBusyId(p.product_id);
    try {
      await api.post(`/products/${p.product_id}/track`, { tracked: !p.tracked });
      setItems((prev) => prev.map((x) => x.product_id === p.product_id ? { ...x, tracked: !p.tracked } : x));
    } finally {
      setBusyId(null);
    }
  };

  return (
    <div data-testid="products-page">
      <PageHeader title="catalog" subtitle="Products" />
      <div className="px-8 py-6 space-y-4">
        <div className="flex flex-wrap items-center gap-3">
          <div className="relative w-full sm:w-96">
            <MagnifyingGlassIcon size={14} weight="bold" color="#71717A"
              className="absolute left-3 top-1/2 -translate-y-1/2 pointer-events-none" />
            <input value={q} onChange={(e) => setQ(e.target.value)}
              placeholder="Search id, seller, name, url…"
              className="input-shell pl-8 text-sm"
              data-testid="products-search-input" />
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
                className={"px-3 py-1.5 text-[11px] font-mono uppercase tracking-wider rounded-sm " +
                  (filter === k
                    ? "bg-[#007AFF] text-white"
                    : "bg-[#141414] text-[#A1A1AA] border border-[#2A2A2A] hover:bg-[#1F1F1F]")}
                data-testid={`products-filter-${k}`}
              >{label}</button>
            ))}
          </div>
          <div className="flex-1" />
          <div className="font-mono text-xs text-[#71717A]">
            {fmtNumber(total)} product(s)
          </div>
        </div>

        <div className="table-wrap">
          <table className="dense">
            <thead>
              <tr>
                <th className="w-12"></th>
                <th className="cursor-pointer hover:text-white" onClick={() => toggleSort("product_id")}>
                  Product{sortIndicator("product_id")}
                </th>
                <th>Seller</th>
                <th className="num cursor-pointer hover:text-white" onClick={() => toggleSort("total_reviews")}>
                  Reviews{sortIndicator("total_reviews")}
                </th>
                <th>Avg Rating</th>
                <th className="num cursor-pointer hover:text-white" onClick={() => toggleSort("updated_at")}>
                  Updated{sortIndicator("updated_at")}
                </th>
                <th>Track</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {loading && (
                <tr><td colSpan={8} className="text-center py-8 text-[#71717A] font-mono text-xs">
                  <span className="cursor-blink">LOADING</span>
                </td></tr>
              )}
              {!loading && items.length === 0 && (
                <tr><td colSpan={8} className="text-center py-10 text-[#71717A] text-sm">
                  No products. Submit a job to start scraping.
                </td></tr>
              )}
              {items.map((p) => (
                <tr key={p.product_id} data-testid={`product-row-${p.product_id}`}>
                  <td>
                    <div className="h-10 w-10 media-thumb flex items-center justify-center overflow-hidden">
                      {p.image ? (
                        <img src={p.image} alt="" loading="lazy" className="h-full w-full object-cover" />
                      ) : (
                        <ImageSquareIcon size={16} color="#3a3a3a" />
                      )}
                    </div>
                  </td>
                  <td>
                    <div className="font-mono text-xs text-white">{p.product_id}</div>
                    {p.product_name && (
                      <div className="text-[12px] text-white/90 max-w-md truncate">{p.product_name}</div>
                    )}
                    <div className="text-[11px] text-[#71717A] max-w-md truncate">{p.product_url}</div>
                  </td>
                  <td className="text-sm">{p.seller?.name || "—"}</td>
                  <td className="num font-mono text-sm">{fmtNumber(p.total_reviews)}</td>
                  <td>
                    <div className="flex items-center gap-2">
                      <StarRow rating={p.avg_rating} />
                      <span className="font-mono text-xs text-[#A1A1AA]">{p.avg_rating ?? "—"}</span>
                    </div>
                  </td>
                  <td className="num text-xs text-[#A1A1AA]">{fmtRelative(p.updated_at)}</td>
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
                    <Link to={`/products/${p.product_id}`} className="btn-ghost inline-flex items-center gap-1 text-xs"
                      data-testid={`view-product-${p.product_id}`}>
                      View <ArrowUpRightIcon size={12} weight="bold" />
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
