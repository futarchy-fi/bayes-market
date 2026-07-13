import { useEffect, useMemo } from "react";
import { useNavigate } from "react-router-dom";
import { parseExchangeFragment, useExchangeSession } from "@/lib/exchange/session";

export default function ExchangeCallback() {
  const navigate = useNavigate();
  const { setSession } = useExchangeSession();
  const parsed = useMemo(() => parseExchangeFragment(window.location.hash), []);

  useEffect(() => {
    if (!parsed) return;
    setSession(parsed);
    window.history.replaceState(null, "", window.location.pathname);
    navigate("/portfolio", { replace: true });
  }, [navigate, parsed, setSession]);

  return (
    <div style={{ textAlign: "center", padding: "var(--space-xl)", color: parsed ? "var(--color-text-muted)" : "var(--color-danger)" }}>
      {parsed ? "Signing you in…" : "GitHub sign-in did not return an API key. Please try again."}
    </div>
  );
}
