import { useEffect, useState } from "react";
import {
  ClockIcon, ToggleLeftIcon, ToggleRightIcon, FloppyDiskIcon, PlayIcon,
  CalendarBlankIcon, PlusIcon, XIcon,
} from "@phosphor-icons/react";
import api, { formatApiError } from "@/lib/api";
import PageHeader from "@/components/PageHeader";

const WEEKDAYS = [
  { i: 0, label: "MON" },
  { i: 1, label: "TUE" },
  { i: 2, label: "WED" },
  { i: 3, label: "THU" },
  { i: 4, label: "FRI" },
  { i: 5, label: "SAT" },
  { i: 6, label: "SUN" },
];

function Toggle({ value, onChange, testid }) {
  return (
    <button
      onClick={() => onChange(!value)}
      className="flex items-center gap-1 text-sm"
      data-testid={testid}
    >
      {value ? <ToggleRightIcon size={28} weight="fill" color="#00E676" />
             : <ToggleLeftIcon size={28} weight="fill" color="#3a3a3a" />}
      <span className={"font-mono text-[11px] uppercase tracking-wider " + (value ? "text-[#00E676]" : "text-[#71717A]")}>
        {value ? "ON" : "OFF"}
      </span>
    </button>
  );
}

export default function SettingsPage() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");
  const [newSkipDate, setNewSkipDate] = useState("");

  const load = () => {
    setLoading(true);
    api.get("/settings").then((r) => {
      const d = r.data;
      d.skip_dates = d.skip_dates || [];
      d.skip_weekdays = d.skip_weekdays || [];
      setData(d);
    }).finally(() => setLoading(false));
  };
  useEffect(() => {
    document.title = "Settings · Seller Central";
    load();
  }, []);

  const save = async () => {
    setSaving(true); setMsg(""); setErr("");
    try {
      const body = {
        scrape_enabled: data.scrape_enabled,
        scrape_time: data.scrape_time,
        label_enabled: data.label_enabled,
        label_time: data.label_time,
        skip_dates: [...new Set(data.skip_dates || [])].sort(),
        skip_weekdays: [...new Set(data.skip_weekdays || [])].sort((a, b) => a - b),
      };
      const { data: updated } = await api.put("/settings", body);
      updated.skip_dates = updated.skip_dates || [];
      updated.skip_weekdays = updated.skip_weekdays || [];
      setData(updated);
      setMsg("Settings saved.");
      setTimeout(() => setMsg(""), 2500);
    } catch (e) {
      setErr(formatApiError(e));
    } finally {
      setSaving(false);
    }
  };

  const runNow = async (what) => {
    setMsg(""); setErr("");
    try {
      await api.post(`/scheduler/run-now?what=${what}`);
      const labels = { scrape: "Scrape", label: "Label", snapshot: "Snapshot" };
      setMsg(`${labels[what]} jobs queued.`);
      setTimeout(() => setMsg(""), 2500);
    } catch (e) {
      setErr(formatApiError(e));
    }
  };

  if (loading || !data) {
    return (
      <div className="flex h-full items-center justify-center">
        <div className="font-mono text-xs uppercase tracking-widest text-[#71717A] cursor-blink">LOADING</div>
      </div>
    );
  }

  const fmtNext = (iso) => {
    if (!iso) return "—";
    try { return new Date(iso).toLocaleString(); } catch { return iso; }
  };

  const toggleWeekday = (i) => {
    const cur = data.skip_weekdays || [];
    const next = cur.includes(i) ? cur.filter((x) => x !== i) : [...cur, i];
    setData({ ...data, skip_weekdays: next });
  };

  const addSkipDate = () => {
    if (!newSkipDate) return;
    const cur = data.skip_dates || [];
    if (cur.includes(newSkipDate)) { setNewSkipDate(""); return; }
    setData({ ...data, skip_dates: [...cur, newSkipDate].sort() });
    setNewSkipDate("");
  };

  const removeSkipDate = (d) => {
    setData({ ...data, skip_dates: (data.skip_dates || []).filter((x) => x !== d) });
  };

  return (
    <div data-testid="settings-page">
      <PageHeader
        title="config"
        subtitle="Settings"
        right={
          <button onClick={save} disabled={saving} className="btn-primary text-sm flex items-center gap-2"
            data-testid="save-settings-button">
            <FloppyDiskIcon size={14} weight="bold" />
            {saving ? "Saving…" : "Save"}
          </button>
        }
      />

      <div className="px-8 py-6 max-w-3xl space-y-4">
        {msg && (
          <div className="border border-[#00E676]/30 bg-[#00E676]/10 px-3 py-2 font-mono text-xs text-[#00E676]"
            data-testid="settings-msg">{msg}</div>
        )}
        {err && (
          <div className="border border-[#FF3B30]/30 bg-[#FF3B30]/10 px-3 py-2 font-mono text-xs text-[#FF3B30]"
            data-testid="settings-err">{err}</div>
        )}

        {/* SCRAPE */}
        <div className="panel p-5 space-y-4">
          <div className="flex items-center gap-2">
            <ClockIcon size={18} weight="bold" color="#007AFF" />
            <div className="font-display text-base">Daily Product Scrape</div>
          </div>
          <p className="text-xs text-[#A1A1AA]">
            Every day at the time below ({data.timezone}), the backend enqueues a scrape job for
            each <span className="code-tag">tracked</span> product, then takes a daily snapshot
            5 minutes later for the trend chart.
          </p>
          <div className="flex flex-wrap items-center gap-6">
            <div>
              <div className="section-label mb-1">/ enabled</div>
              <Toggle
                value={data.scrape_enabled}
                onChange={(v) => setData({ ...data, scrape_enabled: v })}
                testid="toggle-scrape-enabled"
              />
            </div>
            <div>
              <div className="section-label mb-1">/ time (24h)</div>
              <input
                type="time"
                value={data.scrape_time}
                onChange={(e) => setData({ ...data, scrape_time: e.target.value })}
                className="input-shell font-mono text-sm w-32"
                data-testid="scrape-time-input"
              />
            </div>
            <div>
              <div className="section-label mb-1">/ next run</div>
              <div className="font-mono text-xs text-[#A1A1AA]">{fmtNext(data.next_runs?.daily_scrape)}</div>
            </div>
            <button onClick={() => runNow("scrape")} className="btn-secondary text-xs flex items-center gap-1"
              data-testid="run-scrape-now">
              <PlayIcon size={12} weight="bold" /> Run now
            </button>
            <button onClick={() => runNow("snapshot")} className="btn-secondary text-xs flex items-center gap-1"
              data-testid="run-snapshot-now">
              <PlayIcon size={12} weight="bold" /> Snapshot now
            </button>
          </div>
        </div>

        {/* LABEL */}
        <div className="panel p-5 space-y-4">
          <div className="flex items-center gap-2">
            <ClockIcon size={18} weight="bold" color="#F5A623" />
            <div className="font-display text-base">Daily Label Download</div>
          </div>
          <p className="text-xs text-[#A1A1AA]">
            Runs the supplier-portal automation on EC2 to accept pending orders and download
            shipping labels for every <span className="code-tag">enabled</span> account.
          </p>
          <div className="flex flex-wrap items-center gap-6">
            <div>
              <div className="section-label mb-1">/ enabled</div>
              <Toggle
                value={data.label_enabled}
                onChange={(v) => setData({ ...data, label_enabled: v })}
                testid="toggle-label-enabled"
              />
            </div>
            <div>
              <div className="section-label mb-1">/ time (24h)</div>
              <input
                type="time"
                value={data.label_time}
                onChange={(e) => setData({ ...data, label_time: e.target.value })}
                className="input-shell font-mono text-sm w-32"
                data-testid="label-time-input"
              />
            </div>
            <div>
              <div className="section-label mb-1">/ next run</div>
              <div className="font-mono text-xs text-[#A1A1AA]">{fmtNext(data.next_runs?.daily_label)}</div>
            </div>
            <button onClick={() => runNow("label")} className="btn-secondary text-xs flex items-center gap-1"
              data-testid="run-label-now">
              <PlayIcon size={12} weight="bold" /> Run now
            </button>
          </div>
        </div>

        {/* SKIP RULES */}
        <div className="panel p-5 space-y-4" data-testid="skip-rules-panel">
          <div className="flex items-center gap-2">
            <CalendarBlankIcon size={18} weight="bold" color="#FF8C42" />
            <div className="font-display text-base">Label Skip Rules</div>
          </div>
          <p className="text-xs text-[#A1A1AA]">
            On these days the daily label downloader will be <span className="text-[#FF8C42]">skipped</span> automatically
            (e.g. weekly off, holidays). The product scrape is unaffected.
          </p>

          {/* WEEKDAY CHIPS */}
          <div>
            <div className="section-label mb-2">/ skip weekdays</div>
            <div className="flex flex-wrap gap-2">
              {WEEKDAYS.map(({ i, label }) => {
                const active = (data.skip_weekdays || []).includes(i);
                return (
                  <button
                    key={i}
                    onClick={() => toggleWeekday(i)}
                    className={
                      "px-3 py-1.5 font-mono text-[11px] uppercase tracking-wider rounded-sm border transition-colors " +
                      (active
                        ? "bg-[#FF8C42] border-[#FF8C42] text-white"
                        : "bg-[#141414] border-[#2A2A2A] text-[#A1A1AA] hover:bg-[#1F1F1F]")
                    }
                    data-testid={`weekday-chip-${i}`}
                  >
                    {label}
                  </button>
                );
              })}
            </div>
          </div>

          {/* SKIP DATES */}
          <div>
            <div className="section-label mb-2">/ skip specific dates</div>
            <div className="flex items-center gap-2 mb-3">
              <input
                type="date"
                value={newSkipDate}
                onChange={(e) => setNewSkipDate(e.target.value)}
                className="input-shell font-mono text-sm w-44"
                data-testid="skip-date-input"
              />
              <button
                onClick={addSkipDate}
                disabled={!newSkipDate}
                className="btn-secondary text-xs flex items-center gap-1"
                data-testid="skip-date-add"
              >
                <PlusIcon size={12} weight="bold" /> Add
              </button>
            </div>
            {(data.skip_dates || []).length === 0 ? (
              <div className="text-xs text-[#71717A] font-mono">no skip dates configured</div>
            ) : (
              <div className="flex flex-wrap gap-2">
                {(data.skip_dates || []).map((d) => (
                  <span
                    key={d}
                    className="inline-flex items-center gap-1 px-2 py-1 font-mono text-[11px]
                      bg-[#FF8C42]/10 border border-[#FF8C42]/40 text-[#FF8C42] rounded-sm"
                    data-testid={`skip-date-chip-${d}`}
                  >
                    {d}
                    <button
                      onClick={() => removeSkipDate(d)}
                      className="hover:text-white"
                      data-testid={`skip-date-remove-${d}`}
                    >
                      <XIcon size={10} weight="bold" />
                    </button>
                  </span>
                ))}
              </div>
            )}
          </div>

          <div className="text-[10px] font-mono text-[#71717A] pt-1">
            Don't forget to click <span className="text-[#A1A1AA]">Save</span> at the top to apply skip changes.
          </div>
        </div>

        <div className="panel p-5">
          <div className="section-label mb-3">/ worker status</div>
          <p className="text-xs text-[#A1A1AA] leading-relaxed">
            Workers run on your machines and talk to the same MongoDB:
            <span className="code-tag mx-1">/scraper/</span> for the Windows product scraper,
            <span className="code-tag mx-1">/scraper-ec2/</span> for the Ubuntu label worker.
          </p>
        </div>
      </div>
    </div>
  );
}
