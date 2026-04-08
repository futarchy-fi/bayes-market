export function Spinner({ size = 24 }: { size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      style={{ animation: "spin 1s linear infinite" }}
    >
      <style>{`@keyframes spin { to { transform: rotate(360deg) } }`}</style>
      <circle
        cx="12" cy="12" r="10"
        fill="none"
        stroke="var(--color-primary)"
        strokeWidth="3"
        strokeDasharray="31.4 31.4"
        strokeLinecap="round"
      />
    </svg>
  );
}

export function LoadingPage() {
  return (
    <div style={{ display: "flex", justifyContent: "center", alignItems: "center", padding: "var(--space-xl)" }}>
      <Spinner size={32} />
    </div>
  );
}

export function ErrorMessage({ message }: { message: string }) {
  return (
    <div style={{
      padding: "var(--space-md)",
      borderRadius: "var(--radius-md)",
      border: "1px solid var(--color-danger)",
      color: "var(--color-danger)",
      background: "rgba(239, 68, 68, 0.1)",
    }}>
      {message}
    </div>
  );
}
