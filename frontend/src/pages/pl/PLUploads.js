import { useEffect, useState, useCallback } from "react";
import { UploadSimpleIcon, ArrowsClockwiseIcon, TrashIcon, FileXlsIcon } from "@phosphor-icons/react";
import api, { formatApiError } from "@/lib/api";
import { usePL, inr } from "./PLLayout";

export default function PLUploads() {
  const { accountId, accounts, reloadAccounts } = usePL();
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [err, setErr] = useState("");
  const [msg, setMsg] = useState("");
  const [pickedAccountId, setPickedAccountId] = useState(accountId !== "all" ? accountId : "");

  useEffect(() => {
    setPickedAccountId(accountId !== "all" ? accountId : "");
  }, [accountId]);

  const load = useCallback(async () => {
    setLoading(true); setErr("");
    try {
      const url = `/pl/uploads${accountId && accountId !== "all" ? `?account_id=${accountId}` : ""}`;
      const { data } = await api.get(url);
      setItems(data.items || []);
    } catch (e) {
      setErr(formatApiError(e));
    } finally { setLoading(false); }
  }, [accountId]);

  useEffect(() => {
    reloadAccounts();
    load();
  }, [load, reloadAccounts]);

  const onUpload = async (file) => {
    if (!file) return;
    if (!pickedAccountId) { setErr("Select an account first."); return; }
    setUploading(true); setErr(""); setMsg("");
    try {
      const fd = new FormData(); fd.append("file", file);
      const { data } = await api.post(`/pl/upload?account_id=${pickedAccountId}`, fd, {
        headers: { "Content-Type": "multipart/form-data" }, timeout: 120000,
      });
      setMsg(`Imported: ${data.inserted} new, ${data.updated} updated, ${data.skipped} skipped, ${data.ads_rows} ad rows`);
      setTimeout(() => setMsg(""), 4000);
      await load();
    } catch (e) {
      setErr(formatApiError(e));
    } finally { setUploading(false); }
  };

  const del = async (id, fn) => {
    if (!window.confirm(`Roll back upload "${fn}"? Orders inserted by this upload will be removed if no other upload covers them.`)) return;
    try {
      await api.delete(`/pl/uploads/${id}`);
      setMsg("Upload rolled back."); setTimeout(() => setMsg(""), 2500);
      await load();
    } catch (e) { setErr(formatApiError(e)); }
  };

  const accName = (id) => accounts.find((a) => a.id === id)?.name || id;

  return (
    <div className="px-8 py-6 space-y-4" data-testid="pl-uploads-page">
      {msg && <div className="border border-[#00E676]/30 bg-[#00E676]/10 px-3 py-2 font-mono text-xs text-[#00E676]" data-testid="pl-upload-msg">{msg}</div>}
      {err && <div className="border border-[#FF3B30]/30 bg-[#FF3B30]/10 px-3 py-2 font-mono text-xs text-[#FF3B30]" data-testid="pl-upload-err">{err}</div>}

      <div className="panel p-5 space-y-4">
        <div className="font-display text-base">Upload Meesho Payment File</div>
        <div className="text-[11px] text-[#A1A1AA]">
          Drop the monthly Meesho payment xlsx (the one with sheets <span className="code-tag">Order Payments</span>,{" "}
          <span className="code-tag">Ads Cost</span>, etc). Re-uploads are idempotent — same file twice = zero net change.
        </div>
        <div className="flex flex-wrap gap-3 items-end">
          <div className="min-w-[200px]">
            <div className="section-label mb-1">/ account</div>
            <select value={pickedAccountId} onChange={(e) => setPickedAccountId(e.target.value)}
              className="input-shell font-mono text-xs w-full" data-testid="pl-upload-account">
              <option value="">Select account…</option>
              {accounts.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
            </select>
          </div>
          <label className={`btn-primary text-xs flex items-center gap-2 cursor-pointer ${(!pickedAccountId || uploading) ? "opacity-50 pointer-events-none" : ""}`}
            data-testid="pl-upload-btn">
            <UploadSimpleIcon size={14} weight="bold" />
            {uploading ? "Uploading…" : "Upload xlsx"}
            <input type="file" accept=".xlsx,.xls" className="hidden" disabled={uploading || !pickedAccountId}
              onChange={(e) => onUpload(e.target.files[0])} data-testid="pl-upload-input" />
          </label>
          <button onClick={load} className="btn-ghost text-xs flex items-center gap-1" data-testid="pl-upload-refresh">
            <ArrowsClockwiseIcon size={12} weight="bold" /> Refresh
          </button>
        </div>
      </div>

      <div className="panel">
        <div className="border-b border-[#2A2A2A] px-5 py-3 flex items-center justify-between">
          <div className="font-display text-sm font-medium">Upload History</div>
          <span className="code-tag">{items.length}</span>
        </div>
        <div className="overflow-x-auto">
          <table className="dense">
            <thead>
              <tr>
                <th>File</th>
                <th>Account</th>
                <th className="num">Inserted</th>
                <th className="num">Updated</th>
                <th className="num">Skipped</th>
                <th className="num">Ads</th>
                <th className="num">Settlement</th>
                <th>Period</th>
                <th>Uploaded</th>
                <th className="text-right">Actions</th>
              </tr>
            </thead>
            <tbody>
              {loading && (
                <tr><td colSpan={10} className="text-center py-8 text-[#71717A] font-mono text-xs">
                  <span className="cursor-blink">LOADING</span>
                </td></tr>
              )}
              {!loading && items.length === 0 && (
                <tr><td colSpan={10} className="text-center py-10 text-[#71717A] text-sm">
                  No uploads yet. Upload your first Meesho payment file above.
                </td></tr>
              )}
              {items.map((u) => (
                <tr key={u.id} data-testid={`pl-upload-row-${u.id}`}>
                  <td className="font-mono text-[11px] flex items-center gap-1">
                    <FileXlsIcon size={12} weight="bold" color="#00E676" />
                    {u.filename}
                  </td>
                  <td className="font-mono text-[10px] text-[#A1A1AA]">{u.account_name || accName(u.account_id)}</td>
                  <td className="num font-mono text-xs text-[#00E676]">{u.inserted ?? "—"}</td>
                  <td className="num font-mono text-xs text-[#007AFF]">{u.updated ?? "—"}</td>
                  <td className="num font-mono text-xs text-[#71717A]">{u.skipped ?? "—"}</td>
                  <td className="num font-mono text-xs text-[#F5A623]">{u.ads_rows ?? 0}</td>
                  <td className="num font-mono text-xs">{u.settlement_total != null ? inr(u.settlement_total) : "—"}</td>
                  <td className="font-mono text-[10px] text-[#71717A]">
                    {u.min_order_date ? `${(u.min_order_date || "").split(" ")[0]} → ${(u.max_order_date || "").split(" ")[0]}` : "—"}
                  </td>
                  <td className="font-mono text-[10px] text-[#A1A1AA]">{new Date(u.uploaded_at).toLocaleString()}</td>
                  <td className="text-right">
                    <button onClick={() => del(u.id, u.filename)}
                      className="btn-ghost text-xs flex items-center gap-1 hover:text-[#FF3B30] ml-auto"
                      data-testid={`pl-upload-del-${u.id}`}>
                      <TrashIcon size={12} weight="bold" /> Roll back
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
