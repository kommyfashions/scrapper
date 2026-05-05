import { useEffect, useState, useCallback } from "react";
import {
  UserCircleIcon,
  PlusCircleIcon,
  PencilSimpleIcon,
  TrashIcon,
  ArrowsClockwiseIcon,
  XIcon,
  ToggleLeftIcon,
  ToggleRightIcon,
} from "@phosphor-icons/react";
import api, { formatApiError } from "@/lib/api";
import PageHeader from "@/components/PageHeader";
import { fmtRelative } from "@/lib/format";

const EMPTY = { name: "", alias: "", debug_port: 9222, profile_dir: "", enabled: true };

function AccountModal({ open, account, onClose, onSaved }) {
  const editing = !!account?.id;
  const [form, setForm] = useState(EMPTY);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  useEffect(() => {
    if (!open) return;
    setErr("");
    if (editing) {
      setForm({
        name: account.name || "",
        alias: account.alias || "",
        debug_port: account.debug_port || 9222,
        profile_dir: account.profile_dir || "",
        enabled: account.enabled ?? true,
      });
    } else {
      // pull suggested defaults from backend
      api.get("/accounts/defaults")
        .then((r) => setForm({ ...EMPTY, ...r.data }))
        .catch(() => setForm(EMPTY));
    }
  }, [open, account, editing]);

  if (!open) return null;

  const save = async () => {
    setBusy(true); setErr("");
    try {
      const body = {
        name: form.name.trim(),
        alias: (form.alias || "").trim() || null,
        debug_port: Number(form.debug_port),
        profile_dir: form.profile_dir.trim(),
        enabled: form.enabled,
      };
      if (!body.name) throw new Error("Name is required");
      if (!body.profile_dir) throw new Error("Profile dir is required");
      if (!body.debug_port) throw new Error("Debug port is required");
      if (editing) {
        await api.put(`/accounts/${account.id}`, body);
      } else {
        await api.post("/accounts", body);
      }
      onSaved();
    } catch (e) {
      setErr(e?.message || formatApiError(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm"
      onClick={onClose}
      data-testid="account-modal"
    >
      <div
        className="panel w-[480px] max-w-[92vw] p-6 space-y-4"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between">
          <div>
            <div className="section-label mb-1">/ {editing ? "edit" : "new"} account</div>
            <h2 className="font-display text-xl">
              {editing ? form.name || "Account" : "Add Meesho Account"}
            </h2>
          </div>
          <button onClick={onClose} className="btn-ghost" data-testid="account-modal-close">
            <XIcon size={16} weight="bold" />
          </button>
        </div>

        {err && (
          <div className="border border-[#FF3B30]/30 bg-[#FF3B30]/10 px-3 py-2 font-mono text-xs text-[#FF3B30]"
            data-testid="account-form-err">{err}</div>
        )}

        <div>
          <div className="section-label mb-1">/ name (account suffix e.g. uobfs)</div>
          <input
            value={form.name}
            onChange={(e) => setForm({ ...form, name: e.target.value })}
            placeholder="uobfs"
            className="input-shell font-mono text-sm w-full"
            data-testid="account-name-input"
          />
          <div className="text-[10px] font-mono text-[#71717A] mt-1">
            System identifier — used in Meesho URLs & API paths.
          </div>
        </div>

        <div>
          <div className="section-label mb-1">/ alias (human-friendly label, optional)</div>
          <input
            value={form.alias}
            onChange={(e) => setForm({ ...form, alias: e.target.value })}
            placeholder="e.g. Kommy Fashions"
            className="input-shell font-mono text-sm w-full"
            data-testid="account-alias-input"
          />
          <div className="text-[10px] font-mono text-[#71717A] mt-1">
            Shown in the UI & dropdowns. The system name above is still used for scraping and file paths.
          </div>
        </div>

        <div className="grid grid-cols-2 gap-3">
          <div>
            <div className="section-label mb-1">/ chrome debug port</div>
            <input
              type="number"
              value={form.debug_port}
              onChange={(e) => setForm({ ...form, debug_port: e.target.value })}
              className="input-shell font-mono text-sm w-full"
              data-testid="account-port-input"
            />
          </div>
          <div className="flex items-end">
            <button
              onClick={() => setForm({ ...form, enabled: !form.enabled })}
              className="flex items-center gap-1 text-sm pb-1.5"
              data-testid="account-enabled-toggle"
            >
              {form.enabled ? <ToggleRightIcon size={28} weight="fill" color="#00E676" />
                            : <ToggleLeftIcon size={28} weight="fill" color="#3a3a3a" />}
              <span className={"font-mono text-[11px] uppercase tracking-wider " +
                (form.enabled ? "text-[#00E676]" : "text-[#71717A]")}>
                {form.enabled ? "ENABLED" : "DISABLED"}
              </span>
            </button>
          </div>
        </div>

        <div>
          <div className="section-label mb-1">/ chrome profile dir (on EC2)</div>
          <input
            value={form.profile_dir}
            onChange={(e) => setForm({ ...form, profile_dir: e.target.value })}
            placeholder="/home/ubuntu/chrome-profile1"
            className="input-shell font-mono text-sm w-full"
            data-testid="account-profile-input"
          />
          <div className="text-[10px] font-mono text-[#71717A] mt-1">
            Tip: launch chrome separately on this port + profile (your start_chromes.sh handles it).
          </div>
        </div>

        <div className="flex justify-end gap-2 pt-2">
          <button onClick={onClose} className="btn-secondary text-sm" data-testid="account-cancel">
            Cancel
          </button>
          <button onClick={save} disabled={busy} className="btn-primary text-sm" data-testid="account-save">
            {busy ? "Saving…" : editing ? "Save Changes" : "Add Account"}
          </button>
        </div>
      </div>
    </div>
  );
}

export default function AccountsPage() {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState("");
  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState(null);
  const [confirmDel, setConfirmDel] = useState(null);

  const load = useCallback(async () => {
    setLoading(true); setErr("");
    try {
      const { data } = await api.get("/accounts");
      setItems(data.items || []);
    } catch (e) {
      setErr(formatApiError(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    document.title = "Accounts · Seller Central";
    load();
  }, [load]);

  const openNew = () => { setEditing(null); setModalOpen(true); };
  const openEdit = (a) => { setEditing(a); setModalOpen(true); };
  const onSaved = async () => { setModalOpen(false); await load(); };

  const toggleEnabled = async (a) => {
    try {
      await api.put(`/accounts/${a.id}`, { enabled: !a.enabled });
      await load();
    } catch (e) {
      setErr(formatApiError(e));
    }
  };

  const doDelete = async () => {
    if (!confirmDel) return;
    try {
      await api.delete(`/accounts/${confirmDel.id}`);
      setConfirmDel(null);
      await load();
    } catch (e) {
      setErr(formatApiError(e));
    }
  };

  return (
    <div data-testid="accounts-page">
      <PageHeader
        title="automation"
        subtitle="Accounts"
        right={
          <>
            <button onClick={load} className="btn-secondary text-sm flex items-center gap-2"
              data-testid="accounts-refresh">
              <ArrowsClockwiseIcon size={14} weight="bold" /> Refresh
            </button>
            <button onClick={openNew} className="btn-primary text-sm flex items-center gap-2"
              data-testid="accounts-add">
              <PlusCircleIcon size={14} weight="bold" /> Add Account
            </button>
          </>
        }
      />

      <div className="px-8 py-6 space-y-4">
        <div className="panel p-5 flex gap-4 items-start">
          <UserCircleIcon size={28} weight="bold" color="#007AFF" />
          <div className="flex-1 space-y-2">
            <div className="font-display text-base">Multi-account label downloads</div>
            <p className="text-xs text-[#A1A1AA] leading-relaxed">
              Each Meesho seller account uses its own Chrome profile on the EC2 worker. Add an entry
              here for every login (e.g. <span className="code-tag">uobfs</span>, <span className="code-tag">hrbib</span>),
              point it to a unique <span className="code-tag">debug_port</span> and <span className="code-tag">profile_dir</span>,
              then launch chrome on that port via your <span className="code-tag">start_chromes.sh</span> on EC2.
            </p>
          </div>
        </div>

        {err && (
          <div className="border border-[#FF3B30]/30 bg-[#FF3B30]/10 px-3 py-2 font-mono text-xs text-[#FF3B30]"
            data-testid="accounts-err">{err}</div>
        )}

        <div className="panel">
          <div className="border-b border-[#2A2A2A] px-5 py-3 flex items-center justify-between">
            <div className="font-display text-sm font-medium">Accounts</div>
            <span className="code-tag">{items.length}</span>
          </div>
          <div className="overflow-x-auto">
            <table className="dense">
              <thead>
                <tr>
                  <th>Name</th>
                  <th className="num">Port</th>
                  <th>Profile Dir</th>
                  <th>Status</th>
                  <th className="num">Last Used</th>
                  <th className="text-right">Actions</th>
                </tr>
              </thead>
              <tbody>
                {loading && (
                  <tr><td colSpan={6} className="text-center py-8 text-[#71717A] font-mono text-xs">
                    <span className="cursor-blink">LOADING</span>
                  </td></tr>
                )}
                {!loading && items.length === 0 && (
                  <tr><td colSpan={6} className="text-center py-10 text-[#71717A] text-sm">
                    No accounts yet. Click "Add Account" to create the first one.
                  </td></tr>
                )}
                {items.map((a) => (
                  <tr key={a.id} data-testid={`account-row-${a.id}`}>
                    <td className="font-mono text-sm">
                      {a.alias ? (
                        <>
                          <div>{a.alias}</div>
                          <div className="font-mono text-[10px] text-[#71717A]">{a.name}</div>
                        </>
                      ) : (
                        a.name
                      )}
                    </td>
                    <td className="num font-mono text-xs text-[#A1A1AA]">{a.debug_port}</td>
                    <td className="font-mono text-xs text-[#A1A1AA] truncate max-w-[280px]" title={a.profile_dir}>
                      {a.profile_dir}
                    </td>
                    <td>
                      <button onClick={() => toggleEnabled(a)} className="flex items-center gap-1"
                        data-testid={`account-toggle-${a.id}`}>
                        {a.enabled ? <ToggleRightIcon size={22} weight="fill" color="#00E676" />
                                   : <ToggleLeftIcon size={22} weight="fill" color="#3a3a3a" />}
                        <span className={"font-mono text-[10px] uppercase tracking-wider " +
                          (a.enabled ? "text-[#00E676]" : "text-[#71717A]")}>
                          {a.enabled ? "ENABLED" : "DISABLED"}
                        </span>
                      </button>
                    </td>
                    <td className="num text-xs text-[#A1A1AA]">{fmtRelative(a.last_used_at)}</td>
                    <td className="text-right">
                      <div className="flex items-center justify-end gap-1">
                        <button onClick={() => openEdit(a)} className="btn-ghost text-xs flex items-center gap-1"
                          data-testid={`account-edit-${a.id}`}>
                          <PencilSimpleIcon size={12} weight="bold" /> Edit
                        </button>
                        <button onClick={() => setConfirmDel(a)}
                          className="btn-ghost text-xs flex items-center gap-1 hover:text-[#FF3B30]"
                          data-testid={`account-delete-${a.id}`}>
                          <TrashIcon size={12} weight="bold" /> Delete
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>

      <AccountModal open={modalOpen} account={editing} onClose={() => setModalOpen(false)} onSaved={onSaved} />

      {confirmDel && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm"
          onClick={() => setConfirmDel(null)} data-testid="account-confirm-delete">
          <div className="panel w-[420px] p-6 space-y-4" onClick={(e) => e.stopPropagation()}>
            <div>
              <div className="section-label mb-1">/ confirm delete</div>
              <h2 className="font-display text-lg">Delete "{confirmDel.name}"?</h2>
              <p className="text-xs text-[#A1A1AA] mt-2">
                Existing label runs in history are kept. New runs will no longer queue for this account.
              </p>
            </div>
            <div className="flex justify-end gap-2">
              <button onClick={() => setConfirmDel(null)} className="btn-secondary text-sm"
                data-testid="account-confirm-cancel">Cancel</button>
              <button onClick={doDelete} className="btn-primary text-sm bg-[#FF3B30] hover:bg-[#ff5849] border-[#FF3B30]"
                data-testid="account-confirm-delete-btn">Delete</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
