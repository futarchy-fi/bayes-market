import { useEffect, useRef, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import {
  clearSelectAccountFlag,
  consumeReturnTo,
  parseExchangeCallbackError,
  parseExchangeFragment,
  startGithubLogin,
  useExchangeSession,
  type ExchangeSession,
} from "@/lib/exchange/session";

const CALLBACK_ERROR_MESSAGES: Record<string, string> = {
  access_denied:
    "You cancelled the GitHub authorization request. No changes were made to your account.",
  invalid_state:
    "Your sign-in session expired or did not match this browser tab. Please start GitHub sign-in again.",
  code_exchange_failed:
    "We could not complete token exchange with GitHub right now. Please try again in a moment.",
  github_profile_failed:
    "We could not load your GitHub profile to finish signing in. Please try again.",
  profile_fetch_failed:
    "We could not load your GitHub profile to finish signing in. Please try again.",
  user_fetch_failed:
    "We could not load your GitHub profile to finish signing in. Please try again.",
  oauth_not_configured:
    "GitHub sign-in is temporarily unavailable on the exchange. Please try again later.",
  provider_unavailable:
    "GitHub sign-in is temporarily unavailable on the exchange. Please try again later.",
};

export function describeCallbackError(slug: string): string {
  const normalized = slug.trim().toLowerCase();
  if (normalized in CALLBACK_ERROR_MESSAGES) {
    return CALLBACK_ERROR_MESSAGES[normalized]!;
  }
  return `GitHub returned an error (${slug}) while signing in. Please try again.`;
}

interface CallbackInitialState {
  errorSlug: string | null;
  session: ExchangeSession | null;
}

export default function ExchangeCallback() {
  const navigate = useNavigate();
  const location = useLocation();
  const { setSession } = useExchangeSession();
  const handledRef = useRef(false);

  // Capture hash/query once on mount before history.replaceState strips the URL.
  const [initial] = useState<CallbackInitialState>(() => {
    const hash = window.location.hash || location.hash || "";
    const search = window.location.search || location.search || "";
    const errorSlug = parseExchangeCallbackError(hash, search);
    if (errorSlug) {
      return { errorSlug, session: null };
    }
    return { errorSlug: null, session: parseExchangeFragment(hash) };
  });

  useEffect(() => {
    if (handledRef.current) return;
    handledRef.current = true;

    // Always strip fragment and query parameters from the URL bar so secrets or
    // OAuth error parameters never linger in browser history.
    if (window.location.hash || window.location.search) {
      window.history.replaceState(null, "", window.location.pathname);
    }

    if (initial.errorSlug || !initial.session) {
      return;
    }

    setSession(initial.session);
    clearSelectAccountFlag();
    const returnTo = consumeReturnTo();
    navigate(returnTo ?? "/portfolio", { replace: true });
  }, [initial, navigate, setSession]);

  if (!initial.errorSlug && initial.session) {
    return (
      <div style={{ textAlign: "center", padding: "var(--space-xl)", color: "var(--color-text-muted)" }}>
        Signing you in…
      </div>
    );
  }

  const description = initial.errorSlug
    ? describeCallbackError(initial.errorSlug)
    : "GitHub sign-in did not return an API key. Please try again.";

  return (
    <div style={cardWrapStyle}>
      <section role="alert" style={errorCardStyle}>
        <h1 style={{ fontSize: "1.25rem", fontWeight: 600, color: "var(--color-text)" }}>
          GitHub sign-in didn&apos;t complete
        </h1>
        <p style={{ color: "var(--color-text-muted)", fontSize: "0.9rem", lineHeight: 1.55 }}>
          {description}
        </p>
        <div style={actionsStyle}>
          <button
            type="button"
            onClick={() => startGithubLogin()}
            style={primaryButtonStyle}
          >
            Try signing in again
          </button>
          <Link to="/" style={secondaryLinkStyle}>
            Back to Network
          </Link>
        </div>
      </section>
    </div>
  );
}

const cardWrapStyle: React.CSSProperties = {
  display: "flex",
  justifyContent: "center",
  padding: "var(--space-xl) var(--space-md)",
};

const errorCardStyle: React.CSSProperties = {
  display: "grid",
  gap: "var(--space-md)",
  maxWidth: 460,
  width: "100%",
  padding: "var(--space-lg)",
  borderRadius: "var(--radius-md)",
  border: "1px solid var(--color-border)",
  background: "var(--color-bg-surface)",
};

const actionsStyle: React.CSSProperties = {
  display: "flex",
  flexWrap: "wrap",
  alignItems: "center",
  gap: "var(--space-md)",
  marginTop: "var(--space-xs)",
};

const primaryButtonStyle: React.CSSProperties = {
  padding: "8px 16px",
  borderRadius: "var(--radius-sm)",
  border: 0,
  background: "var(--color-primary)",
  color: "#fff",
  fontSize: "0.875rem",
  fontWeight: 600,
  cursor: "pointer",
};

const secondaryLinkStyle: React.CSSProperties = {
  fontSize: "0.875rem",
  color: "var(--color-text-muted)",
  fontWeight: 500,
  textDecoration: "none",
};
