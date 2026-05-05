import { useEffect, useState, useCallback, createContext, useContext } from "react";
import { NavLink, Outlet } from "react-router-dom";
import api from "@/lib/api";

const PLContext = createContext(null);
export const usePL = () => useContext(PLContext);

const SUB = [
  { to: "/pl/dashboard", label: "Dashboard", testid: "pl-nav-dashboard" },
  { to: "/pl/orders", label: "Orders", testid: "pl-nav-orders" },
  { to: "/pl/sku-analysis", label: "SKU Analysis", testid: "pl-nav-sku-analysis" },
  { to: "/pl/exchange", label: "Exchange", testid: "pl-nav-exchange" },
  { to: "/pl/ad-orders", label: "Ad Orders", testid: "pl-nav-ad-orders" },
  { to: "/pl/sku-costs", label: "SKU Costs", testid: "pl-nav-sku-costs" },
  { to: "/pl/uploads", label: "Uploads", testid: "pl-nav-uploads" },
  { to: "/pl/tax-docs", label: "GST & Tax Docs", testid: "pl-nav-tax-docs" },
];

export default function PLLayout() {
  const [accounts, setAccounts] = useState([]);
  const [accountId, setAccountIdState] = useState(localStorage.getItem("pl_account_id") || "all");
  const [dateRange, setDateRange] = useState({ start_date: "", end_date: "" });

  const setAccountId = useCallback((id) => {
    setAccountIdState(id);
    localStorage.setItem("pl_account_id", id);
  }, []);

  const loadAccounts = useCallback(async () => {
    try {
      const { data } = await api.get("/accounts");
      setAccounts(data.items || []);
    } catch (_) {}
  }, []);

  useEffect(() => {
    document.title = "Profit & Loss · Seller Central";
    loadAccounts();
  }, [loadAccounts]);

  return (
    <PLContext.Provider value={{ accounts, accountId, setAccountId, dateRange, setDateRange, reloadAccounts: loadAccounts }}>
      <div data-testid="pl-layout">
        <div className="border-b border-[#2A2A2A] px-8 py-5">
          <div className="flex flex-wrap items-center justify-between gap-4">
            <div>
              <div className="section-label mb-1">/ profit &amp; loss</div>
              <h1 className="font-display text-3xl font-semibold tracking-tight text-white">
                P&amp;L Analyzer
              </h1>
            </div>
            <div className="flex items-center gap-3">
              <div className="section-label">/ account</div>
              <select
                value={accountId}
                onChange={(e) => setAccountId(e.target.value)}
                className="input-shell font-mono text-sm min-w-[160px]"
                data-testid="pl-account-selector"
              >
                <option value="all">All Accounts</option>
                {accounts.map((a) => (
                  <option key={a.id} value={a.id}>{a.name}</option>
                ))}
              </select>
            </div>
          </div>
          <div className="mt-4 flex flex-wrap gap-1 -mb-1" data-testid="pl-subnav">
            {SUB.map((s) => (
              <NavLink
                key={s.to}
                to={s.to}
                data-testid={s.testid}
                className={({ isActive }) =>
                  "px-3 py-1.5 font-mono text-[11px] uppercase tracking-wider border-b-2 transition-colors " +
                  (isActive
                    ? "border-[#007AFF] text-white"
                    : "border-transparent text-[#71717A] hover:text-[#A1A1AA]")
                }
              >
                {s.label}
              </NavLink>
            ))}
          </div>
        </div>
        <Outlet />
      </div>
    </PLContext.Provider>
  );
}

export function inr(n) {
  if (n === null || n === undefined) return "—";
  return new Intl.NumberFormat("en-IN", {
    style: "currency", currency: "INR",
    minimumFractionDigits: 0, maximumFractionDigits: 0,
  }).format(n);
}

export function DateRangeFilter() {
  const { dateRange, setDateRange } = usePL();
  return (
    <div className="panel p-3 flex flex-wrap items-end gap-3" data-testid="pl-date-filter">
      <div>
        <div className="section-label mb-1">/ start</div>
        <input
          type="date"
          value={dateRange.start_date}
          onChange={(e) => setDateRange({ ...dateRange, start_date: e.target.value })}
          className="input-shell font-mono text-xs"
          data-testid="pl-date-start"
        />
      </div>
      <div>
        <div className="section-label mb-1">/ end</div>
        <input
          type="date"
          value={dateRange.end_date}
          onChange={(e) => setDateRange({ ...dateRange, end_date: e.target.value })}
          className="input-shell font-mono text-xs"
          data-testid="pl-date-end"
        />
      </div>
      {(dateRange.start_date || dateRange.end_date) && (
        <button
          onClick={() => setDateRange({ start_date: "", end_date: "" })}
          className="btn-ghost text-xs"
          data-testid="pl-date-clear"
        >
          Clear
        </button>
      )}
    </div>
  );
}

export function buildQuery({ accountId, dateRange }) {
  const p = new URLSearchParams();
  if (accountId && accountId !== "all") p.append("account_id", accountId);
  if (dateRange?.start_date) p.append("start_date", dateRange.start_date);
  if (dateRange?.end_date) p.append("end_date", dateRange.end_date);
  return p.toString();
}
