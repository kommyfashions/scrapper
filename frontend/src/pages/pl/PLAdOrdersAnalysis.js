import { useEffect, useState, useCallback } from "react";
import api, { formatApiError } from "@/lib/api";
import { usePL, DateRangeFilter, buildQuery, inr } from "./PLLayout";

function MetricRow({ label, ad, normal, color }) {
  return (
    <div className="grid grid-cols-3 py-2 border-b border-[#2A2A2A] last:border-b-0">
      <div className="section-label">/ {label}</div>
      <div className="font-mono text-sm" style={{ color }}>{ad}</div>
      <div className="font-mono text-sm" style={{ color }}>{normal}</div>
    </div>
  );
}

export default function PLAdOrdersAnalysis() {
  const { accountId, dateRange } = usePL();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState("");

  const load = useCallback(async () => {
    setLoading(true); setErr("");
    try {
      const { data } = await api.get(`/pl/ad-orders-analysis?${buildQuery({ accountId, dateRange })}`);
      setData(data);
    } catch (e) { setErr(formatApiError(e)); }
    finally { setLoading(false); }
  }, [accountId, dateRange]);

  useEffect(() => { load(); }, [load]);

  return (
    <div className="px-8 py-6 space-y-4" data-testid="pl-adorders-page">
      <DateRangeFilter />
      {err && <div className="border border-[#FF3B30]/30 bg-[#FF3B30]/10 px-3 py-2 font-mono text-xs text-[#FF3B30]">{err}</div>}
      {loading && !data ? (
        <div className="font-mono text-xs uppercase tracking-widest text-[#71717A] cursor-blink py-10 text-center">LOADING</div>
      ) : data && (
        <>
          <div className="grid grid-cols-3 gap-3">
            <div className="panel p-4">
              <div className="section-label">/ ad share</div>
              <div className="font-display text-2xl font-semibold text-[#007AFF]" data-testid="pl-ad-share">{data.comparison.ad_order_percentage}%</div>
            </div>
            <div className="panel p-4">
              <div className="section-label">/ normal share</div>
              <div className="font-display text-2xl font-semibold text-[#A1A1AA]" data-testid="pl-norm-share">{data.comparison.normal_order_percentage}%</div>
            </div>
            <div className="panel p-4">
              <div className="section-label">/ ad return-rate Δ vs normal</div>
              <div className="font-display text-2xl font-semibold"
                   style={{ color: data.comparison.ad_return_rate_vs_normal <= 0 ? "#00E676" : "#FF3B30" }}
                   data-testid="pl-rr-delta">
                {data.comparison.ad_return_rate_vs_normal > 0 ? "+" : ""}{data.comparison.ad_return_rate_vs_normal}pp
              </div>
            </div>
          </div>

          <div className="panel p-5">
            <div className="grid grid-cols-3 mb-3">
              <div className="section-label">/ metric</div>
              <div className="section-label text-[#007AFF]">/ ad orders</div>
              <div className="section-label">/ normal orders</div>
            </div>
            <MetricRow label="orders" ad={data.ad_orders.total_orders} normal={data.normal_orders.total_orders} color="#A1A1AA" />
            <MetricRow label="delivered" ad={data.ad_orders.delivered} normal={data.normal_orders.delivered} color="#00E676" />
            <MetricRow label="returned" ad={data.ad_orders.returned} normal={data.normal_orders.returned} color="#FF3B30" />
            <MetricRow label="rto" ad={data.ad_orders.rto} normal={data.normal_orders.rto} color="#FF8C42" />
            <MetricRow label="return rate" ad={`${data.ad_orders.return_rate}%`} normal={`${data.normal_orders.return_rate}%`} color="#A1A1AA" />
            <MetricRow label="profit" ad={inr(data.ad_orders.total_profit)} normal={inr(data.normal_orders.total_profit)} color="#00E676" />
            <MetricRow label="loss" ad={inr(data.ad_orders.total_loss)} normal={inr(data.normal_orders.total_loss)} color="#FF3B30" />
            <MetricRow label="net contribution"
              ad={inr(data.ad_orders.net_contribution)}
              normal={inr(data.normal_orders.net_contribution)} color="#A1A1AA" />
            <MetricRow label="profit / delivered" ad={inr(data.ad_orders.profit_per_delivered_order)} normal={inr(data.normal_orders.profit_per_delivered_order)} color="#A1A1AA" />
          </div>

          <div className="text-[10px] font-mono text-[#71717A]">
            Note: classification uses Meesho's <span className="code-tag">Order source</span> column. Orders flagged as "Ad order" are isolated from organic.
          </div>
        </>
      )}
    </div>
  );
}
