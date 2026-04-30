import { Navigate } from "react-router-dom";
import { useAuth } from "@/auth/AuthContext";

export default function ProtectedRoute({ children }) {
  const { user } = useAuth();
  if (user === null) {
    return (
      <div className="grid-bg flex h-screen items-center justify-center">
        <div className="font-mono text-xs uppercase tracking-widest text-[#71717A] cursor-blink">
          AUTHENTICATING
        </div>
      </div>
    );
  }
  if (user === false) return <Navigate to="/login" replace />;
  return children;
}
