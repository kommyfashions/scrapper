import { useEffect, useState } from "react";
import { ClockIcon, ToggleLeftIcon, ToggleRightIcon, FloppyDiskIcon, PlayIcon } from "@phosphor-icons/react";
import api, { formatApiError } from "@/lib/api";
import PageHeader from "@/components/PageHeader";

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

  const load = () => {
    setLoading(true);
    api.get("/settings").then((r) => setData(r.data)).finally(() => setLoading(false));
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
      };
      const { data: updated } = await api.put("/settings", body);
      setData(updated);
      setMsg("Schedule saved.");
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
      setMsg(`${what === "scrape" ? "Scrape" : "Label"} jobs queued.`);
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

        <div className="panel p-5 space-y-4">
          <div className="flex items-center gap-2">
            <ClockIcon size={18} weight="bold" color="#007AFF" />
            <div className="font-display text-base">Daily Product Scrape</div>
          </div>
          <p className="text-xs text-[#A1A1AA]">
            Every day at the time below ({data.timezone}), the backend will enqueue a scrape job for
            each <span className="code-tag">tracked</span> product. Your local worker will pick them
            up whenever it's running.
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
          </div>
        </div>

        <div className="panel p-5 space-y-4">
          <div className="flex items-center gap-2">
            <ClockIcon size={18} weight="bold" color="#F5A623" />
            <div className="font-display text-base">Daily Label Download</div>
          </div>
          <p className="text-xs text-[#A1A1AA]">
            Runs the Meesho supplier-portal automation on your local machine to
            accept pending orders and download shipping labels.
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

        <div className="panel p-5">
          <div className="section-label mb-3">/ worker status</div>
          <p className="text-xs text-[#A1A1AA] leading-relaxed">
            The worker runs on your local Windows machine and talks to the same MongoDB.
            Setup files (batch launcher + Task Scheduler) are provided under <span className="code-tag">/scraper/</span>.
            Once installed, the worker auto-starts on laptop boot and polls the queue continuously.
          </p>
        </div>
      </div>
    </div>
  );
}
