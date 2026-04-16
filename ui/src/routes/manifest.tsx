import type { ReactNode } from "react";
import { WorkbenchPage } from "../features/workbench/workbench-page";
import { DiscoverPage } from "../features/discover/discover-page";
import { ResearchPage } from "../features/research/research-page";
import { PortfolioPage } from "../features/portfolio/portfolio-page";
import { LiveSimPage } from "../features/quant/live-sim-page";
import { HisReplayPage } from "../features/quant/his-replay-page";
import { AiMonitorPage } from "../features/monitor/ai-monitor-page";
import { RealMonitorPage } from "../features/monitor/real-monitor-page";
import { SettingsPage } from "../features/settings/settings-page";

export type AppRouteItem = {
  path: string;
  labelKey: string;
  groupKey: string;
  element: ReactNode;
};

export const APP_ROUTE_ITEMS: AppRouteItem[] = [
  { path: "/main", labelKey: "Workbench", groupKey: "Workbench", element: <WorkbenchPage /> },
  { path: "/discover", labelKey: "Discover", groupKey: "Discover", element: <DiscoverPage /> },
  { path: "/research", labelKey: "Research", groupKey: "Discover", element: <ResearchPage /> },
  { path: "/portfolio", labelKey: "Portfolio", groupKey: "Portfolio", element: <PortfolioPage /> },
  { path: "/live-sim", labelKey: "Quant simulation", groupKey: "Portfolio", element: <LiveSimPage /> },
  { path: "/his-replay", labelKey: "Historical replay", groupKey: "Portfolio", element: <HisReplayPage /> },
  { path: "/ai-monitor", labelKey: "AI monitor", groupKey: "Portfolio", element: <AiMonitorPage /> },
  { path: "/real-monitor", labelKey: "Real-time monitor", groupKey: "Portfolio", element: <RealMonitorPage /> },
  { path: "/settings", labelKey: "Settings", groupKey: "Settings", element: <SettingsPage /> },
];

export const APP_ROUTE_LABELS = Object.fromEntries(
  APP_ROUTE_ITEMS.map((item) => [item.path, item.labelKey]),
) as Record<string, string>;
