import { useEffect, useState, useCallback, useMemo } from "react";
import {
  ArrowsClockwiseIcon, FloppyDiskIcon, TrashIcon, PlusIcon,
  PackageIcon, WarningCircleIcon, XIcon,
} from "@phosphor-icons/react";
import api, { formatApiError } from "@/lib/api";
import { usePL, inr } from "./PLLayout";

const TABS = [
  { k: "articles", label: "Articles", testid: "skucosts-tab-articles" },
  { k: "missing", label: "Missing Articles", testid: "skucosts-tab-missing" },
];

function ArticleForm({ accounts, initial, onSave, onCancel, saving }) {
  const [name, setName] = useState(initial?.name || "");
  const [cost, setCost] = useState(initial?.default_cost_price ?? "");
  const initialMap = useMemo(() => {
    // group sku_map by account_id → list of skus
    const m = {};
    (initial?.sku_map || []).forEach((r) => {
      m[r.account_id] = m[r.account_id] || [];
      // split any comma-separated legacy entries on the way in
      String(r.sku || "").split(",").map((s) => s.trim()).filter(Boolean).forEach((s) => {
        if (!m[r.account_id].includes(s)) m[r.account_id].push(s);
      });
    });
    return m;
  }, [initial]);
  const [skuByAcc, setSkuByAcc] = useState(initialMap);
  const [draftByAcc, setDraftByAcc] = useState({});

  const addChip = (accId) => {
    const v = (draftByAcc[accId] || "").trim();
    if (!v) return;
    const cur = skuByAcc[accId] || [];
    if (cur.includes(v)) { setDraftByAcc({ ...draftByAcc, [accId]: "" }); return; }
    setSkuByAcc({ ...skuByAcc, [accId]: [...cur, v] });
    setDraftByAcc({ ...draftByAcc, [accId]: "" });
  };
  const removeChip = (accId, sku) => {
    setSkuByAcc({ ...skuByAcc, [accId]: (skuByAcc[accId] || []).filter((x) => x !== sku) });
  };

  const onSubmit = (e) => {
    e.preventDefault();
    if (!name.trim()) return;
    // commit any draft input that the user typed but didn't enter
    const finalMap = { ...skuByAcc };
    Object.entries(draftByAcc).forEach(([accId, v]) => {
      const t = (v || "").trim();
      if (t) {
        finalMap[accId] = [...(finalMap[accId] || []), ...(finalMap[accId]?.includes(t) ? [] : [t])];
      }
    });
    const flat = [];
    Object.entries(finalMap).forEach(([accId, list]) => {
      (list || []).forEach((sku) => flat.push({ account_id: accId, sku }));
    });
    onSave({
      name: name.trim(),
      default_cost_price: Number(cost) || 0,
      sku_map: flat,
    });
  };

  return (
    <form onSubmit={onSubmit} className="panel p-4 space-y-3" data-testid="article-form">
      <div className="flex items-center justify-between">
        <div className="font-display text-sm">{initial ? "Edit Article" : "New Article"}</div>
        <button type="button" onClick={onCancel} className="btn-ghost text-xs"><XIcon size={12} weight="bold" /></button>
      </div>
      <div className="grid grid-cols-12 gap-3">
        <div className="col-span-6">
          <div className="section-label mb-1">/ article name</div>
          <input value={name} onChange={(e) => setName(e.target.value)}
            placeholder="e.g. Vertis"
            className="input-shell font-mono text-sm w-full"
            data-testid="article-name-input" required />
        </div>
        <div className="col-span-6">
          <div className="section-label mb-1">/ global cost (INR)</div>
          <input type="number" step="0.01" min="0" value={cost}
            onChange={(e) => setCost(e.target.value)}
            placeholder="110"
            className="input-shell font-mono text-sm w-full"
            data-testid="article-cost-input" required />
        </div>
      </div>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        {accounts.map((a) => {
          const chips = skuByAcc[a.id] || [];
          return (
            <div key={a.id}>
              <div className="section-label mb-1">
                / skus on <span className="text-white">{a.alias || a.name}</span>
                {a.alias && <span className="text-[#71717A]"> ({a.name})</span>}
                <span className="text-[#3F3F46] ml-2">enter ↵ or , to add</span>
              </div>
              <div className="input-shell flex flex-wrap gap-1 min-h-[38px] py-1">
                {chips.map((s) => (
                  <span key={s}
                    className="inline-flex items-center gap-1 bg-[#007AFF]/20 border border-[#007AFF]/40 text-[#7DB9FF] font-mono text-[11px] px-2 py-0.5 rounded-sm"
                    data-testid={`article-chip-${a.id}-${s}`}>
                    {s}
                    <button type="button" onClick={() => removeChip(a.id, s)}
                      className="hover:text-white text-[#7DB9FF]/70">
                      <XIcon size={10} weight="bold" />
                    </button>
                  </span>
                ))}
                <input
                  value={draftByAcc[a.id] || ""}
                  onChange={(e) => {
                    const v = e.target.value;
                    if (v.endsWith(",")) {
                      setDraftByAcc({ ...draftByAcc, [a.id]: v.slice(0, -1) });
                      setTimeout(() => addChip(a.id), 0);
                    } else {
                      setDraftByAcc({ ...draftByAcc, [a.id]: v });
                    }
                  }}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" || e.key === ",") {
                      e.preventDefault(); addChip(a.id);
                    } else if (e.key === "Backspace" && !(draftByAcc[a.id] || "") && chips.length) {
                      removeChip(a.id, chips[chips.length - 1]);
                    }
                  }}
                  placeholder={chips.length ? "" : "leave blank if not sold here"}
                  className="bg-transparent flex-1 min-w-[120px] outline-none font-mono text-xs"
                  data-testid={`article-sku-input-${a.id}`}
                />
              </div>
            </div>
          );
        })}
      </div>
      <div className="flex gap-2 justify-end">
        <button type="button" onClick={onCancel} className="btn-ghost text-xs">Cancel</button>
        <button type="submit" disabled={saving}
          className={`btn-primary text-xs flex items-center gap-1 ${saving ? "opacity-50 pointer-events-none" : ""}`}
          data-testid="article-save-btn">
          <FloppyDiskIcon size={12} weight="bold" /> {saving ? "Saving…" : "Save Article"}
        </button>
      </div>
    </form>
  );
}

function ArticlesTab({ accounts, accountId }) {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState("");
  const [editing, setEditing] = useState(null); // null = closed; "new" or article obj
  const [saving, setSaving] = useState(false);

  // When a specific account is chosen in the PL top-bar, only show that
  // column and filter articles that have a SKU mapped under it.
  const visibleAccounts = useMemo(() => {
    if (!accountId || accountId === "all") return accounts;
    return accounts.filter((a) => a.id === accountId);
  }, [accounts, accountId]);

  const visibleItems = useMemo(() => {
    if (!accountId || accountId === "all") return items;
    return items.filter((art) =>
      (art.sku_map || []).some((m) => m.account_id === accountId)
    );
  }, [items, accountId]);

  const accLookup = useMemo(() => {
    const m = {};
    accounts.forEach((a) => { m[a.id] = a; });
    return m;
  }, [accounts]);

  const load = useCallback(async () => {
    setLoading(true); setErr("");
    try {
      const { data } = await api.get("/pl/articles");
      setItems(data.items || []);
    } catch (e) { setErr(formatApiError(e)); }
    finally { setLoading(false); }
  }, []);

  useEffect(() => { load(); }, [load]);

  const save = async (payload) => {
    setSaving(true); setErr("");
    try {
      if (editing === "new") {
        await api.post("/pl/articles", payload);
      } else {
        await api.put(`/pl/articles/${editing.id}`, payload);
      }
      setEditing(null);
      await load();
    } catch (e) { setErr(formatApiError(e)); }
    finally { setSaving(false); }
  };

  const del = async (id, name) => {
    if (!window.confirm(`Delete article "${name}" and all its SKU mappings? This can't be undone.`)) return;
    try { await api.delete(`/pl/articles/${id}`); await load(); }
    catch (e) { setErr(formatApiError(e)); }
  };

  return (
    <div className="space-y-4" data-testid="articles-tab">
      {err && <div className="border border-[#FF3B30]/30 bg-[#FF3B30]/10 px-3 py-2 font-mono text-xs text-[#FF3B30]">{err}</div>}
      {!editing && (
        <div className="flex items-center justify-between">
          <div className="text-[11px] text-[#A1A1AA]">
            One article = one physical product across all accounts. The <span className="code-tag">Global Cost</span> is the single
            purchase/landing cost used by P&L. Add an SKU for each account that sells it; new accounts you onboard will appear here
            automatically with empty SKU slots.
          </div>
          <button onClick={() => setEditing("new")} className="btn-primary text-xs flex items-center gap-1" data-testid="article-new-btn">
            <PlusIcon size={12} weight="bold" /> New Article
          </button>
        </div>
      )}

      {editing && (
        <ArticleForm
          accounts={accounts}
          initial={editing === "new" ? null : editing}
          onSave={save}
          onCancel={() => setEditing(null)}
          saving={saving}
        />
      )}

      <div className="panel p-0 overflow-hidden">
        <div className="overflow-x-auto">
          <table className="dense">
            <thead>
              <tr>
                <th>Article</th>
                {visibleAccounts.map((a) => (
                  <th key={a.id} className="font-mono text-[10px]">
                    {a.alias || a.name}
                    {a.alias && <span className="text-[#71717A]"> ({a.name})</span>}
                  </th>
                ))}
                <th className="text-right">Global Cost</th>
                <th className="text-right">Actions</th>
              </tr>
            </thead>
            <tbody>
              {loading && <tr><td colSpan={visibleAccounts.length + 3} className="text-center py-10 text-[#71717A]"><span className="cursor-blink">LOADING</span></td></tr>}
              {!loading && visibleItems.length === 0 && (
                <tr><td colSpan={visibleAccounts.length + 3} className="text-center py-10 text-[#71717A] text-sm">
                  {accountId && accountId !== "all"
                    ? "No articles mapped to this account yet. Switch to All Accounts or map SKUs."
                    : (<>No articles yet. Click <span className="code-tag">New Article</span> to get started.</>)}
                </td></tr>
              )}
              {visibleItems.map((art) => {
                const skusOn = (accId) => (art.sku_map || []).filter((x) => x.account_id === accId).map((x) => x.sku);
                return (
                  <tr key={art.id} data-testid={`article-row-${art.id}`}>
                    <td>
                      <div className="flex items-center gap-2">
                        <PackageIcon size={14} color="#00E676" weight="bold" />
                        <span className="font-display text-sm">{art.name}</span>
                      </div>
                    </td>
                    {visibleAccounts.map((a) => {
                      const ss = skusOn(a.id);
                      return (
                        <td key={a.id} className="font-mono text-[11px]">
                          {ss.length === 0 ? (
                            <span className="text-[#3F3F46]">—</span>
                          ) : (
                            <div className="flex flex-wrap gap-1">
                              {ss.map((s) => (
                                <span key={s}
                                  className="bg-[#1F2937] border border-[#2A2A2A] text-white px-1.5 py-0.5 rounded-sm text-[10px]">
                                  {s}
                                </span>
                              ))}
                            </div>
                          )}
                        </td>
                      );
                    })}
                    <td className="text-right font-mono text-sm">{inr(art.default_cost_price)}</td>
                    <td className="text-right">
                      <div className="flex gap-1 justify-end">
                        <button onClick={() => setEditing(art)}
                          className="btn-ghost text-xs" data-testid={`article-edit-${art.id}`}>Edit</button>
                        <button onClick={() => del(art.id, art.name)}
                          className="btn-ghost text-xs hover:text-[#FF3B30]"
                          data-testid={`article-del-${art.id}`}>
                          <TrashIcon size={12} weight="bold" />
                        </button>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

function MissingArticlesTab({ accounts, accountId, onMap }) {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState("");
  const [q, setQ] = useState("");

  const load = useCallback(async () => {
    setLoading(true); setErr("");
    try {
      const { data } = await api.get("/pl/articles/missing-skus");
      setItems(data.items || []);
    } catch (e) { setErr(formatApiError(e)); }
    finally { setLoading(false); }
  }, []);

  useEffect(() => { load(); }, [load]);

  const rows = useMemo(() => {
    const filt = q.trim().toLowerCase();
    let r = items;
    if (accountId && accountId !== "all") {
      r = r.filter((x) => x.account_id === accountId);
    }
    if (!filt) return r;
    return r.filter(
      (x) => x.sku?.toLowerCase().includes(filt) || x.account_name?.toLowerCase().includes(filt)
    );
  }, [items, q, accountId]);

  return (
    <div className="space-y-4" data-testid="missing-tab">
      {err && <div className="border border-[#FF3B30]/30 bg-[#FF3B30]/10 px-3 py-2 font-mono text-xs text-[#FF3B30]">{err}</div>}
      <div className="flex items-center gap-3 flex-wrap">
        <div className="text-[11px] text-[#A1A1AA] flex-1">
          SKUs that have appeared in your payment/order data but aren't mapped to any article yet. Their cost resolves to
          <span className="code-tag text-[#F5A623] ml-1">UNKNOWN</span> in P&L until you map them. Click <span className="code-tag">Map</span> to
          create or attach to an article.
        </div>
        <input value={q} onChange={(e) => setQ(e.target.value)}
          placeholder="Filter by SKU or account…"
          className="input-shell font-mono text-xs min-w-[240px]" data-testid="missing-filter" />
        <button onClick={load} className="btn-ghost text-xs flex items-center gap-1">
          <ArrowsClockwiseIcon size={12} weight="bold" /> Refresh
        </button>
      </div>
      <div className="panel p-0 overflow-hidden">
        <div className="overflow-x-auto">
          <table className="dense">
            <thead>
              <tr>
                <th>SKU</th>
                <th>Account</th>
                <th className="text-right">Orders</th>
                <th>Last seen</th>
                <th className="text-right">Action</th>
              </tr>
            </thead>
            <tbody>
              {loading && <tr><td colSpan={5} className="text-center py-8 text-[#71717A]"><span className="cursor-blink">LOADING</span></td></tr>}
              {!loading && rows.length === 0 && (
                <tr><td colSpan={5} className="text-center py-10 text-[#00E676]">
                  🎉 All SKUs mapped — no missing articles.
                </td></tr>
              )}
              {rows.map((r) => (
                <tr key={`${r.account_id}-${r.sku}`} data-testid={`missing-row-${r.sku}`}>
                  <td className="font-mono text-xs text-white">{r.sku}</td>
                  <td className="font-mono text-[11px] text-[#A1A1AA]">
                    {r.account_alias || r.account_name}
                    {r.account_alias && <span className="text-[#3F3F46] ml-1">({r.account_name})</span>}
                  </td>
                  <td className="text-right font-mono text-xs">{r.orders}</td>
                  <td className="font-mono text-[10px] text-[#71717A]">{r.last_seen ? new Date(r.last_seen).toLocaleDateString() : "—"}</td>
                  <td className="text-right">
                    <button onClick={() => onMap(r)}
                      className="btn-primary text-xs flex items-center gap-1 ml-auto"
                      data-testid={`missing-map-${r.sku}`}>
                      <WarningCircleIcon size={12} weight="bold" /> Map
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

export default function PLSKUCosts() {
  const { accounts, accountId, reloadAccounts } = usePL();
  const [tab, setTab] = useState("articles");
  const [prefill, setPrefill] = useState(null); // {account_id, sku} → open Articles tab in "new" mode with prefill

  useEffect(() => { reloadAccounts(); }, [reloadAccounts]);

  // when user clicks "Map" on a missing row, jump to Articles tab & prefill
  const handleMap = (row) => {
    setPrefill(row);
    setTab("articles");
  };

  return (
    <div className="px-8 py-6 space-y-5" data-testid="pl-sku-costs-page">
      <div className="flex gap-1 border-b border-[#2A2A2A]">
        {TABS.map((t) => (
          <button key={t.k} onClick={() => setTab(t.k)}
            className={`px-4 py-2 font-mono text-[11px] uppercase tracking-wider border-b-2 transition-colors ${
              tab === t.k ? "border-[#007AFF] text-white" : "border-transparent text-[#71717A] hover:text-[#A1A1AA]"
            }`} data-testid={t.testid}>
            {t.label}
          </button>
        ))}
      </div>
      {tab === "articles" && <ArticlesTab accounts={accounts} accountId={accountId} key={(prefill?.sku || "plain") + ":" + (accountId || "all")} />}
      {tab === "missing" && <MissingArticlesTab accounts={accounts} accountId={accountId} onMap={handleMap} />}
    </div>
  );
}
