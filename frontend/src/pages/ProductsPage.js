import { useEffect, useState, useCallback } from "react";
import { Link } from "react-router-dom";
import { MagnifyingGlassIcon, ArrowUpRightIcon } from "@phosphor-icons/react";
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

  const load = useCallback(() => {
    setLoading(true);
    api
      .get("/products", { params: { q: q || undefined, sort, order, limit: 100 } })
      .then((r) => {
        setItems(r.data.items);
        setTotal(r.data.total);
      })
      .finally(() => setLoading(false));
  }, [q, sort, order]);

  useEffect(() => {
    document.title = "Products · Seller Central";
    load();
  }, [load]);

  const toggleSort = (field) => {
    if (sort === field) setOrder(order === "desc" ? "asc" : "desc");
    else {
      setSort(field);
      setOrder("desc");
    }
  };

  const sortIndicator = (field) =>
    sort === field ? (order === "desc" ? " ↓" : " ↑") : "";

  return (
    <div data-testid="products-page">
      <PageHeader title="catalog" subtitle="Products" />
      <div className="px-8 py-6 space-y-4">
        <div className="flex items-center gap-3">
          <div className="relative w-full sm:w-96">
            <MagnifyingGlassIcon
              size={14}
              weight="bold"
              color="#71717A"
              className="absolute left-3 top-1/2 -translate-y-1/2 pointer-events-none"
            />
            <input
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="Search id, seller, url…"
              className="input-shell pl-8 text-sm"
              data-testid="products-search-input"
            />
          </div>
          <div className="font-mono text-xs text-[#71717A]">
            {fmtNumber(total)} product(s)
          </div>
        </div>

        <div className="table-wrap">
          <table className="dense">
            <thead>
              <tr>
                <th
                  className="cursor-pointer hover:text-white"
                  onClick={() => toggleSort("product_id")}
                  data-testid="sort-product-id"
                >
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
                <th></th>
              </tr>
            </thead>
            <tbody>
              {loading && (
                <tr>
                  <td colSpan={6} className="text-center py-8 text-[#71717A] font-mono text-xs">
                    <span className="cursor-blink">LOADING</span>
                  </td>
                </tr>
              )}
              {!loading && items.length === 0 && (
                <tr>
                  <td colSpan={6} className="text-center py-10 text-[#71717A] text-sm">
                    No products. Submit a job to start scraping.
                  </td>
                </tr>
              )}
              {items.map((p) => (
                <tr key={p.product_id} data-testid={`product-row-${p.product_id}`}>
                  <td>
                    <div className="font-mono text-xs text-white">{p.product_id}</div>
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
                  <td className="num text-xs text-[#A1A1AA]">{fmtRelative(p.updated_at)}</td>
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
      </div>
    </div>
  );
}
