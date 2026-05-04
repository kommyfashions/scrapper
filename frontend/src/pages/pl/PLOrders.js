import { useEffect, useState, useCallback } from "react";
import { ArrowsClockwiseIcon, DownloadSimpleIcon, MagnifyingGlassIcon } from "@phosphor-icons/react";
import api, { formatApiError, API } from "@/lib/api";
import { usePL, inr } from "./PLLayout";

const STATUSES = ["all", "DELIVERED", "SHIPPED", "RETURNED", "RTO", "EXCHANGE", "CANCELLED"];

const STATUS_COLOR = {
  DELIVERED: "#00E676", SHIPPED: "#007AFF", RETURNED: "#FF3B30",
  RTO: "#FF8C42", EXCHANGE: "#9333ea", CANCELLED: "#71717A",
};

export default function PLOrders() {
  const { accountId } = usePL();
  const [items, setItems] = useState([]);
  const [total, setTotal] = useState(0);
  const [status, setStatus] = useState("all");
  const [q, setQ] = useState("");
  const [skip, setSkip] = useState(0);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState("");
  const limit = 100;

  const load = useCallback(async () => {
    setLoading(true); setErr("");
    try {
      const p = new URLSearchParams();
      if (accountId && accountId !== "all") p.append("account_id", accountId);
      if (status && status !== "all") p.append("status", status);
      if (q) p.append("q", q);
      p.append("limit", limit); p.append("skip", skip);
      const { data } = await api.get(`/pl/orders?${p.toString()}`);
      setItems(data.items || []); setTotal(data.total || 0);
    } catch (e) {
      setErr(formatApiError(e));
    } finally { setLoading(false); }
  }, [accountId, status, q, skip]);

  useEffect(() => { load(); }, [load]);
  useEffect(() => { setSkip(0); }, [accountId, status, q]);

  const exportUrl = () => {
    const p = new URLSearchParams();
    if (accountId && accountId !== "all") p.append("account_id", accountId);
    if (status && status !== "all") p.append("status", status);
    return `${API}/pl/orders/export?${p.toString()}`;
  };

  return (
    <div className="px-8 py-6 space-y-4" data-testid="pl-orders-page">
      <div className="flex flex-wrap items-end gap-3">
        <div>
          <div className="section-label mb-1">/ status</div>
          <select value={status} onChange={(e) => setStatus(e.target.value)}
            className="input-shell font-mono text-xs" data-testid="pl-orders-status">
            {STATUSES.map((s) => <option key={s} value={s}>{s}</option>)}
          </select>
        </div>
        <div className="flex-1 min-w-[200px]">
          <div className="section-label mb-1">/ search (sku / sub-order / product)</div>
          <div className="relative">
            <MagnifyingGlassIcon size={14} weight="bold" className="absolute left-2 top-1/2 -translate-y-1/2 text-[#71717A]" />
            <input value={q} onChange={(e) => setQ(e.target.value)}
              placeholder="search…"
              className="input-shell font-mono text-xs pl-7 w-full"
              data-testid="pl-orders-search" />
          </div>
        </div>
        <button onClick={load} className="btn-secondary text-xs flex items-center gap-1" data-testid="pl-orders-refresh">
          <ArrowsClockwiseIcon size={12} weight="bold" /> Refresh
        </button>
        <a href={exportUrl()} className="btn-secondary text-xs flex items-center gap-1" data-testid="pl-orders-export">
          <DownloadSimpleIcon size={12} weight="bold" /> Export
        </a>
      </div>

      {err && <div className="border border-[#FF3B30]/30 bg-[#FF3B30]/10 px-3 py-2 font-mono text-xs text-[#FF3B30]" data-testid="pl-orders-err">{err}</div>}

      <div className="panel">
        <div className="border-b border-[#2A2A2A] px-5 py-3 flex items-center justify-between">
          <div className="font-display text-sm font-medium">Orders Ledger</div>
          <span className="code-tag" data-testid="pl-orders-total">{total} total</span>
        </div>
        <div className="overflow-x-auto">
          <table className="dense">
            <thead>
              <tr>
                <th>Sub Order #</th>
                <th>SKU</th>
                <th>Product</th>
                <th>Status</th>
                <th>Pay</th>
                <th>Order Date</th>
                <th className="num">Settlement</th>
                <th className="num">Deductions</th>
                <th className="num">Return Chg</th>
                <th>Source</th>
                <th>Account</th>
              </tr>
            </thead>
            <tbody>
              {loading && (
                <tr><td colSpan={11} className="text-center py-8 text-[#71717A] font-mono text-xs">
                  <span className="cursor-blink">LOADING</span>
                </td></tr>
              )}
              {!loading && items.length === 0 && (
                <tr><td colSpan={11} className="text-center py-10 text-[#71717A] text-sm">
                  No orders. Upload a Meesho payment file from the <a href="/pl/uploads" className="underline">Uploads</a> tab.
                </td></tr>
              )}
              {items.map((o) => (
                <tr key={o.account_id + o.sub_order_no} data-testid={`pl-order-${o.sub_order_no}`}>
                  <td className="font-mono text-[10px]">{o.sub_order_no}</td>
                  <td className="font-mono text-[11px]">{o.sku}</td>
                  <td className="text-[11px] truncate max-w-[260px]" title={o.product_name}>{o.product_name}</td>
                  <td>
                    <span className="font-mono text-[10px] uppercase tracking-wider px-2 py-0.5 rounded-sm"
                      style={{ background: `${STATUS_COLOR[o.order_status]}1a`, color: STATUS_COLOR[o.order_status] }}>
                      {o.order_status}
                    </span>
                  </td>
                  <td className="font-mono text-[10px] text-[#A1A1AA]">{o.payment_status}</td>
                  <td className="font-mono text-[10px] text-[#A1A1AA]">{(o.order_date || "").split(" ")[0]}</td>
                  <td className="num font-mono text-xs">{inr(o.net_settlement_amount)}</td>
                  <td className="num font-mono text-xs text-[#FF3B30]">{inr(-(o.total_deductions || 0))}</td>
                  <td className="num font-mono text-xs">{inr(o.return_charges)}</td>
                  <td className="font-mono text-[10px] text-[#A1A1AA]">{o.order_source || "—"}</td>
                  <td className="font-mono text-[10px] text-[#A1A1AA]">{o.account_name}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="border-t border-[#2A2A2A] px-5 py-3 flex items-center justify-between text-xs">
          <span className="font-mono text-[#71717A]">
            Showing {items.length === 0 ? 0 : skip + 1}-{skip + items.length} of {total}
          </span>
          <div className="flex gap-2">
            <button disabled={skip === 0} onClick={() => setSkip(Math.max(0, skip - limit))}
              className="btn-ghost text-xs disabled:opacity-30" data-testid="pl-orders-prev">Prev</button>
            <button disabled={skip + limit >= total} onClick={() => setSkip(skip + limit)}
              className="btn-ghost text-xs disabled:opacity-30" data-testid="pl-orders-next">Next</button>
          </div>
        </div>
      </div>
    </div>
  );
}
