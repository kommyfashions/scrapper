import { NavLink, useNavigate } from "react-router-dom";
import {
  GaugeIcon,
  PlusCircleIcon,
  ListChecksIcon,
  PackageIcon,
  ChartBarIcon,
  SignOutIcon,
  TerminalWindowIcon,
  PrinterIcon,
  GearIcon,
  UserCircleIcon,
  CurrencyInrIcon,
} from "@phosphor-icons/react";
import { useAuth } from "@/auth/AuthContext";

const NAV_SECTIONS = [
  {
    label: "OPERATIONS",
    items: [
      { to: "/", label: "Dashboard", Icon: GaugeIcon, end: true, testid: "nav-dashboard" },
      { to: "/jobs/new", label: "Submit Job", Icon: PlusCircleIcon, testid: "nav-submit" },
      { to: "/jobs", label: "Jobs", Icon: ListChecksIcon, testid: "nav-jobs" },
    ],
  },
  {
    label: "INSIGHTS",
    items: [
      { to: "/products", label: "Products", Icon: PackageIcon, testid: "nav-products" },
      { to: "/analytics", label: "Analytics", Icon: ChartBarIcon, testid: "nav-analytics" },
    ],
  },
  {
    label: "AUTOMATION",
    items: [
      { to: "/accounts", label: "Accounts", Icon: UserCircleIcon, testid: "nav-accounts" },
      { to: "/labels", label: "Label Download", Icon: PrinterIcon, testid: "nav-labels" },
      { to: "/settings", label: "Settings", Icon: GearIcon, testid: "nav-settings" },
    ],
  },
  {
    label: "PROFIT & LOSS",
    items: [
      { to: "/pl/dashboard", label: "P&L Dashboard", Icon: CurrencyInrIcon, testid: "nav-pl-dashboard" },
      { to: "/pl/orders", label: "P&L Orders", Icon: ListChecksIcon, testid: "nav-pl-orders" },
      { to: "/pl/sku-analysis", label: "SKU Analysis", Icon: ChartBarIcon, testid: "nav-pl-sku-analysis" },
      { to: "/pl/sku-costs", label: "SKU Costs", Icon: PackageIcon, testid: "nav-pl-sku-costs" },
      { to: "/pl/uploads", label: "Uploads", Icon: PlusCircleIcon, testid: "nav-pl-uploads" },
    ],
  },
];

export default function Sidebar() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();

  const handleLogout = () => {
    logout();
    navigate("/login", { replace: true });
  };

  return (
    <aside
      className="flex h-screen w-64 flex-col border-r border-[#2A2A2A] bg-[#0A0A0A]"
      data-testid="sidebar"
    >
      <div className="flex items-center gap-2 px-5 py-5 border-b border-[#2A2A2A]">
        <TerminalWindowIcon size={22} weight="bold" color="#007AFF" />
        <div>
          <div className="font-display text-base font-semibold tracking-tight">
            Seller Central
          </div>
          <div className="font-mono text-[10px] uppercase tracking-[0.2em] text-[#71717A]">
            v0.1 · meesho ops
          </div>
        </div>
      </div>

      <nav className="flex-1 overflow-y-auto px-3 py-4 space-y-6">
        {NAV_SECTIONS.map((section) => (
          <div key={section.label}>
            <div className="section-label mb-2 px-2">{section.label}</div>
            <div className="space-y-1">
              {section.items.map(({ to, label, Icon, end, testid }) => (
                <NavLink
                  key={to}
                  to={to}
                  end={end}
                  data-testid={testid}
                  className={({ isActive }) =>
                    `sidebar-link${isActive ? " active" : ""}`
                  }
                >
                  <Icon size={16} weight="bold" />
                  <span>{label}</span>
                </NavLink>
              ))}
            </div>
          </div>
        ))}

        <div>
          <div className="section-label mb-2 px-2">FUTURE MODULES</div>
          <div className="space-y-1 px-2">
            {["Auto Payment Scraper", "Inventory Loss"].map((m) => (
              <div
                key={m}
                className="flex items-center justify-between text-xs text-[#71717A] py-1"
              >
                <span>{m}</span>
                <span className="font-mono text-[9px] tracking-widest text-[#3a3a3a]">
                  SOON
                </span>
              </div>
            ))}
          </div>
        </div>
      </nav>

      <div className="border-t border-[#2A2A2A] px-4 py-3">
        <div className="text-xs text-[#A1A1AA] truncate" data-testid="sidebar-user-email">
          {user?.email}
        </div>
        <button
          onClick={handleLogout}
          className="btn-ghost mt-2 flex w-full items-center justify-between text-xs"
          data-testid="logout-button"
        >
          <span>Sign out</span>
          <SignOutIcon size={14} weight="bold" />
        </button>
      </div>
    </aside>
  );
}
