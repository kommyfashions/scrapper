import { useEffect, useState, useCallback } from "react";
import api, { formatApiError } from "@/lib/api";
import { usePL, DateRangeFilter, buildQuery, inr } from "./PLLayout";

function Stat({ label, value, color, testid }) {
  return (
    <div className="panel p-4" data-testid={testid}>
      <div className="section-label">/ {label}</div>
      <div className="font-display text-2xl font-semibold mt-1" style={{ color: color || "white" }}>{value}</div>
    </div>
  );
}

export default function PLExchangeAnalysis() {
  const { accountId, dateRange } = usePL();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState("");

  const load = useCallback(async () => {
    setLoading(true); setErr("");
    try {
      const { data } = await api.get(`/pl/exchange-analysis?${buildQuery({ accountId, dateRange })}`);
      setData(data);
    } catch (e) { setErr(formatApiError(e)); }
    finally { setLoading(false); }
  }, [accountId, dateRange]);

  useEffect(() => { load(); }, [load]);

  return (
    <div className="px-8 py-6 space-y-4" data-testid="pl-exchange-page">
      <DateRangeFilter />
      {err && <div className="border border-[#FF3B30]/30 bg-[#FF3B30]/10 px-3 py-2 font-mono text-xs text-[#FF3B30]">{err}</div>}
      {loading && !data ? (
        <div className="font-mono text-xs uppercase tracking-widest text-[#71717A] cursor-blink py-10 text-center">LOADING</div>
      ) : data && (
        <>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            <Stat label="exchange orders" value={data.total_exchange_orders} color="#9333ea" testid="pl-ex-total" />
            <Stat label="total p&l" value={inr(data.total_profit_loss)}
              color={data.total_profit_loss >= 0 ? "#00E676" : "#FF3B30"} testid="pl-ex-pl" />
            <Stat label="positive settlement" value={`${data.positive_settlement_count} · ${inr(data.positive_settlement_total)}`} color="#00E676" testid="pl-ex-pos" />
            <Stat label="negative settlement" value={`${data.negative_settlement_count} · ${inr(data.negative_settlement_total)}`} color="#FF3B30" testid="pl-ex-neg" />
          </div>

          <div className="panel">
            <div className="border-b border-[#2A2A2A] px-5 py-3 font-display text-sm">Top SKUs (by P&L impact)</div>
            <div className="overflow-x-auto">
              <table className="dense">
                <thead>
                  <tr><th>SKU</th><th>Product</th><th className="num">Count</th><th className="num">Settlement</th><th className="num">P&L</th></tr>
                </thead>
                <tbody>
                  {data.sku_breakdown.slice(0, 20).map((s) => (
                    <tr key={s.sku} data-testid={`pl-ex-sku-${s.sku}`}>
                      <td className="font-mono text-[11px]">{s.sku}</td>
                      <td className="text-[11px] truncate max-w-[260px]" title={s.product_name}>{s.product_name}</td>
                      <td className="num font-mono text-xs">{s.count}</td>
                      <td className="num font-mono text-xs">{inr(s.total_settlement)}</td>
                      <td className="num font-mono text-xs" style={{ color: s.total_profit_loss >= 0 ? "#00E676" : "#FF3B30" }}>
                        {inr(s.total_profit_loss)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
