import { useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useMarkets, useNetwork } from "@/lib/query/hooks";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { LoadingPage, ErrorMessage } from "@/components/ui/Spinner";
import { ReconnectingHint } from "@/components/ui/ReconnectingHint";
import { formatCurrency, timeUntil } from "@/lib/utils/format";
import {
  isMarketListSort,
  isMarketListStatusFilter,
  marketListSearchParams,
  readMarketListFiltersFromSearchParams,
} from "@/lib/marketListFilters";
import { filterMarketList } from "@/lib/dataSource";
import type { MarketListSort, MarketStatus } from "@/lib/api/types";
import { isExchangeMode } from "@/lib/exchangeMode";
import { useInstruments } from "@/lib/exchange/hooks";
import {
  buildCategoryPills,
  categoryOfMarket,
  GROUP_COLORS,
  isMarketCategory,
  matchesMarketCategory,
  type MarketCategory,
} from "@/features/graph/mapLayout";

const STATUSES = ["", "active", "resolved", "closed", "draft"] as const;
const EXCHANGE_SORTS: Array<"" | MarketListSort> = ["", "volume", "liquidity", "probability", "linked"];
const PAPER_SORTS: Array<"" | MarketListSort> = ["", "volume", "liquidity", "created", "probability", "linked"];
const SEARCH_DEBOUNCE_MS = 300;

const CARD_CATEGORY_META: Record<
  Exclude<MarketCategory, "all">,
  { label: string; color: string }
> = {
  ftm: { label: "FTM", color: GROUP_COLORS.agi_rampup },
  dwarkesh: { label: "Dwarkesh", color: GROUP_COLORS.dwarkesh },
  policy: { label: "Policy", color: GROUP_COLORS.policy },
  futurist: { label: "Futurist", color: GROUP_COLORS.futurist },
  manifold: { label: "Manifold", color: GROUP_COLORS.external_other },
};

function sortLabel(sort: "" | MarketListSort) {
  if (sort === "") return "Default order";
  if (sort === "created") return "Newest";
  if (sort === "probability") return "Probability (High→Low)";
  if (sort === "linked") return "Linked";
  return sort.charAt(0).toUpperCase() + sort.slice(1);
}

function buildPageSearchParams(filters: {
  status?: MarketStatus;
  sort?: MarketListSort;
  q?: string;
  category?: MarketCategory;
}): URLSearchParams {
  const params = marketListSearchParams({
    status: filters.status,
    sort: filters.sort,
    q: filters.q,
  });
  if (filters.category && filters.category !== "all") {
    params.set("category", filters.category);
  }
  return params;
}

function updateSearchParams(
  setSearchParams: ReturnType<typeof useSearchParams>[1],
  filters: {
    status?: MarketStatus;
    sort?: MarketListSort;
    q?: string;
    category?: MarketCategory;
  },
  opts?: { replace?: boolean },
) {
  setSearchParams(buildPageSearchParams(filters), opts);
}

export default function MarketList() {
  const exchangeMode = isExchangeMode();
  const [searchParams, setSearchParams] = useSearchParams();
  const filters = readMarketListFiltersFromSearchParams(searchParams);
  const rawCategory = searchParams.get("category");
  const categoryFilter: MarketCategory =
    isMarketCategory(rawCategory) && rawCategory !== "all" ? rawCategory : "all";
  const statusFilter = filters.status ?? "";
  const sortFilter = filters.sort ?? "";
  const committedSearch = filters.q ?? "";
  const [searchInput, setSearchInput] = useState(committedSearch);
  const { data, isLoading, error } = useMarkets(filters);
  const networkQuery = useNetwork({ enabled: exchangeMode || sortFilter === "linked" });
  const instruments = useInstruments(exchangeMode);
  const instrumentsByNetMarket = new Map(instruments.data?.flatMap((instrument) =>
    instrument.listings
      .filter((listing) => listing.venue === "net")
      .map((listing) => [listing.marketId, instrument] as const),
  ));

  const linkCounts = useMemo(() => {
    const counts = new Map<string, number>();
    for (const edge of networkQuery?.data?.edges ?? []) {
      counts.set(edge.from, (counts.get(edge.from) ?? 0) + 1);
      counts.set(edge.to, (counts.get(edge.to) ?? 0) + 1);
    }
    return counts;
  }, [networkQuery?.data?.edges]);

  const categoryPills = useMemo(
    () => buildCategoryPills(data?.markets ?? []),
    [data?.markets],
  );

  // Apply category filter + client-side sorting when sorting by linked degree or probability.
  const displayedMarkets = useMemo(() => {
    if (!data) return undefined;
    const base =
      sortFilter === "linked" || sortFilter === "probability"
        ? filterMarketList(data, { sort: sortFilter }, linkCounts).markets
        : data.markets;
    if (categoryFilter === "all") return base;
    return base.filter((m) => matchesMarketCategory(m, categoryFilter));
  }, [data, sortFilter, linkCounts, categoryFilter]);

  const sortOptions = exchangeMode ? EXCHANGE_SORTS : PAPER_SORTS;

  useEffect(() => {
    const rawStatus = searchParams.get("status");
    const rawSort = searchParams.get("sort");
    const rawCat = searchParams.get("category");
    const next = buildPageSearchParams({
      status: isMarketListStatusFilter(rawStatus) && rawStatus !== "all" ? rawStatus : undefined,
      sort: isMarketListSort(rawSort) ? rawSort : undefined,
      q: searchParams.get("q") ?? undefined,
      category: isMarketCategory(rawCat) && rawCat !== "all" ? rawCat : undefined,
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
          category: categoryFilter !== "all" ? categoryFilter : undefined,
        },
        { replace: true },
      );
    }, SEARCH_DEBOUNCE_MS);

    return () => window.clearTimeout(handle);
  }, [categoryFilter, committedSearch, searchInput, setSearchParams, sortFilter, statusFilter]);

  return (
    <div style={{ minWidth: 0 }}>
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
          marginBottom: categoryPills.length > 0 ? "var(--space-md)" : "var(--space-lg)",
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
                category: categoryFilter !== "all" ? categoryFilter : undefined,
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
                category: categoryFilter !== "all" ? categoryFilter : undefined,
              })
            }
            style={controlStyle}
          >
            {sortOptions.map((sort) => (
              <option key={sort} value={sort}>
                {sortLabel(sort)}
              </option>
            ))}
          </select>
        </label>
      </div>

      {categoryPills.length > 0 && (
        <div
          role="group"
          aria-label="Filter markets by category"
          style={categoryBarStyle}
        >
          {categoryPills.map((pill) => {
            const isActive = categoryFilter === pill.key;
            return (
              <button
                key={pill.key}
                type="button"
                aria-pressed={isActive}
                onClick={() =>
                  updateSearchParams(setSearchParams, {
                    status: statusFilter || undefined,
                    sort: sortFilter || undefined,
                    q: searchInput || undefined,
                    category: pill.key === "all" ? undefined : pill.key,
                  })
                }
                style={categoryPillStyle(isActive, pill.color)}
              >
                {pill.color && (
                  <span
                    aria-hidden="true"
                    style={{
                      width: 7,
                      height: 7,
                      borderRadius: "50%",
                      background: isActive ? "#fff" : pill.color,
                      display: "inline-block",
                      flexShrink: 0,
                    }}
                  />
                )}
                <span>{pill.label}</span>
                <span style={{ opacity: isActive ? 0.9 : 0.65, fontVariantNumeric: "tabular-nums" }}>
                  {pill.count}
                </span>
              </button>
            );
          })}
        </div>
      )}

      {isLoading && <LoadingPage />}
      {error && !data && <ErrorMessage message={error instanceof Error ? error.message : "Failed to load markets"} />}
      {error && data && <ReconnectingHint />}

      {displayedMarkets && displayedMarkets.length > 0 && (
        <div style={{ display: "flex", flexWrap: "wrap", gap: "var(--space-lg)", fontSize: "0.8rem", color: "var(--color-text-muted)", marginBottom: "var(--space-md)" }}>
          <span>{displayedMarkets.length} market{displayedMarkets.length !== 1 ? "s" : ""}</span>
          {exchangeMode ? (
            <>
              <span>Live net-venue prices</span>
              {displayedMarkets.some((m) => m.volume > 0) && (
                <span>Total Volume: {formatCurrency(displayedMarkets.reduce((s, m) => s + m.volume, 0))} credits</span>
              )}
              {displayedMarkets.some((m) => m.liquidity > 0) && (
                <span>Total Liquidity: {formatCurrency(displayedMarkets.reduce((s, m) => s + m.liquidity, 0))} credits</span>
              )}
            </>
          ) : (
            <>
              <span>Total Volume: {formatCurrency(displayedMarkets.reduce((s, m) => s + m.volume, 0))}</span>
              <span>Total Liquidity: {formatCurrency(displayedMarkets.reduce((s, m) => s + m.liquidity, 0))}</span>
            </>
          )}
        </div>
      )}

      {displayedMarkets && (
        <div style={{ display: "grid", gap: "var(--space-md)", gridTemplateColumns: "repeat(auto-fill, minmax(min(360px, 100%), 1fr))" }}>
          {displayedMarkets.map((m) => {
            const instrument = instrumentsByNetMarket.get(m.id);
            const links = linkCounts.get(m.id) ?? 0;
            const cat = categoryOfMarket(m);
            const catMeta = cat !== "other" ? CARD_CATEGORY_META[cat] : undefined;
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
                  minWidth: 0,
                }}
                onMouseEnter={(e) => (e.currentTarget.style.borderColor = "var(--color-primary)")}
                onMouseLeave={(e) => (e.currentTarget.style.borderColor = "var(--color-border)")}
              >
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "start", gap: 8, marginBottom: "var(--space-sm)" }}>
                  <span style={{ fontWeight: 500, fontSize: "0.95rem" }}>{m.title}</span>
                  <div style={{ display: "inline-flex", alignItems: "center", gap: 6, flexShrink: 0 }}>
                    {catMeta && (
                      <span
                        style={{
                          padding: "2px 7px",
                          borderRadius: 999,
                          fontSize: "0.68rem",
                          fontWeight: 600,
                          border: `1px solid ${catMeta.color}`,
                          color: catMeta.color,
                          whiteSpace: "nowrap",
                        }}
                      >
                        {catMeta.label}
                      </span>
                    )}
                    <StatusBadge status={m.status} />
                  </div>
                </div>
                <PriceBar marginals={m.marginals} />
                {exchangeMode ? (
                  <div style={{ display: "flex", flexWrap: "wrap", gap: "var(--space-sm)", alignItems: "center", fontSize: "0.8rem", color: "var(--color-text-muted)" }}>
                    <span>Net venue</span>
                    {links > 0 && <span>· {links} link{links === 1 ? "" : "s"}</span>}
                    {m.volume > 0 && <span>· Vol {formatCurrency(m.volume)}</span>}
                    {m.liquidity > 0 && <span>· Liq {formatCurrency(m.liquidity)}</span>}
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

      {displayedMarkets && displayedMarkets.length === 0 && (
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

const categoryBarStyle: React.CSSProperties = {
  display: "flex",
  flexWrap: "wrap",
  alignItems: "center",
  gap: 8,
  marginBottom: "var(--space-lg)",
};

function categoryPillStyle(active: boolean, color?: string): React.CSSProperties {
  const accent = color ?? "var(--color-primary)";
  return {
    display: "inline-flex",
    alignItems: "center",
    gap: 6,
    padding: "5px 12px",
    borderRadius: 999,
    border: `1px solid ${active ? accent : "var(--color-border)"}`,
    background: active ? accent : "var(--color-bg-surface)",
    color: active ? "#fff" : "var(--color-text)",
    fontSize: "0.78rem",
    fontWeight: active ? 600 : 500,
    cursor: "pointer",
    transition: "border-color 0.15s, background 0.15s, color 0.15s",
  };
}
