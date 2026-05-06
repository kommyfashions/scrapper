import { useEffect, useState, useCallback } from "react";
import api, { formatApiError } from "@/lib/api";
import { usePL, DateRangeFilter, buildQuery, inr } from "./PLLayout";

const CLASS_COLOR = { Winner: "#00E676", Risky: "#F5A623", Loser: "#FF3B30" };

const VIEWS = [
  { k: "sku", label: "By SKU" },
  { k: "article", label: "By Article" },
];

export default function PLSKUAnalysis() {
  const { accountId, dateRange } = usePL();
  const [items, setItems] = useState([]);
  const [view, setView] = useState("sku");
  const [filter, setFilter] = useState("all");
  const [sortBy, setSortBy] = useState("net_sku_contribution");
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState("");

  const load = useCallback(async () => {
    setLoading(true); setErr("");
    try {
      const q = buildQuery({ accountId, dateRange });
      const { data } = await api.get(`/pl/sku-analysis?${q}&group_by=${view}`);
      setItems(data.items || []);
    } catch (e) { setErr(formatApiError(e)); }
    finally { setLoading(false); }
  }, [accountId, dateRange, view]);

  useEffect(() => { load(); }, [load]);

  const filtered = items
    .filter((i) => filter === "all" || i.classification === filter)
    .sort((a, b) => (b[sortBy] || 0) - (a[sortBy] || 0));

  const counts = items.reduce((acc, i) => {
    acc[i.classification] = (acc[i.classification] || 0) + 1; return acc;
  }, {});

  const isArticleView = view === "article";

  return (
    <div className="px-8 py-6 space-y-4" data-testid="pl-sku-analysis">
      <DateRangeFilter />

      <div className="grid grid-cols-3 gap-3">
        {["Winner", "Risky", "Loser"].map((c) => (
          <button key={c} onClick={() => setFilter(filter === c ? "all" : c)}
            className={"panel p-4 text-left transition-colors " + (filter === c ? "ring-2 ring-[#007AFF]" : "")}
            data-testid={`pl-sku-filter-${c.toLowerCase()}`}>
            <div className="section-label">/ {c.toLowerCase()}s</div>
            <div className="font-display text-2xl font-semibold mt-1" style={{ color: CLASS_COLOR[c] }}>
              {counts[c] || 0}
            </div>
          </button>
        ))}
      </div>

      <div className="flex flex-wrap items-end gap-3">
        <div>
          <div className="section-label mb-1">/ view</div>
          <div className="flex border border-[#2A2A2A] rounded-sm overflow-hidden">
            {VIEWS.map((v) => (
              <button key={v.k} onClick={() => setView(v.k)}
                className={`px-3 py-1.5 font-mono text-[11px] uppercase tracking-wider transition-colors ${
                  view === v.k ? "bg-[#007AFF]/20 text-white" : "text-[#71717A] hover:text-white"
                }`}
                data-testid={`pl-sku-view-${v.k}`}>
                {v.label}
              </button>
            ))}
          </div>
        </div>
        <div>
          <div className="section-label mb-1">/ filter</div>
          <select value={filter} onChange={(e) => setFilter(e.target.value)}
            className="input-shell font-mono text-xs" data-testid="pl-sku-class-filter">
            <option value="all">All ({items.length})</option>
            <option value="Winner">Winner</option>
            <option value="Risky">Risky</option>
            <option value="Loser">Loser</option>
          </select>
        </div>
        <div>
          <div className="section-label mb-1">/ sort by</div>
          <select value={sortBy} onChange={(e) => setSortBy(e.target.value)}
            className="input-shell font-mono text-xs" data-testid="pl-sku-sort">
            <option value="net_sku_contribution">Net Contribution</option>
            <option value="return_rate">Return Rate</option>
            <option value="units_ordered">Units Ordered</option>
            <option value="net_realized_profit">Realized Profit</option>
            <option value="total_return_loss">Return Loss</option>
            <option value="ship_out">Shipping Out</option>
            <option value="ship_return">Return Shipping</option>
          </select>
        </div>
      </div>

      {err && <div className="border border-[#FF3B30]/30 bg-[#FF3B30]/10 px-3 py-2 font-mono text-xs text-[#FF3B30]" data-testid="pl-sku-err">{err}</div>}

      <div className="panel">
        <div className="overflow-x-auto">
          <table className="dense">
            <thead>
              <tr>
                {isArticleView ? (
                  <>
                    <th>Article</th>
                    <th className="num">SKUs</th>
                  </>
                ) : (
                  <>
                    <th>Article</th>
                    <th>SKU</th>
                    <th>Product</th>
                  </>
                )}
                <th className="num">Ordered</th>
                <th className="num">Delivered</th>
                <th className="num">Returned</th>
                <th className="num">RR %</th>
                <th className="num" title="Sum of Shipping Charge (Incl. GST) for delivered">Ship Out</th>
                <th className="num" title="Sum of Return Shipping Charge (Incl. GST) for returns">Ship Return</th>
                <th className="num">Profit</th>
                <th className="num">Loss</th>
                <th className="num">Net</th>
                <th className="num">P/U</th>
                <th>Class</th>
              </tr>
            </thead>
            <tbody>
              {loading && (
                <tr><td colSpan={isArticleView ? 12 : 13} className="text-center py-8 text-[#71717A] font-mono text-xs">
                  <span className="cursor-blink">LOADING</span>
                </td></tr>
              )}
              {!loading && filtered.length === 0 && (
                <tr><td colSpan={isArticleView ? 12 : 13} className="text-center py-10 text-[#71717A] text-sm">No data.</td></tr>
              )}
              {filtered.map((i) => (
                <tr key={isArticleView ? (i.article_name || `unmapped-${i.sku_count}`) : i.sku}
                  data-testid={isArticleView ? `pl-article-row-${i.article_name || "unmapped"}` : `pl-sku-row-${i.sku}`}
                  className={i.is_unmapped ? "bg-[#F5A623]/5" : ""}>
                  {isArticleView ? (
                    <>
                      <td className="font-mono text-[11px]">
                        {i.is_unmapped ? (
                          <span className="text-[#F5A623]" title={(i.skus || []).slice(0, 30).join(", ")}>
                            {i.article_name}
                          </span>
                        ) : (
                          <span className="text-white font-display text-sm">{i.article_name}</span>
                        )}
                      </td>
                      <td className="num font-mono text-[10px] text-[#A1A1AA]">{i.sku_count}</td>
                    </>
                  ) : (
                    <>
                      <td className="font-mono text-[11px]">
                        {i.article_name
                          ? <span className="text-[#00E676]">{i.article_name}</span>
                          : <span className="text-[#71717A]">—</span>}
                      </td>
                      <td className="font-mono text-[11px]">{i.sku}</td>
                      <td className="text-[11px] truncate max-w-[200px]" title={i.product_name}>{i.product_name}</td>
                    </>
                  )}
                  <td className="num font-mono text-xs">{i.units_ordered}</td>
                  <td className="num font-mono text-xs text-[#00E676]">{i.units_delivered}</td>
                  <td className="num font-mono text-xs text-[#FF3B30]">{i.units_returned}</td>
                  <td className="num font-mono text-xs">{i.return_rate}%</td>
                  <td className="num font-mono text-xs text-[#7DB9FF]">{inr(i.ship_out)}</td>
                  <td className="num font-mono text-xs text-[#F5A623]">{inr(i.ship_return)}</td>
                  <td className="num font-mono text-xs text-[#00E676]">{inr(i.net_realized_profit)}</td>
                  <td className="num font-mono text-xs text-[#FF3B30]">{inr(i.total_return_loss)}</td>
                  <td className="num font-mono text-xs"
                      style={{ color: i.net_sku_contribution >= 0 ? "#00E676" : "#FF3B30" }}>
                    {inr(i.net_sku_contribution)}
                  </td>
                  <td className="num font-mono text-xs">{inr(i.profit_per_delivered_unit)}</td>
                  <td>
                    <span className="font-mono text-[10px] uppercase tracking-wider px-2 py-0.5 rounded-sm"
                      style={{ background: `${CLASS_COLOR[i.classification]}1a`, color: CLASS_COLOR[i.classification] }}>
                      {i.classification}
                    </span>
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
