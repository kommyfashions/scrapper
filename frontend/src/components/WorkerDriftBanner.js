import { useCallback, useEffect, useState } from "react";
import { WarningOctagonIcon } from "@phosphor-icons/react";
import api, { formatApiError } from "@/lib/api";

/**
 * Shows a banner when the dashboard is enqueueing job types the EC2
 * label_worker doesn't yet know about (classic deploy-drift issue), OR
 * when there are >15min-stuck pending jobs of ANY type not currently
 * being served (typical after removing a legacy scraper).
 *
 * Includes a one-click "Clear all stuck jobs" action to purge stale
 * pending jobs without needing to leave the page.
 */
export default function WorkerDriftBanner({ neededTypes }) {
  const [drift, setDrift] = useState(null);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");

  const load = useCallback(async () => {
    try {
      const r = await api.get("/worker-health");
      const missing = r.data.missing_from_workers || [];
      const stuck = r.data.stuck_pending_by_type || {};
      const relevantMissing = neededTypes
        ? missing.filter((t) => neededTypes.includes(t))
        : missing;
      if (relevantMissing.length > 0 || Object.keys(stuck).length > 0) {
        setDrift({ missing: relevantMissing, stuck });
      } else {
        setDrift(null);
      }
    } catch (e) { /* silent */ }
  }, [neededTypes]);

  useEffect(() => {
    let cancelled = false;
    (async () => { if (!cancelled) await load(); })();
    return () => { cancelled = true; };
  }, [load]);

  const clearStuck = async () => {
    setBusy(true); setMsg("");
    try {
      // Cancel every pending job older than 15 min, regardless of type —
      // covers deprecated types like `product_scrape` still lingering
      // in the queue.
      const r = await api.post(
        "/jobs/cancel-stuck?older_than_minutes=15&delete=true"
      );
      setMsg(`Cleared ${r.data.cancelled || 0} stuck job(s).`);
      await load();
    } catch (e) {
      setMsg(formatApiError(e));
    } finally {
      setBusy(false);
    }
  };

  if (!drift) return null;
  return (
    <div
      data-testid="worker-drift-banner"
      className="rounded border border-rose-500/40 bg-rose-500/10 px-4 py-3"
    >
      <div className="flex items-start gap-3">
        <WarningOctagonIcon size={18} weight="bold" color="#F87171" />
        <div className="flex-1 text-sm text-rose-100">
          <div className="flex items-center justify-between gap-3">
            <div className="font-semibold">
              Scraper on your EC2 is out of date — jobs will stay <span className="font-mono">pending</span>.
            </div>
            <button
              data-testid="clear-all-stuck-btn"
              onClick={clearStuck}
              disabled={busy}
              className="shrink-0 rounded-md border border-rose-400/50 bg-rose-500/20 px-3 py-1 text-[11px] font-semibold uppercase tracking-widest text-rose-100 transition hover:bg-rose-500/30 disabled:opacity-40"
            >
              {busy ? "Clearing…" : "Clear all stuck jobs"}
            </button>
          </div>
          {drift.missing.length > 0 && (
            <div className="mt-1 text-xs">
              Worker doesn&apos;t advertise these job types:{" "}
              {drift.missing.map((t) => (
                <code key={t} className="mx-1 rounded bg-black/30 px-1.5 py-0.5">{t}</code>
              ))}
            </div>
          )}
          {Object.keys(drift.stuck).length > 0 && (
            <div className="mt-1 text-xs">
              Stuck &gt;15 min:{" "}
              {Object.entries(drift.stuck).map(([t, n]) => (
                <span key={t} className="mx-1">
                  <code className="rounded bg-black/30 px-1.5 py-0.5">{t}</code>×{n}
                </span>
              ))}
            </div>
          )}
          <div className="mt-2 rounded bg-black/30 px-3 py-2 font-mono text-[11px] leading-relaxed">
            {`# On your EC2 box:
cd ~/scrapper && git pull origin main
cd scraper-ec2 && sudo bash update.sh`}
          </div>
          {msg && (
            <div className="mt-2 text-[11px] text-emerald-200" data-testid="drift-msg">{msg}</div>
          )}
        </div>
      </div>
    </div>
  );
}
