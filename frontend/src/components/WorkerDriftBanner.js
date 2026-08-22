import { useEffect, useState } from "react";
import { WarningOctagonIcon } from "@phosphor-icons/react";
import api from "@/lib/api";

/**
 * Shows a banner when the dashboard is enqueueing job types the EC2
 * label_worker doesn't yet know about (classic deploy-drift issue).
 * Uses /api/worker-health.
 */
export default function WorkerDriftBanner({ neededTypes }) {
  const [drift, setDrift] = useState(null);

  useEffect(() => {
    let cancelled = false;
    api.get("/worker-health")
      .then((r) => {
        if (cancelled) return;
        const missing = r.data.missing_from_workers || [];
        const stuck = r.data.stuck_pending_by_type || {};
        const relevantMissing = neededTypes
          ? missing.filter((t) => neededTypes.includes(t))
          : missing;
        if (relevantMissing.length > 0 || Object.keys(stuck).length > 0) {
          setDrift({ missing: relevantMissing, stuck });
        }
      })
      .catch(() => { /* silent */ });
    return () => { cancelled = true; };
  }, [neededTypes]);

  if (!drift) return null;
  return (
    <div
      data-testid="worker-drift-banner"
      className="rounded border border-rose-500/40 bg-rose-500/10 px-4 py-3"
    >
      <div className="flex items-start gap-3">
        <WarningOctagonIcon size={18} weight="bold" color="#F87171" />
        <div className="flex-1 text-sm text-rose-100">
          <div className="font-semibold">
            Scraper on your EC2 is out of date — jobs will stay <span className="font-mono">pending</span>.
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
        </div>
      </div>
    </div>
  );
}
