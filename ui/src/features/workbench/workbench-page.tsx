import { useCallback, useEffect, useState } from "react";
import { apiClient, type ApiClient } from "../../lib/api-client";
import { PageHeader } from "../../components/ui/page-header";
import { WorkbenchCard } from "../../components/ui/workbench-card";
import { PageEmptyState, PageErrorState, PageLoadingState } from "../../components/ui/page-state";
import { usePageData } from "../../lib/use-page-data";
import { NextStepsPanel } from "./next-steps-panel";
import { StockAnalysisPanel } from "./stock-analysis-panel";
import { WatchlistPanel } from "./watchlist-panel";
import { t } from "../../lib/i18n";
import { useCompactLayout } from "../../lib/use-compact-layout";

type WorkbenchPageProps = {
  client?: ApiClient;
};

const DEFAULT_ANALYSTS = ["technical", "fundamental", "fund_flow", "risk"];

export function WorkbenchPage({ client }: WorkbenchPageProps) {
  const isCompactLayout = useCompactLayout();
  const activeClient = client ?? apiClient;
  const resource = usePageData("workbench", activeClient);
  const [tableSnapshot, setTableSnapshot] = useState<typeof resource.data | null>(null);
  const snapshot = tableSnapshot ?? resource.data;
  const analysisJob = snapshot?.analysisJob ?? null;
  const [localAnalysisPending, setLocalAnalysisPending] = useState(false);
  const [analysisInputSeed, setAnalysisInputSeed] = useState("");
  const analysisBusy = Boolean(analysisJob && ["queued", "running"].includes(analysisJob.status));
  const analysisSummary = snapshot?.analysis?.summaryBody?.trim() ?? "";
  const analysisDecision = (snapshot?.analysis?.finalDecisionText ?? snapshot?.analysis?.decision ?? "").trim();
  const placeholderTexts = new Set([
    "",
    t("Add symbols to watchlist first, then start analysis."),
    t("Enter stock code to generate full analysis results."),
    t("Enter stock code before viewing analysis."),
    t("Analysis completed."),
  ]);
  const hasUsableAnalysis = Boolean(
    snapshot?.analysis?.generatedAt ||
      (analysisSummary && !placeholderTexts.has(analysisSummary)) ||
      (analysisDecision && !placeholderTexts.has(analysisDecision)) ||
      snapshot?.analysis?.analystViews?.length ||
      snapshot?.analysis?.results?.length,
  );
  const showAnalysisBusy = localAnalysisPending || analysisBusy;
  const analysisBusyMessage = analysisJob?.message ?? t("Starting...");
  const analysisRefreshFailure =
    analysisJob?.status === "failed" && hasUsableAnalysis
      ? {
          title: t("Refresh failed most recently"),
          body: analysisJob.message ?? t("Currently showing the latest successful analysis."),
          generatedAt: snapshot?.analysis?.generatedAt ?? "",
        }
      : null;

  useEffect(() => {
    // Poll only when backend provides async task states, to avoid overriding sync analysis by default snapshots.
    if (!analysisBusy) return undefined;
    const timer = window.setInterval(() => {
      void resource.refresh();
    }, 2000);
    return () => window.clearInterval(timer);
  }, [analysisBusy, resource.refresh]);

  useEffect(() => {
    if (analysisBusy) return;
    setLocalAnalysisPending(false);
  }, [analysisBusy]);

  useEffect(() => {
    const timer = window.setInterval(() => {
      void resource.refresh();
    }, 5 * 60 * 1000);
    return () => window.clearInterval(timer);
  }, [resource.refresh]);

  const handleWatchlistTableQuery = useCallback(
    (query: { search: string; page: number; pageSize: number }) => {
      void activeClient.getPageSnapshot("workbench", query).then((next) => setTableSnapshot(next as typeof resource.data)).catch(() => undefined);
    },
    [activeClient],
  );

  if (resource.status === "loading" && !resource.data) {
    return <PageLoadingState title={t("Workbench loading...")} description={t("Loading watchlist, stock analysis, and next-step entries.")} />;
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

  const handleAnalyze = async (payload: { symbol: string; analysts: string[]; mode: string; cycle: string }) => {
    if (showAnalysisBusy) return;
    setLocalAnalysisPending(true);
    try {
      await resource.runAction("analysis", {
        stockCode: payload.symbol,
        analysts: payload.analysts,
        mode: payload.mode,
        cycle: payload.cycle,
      });
    } finally {
      setLocalAnalysisPending(false);
    }
  };

  const handleBatchAnalyze = async (payload: { stockCodes: string[]; analysts: string[]; mode: string; cycle: string }) => {
    if (showAnalysisBusy) return;
    setLocalAnalysisPending(true);
    try {
      await resource.runAction("analysis-batch", {
        stockCodes: payload.stockCodes,
        analysts: payload.analysts,
        mode: payload.mode,
        cycle: payload.cycle,
      });
    } finally {
      setLocalAnalysisPending(false);
    }
  };

  const handleBatchFillAnalysisInput = (codes: string[]) => {
    const normalized = Array.from(new Set(codes.map((item) => item.trim()).filter(Boolean)));
    if (normalized.length === 0) return;
    setAnalysisInputSeed(normalized.join(","));
  };

  const handleBatchAnalyzeFromWatchlist = (codes: string[]) => {
    const normalized = Array.from(new Set(codes.map((item) => item.trim()).filter(Boolean)));
    if (normalized.length === 0) return;
    handleBatchFillAnalysisInput(normalized);
    const cycle = snapshot.analysis.cycle;
    if (normalized.length === 1) {
      void handleAnalyze({
        symbol: normalized[0],
        analysts: defaultAnalysts,
        mode: t("Single analysis"),
        cycle,
      });
      return;
    }
    void handleBatchAnalyze({
      stockCodes: normalized,
      analysts: defaultAnalysts,
      mode: t("Batch analysis"),
      cycle,
    });
  };

  const handleRefreshWatchlist = async (codes: string[]) => {
    if (codes.length === 0) return;
    await resource.runAction("refresh-watchlist", { codes, fullRefresh: true, triggerAt: Date.now() });
    await resource.refresh();
  };

  const defaultAnalysts = (() => {
    const selected = snapshot.analysis.analysts.filter((item) => item.selected).map((item) => item.value);
    return selected.length > 0 ? selected : DEFAULT_ANALYSTS;
  })();

  return (
    <div>
      <PageHeader
        eyebrow={t("AI Stock Analyst Team")}
        title={t("Workbench")}
        description={t("Start with watchlist, then continue with stock analysis, discovery, research, and quant validation on this page.")}
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
            }}
            onRefresh={(codes) => {
              void handleRefreshWatchlist(codes);
            }}
            onBatchQuant={(codes) => {
              void resource.runAction("batch-quant", { codes });
            }}
            onBatchPortfolio={async (codes, options) => {
              await resource.runAction("batch-portfolio", {
                codes,
                costPrice: options?.costPrice,
                quantity: options?.quantity,
              });
            }}
            onBatchAnalyze={handleBatchAnalyzeFromWatchlist}
            analysisBusy={showAnalysisBusy}
            analysisBusyMessage={analysisBusyMessage}
            onClearSelection={() => {
              void resource.runAction("clear-selection");
            }}
            onRemoveWatchlist={(code) => {
              void resource.runAction("delete-watchlist", { code });
            }}
            onTableQueryChange={handleWatchlistTableQuery}
          />
          <StockAnalysisPanel
            analysis={snapshot.analysis}
            analysisJob={analysisJob}
            busy={showAnalysisBusy}
            busyMessage={analysisBusyMessage}
            refreshFailure={analysisRefreshFailure}
            inputSeed={analysisInputSeed}
            onAnalyze={handleAnalyze}
            onBatchAnalyze={handleBatchAnalyze}
            onClearInput={() => undefined}
          />
          {isCompactLayout ? <NextStepsPanel steps={snapshot.nextSteps} /> : null}
        </div>
        {!isCompactLayout ? <NextStepsPanel steps={snapshot.nextSteps} /> : null}
      </div>
    </div>
  );
}
