import { useCallback, useEffect, useMemo, useState } from "react";
import {
  ArrowsClockwiseIcon,
  CaretDownIcon,
  CaretRightIcon,
  ChartBarIcon,
  DownloadSimpleIcon,
  MagnifyingGlassIcon,
  TrendUpIcon,
  TrendDownIcon,
  UsersThreeIcon,
  WarningCircleIcon,
  XIcon,
} from "@phosphor-icons/react";
import {
  CartesianGrid, Legend, Line, LineChart, ResponsiveContainer,
  Tooltip, XAxis, YAxis,
} from "recharts";
import api, { formatApiError } from "@/lib/api";
import { usePL, inr, DateRangeFilter, buildQuery } from "./PLLayout";

// ============================================================================
// Reusable
// ============================================================================
const CLS = {
  Winner: "chip chip-accent",
  Loser: "chip chip-danger",
  Risky: "chip chip-warn",
  "No Data": "chip",
};

function formatKpiValue(k) {
  if (k.is_percent) return `${k.value.toFixed(2)}%`;
  if (k.currency) return inr(k.value);
  return typeof k.value === "number" ? k.value.toLocaleString() : k.value;
}

function KPICard({ k }) {
  const positiveDeltaGood = !["returned", "return_rate"].includes(k.key);
  const isUp = k.delta_pct != null && k.delta_pct >= 0;
  const isGood = k.delta_pct != null && (positiveDeltaGood ? isUp : !isUp);
  const Icon = isUp ? TrendUpIcon : TrendDownIcon;
  return (
    <div className="kpi-card" data-testid={`ana-kpi-${k.key}`}>
      <div className="section-label mb-1">{k.label}</div>
      <div className="font-display text-3xl leading-tight">
        {formatKpiValue(k)}
      </div>
      <div className="text-[11px] font-mono mt-1 flex items-center gap-1">
        {k.delta_pct != null ? (
          <span className={isGood ? "text-[#6EE7B7]" : "text-[#FCA5A5]"}>
            <Icon size={11} weight="bold" className="inline" />{" "}
            {k.delta_pct > 0 ? "+" : ""}{k.delta_pct}% vs prev period
          </span>
        ) : (
          <span className="text-[var(--text-muted)]">
            {k.sub || "no prev data"}
          </span>
        )}
      </div>
    </div>
  );
}

function TrendChart({ series }) {
  return (
    <div className="panel p-4" data-testid="ana-trend">
      <div className="flex items-center gap-2 mb-3">
        <ChartBarIcon size={14} weight="bold" color="#10B981" />
        <h3 className="font-display text-sm">Profit Trend</h3>
      </div>
      <div className="h-64">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={series} margin={{ top: 6, right: 12, left: -20, bottom: 0 }}>
            <CartesianGrid stroke="#273449" strokeDasharray="3 3" vertical={false} />
            <XAxis dataKey="date" tick={{ fill: "#94A3B8", fontSize: 10, fontFamily: "JetBrains Mono" }} />
            <YAxis yAxisId="l" tick={{ fill: "#94A3B8", fontSize: 10 }} />
            <YAxis yAxisId="r" orientation="right"
              tick={{ fill: "#94A3B8", fontSize: 10 }}
              tickFormatter={(v) => `${v}%`} />
            <Tooltip
              contentStyle={{
                background: "#1E293B", border: "1px solid #334155",
                fontFamily: "JetBrains Mono", fontSize: 11,
              }}
              itemStyle={{ padding: 0 }}
            />
            <Legend wrapperStyle={{ fontSize: 11, fontFamily: "JetBrains Mono" }} />
            <Line yAxisId="l" type="monotone" dataKey="revenue" stroke="#38BDF8" strokeWidth={2} dot={false} name="Revenue" />
            <Line yAxisId="l" type="monotone" dataKey="profit"  stroke="#10B981" strokeWidth={2} dot={false} name="Profit" />
            <Line yAxisId="r" type="monotone" dataKey="return_rate" stroke="#F59E0B" strokeWidth={2} dot={false} name="Return %" />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

function AccountPerformanceTable({ rows }) {
  return (
    <div className="panel p-4" data-testid="ana-accounts">
      <div className="flex items-center gap-2 mb-3">
        <UsersThreeIcon size={14} weight="bold" color="#10B981" />
        <h3 className="font-display text-sm">Account Performance</h3>
      </div>
      <div className="table-wrap max-h-72">
        <table className="dense">
          <thead>
            <tr>
              <th>Account</th>
              <th className="num">Orders</th>
              <th className="num">Revenue</th>
              <th className="num">RR %</th>
              <th className="num">Profit</th>
              <th className="num">Margin %</th>
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 && (
              <tr><td colSpan={6} className="text-center py-4 text-[var(--text-muted)]">no data</td></tr>
            )}
            {rows.map((r) => (
              <tr key={r.account_id} data-testid={`ana-acc-${r.account_id}`}>
                <td>{r.account_alias || r.account_name || "—"}</td>
                <td className="num font-mono">{r.ordered}</td>
                <td className="num font-mono">{inr(r.revenue)}</td>
                <td className="num font-mono">{r.return_rate}%</td>
                <td className={"num font-mono " + (r.profit >= 0 ? "text-[#6EE7B7]" : "text-[#FCA5A5]")}>
                  {inr(r.profit)}
                </td>
                <td className="num font-mono">{r.margin_pct}%</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ---------------- Tree ----------------
function AggBadges({ agg }) {
  if (!agg || !agg.units_ordered) return <span className="text-[var(--text-muted)] text-xs">no data</span>;
  const cls = CLS[agg.classification] || "chip";
  return (
    <div className="flex flex-wrap gap-1.5 items-center text-[10px] font-mono">
      <span className="chip">ORD {agg.units_ordered}</span>
      <span className="chip">DEL {agg.units_delivered}</span>
      <span className="chip">RET {agg.units_returned}</span>
      <span className="chip">RR {agg.return_rate}%</span>
      <span className={"chip " + (agg.net_realized_profit >= 0 ? "chip-accent" : "chip-danger")}>
        PROFIT {inr(agg.net_realized_profit)}
      </span>
      <span className="chip">LOSS {inr(agg.total_return_loss)}</span>
      <span className={"chip " + (agg.net_sku_contribution >= 0 ? "chip-accent" : "chip-danger")}>
        NET {inr(agg.net_sku_contribution)}
      </span>
      <span className={cls}>{agg.classification}</span>
    </div>
  );
}

function SkuTable({ rows, onSkuClick }) {
  if (!rows?.length) return <div className="px-4 py-2 text-xs text-[var(--text-muted)]">no SKU rows</div>;
  return (
    <div className="table-wrap my-2">
      <table className="dense">
        <thead>
          <tr>
            <th>SKU</th>
            <th className="num">Ordered</th>
            <th className="num">Delivered</th>
            <th className="num">Returned</th>
            <th className="num">RR %</th>
            <th className="num">Revenue Profit</th>
            <th className="num">Loss</th>
            <th className="num">Net</th>
            <th>Class</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.sku} onClick={() => onSkuClick(r)} className="cursor-pointer"
                data-testid={`ana-sku-${r.sku}`}>
              <td className="font-mono text-[11px] text-white">{r.sku}</td>
              <td className="num">{r.units_ordered}</td>
              <td className="num">{r.units_delivered}</td>
              <td className="num">{r.units_returned}</td>
              <td className="num">{r.return_rate}%</td>
              <td className="num text-[#6EE7B7]">{inr(r.net_realized_profit)}</td>
              <td className="num text-[#FCA5A5]">{inr(r.total_return_loss)}</td>
              <td className="num font-semibold">{inr(r.net_sku_contribution)}</td>
              <td><span className={CLS[r.classification] || "chip"}>{r.classification}</span></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function AccountNode({ node, onSkuClick }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="tree-guide">
      <div
        className="flex items-center gap-2 py-1.5 cursor-pointer hover:bg-[var(--bg-surface-2)] rounded px-2"
        onClick={() => setOpen((o) => !o)}
        data-testid={`ana-acc-node-${node.account_id}`}
      >
        {open ? <CaretDownIcon size={12} weight="bold" /> : <CaretRightIcon size={12} weight="bold" />}
        <span className="font-mono text-xs">
          {node.account_alias || node.account_name || "Unknown Account"}
        </span>
        {node.is_unmapped && (
          <span className="chip chip-warn">
            <WarningCircleIcon size={10} weight="bold" /> unmapped
          </span>
        )}
        {node.cost_price ? <span className="code-tag">cost {inr(node.cost_price)}</span> : null}
        <div className="ml-auto">
          {node.no_skus ? (
            <span className="chip chip-warn">
              <WarningCircleIcon size={10} weight="bold" /> No SKU Assigned
            </span>
          ) : <AggBadges agg={node.aggregate} />}
        </div>
      </div>
      {open && !node.no_skus && (
        <div className="ml-6"><SkuTable rows={node.skus} onSkuClick={onSkuClick} /></div>
      )}
    </div>
  );
}

function ColorNode({ node, onSkuClick }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="tree-guide">
      <div className="flex items-center gap-2 py-1.5 cursor-pointer hover:bg-[var(--bg-surface-2)] rounded px-2"
           onClick={() => setOpen((o) => !o)}>
        {open ? <CaretDownIcon size={14} weight="bold" /> : <CaretRightIcon size={14} weight="bold" />}
        <span className="font-mono text-sm">{node.color}</span>
        <span className="text-[var(--text-muted)] text-xs">
          ({node.accounts.length} account{node.accounts.length !== 1 ? "s" : ""})
        </span>
        <div className="ml-auto"><AggBadges agg={node.aggregate} /></div>
      </div>
      {open && (
        <div className="ml-6 space-y-1">
          {node.accounts.map((a) => (
            <AccountNode key={a.account_id + (a.product_id || "")} node={a} onSkuClick={onSkuClick} />
          ))}
        </div>
      )}
    </div>
  );
}

function CategoryNode({ node, onSkuClick }) {
  const [open, setOpen] = useState(true);
  return (
    <div className="panel p-3">
      <div className="flex items-center gap-2 cursor-pointer" onClick={() => setOpen((o) => !o)}
           data-testid={`ana-cat-${node.main_category}`}>
        {open ? <CaretDownIcon size={16} weight="bold" /> : <CaretRightIcon size={16} weight="bold" />}
        <ChartBarIcon size={16} weight="bold" color="#10B981" />
        <span className="font-display text-lg">{node.main_category}</span>
        <span className="text-[var(--text-muted)] text-xs">· {node.colors.length} color{node.colors.length !== 1 ? "s" : ""}</span>
        <div className="ml-auto"><AggBadges agg={node.aggregate} /></div>
      </div>
      {open && (
        <div className="mt-2 ml-2 space-y-1">
          {node.colors.map((c) => <ColorNode key={c.color} node={c} onSkuClick={onSkuClick} />)}
        </div>
      )}
    </div>
  );
}

// ---------------- SKU Drawer ----------------
function SkuDrawer({ sku, onClose, accountId, dateRange }) {
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!sku) return;
    setLoading(true);
    const qs = buildQuery({ accountId, dateRange });
    api.get(`/pl/analyzer/sku/${encodeURIComponent(sku.sku)}/orders?${qs}&limit=20`)
      .then((r) => setRows(r.data.items || []))
      .catch(() => setRows([]))
      .finally(() => setLoading(false));
  }, [sku, accountId, dateRange]);

  if (!sku) return null;
  return (
    <div className="fixed inset-y-0 right-0 w-[560px] max-w-[95vw] z-40 bg-[var(--bg-surface)]
                    border-l border-[var(--border)] shadow-2xl overflow-y-auto" data-testid="ana-drawer">
      <div className="flex items-center justify-between p-4 border-b border-[var(--border)] sticky top-0
                      bg-[var(--bg-surface)] z-10">
        <div>
          <div className="font-display text-lg">{sku.sku}</div>
          <div className="text-xs text-[var(--text-muted)]">{sku.product_name || "—"}</div>
        </div>
        <button onClick={onClose} className="btn-ghost" data-testid="ana-drawer-close">
          <XIcon size={16} weight="bold" />
        </button>
      </div>
      <div className="p-4 space-y-4">
        <div className="grid grid-cols-2 gap-2">
          <SkuStat label="Ordered" value={sku.units_ordered} />
          <SkuStat label="Delivered" value={sku.units_delivered} />
          <SkuStat label="Returned" value={sku.units_returned} />
          <SkuStat label="RR %" value={`${sku.return_rate}%`} />
          <SkuStat label="Profit" value={inr(sku.net_realized_profit)} color="#6EE7B7" />
          <SkuStat label="Loss" value={inr(sku.total_return_loss)} color="#FCA5A5" />
          <SkuStat label="Net Contribution" value={inr(sku.net_sku_contribution)}
                   color={sku.net_sku_contribution >= 0 ? "#6EE7B7" : "#FCA5A5"} />
          <SkuStat label="Class" value={<span className={CLS[sku.classification] || "chip"}>{sku.classification}</span>} />
        </div>

        <div>
          <div className="section-label mb-2">Last 20 orders</div>
          <div className="table-wrap max-h-96">
            <table className="dense">
              <thead>
                <tr>
                  <th>Date</th><th>Order #</th><th>Status</th>
                  <th className="num">NSA</th>
                </tr>
              </thead>
              <tbody>
                {loading && <tr><td colSpan={4} className="text-center py-4 text-[var(--text-muted)]">Loading…</td></tr>}
                {!loading && rows.length === 0 && (
                  <tr><td colSpan={4} className="text-center py-4 text-[var(--text-muted)]">No orders in this window</td></tr>
                )}
                {rows.map((o, i) => (
                  <tr key={i}>
                    <td className="text-xs">
                      {o.order_date ? new Date(o.order_date).toLocaleDateString() : "—"}
                    </td>
                    <td className="font-mono text-[10px]">
                      {o.sub_order_no || o.order_id || "—"}
                    </td>
                    <td>
                      <span className={
                        o.order_status === "DELIVERED" ? "chip chip-accent"
                        : o.order_status === "RETURNED" ? "chip chip-danger"
                        : "chip"
                      }>{o.order_status}</span>
                    </td>
                    <td className="num font-mono">{inr(o.net_settlement_amount || 0)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  );
}

function SkuStat({ label, value, color }) {
  return (
    <div className="kpi-card">
      <div className="section-label">{label}</div>
      <div className="font-display text-lg mt-1" style={color ? { color } : {}}>{value}</div>
    </div>
  );
}

// ============================================================================
// Main Page
// ============================================================================
export default function PLSKUAnalysis() {
  const { accountId, dateRange } = usePL();
  const [tree, setTree] = useState([]);
  const [kpis, setKpis] = useState([]);
  const [trend, setTrend] = useState([]);
  const [accounts, setAccounts] = useState([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState("");

  // Filters
  const [q, setQ] = useState("");
  const [qLive, setQLive] = useState("");
  const [category, setCategory] = useState("");
  const [color, setColor] = useState("");
  const [rrMin, setRrMin] = useState("");
  const [rrMax, setRrMax] = useState("");

  // Drawer
  const [selectedSku, setSelectedSku] = useState(null);
  const [exporting, setExporting] = useState(false);

  useEffect(() => {
    const t = setTimeout(() => setQ(qLive), 350);
    return () => clearTimeout(t);
  }, [qLive]);

  const load = useCallback(async () => {
    setLoading(true); setErr("");
    try {
      const qs = buildQuery({ accountId, dateRange });
      const treeUrl = `/pl/sku-analysis-tree?${qs}${q ? `&q=${encodeURIComponent(q)}` : ""}`;
      const [tRes, kRes, trRes, aRes] = await Promise.all([
        api.get(treeUrl),
        api.get(`/pl/analyzer/kpis?${qs}`),
        api.get(`/pl/analyzer/trend?${qs}`),
        api.get(`/pl/analyzer/accounts?${qs}`),
      ]);
      setTree(tRes.data.categories || []);
      setKpis(kRes.data.kpis || []);
      setTrend(trRes.data.series || []);
      setAccounts(aRes.data.items || []);
    } catch (e) {
      setErr(formatApiError(e));
    } finally {
      setLoading(false);
    }
  }, [accountId, dateRange, q]);

  useEffect(() => { load(); }, [load]);

  // Client-side filter for tree (by category / color / RR range)
  const filteredTree = useMemo(() => {
    return tree
      .filter((c) => !category || c.main_category === category)
      .map((cat) => ({
        ...cat,
        colors: cat.colors.filter((cn) => !color || cn.color === color)
          .map((cn) => ({
            ...cn,
            accounts: cn.accounts.map((acc) => {
              const rr = acc.aggregate?.return_rate ?? 0;
              const lo = rrMin === "" ? -Infinity : Number(rrMin);
              const hi = rrMax === "" ? Infinity : Number(rrMax);
              const okRR = rr >= lo && rr <= hi;
              return okRR ? acc : null;
            }).filter(Boolean),
          })).filter((cn) => cn.accounts.length),
      })).filter((cat) => cat.colors.length);
  }, [tree, category, color, rrMin, rrMax]);

  const categories = useMemo(() => tree.map((c) => c.main_category), [tree]);
  const colors = useMemo(() => {
    const set = new Set();
    tree.forEach((c) => c.colors.forEach((cn) => set.add(cn.color)));
    return Array.from(set).sort();
  }, [tree]);

  const exportSummary = useCallback(async () => {
    setExporting(true);
    try {
      const qs = buildQuery({ accountId, dateRange });
      const url = `/pl/analyzer/export?${qs}${q ? `&q=${encodeURIComponent(q)}` : ""}`;
      const r = await api.get(url, {
        responseType: "blob",
        params: { _ts: Date.now() },
        headers: { "Cache-Control": "no-cache", Pragma: "no-cache" },
      });
      const cd = r.headers?.["content-disposition"] || "";
      const match = /filename="?([^"]+)"?/i.exec(cd);
      const stamp = new Date().toISOString().replace(/[:.]/g, "-").slice(0, 19);
      const name = (match && match[1]) || `pl_analyzer_${stamp}.xlsx`;
      const blobUrl = URL.createObjectURL(new Blob([r.data]));
      const a = document.createElement("a");
      a.href = blobUrl;
      a.download = name;
      a.rel = "noopener";
      document.body.appendChild(a);
      a.click();
      setTimeout(() => { URL.revokeObjectURL(blobUrl); a.remove(); }, 4000);
    } catch (e) {
      setErr(formatApiError(e));
    } finally {
      setExporting(false);
    }
  }, [accountId, dateRange, q]);

  return (
    <div className="px-8 py-6 space-y-5" data-testid="pl-sku-analysis-page">
      {/* Header */}
      <div className="flex items-center gap-2">
        <ChartBarIcon size={22} weight="bold" color="#10B981" />
        <div className="flex-1">
          <h2 className="font-display text-xl">P&amp;L Analyzer</h2>
          <div className="text-xs text-[var(--text-muted)]">
            Analyze profit &amp; loss by SKU, Product, Color and Account
          </div>
        </div>
        <button
          onClick={exportSummary}
          disabled={exporting || loading}
          className="btn-ghost text-xs flex items-center gap-1 disabled:opacity-50"
          data-testid="ana-export"
        >
          <DownloadSimpleIcon size={12} weight="bold" />
          {exporting ? "Exporting…" : "Export Summary"}
        </button>
        <button onClick={load} className="btn-ghost text-xs flex items-center gap-1"
                data-testid="ana-refresh">
          <ArrowsClockwiseIcon size={12} weight="bold" /> Refresh
        </button>
      </div>

      {/* Filter bar */}
      <div className="panel p-3 flex flex-wrap items-end gap-2" data-testid="ana-filter-bar">
        <div className="flex-1 min-w-[220px]">
          <div className="section-label mb-1">/ search</div>
          <div className="relative">
            <MagnifyingGlassIcon size={13} weight="bold"
              className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--text-muted)]" />
            <input
              value={qLive}
              onChange={(e) => setQLive(e.target.value)}
              placeholder="SKU / category / color / account…"
              className="input-shell font-mono text-sm pl-8"
              data-testid="ana-search"
            />
          </div>
        </div>
        <div>
          <div className="section-label mb-1">/ category</div>
          <select value={category} onChange={(e) => setCategory(e.target.value)}
            className="input-shell font-mono text-xs min-w-[130px]" data-testid="ana-cat-filter">
            <option value="">All</option>
            {categories.map((c) => <option key={c} value={c}>{c}</option>)}
          </select>
        </div>
        <div>
          <div className="section-label mb-1">/ color</div>
          <select value={color} onChange={(e) => setColor(e.target.value)}
            className="input-shell font-mono text-xs min-w-[110px]" data-testid="ana-color-filter">
            <option value="">All</option>
            {colors.map((c) => <option key={c} value={c}>{c}</option>)}
          </select>
        </div>
        <div>
          <div className="section-label mb-1">/ RR% min</div>
          <input type="number" value={rrMin} onChange={(e) => setRrMin(e.target.value)}
            className="input-shell font-mono text-xs w-20" placeholder="0" data-testid="ana-rr-min" />
        </div>
        <div>
          <div className="section-label mb-1">/ RR% max</div>
          <input type="number" value={rrMax} onChange={(e) => setRrMax(e.target.value)}
            className="input-shell font-mono text-xs w-20" placeholder="100" data-testid="ana-rr-max" />
        </div>
        <button
          onClick={() => { setCategory(""); setColor(""); setRrMin(""); setRrMax(""); setQLive(""); }}
          className="btn-ghost text-xs"
        >Reset</button>
        <DateRangeFilter />
      </div>

      {err && (
        <div className="border border-[rgba(239,68,68,0.35)] bg-[rgba(239,68,68,0.1)] px-3 py-2 font-mono text-xs text-[#FCA5A5]">
          {err}
        </div>
      )}

      {/* KPIs */}
      {kpis.length > 0 && (
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3">
          {kpis.map((k) => <KPICard key={k.key} k={k} />)}
        </div>
      )}

      {/* Trend + Account Performance side-by-side */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-3">
        <div className="lg:col-span-2">
          {trend.length > 0
            ? <TrendChart series={trend} />
            : <div className="panel p-8 text-center text-[var(--text-muted)] text-sm"
                   data-testid="ana-trend">
                No profit trend data in this window
              </div>}
        </div>
        <div><AccountPerformanceTable rows={accounts} /></div>
      </div>

      {/* Tree */}
      {loading ? (
        <div className="text-center text-[var(--text-muted)] py-10">
          <span className="cursor-blink">LOADING</span>
        </div>
      ) : filteredTree.length === 0 ? (
        <div className="panel p-10 text-center text-[var(--text-muted)] text-sm">
          No products match. Upload orders or adjust filters.
        </div>
      ) : (
        <div className="space-y-3" data-testid="ana-tree">
          {filteredTree.map((c) => (
            <CategoryNode key={c.main_category} node={c} onSkuClick={setSelectedSku} />
          ))}
        </div>
      )}

      {/* Drawer */}
      {selectedSku && (
        <>
          <div className="fixed inset-0 bg-black/40 backdrop-blur-sm z-30"
               onClick={() => setSelectedSku(null)} />
          <SkuDrawer sku={selectedSku} onClose={() => setSelectedSku(null)}
                     accountId={accountId} dateRange={dateRange} />
        </>
      )}
    </div>
  );
}
