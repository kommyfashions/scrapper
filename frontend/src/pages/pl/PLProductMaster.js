import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ArrowsClockwiseIcon,
  CaretDownIcon,
  CaretRightIcon,
  DownloadSimpleIcon,
  FloppyDiskIcon,
  MagnifyingGlassIcon,
  PackageIcon,
  PencilSimpleIcon,
  PlusIcon,
  TrashIcon,
  UploadSimpleIcon,
  XIcon,
  FileXlsIcon,
  WarningCircleIcon,
} from "@phosphor-icons/react";
import api, { API, formatApiError } from "@/lib/api";
import { usePL, inr } from "./PLLayout";

const PAGE_SIZES = [25, 50, 100, 200];

// ---------------- Chips input ----------------
function ChipsInput({ value = [], onChange, placeholder, testid }) {
  const [draft, setDraft] = useState("");
  const inputRef = useRef();

  const add = (raw) => {
    const parts = String(raw || "")
      .split(/[,\n;|]+/)
      .map((s) => s.trim())
      .filter(Boolean);
    if (!parts.length) return;
    const next = [...value];
    parts.forEach((p) => {
      if (!next.some((x) => x.toLowerCase() === p.toLowerCase())) next.push(p);
    });
    onChange(next);
    setDraft("");
  };

  const removeAt = (idx) => {
    const next = value.filter((_, i) => i !== idx);
    onChange(next);
  };

  return (
    <div
      className="input-shell flex flex-wrap gap-1 min-h-[38px] py-1 cursor-text"
      onClick={() => inputRef.current?.focus()}
      data-testid={testid}
    >
      {value.map((v, i) => (
        <span key={`${v}-${i}`} className="chip chip-accent">
          {v}
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              removeAt(i);
            }}
            className="opacity-70 hover:opacity-100"
          >
            <XIcon size={10} weight="bold" />
          </button>
        </span>
      ))}
      <input
        ref={inputRef}
        value={draft}
        onChange={(e) => {
          const v = e.target.value;
          if (/[,\n]/.test(v)) {
            add(v);
          } else {
            setDraft(v);
          }
        }}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === ",") {
            e.preventDefault();
            add(draft);
          } else if (e.key === "Backspace" && !draft && value.length) {
            removeAt(value.length - 1);
          }
        }}
        onBlur={() => draft && add(draft)}
        placeholder={value.length ? "" : placeholder || "Type & press Enter"}
        className="bg-transparent flex-1 min-w-[120px] outline-none font-mono text-xs"
      />
    </div>
  );
}

// ---------------- Product form (create/edit) ----------------
function ProductForm({ accounts, initial, onSave, onCancel, saving, err }) {
  const [accountId, setAccountId] = useState(initial?.account_id || "");
  const [mainCategory, setMainCategory] = useState(initial?.main_category || "");
  const [color, setColor] = useState(initial?.color || "");
  const [costPrice, setCostPrice] = useState(
    initial?.cost_price !== undefined ? String(initial.cost_price) : ""
  );
  const [skus, setSkus] = useState(initial?.skus || []);
  const [sizes, setSizes] = useState(initial?.sizes || []);

  const submit = (e) => {
    e.preventDefault();
    onSave({
      account_id: accountId,
      main_category: mainCategory.trim(),
      color: color.trim(),
      cost_price: Number(costPrice) || 0,
      skus,
      sizes,
    });
  };

  return (
    <form onSubmit={submit} className="panel p-5 space-y-4" data-testid="pm-form">
      <div className="flex items-center justify-between">
        <h3 className="font-display text-lg">
          {initial ? "Edit Product" : "New Product"}
        </h3>
        <button type="button" onClick={onCancel} className="btn-ghost">
          <XIcon size={14} weight="bold" />
        </button>
      </div>
      {err && (
        <div className="border border-[rgba(239,68,68,0.35)] bg-[rgba(239,68,68,0.1)] px-3 py-2 font-mono text-xs text-[#FCA5A5]">
          {err}
        </div>
      )}
      <div className="grid grid-cols-12 gap-3">
        <div className="col-span-4">
          <div className="section-label mb-1">/ account</div>
          <select
            className="input-shell font-mono text-sm"
            value={accountId}
            onChange={(e) => setAccountId(e.target.value)}
            required
            data-testid="pm-form-account"
          >
            <option value="">Select account…</option>
            {accounts.map((a) => (
              <option key={a.id} value={a.id}>
                {a.alias ? `${a.alias} (${a.name})` : a.name}
              </option>
            ))}
          </select>
        </div>
        <div className="col-span-4">
          <div className="section-label mb-1">/ main category</div>
          <input
            value={mainCategory}
            onChange={(e) => setMainCategory(e.target.value)}
            placeholder="Vertis, Sofia, Aliya…"
            className="input-shell font-mono text-sm"
            required
            data-testid="pm-form-category"
          />
        </div>
        <div className="col-span-4">
          <div className="section-label mb-1">/ color</div>
          <input
            value={color}
            onChange={(e) => setColor(e.target.value)}
            placeholder="Blue, Black…"
            className="input-shell font-mono text-sm"
            required
            data-testid="pm-form-color"
          />
        </div>
        <div className="col-span-4">
          <div className="section-label mb-1">/ landing cost (INR)</div>
          <input
            type="number"
            step="0.01"
            min="0"
            value={costPrice}
            onChange={(e) => setCostPrice(e.target.value)}
            placeholder="110"
            className="input-shell font-mono text-sm"
            required
            data-testid="pm-form-cost"
          />
        </div>
        <div className="col-span-4">
          <div className="section-label mb-1">/ sizes</div>
          <ChipsInput
            value={sizes}
            onChange={setSizes}
            placeholder="IND-3, IND-4…"
            testid="pm-form-sizes"
          />
        </div>
        <div className="col-span-4">
          <div className="section-label mb-1">/ skus</div>
          <ChipsInput
            value={skus}
            onChange={setSkus}
            placeholder="SKU1, SKU2…"
            testid="pm-form-skus"
          />
        </div>
      </div>
      <div className="flex gap-2 justify-end">
        <button type="button" onClick={onCancel} className="btn-secondary text-xs">
          Cancel
        </button>
        <button
          type="submit"
          disabled={saving}
          className="btn-primary text-xs flex items-center gap-1"
          data-testid="pm-form-save"
        >
          <FloppyDiskIcon size={12} weight="bold" />
          {saving ? "Saving…" : "Save"}
        </button>
      </div>
    </form>
  );
}

// ---------------- Upload dialog ----------------
function UploadDialog({ onClose, onCompleted }) {
  const [file, setFile] = useState(null);
  const [plan, setPlan] = useState(null);
  const [token, setToken] = useState(null);
  const [skipConfirm, setSkipConfirm] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  const doUpload = async () => {
    if (!file) return;
    setBusy(true); setErr("");
    try {
      const fd = new FormData();
      fd.append("file", file);
      const url = `/pm/upload?skip_confirmation=${skipConfirm}`;
      const { data } = await api.post(url, fd, {
        headers: { "Content-Type": "multipart/form-data" },
      });
      if (data.committed) {
        onCompleted(data);
        onClose();
      } else {
        setPlan(data.plan);
        setToken(data.parse_token);
      }
    } catch (e) {
      setErr(formatApiError(e));
    } finally {
      setBusy(false);
    }
  };

  const confirmCommit = async () => {
    setBusy(true); setErr("");
    try {
      const { data } = await api.post("/pm/upload/commit", {
        parse_token: token,
        upload_source: file?.name || "excel-upload",
      });
      onCompleted(data);
      onClose();
    } catch (e) {
      setErr(formatApiError(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div
      className="fixed inset-0 bg-black/70 backdrop-blur-sm z-50 flex items-center justify-center p-6"
      data-testid="pm-upload-dialog"
    >
      <div className="panel w-full max-w-4xl max-h-[85vh] flex flex-col overflow-hidden">
        <div className="flex items-center justify-between px-6 py-4 border-b border-[var(--border)]">
          <div>
            <h3 className="font-display text-lg">Excel Upload</h3>
            <div className="text-xs text-[var(--text-muted)] mt-0.5">
              Columns: <span className="code-tag">Account · Main Category · Color · Size · SKU · Cost</span>
            </div>
          </div>
          <button onClick={onClose} className="btn-ghost">
            <XIcon size={16} weight="bold" />
          </button>
        </div>
        <div className="flex-1 overflow-y-auto p-6 space-y-4">
          {err && (
            <div className="border border-[rgba(239,68,68,0.35)] bg-[rgba(239,68,68,0.1)] px-3 py-2 font-mono text-xs text-[#FCA5A5]">
              {err}
            </div>
          )}
          {!plan && (
            <div className="space-y-4">
              <div className="flex items-center gap-3">
                <label className="btn-secondary text-xs flex items-center gap-2 cursor-pointer">
                  <FileXlsIcon size={14} weight="bold" />
                  <span>{file ? file.name : "Choose .xlsx file"}</span>
                  <input
                    type="file"
                    accept=".xlsx,.xls"
                    className="hidden"
                    onChange={(e) => setFile(e.target.files?.[0] || null)}
                    data-testid="pm-upload-file"
                  />
                </label>
                <a
                  href={`${API}/pm/template`}
                  className="btn-ghost text-xs flex items-center gap-1"
                  data-testid="pm-upload-template"
                >
                  <DownloadSimpleIcon size={12} weight="bold" /> Download template
                </a>
              </div>
              <label className="flex items-center gap-2 text-xs text-[var(--text-secondary)] cursor-pointer">
                <input
                  type="checkbox"
                  checked={skipConfirm}
                  onChange={(e) => setSkipConfirm(e.target.checked)}
                  data-testid="pm-upload-skip"
                />
                Skip confirmation (commit immediately)
              </label>
            </div>
          )}

          {plan && (
            <div className="space-y-4">
              <div className="grid grid-cols-4 gap-2">
                <SummaryCell label="Inserted" value={plan.inserted} color="text-[#6EE7B7]" testid="pm-plan-inserted" />
                <SummaryCell label="Updated" value={plan.updated} color="text-[#FCD34D]" testid="pm-plan-updated" />
                <SummaryCell label="Skipped" value={plan.skipped} color="text-[var(--text-muted)]" testid="pm-plan-skipped" />
                <SummaryCell label="Errors" value={(plan.errors || []).length} color="text-[#FCA5A5]" testid="pm-plan-errors" />
              </div>
              {plan.unknown_accounts?.length > 0 && (
                <div className="border border-[rgba(245,158,11,0.35)] bg-[rgba(245,158,11,0.1)] p-3 rounded">
                  <div className="text-xs font-semibold text-[#FCD34D] mb-1">Unknown accounts (rows will be skipped)</div>
                  <div className="flex flex-wrap gap-1">
                    {plan.unknown_accounts.map((a) => (
                      <span key={a} className="chip chip-warn">{a}</span>
                    ))}
                  </div>
                </div>
              )}
              {plan.sku_clashes?.length > 0 && (
                <div className="border border-[rgba(56,189,248,0.35)] bg-[rgba(56,189,248,0.1)] p-3 rounded text-xs space-y-1">
                  <div className="font-semibold text-[#7DD3FC]">SKUs will be moved</div>
                  {plan.sku_clashes.slice(0, 10).map((c, i) => (
                    <div key={i} className="font-mono text-[11px]">
                      <span className="text-white">{c.sku}</span>{" "}
                      moves from{" "}
                      <span className="chip">{c.already_on.main_category} / {c.already_on.color}</span>
                      {" → "}
                      <span className="chip chip-accent">
                        {c.attempting_to_move_to.main_category} / {c.attempting_to_move_to.color}
                      </span>
                    </div>
                  ))}
                  {plan.sku_clashes.length > 10 && (
                    <div className="text-[var(--text-muted)]">
                      … and {plan.sku_clashes.length - 10} more
                    </div>
                  )}
                </div>
              )}
              {plan.errors?.length > 0 && (
                <div className="border border-[rgba(239,68,68,0.35)] bg-[rgba(239,68,68,0.05)] p-3 rounded text-xs">
                  <div className="font-semibold text-[#FCA5A5] mb-1">Validation errors</div>
                  <div className="space-y-0.5 max-h-32 overflow-y-auto">
                    {plan.errors.slice(0, 20).map((e, i) => (
                      <div key={i} className="font-mono text-[11px]">
                        Row {e.row}: {e.errors.join(", ")}
                      </div>
                    ))}
                  </div>
                </div>
              )}

              <div>
                <div className="section-label mb-1">/ diffs ({plan.diffs?.length || 0})</div>
                <div className="table-wrap max-h-72">
                  <table className="dense">
                    <thead>
                      <tr>
                        <th>Action</th>
                        <th>Account</th>
                        <th>Category</th>
                        <th>Color</th>
                        <th className="num">Cost</th>
                        <th>Sizes</th>
                        <th>SKUs</th>
                      </tr>
                    </thead>
                    <tbody>
                      {(plan.diffs || []).map((d, i) => (
                        <tr key={i}>
                          <td>
                            <span
                              className={
                                "chip " +
                                (d.action === "insert"
                                  ? "chip-accent"
                                  : "chip-warn")
                              }
                            >
                              {d.action}
                            </span>
                          </td>
                          <td className="font-mono text-[11px]">{d.account}</td>
                          <td>{d.main_category}</td>
                          <td>{d.color}</td>
                          <td className="num font-mono text-xs">
                            {d.cost_before ?? "—"} → {d.cost_after}
                          </td>
                          <td className="font-mono text-[11px]">{(d.sizes_after || []).join(", ")}</td>
                          <td className="font-mono text-[11px]">{(d.skus_after || []).join(", ")}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            </div>
          )}
        </div>
        <div className="border-t border-[var(--border)] px-6 py-3 flex items-center justify-end gap-2">
          <button onClick={onClose} className="btn-secondary text-xs">
            Cancel
          </button>
          {!plan && (
            <button
              disabled={!file || busy}
              onClick={doUpload}
              className="btn-primary text-xs flex items-center gap-1"
              data-testid="pm-upload-submit"
            >
              <UploadSimpleIcon size={12} weight="bold" />
              {busy ? "Parsing…" : "Upload & Preview"}
            </button>
          )}
          {plan && (
            <button
              disabled={busy}
              onClick={confirmCommit}
              className="btn-primary text-xs flex items-center gap-1"
              data-testid="pm-upload-confirm"
            >
              <FloppyDiskIcon size={12} weight="bold" />
              {busy ? "Committing…" : "Confirm & Commit"}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

function SummaryCell({ label, value, color, testid }) {
  return (
    <div className="panel p-3 text-center" data-testid={testid}>
      <div className={`font-display text-2xl ${color}`}>{value}</div>
      <div className="section-label mt-1">{label}</div>
    </div>
  );
}

// ---------------- Chips display ----------------
function ChipList({ items, max = 6, kind = "" }) {
  if (!items?.length) return <span className="text-[var(--text-muted)]">—</span>;
  const shown = items.slice(0, max);
  const rest = items.length - shown.length;
  return (
    <div className="flex flex-wrap gap-1">
      {shown.map((s) => (
        <span key={s} className={`chip ${kind}`}>{s}</span>
      ))}
      {rest > 0 && <span className="chip">+{rest}</span>}
    </div>
  );
}

// ---------------- Main page ----------------
export default function PLProductMaster() {
  const { accounts, accountId, reloadAccounts } = usePL();
  const [items, setItems] = useState([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(50);
  const [sort, setSort] = useState("updated_at");
  const [order, setOrder] = useState("desc");
  const [q, setQ] = useState("");
  const [filters, setFilters] = useState({
    main_category: "",
    color: "",
    has_sku: "",
    has_cost: "",
    cost_min: "",
    cost_max: "",
  });
  const [facets, setFacets] = useState({ categories: [], colors: [] });
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState("");
  const [expanded, setExpanded] = useState({});
  const [selected, setSelected] = useState({});
  const [editing, setEditing] = useState(null); // "new" | product obj
  const [formErr, setFormErr] = useState("");
  const [saving, setSaving] = useState(false);
  const [showUpload, setShowUpload] = useState(false);

  const params = useMemo(() => {
    const p = new URLSearchParams();
    if (accountId && accountId !== "all") p.append("account_id", accountId);
    if (filters.main_category) p.append("main_category", filters.main_category);
    if (filters.color) p.append("color", filters.color);
    if (filters.has_sku !== "") p.append("has_sku", filters.has_sku);
    if (filters.has_cost !== "") p.append("has_cost", filters.has_cost);
    if (filters.cost_min !== "") p.append("cost_min", filters.cost_min);
    if (filters.cost_max !== "") p.append("cost_max", filters.cost_max);
    if (q.trim()) p.append("q", q.trim());
    p.append("sort", sort);
    p.append("order", order);
    p.append("page", String(page));
    p.append("page_size", String(pageSize));
    return p;
  }, [accountId, filters, q, sort, order, page, pageSize]);

  const load = useCallback(async () => {
    setLoading(true); setErr("");
    try {
      const { data } = await api.get(`/pm/products?${params.toString()}`);
      setItems(data.items || []);
      setTotal(data.total || 0);
    } catch (e) {
      setErr(formatApiError(e));
    } finally {
      setLoading(false);
    }
  }, [params]);

  const loadFacets = useCallback(async () => {
    try {
      const { data } = await api.get("/pm/facets");
      setFacets({ categories: data.categories || [], colors: data.colors || [] });
    } catch (_) { /* facets are best-effort */ }
  }, []);

  useEffect(() => { reloadAccounts(); loadFacets(); }, [reloadAccounts, loadFacets]);
  useEffect(() => { load(); }, [load]);

  const toggleSort = (field) => {
    if (sort === field) {
      setOrder(order === "asc" ? "desc" : "asc");
    } else {
      setSort(field); setOrder("asc");
    }
  };

  const toggleExpand = (id) => setExpanded((s) => ({ ...s, [id]: !s[id] }));
  const toggleSel = (id) => setSelected((s) => ({ ...s, [id]: !s[id] }));
  const selectedIds = useMemo(() => Object.keys(selected).filter((k) => selected[k]), [selected]);

  const bulkDelete = async () => {
    if (!selectedIds.length) return;
    if (!window.confirm(`Delete ${selectedIds.length} products? Cannot be undone.`)) return;
    try {
      await api.post("/pm/bulk-delete", { ids: selectedIds });
      setSelected({});
      await load();
      await loadFacets();
    } catch (e) {
      setErr(formatApiError(e));
    }
  };

  const saveProduct = async (payload) => {
    setSaving(true); setFormErr("");
    try {
      if (editing === "new") {
        await api.post("/pm/products", payload);
      } else {
        await api.put(`/pm/products/${editing.id}`, payload);
      }
      setEditing(null);
      await load();
      await loadFacets();
    } catch (e) {
      setFormErr(formatApiError(e));
    } finally {
      setSaving(false);
    }
  };

  const delProduct = async (p) => {
    if (!window.confirm(`Delete ${p.main_category} / ${p.color}?`)) return;
    try {
      await api.delete(`/pm/products/${p.id}`);
      await load();
      await loadFacets();
    } catch (e) {
      setErr(formatApiError(e));
    }
  };

  const exportUrl = `${API}/pm/export?${params.toString()}`;

  const clearFilters = () => {
    setFilters({
      main_category: "",
      color: "",
      has_sku: "",
      has_cost: "",
      cost_min: "",
      cost_max: "",
    });
    setQ("");
    setPage(1);
  };

  const totalPages = Math.max(1, Math.ceil(total / pageSize));

  return (
    <div className="px-8 py-6 space-y-5" data-testid="pl-product-master-page">
      {err && (
        <div className="border border-[rgba(239,68,68,0.35)] bg-[rgba(239,68,68,0.1)] px-3 py-2 font-mono text-xs text-[#FCA5A5]">
          {err}
        </div>
      )}

      {editing && (
        <ProductForm
          accounts={accounts}
          initial={editing === "new" ? null : editing}
          onSave={saveProduct}
          onCancel={() => { setEditing(null); setFormErr(""); }}
          saving={saving}
          err={formErr}
        />
      )}

      {showUpload && (
        <UploadDialog
          onClose={() => setShowUpload(false)}
          onCompleted={() => { load(); loadFacets(); }}
        />
      )}

      <div className="flex flex-wrap items-center gap-2 justify-between">
        <div className="flex items-center gap-2">
          <PackageIcon size={22} weight="bold" color="#10B981" />
          <div>
            <h2 className="font-display text-xl">Product Master</h2>
            <div className="text-xs text-[var(--text-muted)]">
              Single source of truth for every product across all accounts.
            </div>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <button
            onClick={() => setShowUpload(true)}
            className="btn-secondary text-xs flex items-center gap-1"
            data-testid="pm-btn-upload"
          >
            <UploadSimpleIcon size={12} weight="bold" /> Upload Excel
          </button>
          <a
            href={exportUrl}
            className="btn-secondary text-xs flex items-center gap-1"
            data-testid="pm-btn-export"
          >
            <DownloadSimpleIcon size={12} weight="bold" /> Export
          </a>
          <button
            onClick={() => { setEditing("new"); setFormErr(""); }}
            className="btn-primary text-xs flex items-center gap-1"
            data-testid="pm-btn-new"
          >
            <PlusIcon size={12} weight="bold" /> New Product
          </button>
        </div>
      </div>

      {/* Search & Filters */}
      <div className="panel p-4 space-y-3">
        <div className="flex flex-wrap gap-3 items-end">
          <div className="flex-1 min-w-[240px]">
            <div className="section-label mb-1">/ search</div>
            <div className="relative">
              <MagnifyingGlassIcon
                size={14}
                weight="bold"
                className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--text-muted)]"
              />
              <input
                value={q}
                onChange={(e) => { setQ(e.target.value); setPage(1); }}
                placeholder="SKU, category, color, account, cost…"
                className="input-shell font-mono text-sm pl-8"
                data-testid="pm-search-input"
              />
            </div>
          </div>
          <div>
            <div className="section-label mb-1">/ category</div>
            <select
              value={filters.main_category}
              onChange={(e) => { setFilters({ ...filters, main_category: e.target.value }); setPage(1); }}
              className="input-shell font-mono text-sm min-w-[140px]"
              data-testid="pm-filter-category"
            >
              <option value="">Any</option>
              {facets.categories.map((c) => <option key={c} value={c}>{c}</option>)}
            </select>
          </div>
          <div>
            <div className="section-label mb-1">/ color</div>
            <select
              value={filters.color}
              onChange={(e) => { setFilters({ ...filters, color: e.target.value }); setPage(1); }}
              className="input-shell font-mono text-sm min-w-[120px]"
              data-testid="pm-filter-color"
            >
              <option value="">Any</option>
              {facets.colors.map((c) => <option key={c} value={c}>{c}</option>)}
            </select>
          </div>
          <div>
            <div className="section-label mb-1">/ skus</div>
            <select
              value={filters.has_sku}
              onChange={(e) => { setFilters({ ...filters, has_sku: e.target.value }); setPage(1); }}
              className="input-shell font-mono text-sm min-w-[110px]"
              data-testid="pm-filter-hassku"
            >
              <option value="">Any</option>
              <option value="true">Has SKUs</option>
              <option value="false">Missing SKUs</option>
            </select>
          </div>
          <div>
            <div className="section-label mb-1">/ cost min</div>
            <input
              type="number"
              value={filters.cost_min}
              onChange={(e) => { setFilters({ ...filters, cost_min: e.target.value }); setPage(1); }}
              className="input-shell font-mono text-sm w-24"
              data-testid="pm-filter-costmin"
            />
          </div>
          <div>
            <div className="section-label mb-1">/ cost max</div>
            <input
              type="number"
              value={filters.cost_max}
              onChange={(e) => { setFilters({ ...filters, cost_max: e.target.value }); setPage(1); }}
              className="input-shell font-mono text-sm w-24"
              data-testid="pm-filter-costmax"
            />
          </div>
          <button onClick={clearFilters} className="btn-ghost text-xs" data-testid="pm-filter-clear">
            Clear
          </button>
          <button onClick={load} className="btn-ghost text-xs flex items-center gap-1" data-testid="pm-btn-refresh">
            <ArrowsClockwiseIcon size={12} weight="bold" /> Refresh
          </button>
        </div>
        {selectedIds.length > 0 && (
          <div className="flex items-center justify-between border-t border-[var(--border-soft)] pt-3">
            <div className="text-xs text-[var(--text-secondary)]">
              {selectedIds.length} selected
            </div>
            <button
              onClick={bulkDelete}
              className="btn-danger text-xs flex items-center gap-1"
              data-testid="pm-bulk-delete"
            >
              <TrashIcon size={12} weight="bold" /> Delete selected
            </button>
          </div>
        )}
      </div>

      {/* Table */}
      <div className="table-wrap">
        <table className="dense">
          <thead>
            <tr>
              <th style={{ width: 30 }}>
                <input
                  type="checkbox"
                  onChange={(e) => {
                    const on = e.target.checked;
                    const next = {};
                    if (on) items.forEach((p) => { next[p.id] = true; });
                    setSelected(next);
                  }}
                  data-testid="pm-select-all"
                />
              </th>
              <th style={{ width: 30 }}></th>
              <SortableHead label="Category" field="main_category" sort={sort} order={order} onClick={toggleSort} />
              <SortableHead label="Color" field="color" sort={sort} order={order} onClick={toggleSort} />
              <th>Account</th>
              <th>Sizes</th>
              <th>SKUs</th>
              <SortableHead label="Cost" field="cost_price" sort={sort} order={order} onClick={toggleSort} className="num" />
              <SortableHead label="Updated" field="updated_at" sort={sort} order={order} onClick={toggleSort} />
              <th className="text-right">Actions</th>
            </tr>
          </thead>
          <tbody>
            {loading && (
              <tr>
                <td colSpan={10} className="text-center py-10 text-[var(--text-muted)]">
                  <span className="cursor-blink">LOADING</span>
                </td>
              </tr>
            )}
            {!loading && items.length === 0 && (
              <tr>
                <td colSpan={10} className="text-center py-10 text-[var(--text-muted)] text-sm">
                  No products match. Upload an Excel or add one manually.
                </td>
              </tr>
            )}
            {!loading && items.map((p) => (
              <ProductRow
                key={p.id}
                p={p}
                expanded={!!expanded[p.id]}
                onToggle={() => toggleExpand(p.id)}
                selected={!!selected[p.id]}
                onSel={() => toggleSel(p.id)}
                onEdit={() => { setEditing(p); setFormErr(""); }}
                onDelete={() => delProduct(p)}
              />
            ))}
          </tbody>
        </table>
      </div>

      {/* Pagination */}
      <div className="flex items-center justify-between text-xs">
        <div className="text-[var(--text-muted)]">
          {total.toLocaleString()} product{total !== 1 ? "s" : ""}
        </div>
        <div className="flex items-center gap-2">
          <select
            value={pageSize}
            onChange={(e) => { setPageSize(Number(e.target.value)); setPage(1); }}
            className="input-shell font-mono text-xs w-20"
            data-testid="pm-page-size"
          >
            {PAGE_SIZES.map((s) => <option key={s} value={s}>{s}/page</option>)}
          </select>
          <button
            disabled={page <= 1}
            onClick={() => setPage((p) => Math.max(1, p - 1))}
            className="btn-ghost text-xs disabled:opacity-30"
            data-testid="pm-page-prev"
          >
            Prev
          </button>
          <span className="font-mono">
            {page} / {totalPages}
          </span>
          <button
            disabled={page >= totalPages}
            onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
            className="btn-ghost text-xs disabled:opacity-30"
            data-testid="pm-page-next"
          >
            Next
          </button>
        </div>
      </div>
    </div>
  );
}

function SortableHead({ label, field, sort, order, onClick, className = "" }) {
  const active = sort === field;
  return (
    <th
      onClick={() => onClick(field)}
      className={`cursor-pointer select-none ${className}`}
    >
      <span className={active ? "text-[var(--accent)]" : ""}>{label}</span>
      {active && <span className="ml-1">{order === "asc" ? "▲" : "▼"}</span>}
    </th>
  );
}

function ProductRow({ p, expanded, onToggle, selected, onSel, onEdit, onDelete }) {
  const missing = (!p.skus || !p.skus.length) ? "no-sku" : "";
  return (
    <>
      <tr data-testid={`pm-row-${p.id}`} className={missing ? "" : ""}>
        <td>
          <input type="checkbox" checked={selected} onChange={onSel} data-testid={`pm-sel-${p.id}`} />
        </td>
        <td>
          <button onClick={onToggle} className="btn-ghost" data-testid={`pm-expand-${p.id}`}>
            {expanded ? <CaretDownIcon size={12} weight="bold" /> : <CaretRightIcon size={12} weight="bold" />}
          </button>
        </td>
        <td className="font-medium">{p.main_category}</td>
        <td>{p.color}</td>
        <td className="text-xs">
          <span>{p.account_alias || p.account_name || "—"}</span>
        </td>
        <td><ChipList items={p.sizes} max={5} /></td>
        <td>
          {(!p.skus || !p.skus.length) ? (
            <span className="chip chip-warn">
              <WarningCircleIcon size={10} weight="bold" /> No SKU assigned
            </span>
          ) : (
            <ChipList items={p.skus} max={5} kind="chip-accent" />
          )}
        </td>
        <td className="num font-mono">{inr(p.cost_price)}</td>
        <td className="text-xs text-[var(--text-muted)]">
          {p.updated_at ? new Date(p.updated_at).toLocaleDateString() : "—"}
        </td>
        <td className="text-right">
          <div className="flex gap-1 justify-end">
            <button onClick={onEdit} className="btn-ghost text-xs" data-testid={`pm-edit-${p.id}`}>
              <PencilSimpleIcon size={12} weight="bold" />
            </button>
            <button onClick={onDelete} className="btn-ghost text-xs hover:text-[var(--status-failed)]" data-testid={`pm-del-${p.id}`}>
              <TrashIcon size={12} weight="bold" />
            </button>
          </div>
        </td>
      </tr>
      {expanded && (
        <tr className="bg-[var(--bg-surface-2)]" data-testid={`pm-expand-panel-${p.id}`}>
          <td colSpan={10} className="p-4">
            <div className="grid grid-cols-4 gap-4 text-xs">
              <div>
                <div className="section-label mb-1">/ product id</div>
                <div className="font-mono text-[11px]">{p.id}</div>
              </div>
              <div>
                <div className="section-label mb-1">/ account</div>
                <div>{p.account_name} {p.account_alias ? `(${p.account_alias})` : ""}</div>
              </div>
              <div>
                <div className="section-label mb-1">/ created</div>
                <div>{p.created_at ? new Date(p.created_at).toLocaleString() : "—"}</div>
              </div>
              <div>
                <div className="section-label mb-1">/ upload source</div>
                <div className="font-mono text-[11px]">{p.upload_source || "manual"}</div>
              </div>
              <div className="col-span-2">
                <div className="section-label mb-1">/ all sizes ({p.sizes?.length || 0})</div>
                <ChipList items={p.sizes} max={999} />
              </div>
              <div className="col-span-2">
                <div className="section-label mb-1">/ all skus ({p.skus?.length || 0})</div>
                <ChipList items={p.skus} max={999} kind="chip-accent" />
              </div>
            </div>
          </td>
        </tr>
      )}
    </>
  );
}
