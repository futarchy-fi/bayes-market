import { useEffect } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { AccountPnlSection } from "@/features/analytics/AccountPnlSection";
import { AnalyticsFilters } from "@/features/analytics/AnalyticsFilters";
import { AnalyticsSummaryCards } from "@/features/analytics/AnalyticsSummaryCards";
import { PriceChart } from "@/features/analytics/PriceChart";
import { TraderLeaderboard } from "@/features/analytics/TraderLeaderboard";
import { VolumeChart } from "@/features/analytics/VolumeChart";
import { useSession } from "@/features/session/context";
import type { AnalyticsInterval, MarketSummary } from "@/lib/api/types";
import { useAccountPnl, useMarketAnalytics, useMarkets } from "@/lib/query/hooks";
import { ErrorMessage, LoadingPage } from "@/components/ui/Spinner";
import { ReconnectingHint } from "@/components/ui/ReconnectingHint";
import { isExchangeMode } from "@/lib/exchangeMode";
import { ExchangeUnavailable } from "@/components/ui/ExchangeUnavailable";

function isAnalyticsInterval(value: string | null): value is AnalyticsInterval {
  return value === "hour" || value === "day";
}

function preferredMarket(markets: MarketSummary[]): MarketSummary | undefined {
  return markets.find((market) => market.status === "active") ?? markets[0];
}

export default function Analytics() {
  const exchangeMode = isExchangeMode();
  const { session } = useSession();
  const marketsQuery = useMarkets();
  const pnlQuery = useAccountPnl(session.accountId, { enabled: !exchangeMode });
  const [searchParams, setSearchParams] = useSearchParams();

  const interval: AnalyticsInterval = isAnalyticsInterval(searchParams.get("interval")) ? (searchParams.get("interval") as AnalyticsInterval) : "day";
  const markets = marketsQuery.data?.markets ?? [];
  const selectedMarket = markets.find((market) => market.id === searchParams.get("market")) ?? preferredMarket(markets);
  const selectedMarketId = selectedMarket?.id ?? "";
  const analyticsQuery = useMarketAnalytics(selectedMarketId, {
    enabled: !exchangeMode && selectedMarketId.length > 0,
    interval,
  });

  useEffect(() => {
    if (!selectedMarketId) {
      return;
    }

    const next = new URLSearchParams(searchParams);
    let changed = false;

    if (next.get("market") !== selectedMarketId) {
      next.set("market", selectedMarketId);
      changed = true;
    }

    if (!isAnalyticsInterval(next.get("interval"))) {
      next.set("interval", interval);
      changed = true;
    }

    if (changed) {
      setSearchParams(next, { replace: true });
    }
  }, [interval, searchParams, selectedMarketId, setSearchParams]);

  if (exchangeMode) {
    return (
      <div style={{ display: "grid", gap: "var(--space-lg)" }}>
        <h1 style={{ fontSize: "1.6rem", fontWeight: 600 }}>Market Analytics</h1>
        <ExchangeUnavailable title="Analytics" />
      </div>
    );
  }

  if (marketsQuery.isLoading && markets.length === 0) {
    return <LoadingPage />;
  }

  if (marketsQuery.error && !marketsQuery.data) {
    return <ErrorMessage message={marketsQuery.error instanceof Error ? marketsQuery.error.message : "Failed to load markets"} />;
  }

  if (markets.length === 0) {
    return (
      <div style={emptyStateStyle}>
        No markets exist yet. Create a market before loading analytics.
        <div style={{ marginTop: "var(--space-sm)" }}>
          <Link to="/markets/new">Create a market</Link>
        </div>
      </div>
    );
  }

  function updateParams(nextValues: { market?: string; interval?: AnalyticsInterval }) {
    const next = new URLSearchParams(searchParams);
    if (nextValues.market) {
      next.set("market", nextValues.market);
    }
    if (nextValues.interval) {
      next.set("interval", nextValues.interval);
    }
    setSearchParams(next);
  }

  return (
    <div style={{ display: "grid", gap: "var(--space-lg)" }}>
      {marketsQuery.error && <ReconnectingHint />}
      <div style={{ display: "grid", gap: "var(--space-xs)" }}>
        <h1 style={{ fontSize: "1.6rem", fontWeight: 600 }}>Market Analytics</h1>
        <p style={introStyle}>
          Track multi-outcome price history, accepted activity volume, top traders, and optional account mark-to-market from one top-level route.
        </p>
      </div>

      <AnalyticsFilters
        markets={markets}
        selectedMarket={selectedMarket}
        selectedMarketId={selectedMarketId}
        interval={interval}
        onMarketChange={(marketId) => updateParams({ market: marketId })}
        onIntervalChange={(nextInterval) => updateParams({ interval: nextInterval })}
      />

      {analyticsQuery.isLoading && !analyticsQuery.data && <LoadingPage />}

      {analyticsQuery.error && !analyticsQuery.data && (
        <ErrorMessage message={analyticsQuery.error instanceof Error ? analyticsQuery.error.message : "Failed to load analytics"} />
      )}

      {analyticsQuery.data && (
        <>
          {analyticsQuery.error && <ReconnectingHint />}
          <AnalyticsSummaryCards summary={analyticsQuery.data.summary} />
          <PriceChart series={analyticsQuery.data.priceSeries} interval={interval} />
          <div style={{ display: "grid", gap: "var(--space-lg)", gridTemplateColumns: "repeat(auto-fit, minmax(320px, 1fr))", alignItems: "start" }}>
            <VolumeChart buckets={analyticsQuery.data.volumeBuckets} interval={interval} />
            <TraderLeaderboard rows={analyticsQuery.data.topTraders} />
          </div>
        </>
      )}

      <AccountPnlSection
        accountId={session.accountId}
        selectedMarketId={selectedMarketId}
        data={pnlQuery.data}
        isLoading={pnlQuery.isLoading}
        error={pnlQuery.error}
      />
    </div>
  );
}

const introStyle: React.CSSProperties = {
  color: "var(--color-text-muted)",
  maxWidth: 760,
};

const emptyStateStyle: React.CSSProperties = {
  textAlign: "center",
  padding: "var(--space-xl)",
  color: "var(--color-text-muted)",
};
