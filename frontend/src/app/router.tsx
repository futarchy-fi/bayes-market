import { createBrowserRouter } from "react-router-dom";
import { AppLayout } from "./App";
import { routerFuture } from "./routerFuture";
import Landing from "@/routes/Landing";
import MarketList from "@/routes/MarketList";
import MarketDetail from "@/routes/MarketDetail";
import Portfolio from "@/routes/Portfolio";
import System from "@/routes/System";
import Compare from "@/routes/Compare";
import ExchangeCallback from "@/routes/ExchangeCallback";
import Leaderboard from "@/routes/Leaderboard";
import Instruments from "@/routes/Instruments";
import InstrumentDetail from "@/routes/InstrumentDetail";
import { CreateMarketForm } from "@/features/market/CreateMarketForm";

export const router = createBrowserRouter(
  [
    {
      element: <AppLayout />,
      children: [
        { index: true, element: <Landing /> },
        { path: "markets", element: <MarketList /> },
        { path: "markets/new", element: <CreateMarketForm /> },
        { path: "markets/:marketId", element: <MarketDetail /> },
        { path: "portfolio", element: <Portfolio /> },
        { path: "compare", element: <Compare /> },
        { path: "leaderboard", element: <Leaderboard /> },
        { path: "instruments", element: <Instruments /> },
        { path: "instruments/:instrumentId", element: <InstrumentDetail /> },
        { path: "exchange/callback", element: <ExchangeCallback /> },
        { path: "system", element: <System /> },
      ],
    },
  ],
  {
    future: routerFuture,
  },
);
