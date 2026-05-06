import { useEffect, useMemo, useState, useCallback } from "react";
import { CaretDownIcon, CaretRightIcon, MagnifyingGlassIcon } from "@phosphor-icons/react";
import api, { formatApiError } from "@/lib/api";
import { usePL, DateRangeFilter, buildQuery, inr } from "./PLLayout";

const CLASS_COLOR = { Winner: "#00E676", Risky: "#F5A623", Loser: "#FF3B30" };

const VIEWS = [
  { k: "sku", label: "By SKU" },
  { k: "article", label: "By Article" },
];

function useDebounced(value, ms = 350) {
  const [v, setV] = useState(value);
  useEffect(() => { const id = setTimeout(() => setV(value), ms); return () => clearTimeout(id); }, [value, ms]);
  return v;
}

export default function PLSKUAnalysis() {
  const { accountId, dateRange } = usePL();
  const [items, setItems] = useState([]);
  const [view, setView] = useState("sku");
  const [filter, setFilter] = useState("all");
  const [sortBy, setSortBy] = useState("net_sku_contribution");
  const [search, setSearch] = useState("");
  const debouncedSearch = useDebounced(search, 350);
  const [collapsed, setCollapsed] = useState(() => new Set());
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState("");

  const load = useCallback(async () => {
    setLoading(true); setErr("");
    try {
      const q = buildQuery({ accountId, dateRange });
      const sp = new URLSearchParams(q);
      sp.set("group_by", view);
      if (debouncedSearch.trim()) sp.set("q", debouncedSearch.trim());
      const { data } = await api.get(`/pl/sku-analysis?${sp.toString()}`);
      setItems(data.items || []);
    } catch (e) { setErr(formatApiError(e)); }
    finally { setLoading(false); }
  }, [accountId, dateRange, view, debouncedSearch]);

  useEffect(() => { load(); }, [load]);

  const isArticleView = view === "article";
  const headers = items.filter((i) => i.is_header);
  const counts = headers.reduce((acc, h) => {
    acc[h.classification] = (acc[h.classification] || 0) + 1; return acc;
  }, {});
  const skuCounts = items.filter((i) => !i.is_header).reduce((acc, i) => {
    acc[i.classification] = (acc[i.classification] || 0) + 1; return acc;
  }, {});
  const totals = isArticleView ? counts : skuCounts;

  // sorting
  const visibleRows = useMemo(() => {
    if (!isArticleView) {
      // By SKU: each row independent → just filter & sort
      return [...items]
        .filter((i) => filter === "all" || i.classification === filter)
        .sort((a, b) => (b[sortBy] || 0) - (a[sortBy] || 0));
    }
    // By Article: keep header→children pairing intact while sorting headers
    const groups = [];
    let current = null;
    for (const r of items) {
      if (r.is_header) {
        current = { header: r, children: [] };
        groups.push(current);
      } else if (current) {
        current.children.push(r);
      }
    }
    const filtered = groups.filter((g) =>
      filter === "all" || g.header.classification === filter
    );
    filtered.sort((a, b) => (b.header[sortBy] || 0) - (a.header[sortBy] || 0));
    const out = [];
    for (const g of filtered) {
      out.push(g.header);
      if (!collapsed.has(g.header.article_name)) {
        for (const c of g.children) out.push(c);
      }
    }
    return out;
  }, [items, isArticleView, filter, sortBy, collapsed]);

  const toggleCollapse = (artName) => {
    setCollapsed((cur) => {
      const next = new Set(cur);
      if (next.has(artName)) next.delete(artName); else next.add(artName);
      return next;
    });
  };

  return (
    <div className="px-8 py-6 space-y-4" data-testid="pl-sku-analysis">
      <DateRangeFilter />

      <div className="grid grid-cols-3 gap-3">
        {["Winner", "Risky", "Loser"].map((c) => (
          <button key={c} onClick={() => setFilter(filter === c ? "all" : c)}
            className={"panel p-4 text-left transition-colors " + (filter === c ? "ring-2 ring-[#007AFF]" : "")}
            data-testid={`pl-sku-filter-${c.toLowerCase()}`}>
            <div className="section-label">/ {c.toLowerCase()}{isArticleView ? " articles" : "s"}</div>
            <div className="font-display text-2xl font-semibold mt-1" style={{ color: CLASS_COLOR[c] }}>
              {totals[c] || 0}
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
        <div className="flex-1 min-w-[260px]">
          <div className="section-label mb-1">/ search</div>
          <div className="relative">
            <MagnifyingGlassIcon size={12} className="absolute left-2 top-1/2 -translate-y-1/2 text-[#71717A]" weight="bold" />
            <input value={search} onChange={(e) => setSearch(e.target.value)}
              placeholder="SKU, article, account, or product…"
              className="input-shell font-mono text-xs w-full pl-7"
              data-testid="pl-sku-search" />
          </div>
        </div>
        <div>
          <div className="section-label mb-1">/ filter</div>
          <select value={filter} onChange={(e) => setFilter(e.target.value)}
            className="input-shell font-mono text-xs" data-testid="pl-sku-class-filter">
            <option value="all">All</option>
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
                <th>Article</th>
                <th>Account</th>
                <th>SKU</th>
                <th>Product</th>
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
                <tr><td colSpan={15} className="text-center py-8 text-[#71717A] font-mono text-xs">
                  <span className="cursor-blink">LOADING</span>
                </td></tr>
              )}
              {!loading && visibleRows.length === 0 && (
                <tr><td colSpan={15} className="text-center py-10 text-[#71717A] text-sm">No data.</td></tr>
              )}
              {visibleRows.map((i) => {
                if (i.is_header) {
                  const isCollapsed = collapsed.has(i.article_name);
                  return (
                    <tr key={`h-${i.article_name}`}
                      onClick={() => toggleCollapse(i.article_name)}
                      className={`cursor-pointer border-t-2 border-[#2A2A2A] hover:bg-[#0F0F12] ${i.is_unmapped ? "bg-[#F5A623]/5" : "bg-[#0A0A0D]"}`}
                      data-testid={`pl-article-header-${i.article_name}`}>
                      <td className="font-display text-sm">
                        <div className="flex items-center gap-2">
                          {isCollapsed ? <CaretRightIcon size={12} weight="bold" /> : <CaretDownIcon size={12} weight="bold" />}
                          <span className={i.is_unmapped ? "text-[#F5A623]" : "text-white"}>{i.article_name}</span>
                          <span className="code-tag text-[10px]">{i.sku_count} skus</span>
                        </div>
                      </td>
                      <td colSpan={3} className="text-[10px] text-[#71717A]">— article rollup —</td>
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
                  );
                }
                // child / leaf row
                return (
                  <tr key={`${i.account_id}-${i.sku}`}
                      className={isArticleView ? "bg-[#0F0F12]/50" : ""}
                      data-testid={`pl-sku-row-${i.account_id}-${i.sku}`}>
                    <td className="font-mono text-[11px]">
                      {isArticleView ? (
                        <span className="text-[#3F3F46] pl-4">↳</span>
                      ) : (
                        i.article_name
                          ? <span className="text-[#00E676]">{i.article_name}</span>
                          : <span className="text-[#71717A]">—</span>
                      )}
                    </td>
                    <td className="font-mono text-[11px] text-[#A1A1AA]">
                      {i.account_alias || i.account_name}
                    </td>
                    <td className="font-mono text-[11px] text-white">{i.sku}</td>
                    <td className="text-[11px] truncate max-w-[180px]" title={i.product_name}>{i.product_name}</td>
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
                );
              })}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
