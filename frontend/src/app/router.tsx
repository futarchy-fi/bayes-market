import { createBrowserRouter } from "react-router-dom";
import { AppLayout } from "./App";
import { routerFuture } from "./routerFuture";
import Landing from "@/routes/Landing";
import MarketList from "@/routes/MarketList";
import MarketDetail from "@/routes/MarketDetail";
import Portfolio from "@/routes/Portfolio";
import System from "@/routes/System";
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
        { path: "system", element: <System /> },
      ],
    },
  ],
  {
    future: routerFuture,
  },
);
