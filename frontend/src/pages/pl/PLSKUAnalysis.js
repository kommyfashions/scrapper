import { useCallback, useEffect, useMemo, useState } from "react";
import {
  CaretDownIcon,
  CaretRightIcon,
  MagnifyingGlassIcon,
  ArrowsClockwiseIcon,
  ChartBarIcon,
  WarningCircleIcon,
} from "@phosphor-icons/react";
import api, { formatApiError } from "@/lib/api";
import { usePL, inr, DateRangeFilter, buildQuery } from "./PLLayout";

const CLASSIFICATION_STYLES = {
  Winner: "chip chip-accent",
  Loser: "chip chip-danger",
  Risky: "chip chip-warn",
  "No Data": "chip",
};

function AggBadge({ label, value, kind = "" }) {
  return (
    <span
      className={
        "inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-mono " +
        (kind === "profit" && value > 0
          ? "text-[#6EE7B7] bg-[rgba(16,185,129,0.08)]"
          : kind === "loss" && value < 0
          ? "text-[#FCA5A5] bg-[rgba(239,68,68,0.08)]"
          : "text-[var(--text-secondary)] bg-[var(--bg-surface-2)]")
      }
    >
      <span className="opacity-70">{label}</span>
      <span className="text-white">{value}</span>
    </span>
  );
}

function AggregateRow({ agg }) {
  if (!agg || !agg.units_ordered) return <span className="text-[var(--text-muted)] text-xs">no data</span>;
  return (
    <div className="flex flex-wrap gap-1.5 items-center">
      <AggBadge label="ORD" value={agg.units_ordered} />
      <AggBadge label="DEL" value={agg.units_delivered} />
      <AggBadge label="RET" value={agg.units_returned} />
      <AggBadge label="RR%" value={agg.return_rate} />
      <AggBadge label="PROFIT" value={inr(agg.net_realized_profit)} kind="profit" />
      <AggBadge label="LOSS" value={inr(agg.total_return_loss)} />
      <AggBadge label="NET" value={inr(agg.net_sku_contribution)} kind={agg.net_sku_contribution >= 0 ? "profit" : "loss"} />
      {agg.classification && (
        <span className={CLASSIFICATION_STYLES[agg.classification] || "chip"}>
          {agg.classification}
        </span>
      )}
    </div>
  );
}

function SkuTable({ rows }) {
  if (!rows?.length) {
    return (
      <div className="px-4 py-2 text-xs text-[var(--text-muted)]">no SKU rows</div>
    );
  }
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
            <th className="num">Ship Out</th>
            <th className="num">Ship Return</th>
            <th className="num">Profit</th>
            <th className="num">Loss</th>
            <th className="num">Net</th>
            <th>Class</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.sku} data-testid={`skua-row-${r.sku}`}>
              <td className="font-mono text-[11px] text-white">{r.sku}</td>
              <td className="num">{r.units_ordered}</td>
              <td className="num">{r.units_delivered}</td>
              <td className="num">{r.units_returned}</td>
              <td className="num">{r.return_rate}%</td>
              <td className="num">{inr(r.ship_out)}</td>
              <td className="num">{inr(r.ship_return)}</td>
              <td className="num text-[#6EE7B7]">{inr(r.net_realized_profit)}</td>
              <td className="num text-[#FCA5A5]">{inr(r.total_return_loss)}</td>
              <td className="num font-semibold">{inr(r.net_sku_contribution)}</td>
              <td>
                <span className={CLASSIFICATION_STYLES[r.classification] || "chip"}>
                  {r.classification}
                </span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function AccountNode({ node }) {
  const [open, setOpen] = useState(false);
  const noSkus = node.no_skus;
  return (
    <div className="tree-guide">
      <div
        className="flex items-center gap-2 py-1.5 cursor-pointer hover:bg-[var(--bg-surface-2)] rounded px-2"
        onClick={() => setOpen((o) => !o)}
        data-testid={`skua-acc-${node.account_id}`}
      >
        {open ? <CaretDownIcon size={12} weight="bold" /> : <CaretRightIcon size={12} weight="bold" />}
        <span className="font-mono text-xs text-[var(--text-primary)]">
          {node.account_alias || node.account_name || "Unknown Account"}
        </span>
        {node.account_alias && node.account_name && (
          <span className="text-[var(--text-muted)] text-xs">({node.account_name})</span>
        )}
        {node.cost_price ? (
          <span className="code-tag">cost {inr(node.cost_price)}</span>
        ) : null}
        {node.is_unmapped && (
          <span className="chip chip-warn">
            <WarningCircleIcon size={10} weight="bold" /> unmapped
          </span>
        )}
        <div className="ml-auto">
          {noSkus ? (
            <span className="chip chip-warn">
              <WarningCircleIcon size={10} weight="bold" /> No SKU Assigned
            </span>
          ) : (
            <AggregateRow agg={node.aggregate} />
          )}
        </div>
      </div>
      {open && !noSkus && (
        <div className="ml-6">
          <SkuTable rows={node.skus} />
        </div>
      )}
    </div>
  );
}

function ColorNode({ node }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="tree-guide">
      <div
        className="flex items-center gap-2 py-1.5 cursor-pointer hover:bg-[var(--bg-surface-2)] rounded px-2"
        onClick={() => setOpen((o) => !o)}
        data-testid={`skua-color-${node.color}`}
      >
        {open ? <CaretDownIcon size={14} weight="bold" /> : <CaretRightIcon size={14} weight="bold" />}
        <span className="font-mono text-sm text-[var(--text-primary)]">{node.color}</span>
        <span className="text-[var(--text-muted)] text-xs">
          ({node.accounts.length} account{node.accounts.length !== 1 ? "s" : ""})
        </span>
        <div className="ml-auto">
          <AggregateRow agg={node.aggregate} />
        </div>
      </div>
      {open && (
        <div className="ml-6 space-y-1">
          {node.accounts.map((a) => (
            <AccountNode key={a.account_id + (a.product_id || "")} node={a} />
          ))}
        </div>
      )}
    </div>
  );
}

function CategoryNode({ node }) {
  const [open, setOpen] = useState(true);
  return (
    <div className="panel p-3">
      <div
        className="flex items-center gap-2 cursor-pointer"
        onClick={() => setOpen((o) => !o)}
        data-testid={`skua-cat-${node.main_category}`}
      >
        {open ? <CaretDownIcon size={16} weight="bold" /> : <CaretRightIcon size={16} weight="bold" />}
        <ChartBarIcon size={16} weight="bold" color="#10B981" />
        <span className="font-display text-lg">{node.main_category}</span>
        <span className="text-[var(--text-muted)] text-xs">
          · {node.colors.length} color{node.colors.length !== 1 ? "s" : ""}
        </span>
        <div className="ml-auto">
          <AggregateRow agg={node.aggregate} />
        </div>
      </div>
      {open && (
        <div className="mt-2 ml-2 space-y-1">
          {node.colors.map((c) => (
            <ColorNode key={c.color} node={c} />
          ))}
        </div>
      )}
    </div>
  );
}

export default function PLSKUAnalysis() {
  const { accountId, dateRange } = usePL();
  const [tree, setTree] = useState([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState("");
  const [q, setQ] = useState("");
  const [qLive, setQLive] = useState("");

  // debounce search
  useEffect(() => {
    const t = setTimeout(() => setQ(qLive), 400);
    return () => clearTimeout(t);
  }, [qLive]);

  const load = useCallback(async () => {
    setLoading(true);
    setErr("");
    try {
      const qs = buildQuery({ accountId, dateRange });
      const url = `/pl/sku-analysis-tree?${qs}${q ? `&q=${encodeURIComponent(q)}` : ""}`;
      const { data } = await api.get(url);
      setTree(data.categories || []);
    } catch (e) {
      setErr(formatApiError(e));
    } finally {
      setLoading(false);
    }
  }, [accountId, dateRange, q]);

  useEffect(() => { load(); }, [load]);

  const overall = useMemo(() => {
    let ordered = 0, delivered = 0, returned = 0;
    let profit = 0, loss = 0, contrib = 0;
    tree.forEach((c) => {
      const a = c.aggregate || {};
      ordered += a.units_ordered || 0;
      delivered += a.units_delivered || 0;
      returned += a.units_returned || 0;
      profit += a.net_realized_profit || 0;
      loss += a.total_return_loss || 0;
      contrib += a.net_sku_contribution || 0;
    });
    return { ordered, delivered, returned, profit, loss, contrib };
  }, [tree]);

  return (
    <div className="px-8 py-6 space-y-5" data-testid="pl-sku-analysis-page">
      <div className="flex items-center gap-2">
        <ChartBarIcon size={22} weight="bold" color="#10B981" />
        <div className="flex-1">
          <h2 className="font-display text-xl">SKU Analysis</h2>
          <div className="text-xs text-[var(--text-muted)]">
            Category → Color → Account → SKUs
          </div>
        </div>
        <button
          onClick={load}
          className="btn-ghost text-xs flex items-center gap-1"
          data-testid="skua-refresh"
        >
          <ArrowsClockwiseIcon size={12} weight="bold" /> Refresh
        </button>
      </div>

      <div className="flex flex-wrap items-end gap-3">
        <div className="flex-1 min-w-[240px]">
          <div className="section-label mb-1">/ search</div>
          <div className="relative">
            <MagnifyingGlassIcon
              size={14}
              weight="bold"
              className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--text-muted)]"
            />
            <input
              value={qLive}
              onChange={(e) => setQLive(e.target.value)}
              placeholder="Filter by SKU, category, color, account…"
              className="input-shell font-mono text-sm pl-8"
              data-testid="skua-search"
            />
          </div>
        </div>
        <DateRangeFilter />
      </div>

      {err && (
        <div className="border border-[rgba(239,68,68,0.35)] bg-[rgba(239,68,68,0.1)] px-3 py-2 font-mono text-xs text-[#FCA5A5]">
          {err}
        </div>
      )}

      {loading ? (
        <div className="text-center text-[var(--text-muted)] py-10">
          <span className="cursor-blink">LOADING</span>
        </div>
      ) : tree.length === 0 ? (
        <div className="panel p-10 text-center text-[var(--text-muted)] text-sm">
          No products in the Product Master yet. Upload an Excel or add one in <span className="code-tag">P&L › Product Master</span>.
        </div>
      ) : (
        <>
          <div className="grid grid-cols-2 md:grid-cols-6 gap-3">
            <StatCard label="Ordered" value={overall.ordered} testid="skua-stat-ordered" />
            <StatCard label="Delivered" value={overall.delivered} testid="skua-stat-delivered" />
            <StatCard label="Returned" value={overall.returned} testid="skua-stat-returned" />
            <StatCard label="Profit" value={inr(overall.profit)} kind="profit" testid="skua-stat-profit" />
            <StatCard label="Loss" value={inr(overall.loss)} kind="loss" testid="skua-stat-loss" />
            <StatCard label="Net" value={inr(overall.contrib)} kind={overall.contrib >= 0 ? "profit" : "loss"} testid="skua-stat-net" />
          </div>
          <div className="space-y-3" data-testid="skua-tree">
            {tree.map((c) => (
              <CategoryNode key={c.main_category} node={c} />
            ))}
          </div>
        </>
      )}
    </div>
  );
}

function StatCard({ label, value, kind, testid }) {
  const color =
    kind === "profit" ? "text-[#6EE7B7]"
    : kind === "loss" ? "text-[#FCA5A5]"
    : "text-[var(--text-primary)]";
  return (
    <div className="kpi-card" data-testid={testid}>
      <div className={`font-display text-xl ${color}`}>{value}</div>
      <div className="section-label mt-1">{label}</div>
    </div>
  );
}
