import { createBrowserRouter, Navigate } from "react-router-dom";
import { AppLayout } from "./App";
import MarketList from "@/routes/MarketList";
import MarketDetail from "@/routes/MarketDetail";
import Portfolio from "@/routes/Portfolio";
import { CreateMarketForm } from "@/features/market/CreateMarketForm";

export const router = createBrowserRouter([
  {
    element: <AppLayout />,
    children: [
      { index: true, element: <Navigate to="/markets" replace /> },
      { path: "markets", element: <MarketList /> },
      { path: "markets/new", element: <CreateMarketForm /> },
      { path: "markets/:marketId", element: <MarketDetail /> },
      { path: "portfolio", element: <Portfolio /> },
    ],
  },
]);
