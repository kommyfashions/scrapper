import { useEffect, useState, useCallback } from "react";
import { ArrowsClockwiseIcon, FloppyDiskIcon, TrashIcon, UploadSimpleIcon } from "@phosphor-icons/react";
import api, { formatApiError } from "@/lib/api";
import { usePL, inr } from "./PLLayout";

export default function PLSKUCosts() {
  const { accountId } = usePL();
  const [items, setItems] = useState([]);
  const [missing, setMissing] = useState([]);
  const [newSku, setNewSku] = useState("");
  const [newCost, setNewCost] = useState("");
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState("");
  const [msg, setMsg] = useState("");

  const acctParam = accountId && accountId !== "all" ? `?account_id=${accountId}` : "";

  const load = useCallback(async () => {
    setLoading(true); setErr("");
    try {
      const [c, m] = await Promise.all([
        api.get(`/pl/sku-costs${acctParam}`),
        api.get(`/pl/missing-sku-costs${acctParam}`),
      ]);
      setItems(c.data.items || []);
      setMissing(m.data.missing_skus || []);
    } catch (e) {
      setErr(formatApiError(e));
    } finally { setLoading(false); }
  }, [acctParam]);

  useEffect(() => { load(); }, [load]);

  const upsert = async (sku, cost_price) => {
    setErr(""); setMsg("");
    try {
      await api.post("/pl/sku-costs", {
        sku, cost_price: Number(cost_price),
        account_id: accountId && accountId !== "all" ? accountId : null,
      });
      setMsg(`Saved ${sku}`); setTimeout(() => setMsg(""), 1500);
      await load();
    } catch (e) { setErr(formatApiError(e)); }
  };

  const addNew = async () => {
    if (!newSku.trim() || !newCost) return;
    await upsert(newSku.trim(), newCost);
    setNewSku(""); setNewCost("");
  };

  const del = async (sku) => {
    if (!window.confirm(`Delete cost for ${sku}?`)) return;
    try {
      const p = new URLSearchParams({ sku });
      if (accountId && accountId !== "all") p.append("account_id", accountId);
      await api.delete(`/pl/sku-costs?${p.toString()}`);
      await load();
    } catch (e) { setErr(formatApiError(e)); }
  };

  const onUpload = async (file) => {
    if (!file) return;
    const fd = new FormData(); fd.append("file", file);
    try {
      const url = `/pl/sku-costs/upload-excel${acctParam}`;
      const { data } = await api.post(url, fd, { headers: { "Content-Type": "multipart/form-data" } });
      setMsg(`Imported: ${data.inserted} new, ${data.updated} updated`); setTimeout(() => setMsg(""), 2500);
      await load();
    } catch (e) { setErr(formatApiError(e)); }
  };

  return (
    <div className="px-8 py-6 space-y-4" data-testid="pl-sku-costs-page">
      {accountId === "all" && (
        <div className="border border-[#007AFF]/30 bg-[#007AFF]/10 px-3 py-2 font-mono text-xs text-[#A1A1AA]">
          Costs added with "All Accounts" selected apply globally as a fallback. Select a specific account to override per-account.
        </div>
      )}

      {msg && <div className="border border-[#00E676]/30 bg-[#00E676]/10 px-3 py-2 font-mono text-xs text-[#00E676]" data-testid="pl-cost-msg">{msg}</div>}
      {err && <div className="border border-[#FF3B30]/30 bg-[#FF3B30]/10 px-3 py-2 font-mono text-xs text-[#FF3B30]" data-testid="pl-cost-err">{err}</div>}

      <div className="panel p-5 space-y-3">
        <div className="font-display text-base">Add / Update SKU cost</div>
        <div className="flex flex-wrap gap-2 items-end">
          <div className="flex-1 min-w-[180px]">
            <div className="section-label mb-1">/ sku</div>
            <input value={newSku} onChange={(e) => setNewSku(e.target.value)}
              list="missing-skus-list"
              placeholder="MSS-VTX-BLACK-01"
              className="input-shell font-mono text-xs w-full"
              data-testid="pl-cost-sku-input" />
            <datalist id="missing-skus-list">
              {missing.map((s) => <option key={s} value={s} />)}
            </datalist>
          </div>
          <div className="w-32">
            <div className="section-label mb-1">/ cost (₹)</div>
            <input type="number" step="0.01" value={newCost}
              onChange={(e) => setNewCost(e.target.value)}
              className="input-shell font-mono text-xs w-full"
              data-testid="pl-cost-price-input" />
          </div>
          <button onClick={addNew} className="btn-primary text-xs flex items-center gap-1" data-testid="pl-cost-add">
            <FloppyDiskIcon size={12} weight="bold" /> Save
          </button>
          <label className="btn-secondary text-xs flex items-center gap-1 cursor-pointer" data-testid="pl-cost-upload-label">
            <UploadSimpleIcon size={12} weight="bold" /> Bulk Excel
            <input type="file" accept=".xlsx,.xls" className="hidden"
              onChange={(e) => onUpload(e.target.files[0])} data-testid="pl-cost-upload-input" />
          </label>
          <button onClick={load} className="btn-ghost text-xs flex items-center gap-1" data-testid="pl-cost-refresh">
            <ArrowsClockwiseIcon size={12} weight="bold" /> Refresh
          </button>
        </div>
        <div className="text-[10px] font-mono text-[#71717A]">
          Excel must have columns: <span className="code-tag">SKU</span> and <span className="code-tag">Cost Price</span>.
          Tip: type / paste a SKU above — auto-completes from the {missing.length} SKUs without cost prices.
        </div>
      </div>

      <div className="panel">
        <div className="border-b border-[#2A2A2A] px-5 py-3 flex items-center justify-between">
          <div className="font-display text-sm font-medium">Cost Prices</div>
          <span className="code-tag">{items.length}</span>
        </div>
        <div className="overflow-x-auto">
          <table className="dense">
            <thead>
              <tr>
                <th>SKU</th>
                <th>Account</th>
                <th className="num">Cost Price</th>
                <th className="num">Updated</th>
                <th className="text-right">Actions</th>
              </tr>
            </thead>
            <tbody>
              {loading && (
                <tr><td colSpan={5} className="text-center py-8 text-[#71717A] font-mono text-xs">
                  <span className="cursor-blink">LOADING</span>
                </td></tr>
              )}
              {!loading && items.length === 0 && (
                <tr><td colSpan={5} className="text-center py-10 text-[#71717A] text-sm">
                  No cost prices yet. Add one above.
                </td></tr>
              )}
              {items.map((i) => (
                <tr key={(i.account_id || "global") + i.sku} data-testid={`pl-cost-row-${i.sku}`}>
                  <td className="font-mono text-[11px]">{i.sku}</td>
                  <td className="font-mono text-[10px] text-[#A1A1AA]">
                    {i.account_id ? "—" : <span className="text-[#007AFF]">Global</span>}
                  </td>
                  <td className="num font-mono text-xs">
                    <input type="number" step="0.01" defaultValue={i.cost_price}
                      onBlur={(e) => {
                        if (Number(e.target.value) !== i.cost_price) upsert(i.sku, e.target.value);
                      }}
                      className="input-shell font-mono text-xs w-24 text-right"
                      data-testid={`pl-cost-edit-${i.sku}`} />
                  </td>
                  <td className="num font-mono text-[10px] text-[#71717A]">
                    {i.updated_at ? new Date(i.updated_at).toLocaleDateString() : "—"}
                  </td>
                  <td className="text-right">
                    <button onClick={() => del(i.sku)}
                      className="btn-ghost text-xs flex items-center gap-1 hover:text-[#FF3B30] ml-auto"
                      data-testid={`pl-cost-del-${i.sku}`}>
                      <TrashIcon size={12} weight="bold" /> Delete
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {missing.length > 0 && (
        <div className="panel p-4">
          <div className="section-label mb-2">/ missing cost prices ({missing.length})</div>
          <div className="flex flex-wrap gap-2">
            {missing.slice(0, 50).map((s) => (
              <button key={s} onClick={() => setNewSku(s)}
                className="px-2 py-1 font-mono text-[11px] border border-[#F5A623]/40 text-[#F5A623] bg-[#F5A623]/10 rounded-sm hover:bg-[#F5A623]/20"
                data-testid={`pl-missing-${s}`}>
                {s}
              </button>
            ))}
            {missing.length > 50 && <span className="font-mono text-[10px] text-[#71717A]">+{missing.length - 50} more…</span>}
          </div>
        </div>
      )}
    </div>
  );
}
