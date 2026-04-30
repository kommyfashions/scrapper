import { useState, useEffect } from "react";
import { useNavigate, Navigate } from "react-router-dom";
import { TerminalWindowIcon, LockKeyIcon, ArrowRightIcon } from "@phosphor-icons/react";
import { useAuth } from "@/auth/AuthContext";

export default function LoginPage() {
  const { user, login } = useAuth();
  const navigate = useNavigate();
  const [email, setEmail] = useState("admin@meesho-dash.local");
  const [password, setPassword] = useState("");
  const [err, setErr] = useState("");
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    document.title = "Sign in · Seller Central";
  }, []);

  if (user && user !== false) return <Navigate to="/" replace />;

  const onSubmit = async (e) => {
    e.preventDefault();
    setErr("");
    setLoading(true);
    const res = await login(email, password);
    setLoading(false);
    if (res.ok) navigate("/", { replace: true });
    else setErr(res.error || "Login failed");
  };

  return (
    <div className="grid-bg scanline-bg flex h-screen items-center justify-center px-6">
      <div className="w-full max-w-md">
        <div className="mb-8 flex items-center gap-3">
          <TerminalWindowIcon size={28} weight="bold" color="#007AFF" />
          <div>
            <div className="font-display text-2xl font-semibold tracking-tight">
              Seller Central
            </div>
            <div className="font-mono text-[10px] uppercase tracking-[0.22em] text-[#71717A]">
              meesho operations · secure sign-in
            </div>
          </div>
        </div>

        <form
          onSubmit={onSubmit}
          className="panel p-7 space-y-5"
          data-testid="login-form"
        >
          <div>
            <div className="section-label mb-2">/ identifier</div>
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
              className="input-shell font-mono text-sm"
              placeholder="admin@meesho-dash.local"
              data-testid="login-email-input"
            />
          </div>

          <div>
            <div className="section-label mb-2 flex items-center gap-1">
              <LockKeyIcon size={11} weight="bold" /> passphrase
            </div>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              className="input-shell font-mono text-sm"
              placeholder="••••••••"
              data-testid="login-password-input"
            />
          </div>

          {err && (
            <div
              className="border border-[#FF3B30]/30 bg-[#FF3B30]/10 px-3 py-2 font-mono text-xs text-[#FF3B30]"
              data-testid="login-error"
            >
              {err}
            </div>
          )}

          <button
            type="submit"
            disabled={loading}
            className="btn-primary flex w-full items-center justify-center gap-2"
            data-testid="login-submit-button"
          >
            {loading ? (
              <span className="font-mono text-xs cursor-blink">AUTHENTICATING</span>
            ) : (
              <>
                <span>Authorize</span>
                <ArrowRightIcon size={14} weight="bold" />
              </>
            )}
          </button>

          <div className="border-t border-[#2A2A2A] pt-4 text-[11px] text-[#71717A] font-mono">
            Default credentials seeded from server <span className="code-tag">.env</span>.
            Single-admin internal tool.
          </div>
        </form>
      </div>
    </div>
  );
}
