import { Link } from "react-router-dom";
import { ErrorMessage, LoadingPage } from "@/components/ui/Spinner";
import { useInstruments } from "@/lib/exchange/hooks";
import { instrumentPriceChips } from "@/lib/exchange/venues";

export default function Instruments() {
  const instruments = useInstruments();

  if (instruments.isLoading) return <LoadingPage />;
  if (instruments.error) return <ErrorMessage message="Could not load exchange instruments." />;

  return (
    <div style={{ display: "grid", gap: "var(--space-lg)" }}>
      <div>
        <h1 style={{ fontSize: "1.5rem", fontWeight: 600 }}>Exchange</h1>
        <p style={noteStyle}>Trade the same question across NET, AMM, and order-book venues.</p>
      </div>
      {(instruments.data?.length ?? 0) === 0 ? (
        <span style={noteStyle}>No cross-venue instruments are listed yet.</span>
      ) : (
        <div style={tableWrapStyle}>
          <table style={tableStyle}>
            <thead>
              <tr style={{ background: "var(--color-bg-hover)" }}>
                <th style={thStyle}>Instrument</th>
                <th style={thStyle}>Live YES prices</th>
                <th style={thStyle} aria-label="Actions" />
              </tr>
            </thead>
            <tbody>{instruments.data?.map((instrument) => (
              <tr key={instrument.instrumentId} style={{ borderTop: "1px solid var(--color-border)" }}>
                <td style={tdStyle}>
                  <Link to={`/instruments/${instrument.instrumentId}`} style={{ fontWeight: 600 }}>{instrument.title}</Link>
                </td>
                <td style={tdStyle}>
                  <div style={{ display: "flex", flexWrap: "wrap", gap: "var(--space-xs)" }}>
                    {instrumentPriceChips(instrument).map((chip) => (
                      <span key={chip.venue} style={priceChipStyle}>
                        {chip.venue.toUpperCase()} <strong>{chip.price}</strong>
                      </span>
                    ))}
                  </div>
                </td>
                <td style={{ ...tdStyle, textAlign: "right" }}>
                  <Link to={`/instruments/${instrument.instrumentId}`}>Trade</Link>
                </td>
              </tr>
            ))}</tbody>
          </table>
        </div>
      )}
    </div>
  );
}

const noteStyle: React.CSSProperties = { color: "var(--color-text-muted)", fontSize: "0.85rem" };
const tableWrapStyle: React.CSSProperties = { borderRadius: "var(--radius-md)", border: "1px solid var(--color-border)", overflow: "auto" };
const tableStyle: React.CSSProperties = { width: "100%", borderCollapse: "collapse", fontSize: "0.875rem" };
const thStyle: React.CSSProperties = { padding: "10px 14px", textAlign: "left", fontWeight: 500 };
const tdStyle: React.CSSProperties = { padding: "12px 14px" };
const priceChipStyle: React.CSSProperties = { padding: "3px 8px", borderRadius: 999, background: "var(--color-bg-hover)", fontFamily: "var(--font-mono)", fontSize: "0.75rem", whiteSpace: "nowrap" };
