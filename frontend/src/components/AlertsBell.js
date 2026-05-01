import { useEffect, useState, useCallback, useRef } from "react";
import { Link } from "react-router-dom";
import {
  BellIcon,
  CheckIcon,
  TrashIcon,
  WarningIcon,
  TrendDownIcon,
  XIcon,
} from "@phosphor-icons/react";
import api, { formatApiError } from "@/lib/api";
import { fmtRelative } from "@/lib/format";

const POLL_MS = 60_000;

const TYPE_META = {
  one_star_spike: { color: "#FF3B30", label: "1★ SPIKE", Icon: WarningIcon },
  rating_drop:    { color: "#F5A623", label: "RATING DROP", Icon: TrendDownIcon },
};

export default function AlertsBell() {
  const [open, setOpen] = useState(false);
  const [items, setItems] = useState([]);
  const [unread, setUnread] = useState(0);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState("");
  const drawerRef = useRef(null);

  const load = useCallback(async () => {
    try {
      const { data } = await api.get("/alerts", { params: { limit: 50 } });
      setItems(data.items || []);
      setUnread(data.unread || 0);
    } catch (e) {
      // silent — keep bell working even on transient errors
    }
  }, []);

  useEffect(() => {
    load();
    const t = setInterval(load, POLL_MS);
    return () => clearInterval(t);
  }, [load]);

  // close on outside click
  useEffect(() => {
    if (!open) return;
    const onDown = (e) => {
      if (drawerRef.current && !drawerRef.current.contains(e.target)) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [open]);

  const markRead = async (id) => {
    try {
      await api.post(`/alerts/${id}/read`);
      await load();
    } catch (e) { setErr(formatApiError(e)); }
  };
  const markAllRead = async () => {
    try {
      await api.post(`/alerts/read-all`);
      await load();
    } catch (e) { setErr(formatApiError(e)); }
  };
  const remove = async (id) => {
    try {
      await api.delete(`/alerts/${id}`);
      await load();
    } catch (e) { setErr(formatApiError(e)); }
  };
  const checkNow = async () => {
    setLoading(true); setErr("");
    try {
      await api.post(`/alerts/check-now`);
      await load();
    } catch (e) { setErr(formatApiError(e)); }
    finally { setLoading(false); }
  };

  return (
    <div className="relative" ref={drawerRef}>
      <button
        onClick={() => setOpen((v) => !v)}
        className="btn-ghost relative flex items-center justify-center h-9 w-9 rounded-sm border border-[#2A2A2A] hover:border-[#3a3a3a]"
        data-testid="alerts-bell"
        title="Alerts"
      >
        <BellIcon size={16} weight="bold" />
        {unread > 0 && (
          <span
            className="absolute -top-1 -right-1 min-w-[16px] h-4 px-1 rounded-full bg-[#FF3B30] text-[9px] font-mono font-bold flex items-center justify-center text-white"
            data-testid="alerts-unread-badge"
          >
            {unread > 99 ? "99+" : unread}
          </span>
        )}
      </button>

      {open && (
        <div
          className="absolute right-0 top-11 z-40 w-[420px] max-w-[92vw] panel shadow-xl"
          data-testid="alerts-drawer"
        >
          <div className="flex items-center justify-between border-b border-[#2A2A2A] px-4 py-3">
            <div className="flex items-center gap-2">
              <BellIcon size={14} weight="bold" color="#F5A623" />
              <div className="font-display text-sm font-medium">Alerts</div>
              {unread > 0 && (
                <span className="code-tag" style={{ background: "#FF3B301a", color: "#FF3B30", borderColor: "#FF3B3055" }}>
                  {unread} new
                </span>
              )}
            </div>
            <div className="flex items-center gap-1">
              <button onClick={checkNow} disabled={loading}
                className="btn-ghost text-[10px] uppercase tracking-wider font-mono"
                data-testid="alerts-check-now">
                {loading ? "checking…" : "check now"}
              </button>
              {unread > 0 && (
                <button onClick={markAllRead}
                  className="btn-ghost text-[10px] uppercase tracking-wider font-mono"
                  data-testid="alerts-mark-all-read">
                  mark all read
                </button>
              )}
              <button onClick={() => setOpen(false)} className="btn-ghost"
                data-testid="alerts-close">
                <XIcon size={12} weight="bold" />
              </button>
            </div>
          </div>

          {err && (
            <div className="border-b border-[#FF3B30]/30 bg-[#FF3B30]/10 px-3 py-2 font-mono text-[11px] text-[#FF3B30]">
              {err}
            </div>
          )}

          <div className="max-h-[440px] overflow-y-auto divide-y divide-[#2A2A2A]">
            {items.length === 0 && (
              <div className="px-4 py-10 text-center text-xs text-[#71717A]">
                <BellIcon size={28} weight="thin" color="#3a3a3a" />
                <div className="mt-2">No alerts yet. The detector runs every 30 min.</div>
              </div>
            )}
            {items.map((a) => {
              const meta = TYPE_META[a.type] || { color: "#A1A1AA", label: (a.type || "ALERT").toUpperCase(), Icon: WarningIcon };
              const Icon = meta.Icon;
              return (
                <div
                  key={a.id}
                  className={"px-4 py-3 flex gap-3 items-start " + (a.read ? "opacity-60" : "")}
                  data-testid={`alert-row-${a.id}`}
                >
                  <Icon size={18} weight="bold" color={meta.color} />
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <span
                        className="code-tag"
                        style={{ background: `${meta.color}1a`, color: meta.color, borderColor: `${meta.color}55` }}
                      >
                        {meta.label}
                      </span>
                      {!a.read && (
                        <span className="h-1.5 w-1.5 rounded-full bg-[#FF3B30]" data-testid={`alert-unread-dot-${a.id}`} />
                      )}
                      <span className="font-mono text-[10px] text-[#71717A] ml-auto">{fmtRelative(a.created_at)}</span>
                    </div>
                    <div className="mt-1.5 text-sm text-white truncate">
                      {a.product_name || a.product_id}
                    </div>
                    <div className="text-xs text-[#A1A1AA]">{a.message}</div>
                    <div className="mt-2 flex items-center gap-1">
                      {a.product_id && (
                        <Link
                          to={`/products/${a.product_id}`}
                          onClick={() => { setOpen(false); markRead(a.id); }}
                          className="btn-ghost text-[10px] uppercase tracking-wider font-mono"
                          data-testid={`alert-open-${a.id}`}
                        >
                          open product →
                        </Link>
                      )}
                      {!a.read && (
                        <button onClick={() => markRead(a.id)}
                          className="btn-ghost text-[10px] uppercase tracking-wider font-mono flex items-center gap-1"
                          data-testid={`alert-mark-${a.id}`}>
                          <CheckIcon size={10} weight="bold" /> mark read
                        </button>
                      )}
                      <button onClick={() => remove(a.id)}
                        className="btn-ghost text-[10px] uppercase tracking-wider font-mono ml-auto hover:text-[#FF3B30] flex items-center gap-1"
                        data-testid={`alert-delete-${a.id}`}>
                        <TrashIcon size={10} weight="bold" /> delete
                      </button>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
