import type { ApiClient } from "../../lib/api-client";
import { PageHeader } from "../../components/ui/page-header";
import { WorkbenchCard } from "../../components/ui/workbench-card";
import { PageEmptyState, PageErrorState, PageLoadingState } from "../../components/ui/page-state";
import { usePageData } from "../../lib/use-page-data";
import { NextStepsPanel } from "./next-steps-panel";
import { StockAnalysisPanel } from "./stock-analysis-panel";
import { WatchlistPanel } from "./watchlist-panel";

type WorkbenchPageProps = {
  client?: ApiClient;
};

export function WorkbenchPage({ client }: WorkbenchPageProps) {
  const resource = usePageData("workbench", client);

  if (resource.status === "loading" && !resource.data) {
    return <PageLoadingState title="工作台加载中" description="正在拉取我的关注、股票分析和下一步入口。" />;
  }

  if (resource.status === "error" && !resource.data) {
    return (
      <PageErrorState
        title="工作台加载失败"
        description={resource.error ?? "无法加载工作台数据，请稍后重试。"}
        actionLabel="重新加载"
        onAction={resource.refresh}
      />
    );
  }

  const snapshot = resource.data;
  if (!snapshot) {
    return <PageEmptyState title="工作台暂无数据" description="后台尚未返回工作台快照。" actionLabel="刷新" onAction={resource.refresh} />;
  }

  return (
    <div>
      <PageHeader
        eyebrow="Workbench"
        title="玄武AI智能体股票团队分析系统"
        description="先看我的关注，再继续做股票分析、发现股票、研究情报和量化验证。所有核心操作都围绕这一套单页面工作台展开。"
      />
      <div className="metric-grid">
        {snapshot.metrics.map((item) => (
          <WorkbenchCard className="metric-card" key={item.label}>
            <div className="metric-card__label">{item.label}</div>
            <div className="metric-card__value">{item.value}</div>
          </WorkbenchCard>
        ))}
      </div>
      <div className="workbench-layout">
        <div className="stack">
          <WatchlistPanel
            watchlist={snapshot.watchlist}
            quantCount={snapshot.watchlistMeta.quantCount}
            refreshHint={snapshot.watchlistMeta.refreshHint}
            onAddWatchlist={(code) => resource.runAction("add-watchlist", { code })}
            onRefresh={() => resource.runAction("refresh-watchlist")}
            onBatchQuant={(codes) => resource.runAction("batch-quant", { codes })}
            onClearSelection={() => resource.runAction("clear-selection")}
            onRemoveWatchlist={(code) => resource.runAction("delete-watchlist", { code })}
            onAnalyzeWatchlist={(code) => resource.runAction("analysis", { stockCode: code })}
          />
          <StockAnalysisPanel
            analysis={snapshot.analysis}
            onAnalyze={(payload) =>
              resource.runAction("analysis", {
                stockCode: payload.symbol,
                analysts: payload.analysts,
                mode: payload.mode,
                cycle: payload.cycle,
              })
            }
            onBatchAnalyze={(payload) =>
              resource.runAction("analysis-batch", {
                stockCodes: payload.stockCodes,
                analysts: payload.analysts,
                mode: payload.mode,
                cycle: payload.cycle,
              })
            }
            onClearInput={() => undefined}
          />
        </div>
        <NextStepsPanel steps={snapshot.nextSteps} />
      </div>
      <WorkbenchCard className="page-footer-card">
        <div className="summary-item__title">最近活动</div>
        <div className="timeline">
          {snapshot.activity.map((item) => (
            <div className="timeline__item" key={`${item.time}-${item.title}`}>
              <div className="timeline__time">{item.time}</div>
              <div className="timeline__content">
                <strong>{item.title}</strong> · {item.body}
              </div>
            </div>
          ))}
        </div>
      </WorkbenchCard>
    </div>
  );
}
