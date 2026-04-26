import { createBrowserRouter, Navigate } from "react-router-dom";
import { AppShell } from "../App";
import { APP_ROUTE_ITEMS } from "./manifest";
import { SignalDetailPage } from "../features/quant/signal-detail-page";
import { PortfolioPositionPage } from "../features/portfolio/portfolio-position-page";

export const router = createBrowserRouter([
  { path: "/", element: <Navigate to="/main" replace /> },
  { path: "/workbench", element: <Navigate to="/main" replace /> },
  {
    element: <AppShell />,
    children: [
      ...APP_ROUTE_ITEMS.map((item) => ({ path: item.path, element: item.element })),
      { path: "/portfolio/position/:symbol", element: <PortfolioPositionPage /> },
      { path: "/signal-detail/:signalId", element: <SignalDetailPage /> },
    ],
  },
]);
