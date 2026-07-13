import { useEffect, useMemo, useState, type FormEvent } from "react";
import { Link, useParams } from "react-router-dom";
import { ErrorMessage, LoadingPage } from "@/components/ui/Spinner";
import { EXCHANGE_API, type InstrumentListing } from "@/lib/exchange/client";
import { TradeCreditsPanel, friendlyExchangeError } from "@/lib/exchange/TradeCreditsPanel";
import {
  useAmmMarket,
  useBookDepth,
  useBookMarket,
  useBookOrders,
  useCancelBookOrder,
  useExchangeMe,
  useInstruments,
  useNetMarket,
  usePlaceBookOrder,
  useTradeAmm,
} from "@/lib/exchange/hooks";
import { useExchangeSession } from "@/lib/exchange/session";
import { validateBookOrder } from "@/lib/exchange/venues";

export default function InstrumentDetail() {
  const { instrumentId = "" } = useParams();
  const instruments = useInstruments();
  const instrument = instruments.data?.find((item) => item.instrumentId === instrumentId);

  if (instruments.isLoading) return <LoadingPage />;
  if (instruments.error) return <ErrorMessage message="Could not load this exchange instrument." />;
  if (!instrument) return <ErrorMessage message="Instrument not found." />;

  const listing = (venue: InstrumentListing["venue"]) => instrument.listings.find((item) => item.venue === venue);

  return (
    <div style={{ display: "grid", gap: "var(--space-lg)" }}>
      <div>
        <Link to="/instruments" style={{ fontSize: "0.8rem" }}>← Exchange</Link>
        <h1 style={{ marginTop: "var(--space-sm)", fontSize: "1.5rem", fontWeight: 600 }}>{instrument.title}</h1>
        <p style={noteStyle}>Compare live prices and trade each venue from one screen.</p>
      </div>
      <div data-testid="venue-grid" style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))", gap: "var(--space-md)", alignItems: "start" }}>
        <NetVenuePanel listing={listing("net")} />
        <AmmVenuePanel listing={listing("amm")} />
        <BookVenuePanel listing={listing("book")} />
      </div>
    </div>
  );
}

function NetVenuePanel({ listing }: { listing?: InstrumentListing }) {
  const market = useNetMarket(listing?.marketId ?? "", Boolean(listing));
  if (!listing) return <UnavailablePanel venue="NET" />;
  return (
    <div data-testid="net-panel" style={{ display: "grid", gap: "var(--space-sm)" }}>
      <VenueHeader name="NET" listing={listing} />
      {market.isLoading ? <LoadingLine /> : market.error ? <span style={errorStyle}>{friendlyExchangeError(market.error)}</span> : market.data ? (
        <TradeCreditsPanel marketId={listing.marketId} variableId={market.data.variableId} />
      ) : null}
    </div>
  );
}

function AmmVenuePanel({ listing }: { listing?: InstrumentListing }) {
  const { isSignedIn } = useExchangeSession();
  const market = useAmmMarket(listing?.marketId ?? "");
  const trade = useTradeAmm(listing?.marketId ?? "");
  const me = useExchangeMe();
  const [action, setAction] = useState<"buy" | "sell">("buy");
  const [outcome, setOutcome] = useState("");
  const [value, setValue] = useState("");
  const [confirming, setConfirming] = useState(false);

  const outcomes = market.data?.outcomes ?? [];
  useEffect(() => { if (!outcome && outcomes[0]) setOutcome(outcomes[0]); }, [outcome, outcomes]);

  if (!listing) return <UnavailablePanel venue="AMM" />;
  const currentPrice = market.data?.prices[outcome];
  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (!confirming) return setConfirming(true);
    trade.mutate({ action, payload: { outcome, ...(action === "buy" ? { budget: value } : { amount: value }) } });
  };
  const reset = () => { setConfirming(false); trade.reset(); };

  return (
    <section data-testid="amm-panel" style={panelStyle}>
      <VenueHeader name="AMM" listing={listing} />
      {market.isLoading ? <LoadingLine /> : market.error ? <span style={errorStyle}>{friendlyExchangeError(market.error)}</span> : market.data ? (
        <>
          <PriceRow prices={market.data.prices} />
          {!isSignedIn ? <SignInPrompt action="trade the AMM" /> : (
            <form onSubmit={submit} style={{ display: "grid", gap: "var(--space-sm)" }}>
              <div style={twoColumnStyle}>
                <label style={labelStyle}>Action
                  <select value={action} onChange={(event) => { setAction(event.target.value as "buy" | "sell"); reset(); }} style={inputStyle}>
                    <option value="buy">Buy</option><option value="sell">Sell</option>
                  </select>
                </label>
                <label style={labelStyle}>Outcome
                  <select value={outcome} onChange={(event) => { setOutcome(event.target.value); reset(); }} style={inputStyle}>
                    {outcomes.map((item) => <option key={item} value={item}>{titleCase(item)}</option>)}
                  </select>
                </label>
              </div>
              <label style={labelStyle}>{action === "buy" ? "Budget (credits)" : "Amount (shares)"}
                <input aria-label={action === "buy" ? "Budget" : "Amount"} type="number" min="0" step="any" value={value} onChange={(event) => { setValue(event.target.value); reset(); }} style={inputStyle} />
              </label>
              {confirming && (
                <div style={confirmStyle}>
                  {titleCase(action)} {titleCase(outcome)} at the posted {formatPrice(currentPrice)} price. Final execution may move with slippage.
                </div>
              )}
              <button disabled={!outcome || !(Number(value) > 0) || trade.isPending} style={buttonStyle}>
                {trade.isPending ? "Trading…" : confirming ? `Confirm ${action}` : `Review ${action}`}
              </button>
              {trade.error && <span style={errorStyle}>{friendlyExchangeError(trade.error)}</span>}
              {trade.data && (
                <span style={successStyle}>
                  Filled {trade.data.amount} {trade.data.outcome} at {formatPrice(trade.data.price)} · available balance {me.data?.available ?? "refreshing…"} credits
                </span>
              )}
            </form>
          )}
        </>
      ) : null}
    </section>
  );
}

function BookVenuePanel({ listing }: { listing?: InstrumentListing }) {
  const { isSignedIn } = useExchangeSession();
  const marketId = listing?.marketId ?? "";
  const market = useBookMarket(marketId);
  const depth = useBookDepth(marketId);
  const orders = useBookOrders();
  const place = usePlaceBookOrder(marketId);
  const cancel = useCancelBookOrder(marketId);
  const [side, setSide] = useState<"bid" | "ask">("bid");
  const [outcome, setOutcome] = useState("yes");
  const [price, setPrice] = useState("0.5");
  const [size, setSize] = useState("1");
  const [validationError, setValidationError] = useState<string | null>(null);
  const openOrders = useMemo(() => (orders.data?.orders ?? []).filter((order) => String(order.marketId) === marketId && ["open", "partial"].includes(order.status)), [marketId, orders.data]);
  const outcomeDepth = depth.data?.outcomes[outcome];

  if (!listing) return <UnavailablePanel venue="BOOK" />;
  const submit = (event: FormEvent) => {
    event.preventDefault();
    const error = validateBookOrder(price, size);
    setValidationError(error);
    if (!error) place.mutate({ marketId: Number(marketId), side, outcome, price, size });
  };

  return (
    <section data-testid="book-panel" style={panelStyle}>
      <VenueHeader name="ORDER BOOK" listing={listing} />
      {market.isLoading || depth.isLoading ? <LoadingLine /> : market.error || depth.error ? <span style={errorStyle}>Could not load the order book.</span> : market.data ? (
        <>
          <div style={twoColumnStyle}>
            <span style={noteStyle}>Best bid <strong style={{ color: "var(--color-text)" }}>{formatPrice(market.data.bestBid)}</strong></span>
            <span style={noteStyle}>Best ask <strong style={{ color: "var(--color-text)" }}>{formatPrice(market.data.bestAsk)}</strong></span>
          </div>
          <label style={labelStyle}>Depth outcome
            <select value={outcome} onChange={(event) => setOutcome(event.target.value)} style={inputStyle}>
              {market.data.outcomes.map((item) => <option key={item} value={item}>{titleCase(item)}</option>)}
            </select>
          </label>
          <DepthTable bids={outcomeDepth?.bids ?? []} asks={outcomeDepth?.asks ?? []} />
          {!isSignedIn ? <SignInPrompt action="place or cancel orders" /> : (
            <>
              <form onSubmit={submit} style={{ display: "grid", gap: "var(--space-sm)" }}>
                <div style={twoColumnStyle}>
                  <label style={labelStyle}>Side
                    <select value={side} onChange={(event) => setSide(event.target.value as "bid" | "ask")} style={inputStyle}>
                      <option value="bid">Bid</option><option value="ask">Ask</option>
                    </select>
                  </label>
                  <label style={labelStyle}>Outcome
                    <select value={outcome} onChange={(event) => setOutcome(event.target.value)} style={inputStyle}>
                      {market.data.outcomes.map((item) => <option key={item} value={item}>{titleCase(item)}</option>)}
                    </select>
                  </label>
                  <label style={labelStyle}>Limit price
                    <input aria-label="Limit price" type="number" min="0.0001" max="0.9999" step="0.0001" value={price} onChange={(event) => setPrice(event.target.value)} style={inputStyle} />
                  </label>
                  <label style={labelStyle}>Size
                    <input aria-label="Size" type="number" min="0.01" step="0.01" value={size} onChange={(event) => setSize(event.target.value)} style={inputStyle} />
                  </label>
                </div>
                <button disabled={place.isPending} style={buttonStyle}>{place.isPending ? "Placing…" : "Place limit order"}</button>
                {(validationError || place.error) && <span style={errorStyle}>{validationError ?? friendlyExchangeError(place.error)}</span>}
                {place.data && <span style={successStyle}>Order {place.data.orderId} {place.data.status} · available balance {place.data.balance.available} credits</span>}
              </form>
              <div style={{ display: "grid", gap: "var(--space-xs)" }}>
                <h3 style={subheadingStyle}>My open orders</h3>
                {openOrders.length === 0 ? <span style={noteStyle}>No open orders for this market.</span> : openOrders.map((order) => (
                  <div key={order.orderId} style={orderRowStyle}>
                    <span>{order.side.toUpperCase()} {order.outcome.toUpperCase()} {order.remaining} @ {formatPrice(order.price)}</span>
                    <button type="button" disabled={cancel.isPending} onClick={() => cancel.mutate(order.orderId)} style={linkButtonStyle}>Cancel</button>
                  </div>
                ))}
                {cancel.error && <span style={errorStyle}>{friendlyExchangeError(cancel.error)}</span>}
              </div>
            </>
          )}
        </>
      ) : null}
    </section>
  );
}

function VenueHeader({ name, listing }: { name: string; listing: InstrumentListing }) {
  return <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", gap: "var(--space-sm)" }}><h2 style={{ fontSize: "1rem", fontWeight: 700 }}>{name}</h2><span style={noteStyle}>{listing.status} · YES {listing.yesPrice === null ? "—" : formatPrice(listing.yesPrice)}</span></div>;
}

function UnavailablePanel({ venue }: { venue: string }) {
  return <section data-testid={`${venue.toLowerCase()}-panel`} style={panelStyle}><h2 style={{ fontSize: "1rem", fontWeight: 700 }}>{venue}</h2><span style={noteStyle}>Not listed on this venue.</span></section>;
}

function SignInPrompt({ action }: { action: string }) {
  return <a href={`${EXCHANGE_API}/v1/auth/github/login`}>Sign in with GitHub to {action}</a>;
}

function PriceRow({ prices }: { prices: Record<string, string> }) {
  return <div style={{ display: "flex", flexWrap: "wrap", gap: "var(--space-sm)" }}>{Object.entries(prices).map(([outcome, price]) => <span key={outcome} style={priceChipStyle}>{titleCase(outcome)} <strong>{formatPrice(price)}</strong></span>)}</div>;
}

function DepthTable({ bids, asks }: { bids: Array<{ price: string; size: string }>; asks: Array<{ price: string; size: string }> }) {
  const rows = Array.from({ length: Math.max(bids.length, asks.length, 1) });
  return <div style={tableWrapStyle}><table style={tableStyle}><thead><tr><th style={thStyle}>Bid</th><th style={thStyle}>Size</th><th style={thStyle}>Ask</th><th style={thStyle}>Size</th></tr></thead><tbody>{rows.map((_, index) => <tr key={index} style={{ borderTop: "1px solid var(--color-border)" }}><td style={tdStyle}>{formatPrice(bids[index]?.price)}</td><td style={tdStyle}>{bids[index]?.size ?? "—"}</td><td style={tdStyle}>{formatPrice(asks[index]?.price)}</td><td style={tdStyle}>{asks[index]?.size ?? "—"}</td></tr>)}</tbody></table></div>;
}

const titleCase = (value: string) => value.charAt(0).toUpperCase() + value.slice(1);
const formatPrice = (value: string | number | null | undefined) => value == null ? "—" : `${(Number(value) * 100).toFixed(1)}%`;
const LoadingLine = () => <span style={noteStyle}>Loading live venue…</span>;

const panelStyle: React.CSSProperties = { display: "grid", gap: "var(--space-sm)", padding: "var(--space-md)", border: "1px solid var(--color-border)", borderRadius: "var(--radius-md)", background: "var(--color-bg-surface)" };
const noteStyle: React.CSSProperties = { color: "var(--color-text-muted)", fontSize: "0.8rem" };
const errorStyle: React.CSSProperties = { color: "var(--color-danger)", fontSize: "0.85rem" };
const successStyle: React.CSSProperties = { color: "var(--color-success)", fontSize: "0.8rem" };
const labelStyle: React.CSSProperties = { display: "grid", gap: "var(--space-xs)", color: "var(--color-text-muted)", fontSize: "0.75rem" };
const inputStyle: React.CSSProperties = { width: "100%", padding: "8px", borderRadius: "var(--radius-sm)", border: "1px solid var(--color-border)", background: "var(--color-bg)", color: "var(--color-text)" };
const buttonStyle: React.CSSProperties = { padding: "8px 14px", border: 0, borderRadius: "var(--radius-sm)", background: "var(--color-primary)", color: "white", cursor: "pointer" };
const linkButtonStyle: React.CSSProperties = { padding: 0, border: 0, background: "transparent", color: "var(--color-primary)", cursor: "pointer" };
const twoColumnStyle: React.CSSProperties = { display: "grid", gridTemplateColumns: "repeat(2, minmax(0, 1fr))", gap: "var(--space-sm)" };
const confirmStyle: React.CSSProperties = { padding: "var(--space-sm)", border: "1px solid var(--color-border)", borderRadius: "var(--radius-sm)", color: "var(--color-text-muted)", fontSize: "0.8rem" };
const priceChipStyle: React.CSSProperties = { padding: "3px 8px", borderRadius: 999, background: "var(--color-bg-hover)", fontSize: "0.75rem" };
const subheadingStyle: React.CSSProperties = { fontSize: "0.85rem", fontWeight: 600 };
const orderRowStyle: React.CSSProperties = { display: "flex", justifyContent: "space-between", gap: "var(--space-sm)", fontSize: "0.75rem" };
const tableWrapStyle: React.CSSProperties = { border: "1px solid var(--color-border)", borderRadius: "var(--radius-sm)", overflow: "auto" };
const tableStyle: React.CSSProperties = { width: "100%", borderCollapse: "collapse", fontSize: "0.7rem" };
const thStyle: React.CSSProperties = { padding: "5px 7px", textAlign: "right", fontWeight: 500 };
const tdStyle: React.CSSProperties = { padding: "5px 7px", textAlign: "right", fontFamily: "var(--font-mono)" };
