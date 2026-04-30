import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { LinkIcon, PaperPlaneTiltIcon } from "@phosphor-icons/react";
import api, { formatApiError } from "@/lib/api";
import PageHeader from "@/components/PageHeader";

export default function SubmitJobPage() {
  const navigate = useNavigate();
  const [bulkText, setBulkText] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState("");

  const onSubmit = async (e) => {
    e.preventDefault();
    setError("");
    setResult(null);
    const urls = bulkText
      .split(/\n+/)
      .map((s) => s.trim())
      .filter(Boolean);
    if (urls.length === 0) {
      setError("Please paste at least one product URL.");
      return;
    }
    setSubmitting(true);
    try {
      const { data } = await api.post("/jobs/bulk", { product_urls: urls });
      setResult(data);
      if (data.created.length > 0 && data.skipped.length === 0) {
        setTimeout(() => navigate("/jobs"), 900);
      }
    } catch (e) {
      setError(formatApiError(e));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div data-testid="submit-job-page">
      <PageHeader title="ingestion" subtitle="Submit Scraping Jobs" />
      <div className="px-8 py-6 max-w-3xl space-y-6">
        <div className="panel p-6">
          <div className="mb-4 flex items-center gap-2">
            <LinkIcon size={18} weight="bold" color="#007AFF" />
            <div className="font-display text-base font-medium">Product URLs</div>
          </div>
          <p className="text-xs text-[#A1A1AA] mb-4 leading-relaxed">
            Paste one or more Meesho product URLs (one per line). Each will create a{" "}
            <span className="code-tag">pending</span> job for the worker to pick up.
            URLs must contain <span className="code-tag">/p/&lt;product_id&gt;</span>.
          </p>
          <form onSubmit={onSubmit} className="space-y-4">
            <textarea
              rows={8}
              value={bulkText}
              onChange={(e) => setBulkText(e.target.value)}
              placeholder={"https://www.meesho.com/sample-product/p/abc123\nhttps://www.meesho.com/another/p/xyz789"}
              className="input-shell font-mono text-xs leading-relaxed resize-y"
              data-testid="bulk-urls-textarea"
            />
            {error && (
              <div className="border border-[#FF3B30]/30 bg-[#FF3B30]/10 px-3 py-2 font-mono text-xs text-[#FF3B30]" data-testid="submit-error">
                {error}
              </div>
            )}
            <div className="flex items-center gap-3">
              <button
                type="submit"
                disabled={submitting}
                className="btn-primary flex items-center gap-2 text-sm"
                data-testid="submit-jobs-button"
              >
                <PaperPlaneTiltIcon size={14} weight="bold" />
                {submitting ? "Queuing…" : "Queue Jobs"}
              </button>
              <span className="font-mono text-xs text-[#71717A]">
                {bulkText.split(/\n+/).filter((s) => s.trim()).length} url(s)
              </span>
            </div>
          </form>
        </div>

        {result && (
          <div className="panel p-5" data-testid="submit-result">
            <div className="font-display text-sm mb-3">Result</div>
            <div className="grid grid-cols-2 gap-4">
              <div>
                <div className="section-label mb-1">/ created</div>
                <div className="font-mono text-2xl text-[#00E676]">
                  {result.created.length}
                </div>
              </div>
              <div>
                <div className="section-label mb-1">/ skipped</div>
                <div className="font-mono text-2xl text-[#F5A623]">
                  {result.skipped.length}
                </div>
              </div>
            </div>
            {result.skipped.length > 0 && (
              <div className="mt-4">
                <div className="section-label mb-2">/ invalid urls</div>
                <ul className="space-y-1 font-mono text-xs text-[#A1A1AA]">
                  {result.skipped.map((s, i) => (
                    <li key={i} className="truncate">· {s.url}</li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
