import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useMarkets } from "@/lib/query/hooks";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { LoadingPage, ErrorMessage } from "@/components/ui/Spinner";
import { formatCurrency, timeUntil } from "@/lib/utils/format";
import {
  isMarketListSort,
  isMarketListStatusFilter,
  marketListSearchParams,
  readMarketListFiltersFromSearchParams,
} from "@/lib/marketListFilters";
import type { MarketListSort, MarketStatus } from "@/lib/api/types";
import { isExchangeMode } from "@/lib/exchangeMode";
import { useInstruments } from "@/lib/exchange/hooks";

const STATUSES = ["", "active", "resolved", "closed", "draft"] as const;
const SORTS = ["", "volume", "liquidity", "created"] as const;
const SEARCH_DEBOUNCE_MS = 300;

function sortLabel(sort: (typeof SORTS)[number]) {
  if (sort === "") {
    return "Default order";
  }

  if (sort === "created") {
    return "Newest";
  }

  return sort.charAt(0).toUpperCase() + sort.slice(1);
}

function updateSearchParams(
  setSearchParams: ReturnType<typeof useSearchParams>[1],
  filters: {
    status?: MarketStatus;
    sort?: MarketListSort;
    q?: string;
  },
  opts?: { replace?: boolean },
) {
  setSearchParams(marketListSearchParams(filters), opts);
}

export default function MarketList() {
  const exchangeMode = isExchangeMode();
  const [searchParams, setSearchParams] = useSearchParams();
  const filters = readMarketListFiltersFromSearchParams(searchParams);
  const statusFilter = filters.status ?? "";
  const sortFilter = filters.sort ?? "";
  const committedSearch = filters.q ?? "";
  const [searchInput, setSearchInput] = useState(committedSearch);
  const { data, isLoading, error } = useMarkets(filters);
  const instruments = useInstruments(exchangeMode);
  const instrumentsByNetMarket = new Map(instruments.data?.flatMap((instrument) =>
    instrument.listings
      .filter((listing) => listing.venue === "net")
      .map((listing) => [listing.marketId, instrument] as const),
  ));

  useEffect(() => {
    const rawStatus = searchParams.get("status");
    const rawSort = searchParams.get("sort");
    const next = marketListSearchParams({
      status: isMarketListStatusFilter(rawStatus) ? rawStatus : undefined,
      sort: isMarketListSort(rawSort) ? rawSort : undefined,
      q: searchParams.get("q") ?? undefined,
    });

    if (next.toString() !== searchParams.toString()) {
      setSearchParams(next, { replace: true });
    }
  }, [searchParams, setSearchParams]);

  useEffect(() => {
    setSearchInput(committedSearch);
  }, [committedSearch]);

  useEffect(() => {
    const handle = window.setTimeout(() => {
      const nextSearch = searchInput.trim() || undefined;

      if (nextSearch === committedSearch) {
        return;
      }

      updateSearchParams(
        setSearchParams,
        {
          status: statusFilter || undefined,
          sort: sortFilter || undefined,
          q: nextSearch,
        },
        { replace: true },
      );
    }, SEARCH_DEBOUNCE_MS);

    return () => window.clearTimeout(handle);
  }, [committedSearch, searchInput, setSearchParams, sortFilter, statusFilter]);

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "start", gap: "var(--space-md)", marginBottom: "var(--space-lg)", flexWrap: "wrap" }}>
        <div style={{ display: "grid", gap: "var(--space-xs)" }}>
          <h1 style={{ fontSize: "1.5rem", fontWeight: 600 }}>Markets</h1>
          <p style={{ margin: 0, color: "var(--color-text-muted)", maxWidth: 720 }}>
            Filter the market directory by status, rank results by activity, and search titles from a shareable URL state.
          </p>
        </div>
        <div style={{ display: "flex", gap: "var(--space-sm)", alignItems: "center", flexWrap: "wrap", justifyContent: "end" }}>
          {!exchangeMode && <Link
            to="/markets/new"
            style={{
              padding: "6px 14px",
              borderRadius: "var(--radius-sm)",
              background: "var(--color-primary)",
              color: "#fff",
              fontSize: "0.875rem",
              fontWeight: 600,
              textDecoration: "none",
            }}
          >
            + New Market
          </Link>}
        </div>
      </div>

      <div
        style={{
          display: "grid",
          gap: "var(--space-sm)",
          gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))",
          marginBottom: "var(--space-lg)",
          padding: "var(--space-md)",
          borderRadius: "var(--radius-md)",
          background: "var(--color-bg-surface)",
          border: "1px solid var(--color-border)",
        }}
      >
        <label style={{ display: "grid", gap: 6, fontSize: "0.8rem", color: "var(--color-text-muted)" }}>
          Search
          <input
            type="search"
            value={searchInput}
            onChange={(e) => setSearchInput(e.target.value)}
            placeholder="Search market titles"
            style={controlStyle}
          />
        </label>

        <label style={{ display: "grid", gap: 6, fontSize: "0.8rem", color: "var(--color-text-muted)" }}>
          Status
          <select
            value={statusFilter}
            onChange={(e) =>
              updateSearchParams(setSearchParams, {
                status: (e.target.value as MarketStatus) || undefined,
                sort: sortFilter || undefined,
                q: searchInput || undefined,
              })
            }
            style={controlStyle}
          >
            {STATUSES.map((status) => (
              <option key={status} value={status}>
                {status || "All statuses"}
              </option>
            ))}
          </select>
        </label>

        <label style={{ display: "grid", gap: 6, fontSize: "0.8rem", color: "var(--color-text-muted)" }}>
          Sort
          <select
            value={sortFilter}
            onChange={(e) =>
              updateSearchParams(setSearchParams, {
                status: statusFilter || undefined,
                sort: (e.target.value as MarketListSort) || undefined,
                q: searchInput || undefined,
              })
            }
            style={controlStyle}
          >
            {SORTS.map((sort) => (
              <option key={sort} value={sort}>
                {sortLabel(sort)}
              </option>
            ))}
          </select>
        </label>
      </div>

      {isLoading && <LoadingPage />}
      {error && <ErrorMessage message={error instanceof Error ? error.message : "Failed to load markets"} />}

      {data && data.markets.length > 0 && (
        <div style={{ display: "flex", gap: "var(--space-lg)", fontSize: "0.8rem", color: "var(--color-text-muted)", marginBottom: "var(--space-md)" }}>
          <span>{data.markets.length} market{data.markets.length !== 1 ? "s" : ""}</span>
          {exchangeMode ? <span>Live net-venue prices</span> : (
            <>
              <span>Total Volume: {formatCurrency(data.markets.reduce((s, m) => s + m.volume, 0))}</span>
              <span>Total Liquidity: {formatCurrency(data.markets.reduce((s, m) => s + m.liquidity, 0))}</span>
            </>
          )}
        </div>
      )}

      {data && (
        <div style={{ display: "grid", gap: "var(--space-md)", gridTemplateColumns: "repeat(auto-fill, minmax(360px, 1fr))" }}>
          {data.markets.map((m) => {
            const instrument = instrumentsByNetMarket.get(m.id);
            return (
            <Link
              key={m.id}
              to={`/markets/${m.id}`}
              style={{
                display: "block",
                padding: "var(--space-md)",
                borderRadius: "var(--radius-md)",
                background: "var(--color-bg-surface)",
                border: "1px solid var(--color-border)",
                textDecoration: "none",
                color: "inherit",
                transition: "border-color 0.15s",
              }}
              onMouseEnter={(e) => (e.currentTarget.style.borderColor = "var(--color-primary)")}
              onMouseLeave={(e) => (e.currentTarget.style.borderColor = "var(--color-border)")}
            >
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "start", marginBottom: "var(--space-sm)" }}>
                <span style={{ fontWeight: 500, fontSize: "0.95rem" }}>{m.title}</span>
                <StatusBadge status={m.status} />
              </div>
              <PriceBar marginals={m.marginals} />
              {exchangeMode ? (
                <div style={{ display: "flex", gap: "var(--space-sm)", alignItems: "center", fontSize: "0.8rem", color: "var(--color-text-muted)" }}>
                  <span>Net venue</span>
                  {instrument && instrument.listings.length > 1 && (
                    <span
                      aria-label={`Available on ${instrument.listings.length} venues`}
                      style={{ padding: "2px 7px", borderRadius: 999, background: "var(--color-bg-hover)", color: "var(--color-primary)", fontSize: "0.7rem", fontWeight: 600 }}
                    >
                      {instrument.listings.map((listing) => listing.venue.toUpperCase()).join(" · ")}
                    </span>
                  )}
                </div>
              ) : (
                <div style={{ display: "flex", gap: "var(--space-lg)", fontSize: "0.8rem", color: "var(--color-text-muted)", marginBottom: "var(--space-sm)" }}>
                  <span>Vol {formatCurrency(m.volume)}</span>
                  <span>Liq {formatCurrency(m.liquidity)}</span>
                  <span>{timeUntil(m.expires_at)}</span>
                </div>
              )}
            </Link>
            );
          })}
        </div>
      )}

      {data && data.markets.length === 0 && (
        <div style={{ textAlign: "center", padding: "var(--space-xl)", color: "var(--color-text-muted)" }}>
          No markets found.
        </div>
      )}
    </div>
  );
}

/** One thin bar on a shared 0-100% scale: the market's P(yes). */
function PriceBar({ marginals }: { marginals?: Record<string, number> }) {
  if (!marginals) return null;
  const p = marginals["yes"] ?? Object.values(marginals)[0];
  if (typeof p !== "number") return null;
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: "var(--space-sm)" }}>
      <div style={{ flex: 1, height: 5, borderRadius: 2.5, background: "var(--color-border)", overflow: "hidden" }}>
        <div style={{ width: `${p * 100}%`, height: "100%", background: "var(--color-info)", borderRadius: "0 2.5px 2.5px 0" }} />
      </div>
      <span style={{ fontSize: "0.8rem", fontWeight: 600, fontVariantNumeric: "tabular-nums" }}>
        {(p * 100).toFixed(1)}%
      </span>
    </div>
  );
}

const controlStyle: React.CSSProperties = {
  padding: "8px 12px",
  borderRadius: "var(--radius-sm)",
  border: "1px solid var(--color-border)",
  background: "var(--color-bg)",
  color: "var(--color-text)",
  fontSize: "0.9rem",
  width: "100%",
  minHeight: 40,
};
