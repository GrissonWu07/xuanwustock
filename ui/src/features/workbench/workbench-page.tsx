import { useCallback, useEffect, useRef, useState } from "react";
import { apiClient, type ApiClient } from "../../lib/api-client";
import { PageHeader } from "../../components/ui/page-header";
import { WorkbenchCard } from "../../components/ui/workbench-card";
import { PageEmptyState, PageErrorState, PageLoadingState } from "../../components/ui/page-state";
import { usePageData } from "../../lib/use-page-data";
import { NextStepsPanel } from "./next-steps-panel";
import { WatchlistPanel } from "./watchlist-panel";
import { t } from "../../lib/i18n";
import { useCompactLayout } from "../../lib/use-compact-layout";

type WorkbenchPageProps = {
  client?: ApiClient;
};

const WORKBENCH_AUTO_REFRESH_MS = 3 * 60 * 1000;
const WORKBENCH_INITIAL_TABLE_QUERY = { search: "", page: 1, pageSize: 20 };
const queryKey = (query: { search: string; page: number; pageSize: number }) => `${query.search}\u0000${query.page}\u0000${query.pageSize}`;

export function WorkbenchPage({ client }: WorkbenchPageProps) {
  const isCompactLayout = useCompactLayout();
  const activeClient = client ?? apiClient;
  const resource = usePageData("workbench", activeClient, WORKBENCH_INITIAL_TABLE_QUERY);
  const [tableSnapshot, setTableSnapshot] = useState<typeof resource.data | null>(null);
  const [watchlistQuery, setWatchlistQuery] = useState({ search: "", page: 1, pageSize: 20 });
  const lastWatchlistQueryKey = useRef(queryKey(WORKBENCH_INITIAL_TABLE_QUERY));
  const snapshot =
    resource.data && tableSnapshot
      ? {
          ...resource.data,
          watchlist: tableSnapshot.watchlist,
          watchlistMeta: tableSnapshot.watchlistMeta ?? resource.data.watchlistMeta,
        }
      : (resource.data ?? tableSnapshot);
  useEffect(() => {
    const timer = window.setInterval(() => {
      void activeClient.getPageSnapshot("workbench", watchlistQuery).then((next) => setTableSnapshot(next as typeof resource.data)).catch(() => undefined);
    }, WORKBENCH_AUTO_REFRESH_MS);
    return () => window.clearInterval(timer);
  }, [activeClient, watchlistQuery]);

  const handleWatchlistTableQuery = useCallback(
    (query: { search: string; page: number; pageSize: number }) => {
      const nextKey = queryKey(query);
      setWatchlistQuery(query);
      if (lastWatchlistQueryKey.current === nextKey) {
        return;
      }
      lastWatchlistQueryKey.current = nextKey;
      void activeClient.getPageSnapshot("workbench", query).then((next) => setTableSnapshot(next as typeof resource.data)).catch(() => undefined);
    },
    [activeClient],
  );

  if (resource.status === "loading" && !resource.data) {
    return <PageLoadingState title={t("Workbench loading...")} description="正在加载关注池和下一步入口。" />;
  }

  if (resource.status === "error" && !resource.data) {
    return (
      <PageErrorState
        title={t("Workbench failed to load")}
        description={resource.error ?? t("Unable to load workbench data. Please retry later.")}
        actionLabel={t("Refresh")}
        onAction={resource.refresh}
      />
    );
  }

  if (!snapshot) {
    return <PageEmptyState title={t("Workbench has no data")} description={t("Backend has not returned a workbench snapshot yet.")} actionLabel={t("Refresh")} onAction={resource.refresh} />;
  }

  const handleRefreshWatchlist = async (codes: string[]) => {
    if (codes.length === 0) return;
    await resource.runAction("refresh-watchlist", { codes, fullRefresh: true, triggerAt: Date.now() });
    await resource.refresh();
    setTableSnapshot(null);
  };

  return (
    <div>
      <PageHeader
        eyebrow={t("AI Stock Analyst Team")}
        title={t("Workbench")}
        description="先维护关注池，再进入股票详情完成单股分析、发现、研究和量化验证。"
      />
      <div className="metric-grid">
        {snapshot.metrics.map((item) => (
          <WorkbenchCard className="metric-card" key={item.label}>
            <div className="metric-card__label">{t(item.label)}</div>
            <div className="metric-card__value">{item.value}</div>
          </WorkbenchCard>
        ))}
      </div>
      <div className="workbench-layout">
        <div className="stack">
          <WatchlistPanel
            watchlist={snapshot.watchlist}
            onAddWatchlist={async (code) => {
              const result = await resource.runAction("add-watchlist", { code });
              if (!result) {
                throw new Error(resource.error ?? t("Invalid stock code"));
              }
              setTableSnapshot(null);
            }}
            onRefresh={(codes) => {
              void handleRefreshWatchlist(codes);
            }}
            onBatchQuant={(codes) => {
              void resource.runAction("batch-quant", { codes }).then(() => setTableSnapshot(null));
            }}
            onBatchRemoveWatchlist={(codes) => {
              void resource.runAction("delete-watchlist", { codes }).then(() => setTableSnapshot(null));
            }}
            onBatchPortfolio={async (codes, options) => {
              await resource.runAction("batch-portfolio", {
                codes,
                costPrice: options?.costPrice,
                quantity: options?.quantity,
              });
              setTableSnapshot(null);
            }}
            onClearSelection={() => {
              void resource.runAction("clear-selection");
            }}
            onTableQueryChange={handleWatchlistTableQuery}
          />
          {isCompactLayout ? <NextStepsPanel steps={snapshot.nextSteps} /> : null}
        </div>
        {!isCompactLayout ? <NextStepsPanel steps={snapshot.nextSteps} /> : null}
      </div>
    </div>
  );
}
