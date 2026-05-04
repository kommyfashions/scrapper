import { useEffect, useState, useCallback } from "react";
import { Link } from "react-router-dom";
import { TrendUpIcon, TrendDownIcon, CurrencyInrIcon, PackageIcon, WarningIcon, MegaphoneIcon } from "@phosphor-icons/react";
import api, { formatApiError } from "@/lib/api";
import { usePL, DateRangeFilter, buildQuery, inr } from "./PLLayout";

function Card({ label, value, hint, color, testid, Icon }) {
  return (
    <div className="panel p-5" data-testid={testid}>
      <div className="flex items-center justify-between mb-2">
        <div className="section-label">/ {label}</div>
        {Icon && <Icon size={18} weight="bold" color={color || "#A1A1AA"} />}
      </div>
      <div className="font-display text-2xl font-semibold" style={{ color: color || "white" }}>
        {value}
      </div>
      {hint && <div className="text-[11px] text-[#71717A] mt-1">{hint}</div>}
    </div>
  );
}

export default function PLDashboard() {
  const { accountId, dateRange } = usePL();
  const [data, setData] = useState(null);
  const [missing, setMissing] = useState(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState("");

  const load = useCallback(async () => {
    setLoading(true); setErr("");
    try {
      const qs = buildQuery({ accountId, dateRange });
      const [d, m] = await Promise.all([
        api.get(`/pl/dashboard?${qs}`),
        api.get(`/pl/missing-sku-costs?${accountId && accountId !== "all" ? "account_id=" + accountId : ""}`),
      ]);
      setData(d.data); setMissing(m.data);
    } catch (e) {
      setErr(formatApiError(e));
    } finally {
      setLoading(false);
    }
  }, [accountId, dateRange]);

  useEffect(() => { load(); }, [load]);

  return (
    <div className="px-8 py-6 space-y-5" data-testid="pl-dashboard">
      <DateRangeFilter />

      {err && (
        <div className="border border-[#FF3B30]/30 bg-[#FF3B30]/10 px-3 py-2 font-mono text-xs text-[#FF3B30]"
          data-testid="pl-dashboard-err">{err}</div>
      )}

      {missing && missing.total_missing > 0 && (
        <div className="border border-[#F5A623]/40 bg-[#F5A623]/10 px-4 py-3 flex items-start gap-3"
          data-testid="pl-missing-skus">
          <WarningIcon size={18} weight="bold" color="#F5A623" />
          <div className="flex-1">
            <div className="font-mono text-xs uppercase tracking-wider text-[#F5A623] mb-1">
              {missing.total_missing} SKU{missing.total_missing > 1 ? "s" : ""} missing cost price
            </div>
            <div className="text-[11px] text-[#A1A1AA] mb-2">
              Profit calculations treat missing-cost SKUs as ₹0 cost. Add cost prices to get accurate profit numbers.
            </div>
            <Link to="/pl/sku-costs" className="btn-secondary text-xs inline-flex" data-testid="pl-link-sku-costs">
              Manage SKU Costs
            </Link>
          </div>
        </div>
      )}

      {loading && !data ? (
        <div className="font-mono text-xs uppercase tracking-widest text-[#71717A] cursor-blink py-10 text-center">
          LOADING
        </div>
      ) : data && (
        <>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
            <Card
              label="Net Contribution"
              value={inr(data.net_contribution)}
              color={data.net_contribution >= 0 ? "#00E676" : "#FF3B30"}
              hint="Profit − Return Loss"
              testid="pl-card-contribution"
              Icon={CurrencyInrIcon}
            />
            <Card
              label="Net Realized Profit"
              value={inr(data.net_realized_profit)}
              color="#00E676"
              hint={`From ${data.delivered_orders} delivered orders`}
              testid="pl-card-profit"
              Icon={TrendUpIcon}
            />
            <Card
              label="Total Return Loss"
              value={inr(data.total_return_loss)}
              color="#FF3B30"
              hint={`${data.returned_orders + data.rto_orders} returns + RTO`}
              testid="pl-card-return-loss"
              Icon={TrendDownIcon}
            />
            <Card
              label="Profit / Delivered Order"
              value={inr(data.profit_per_delivered_order)}
              color="#007AFF"
              hint="Avg margin per delivery"
              testid="pl-card-pdo"
              Icon={PackageIcon}
            />
            <Card
              label="Total Ads Cost"
              value={inr(data.total_ads_cost)}
              color="#F5A623"
              hint="Meesho ads spend in window"
              testid="pl-card-ads"
              Icon={MegaphoneIcon}
            />
            <Card
              label="Net After Ads"
              value={inr(data.net_contribution_after_ads)}
              color={data.net_contribution_after_ads >= 0 ? "#00E676" : "#FF3B30"}
              hint="Contribution − ads"
              testid="pl-card-after-ads"
              Icon={CurrencyInrIcon}
            />
            <Card
              label="Open Exposure"
              value={inr(data.open_exposure)}
              color="#F5A623"
              hint={`${data.shipped_orders} in transit`}
              testid="pl-card-exposure"
              Icon={WarningIcon}
            />
            <Card
              label="Pending Settlement"
              value={inr(data.pending_settlement_amount)}
              color="#9333ea"
              hint="Awaiting payment"
              testid="pl-card-pending"
            />
          </div>

          <div className="panel p-5">
            <div className="font-display text-base mb-4">Order Status Summary</div>
            <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
              <div>
                <div className="section-label">/ total</div>
                <div className="font-display text-2xl font-semibold" data-testid="pl-stat-total">{data.total_orders}</div>
              </div>
              <div>
                <div className="section-label">/ delivered</div>
                <div className="font-display text-2xl font-semibold text-[#00E676]" data-testid="pl-stat-delivered">{data.delivered_orders}</div>
              </div>
              <div>
                <div className="section-label">/ shipped</div>
                <div className="font-display text-2xl font-semibold text-[#007AFF]" data-testid="pl-stat-shipped">{data.shipped_orders}</div>
              </div>
              <div>
                <div className="section-label">/ returned</div>
                <div className="font-display text-2xl font-semibold text-[#FF3B30]" data-testid="pl-stat-returned">{data.returned_orders}</div>
              </div>
              <div>
                <div className="section-label">/ rto</div>
                <div className="font-display text-2xl font-semibold text-[#FF8C42]" data-testid="pl-stat-rto">{data.rto_orders}</div>
              </div>
            </div>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <Link to="/pl/exchange"
              className="panel p-4 hover:bg-[#1F1F1F] transition-colors block"
              data-testid="pl-link-exchange">
              <div className="font-display text-base text-[#9333ea] mb-1">Exchange Orders</div>
              <p className="text-[11px] text-[#A1A1AA]">Separate metrics for exchange orders (kept out of main P&L)</p>
            </Link>
            <Link to="/pl/ad-orders"
              className="panel p-4 hover:bg-[#1F1F1F] transition-colors block"
              data-testid="pl-link-ad-orders">
              <div className="font-display text-base text-[#007AFF] mb-1">Ad Orders vs Normal</div>
              <p className="text-[11px] text-[#A1A1AA]">Compare ad-driven order performance with organic</p>
            </Link>
          </div>
        </>
      )}
    </div>
  );
}
