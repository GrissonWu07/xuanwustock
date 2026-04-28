import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { apiClient, type ApiClient } from "../../lib/api-client";
import { PageHeader } from "../../components/ui/page-header";
import { WorkbenchCard } from "../../components/ui/workbench-card";
import { PageEmptyState, PageErrorState, PageLoadingState } from "../../components/ui/page-state";
import { Sparkline } from "../../components/ui/sparkline";
import { usePageData } from "../../lib/use-page-data";
import type { ReplayCapitalPoolSnapshot, ReplaySnapshot, TableAction, TableRow, TableSection } from "../../lib/page-models";
import { summarizeTaskStatuses, toDisplayText } from "./quant-display";
import { QuantTableSectionCard } from "./quant-table-section";
import { ReplayCapitalPoolPanel } from "./replay-capital-pool-panel";

const REPLAY_MODE_OPTIONS = [
  { value: "historical_range", label: "历史区间回放" },
  { value: "continuous_to_live", label: "从过去接续到实时自动模拟" },
];

const TIMEFRAME_OPTIONS = [
  { value: "30m", label: "30分钟" },
  { value: "1d", label: "日线" },
  { value: "1d+30m", label: "日线方向 + 30分钟确认" },
];

const AI_DYNAMIC_STRATEGY_OPTIONS = [
  { value: "off", label: "关闭" },
  { value: "hybrid", label: "开启" },
];

const MARKET_OPTIONS = ["CN", "HK", "US"] as const;
const REPLAY_PROGRESS_REFRESH_MS = 60 * 1000;
const REPLAY_CHECKPOINT_PAGE_SIZE = 50;
const REPLAY_SUMMARY_METRIC_LABELS = new Set([
  "初始资金",
  "最终权益",
  "最终现金",
  "持仓市值",
  "浮动盈亏",
  "总盈亏",
  "总收益率",
  "期末持仓数",
  "期末清算毛额",
  "期末清算费用",
  "期末清算盈亏",
  "清算后现金",
  "清算后总盈亏",
  "清算后收益率",
]);
type ReplayProgressSnapshot = Pick<ReplaySnapshot, "updatedAt" | "tasks"> &
  Partial<Pick<ReplaySnapshot, "holdings" | "trades" | "signals" | "tradeCostSummary">>;

function parseDateRange(range: string) {
  const match = String(range).match(/(\d{4}-\d{2}-\d{2})\s*->\s*(\d{4}-\d{2}-\d{2}|now)/);
  return {
    startDate: match?.[1] ?? "2026-03-11",
    endDate: match?.[2] && match[2] !== "now" ? match[2] : "2026-04-10",
  };
}

function parseReplayMode(value: string) {
  const normalized = String(value).trim().toLowerCase();
  return normalized === "continuous_to_live" || normalized.includes("接续") ? "continuous_to_live" : "historical_range";
}

function localizeReplayMode(value: string) {
  const normalized = parseReplayMode(value);
  return REPLAY_MODE_OPTIONS.find((option) => option.value === normalized)?.label ?? value ?? "--";
}

function normalizeTimeframe(value: string) {
  const normalized = String(value).trim().toLowerCase();
  return TIMEFRAME_OPTIONS.find((option) => option.value === normalized)?.value ?? "30m";
}

function parseRatePercent(value: string | undefined, fallback: number) {
  const match = String(value ?? "").match(/-?\d+(\.\d+)?/);
  if (!match) return fallback;
  const parsed = Number(match[0]);
  if (!Number.isFinite(parsed)) return fallback;
  return Math.max(0, parsed);
}

function parseMoney(value: string | undefined, fallback: number) {
  const normalized = String(value ?? "").replace(/,/g, "");
  const match = normalized.match(/-?\d+(\.\d+)?/);
  if (!match) return fallback;
  const parsed = Number(match[0]);
  if (!Number.isFinite(parsed)) return fallback;
  return Math.max(0, Math.round(parsed));
}

function normalizeMarket(value: string) {
  const normalized = String(value).trim().toUpperCase();
  return MARKET_OPTIONS.includes(normalized as (typeof MARKET_OPTIONS)[number]) ? normalized : "CN";
}

function normalizeAiDynamicStrategy(value: string) {
  const normalized = String(value).trim().toLowerCase();
  if (!normalized || normalized === "off" || normalized.includes("关")) return "off";
  if (normalized === "template" || normalized === "weights" || normalized === "hybrid" || normalized.includes("开")) return "hybrid";
  return "off";
}

function parseDynamicStrength(value: string | undefined, fallback: number) {
  const match = String(value ?? "").match(/-?\d+(\.\d+)?/);
  if (!match) return fallback;
  const parsed = Number(match[0]);
  if (!Number.isFinite(parsed)) return fallback;
  if (parsed > 1) return Math.max(0, Math.min(1, parsed / 100));
  return Math.max(0, Math.min(1, parsed));
}

function parseDynamicLookback(value: string | undefined, fallback: number) {
  const match = String(value ?? "").match(/\d+/);
  if (!match) return fallback;
  const parsed = Number(match[0]);
  if (!Number.isFinite(parsed)) return fallback;
  return Math.max(6, Math.min(336, Math.round(parsed)));
}

function formatSummaryNumber(value: unknown, fallback = "--") {
  if (typeof value === "number" && Number.isFinite(value)) {
    return value.toFixed(2);
  }
  return toDisplayText(value, fallback);
}

function formatSummaryPercent(value: unknown, fallback = "--") {
  if (typeof value === "number" && Number.isFinite(value)) {
    return `${value.toFixed(2)}%`;
  }
  return toDisplayText(value, fallback);
}

function findMetricValue(metrics: ReplaySnapshot["tradeCostSummary"], label: string) {
  return metrics?.find((metric) => metric.label === label)?.value;
}

function pickPreferredReplayTaskId(
  tasks: Array<{ id: string; status?: string }>,
  previousId = "",
) {
  const activeTask = tasks.find((task) => {
    const normalized = String(task.status || "").trim().toLowerCase();
    return normalized === "running" || normalized === "queued";
  });
  if (activeTask) {
    return activeTask.id;
  }
  if (previousId && tasks.some((task) => task.id === previousId)) {
    return previousId;
  }
  return tasks[0]?.id ?? "";
}

function mergeReplayProgress(snapshot: ReplaySnapshot, progress: ReplayProgressSnapshot | null): ReplaySnapshot {
  if (!progress) {
    return snapshot;
  }

  const existingTasks = new Map(snapshot.tasks.map((task) => [task.id, task]));
  const refreshedTaskIds = new Set(progress.tasks.map((task) => task.id));
  const refreshedTasks = progress.tasks.map((task) => {
    const previous = existingTasks.get(task.id);
    return {
      ...(previous ?? {}),
      ...task,
      holdings: task.holdings ?? previous?.holdings,
    };
  });

  return {
    ...snapshot,
    updatedAt: progress.updatedAt || snapshot.updatedAt,
    tasks: [...refreshedTasks, ...snapshot.tasks.filter((task) => !refreshedTaskIds.has(task.id))],
    holdings: progress.holdings ?? snapshot.holdings,
    trades: progress.trades ?? snapshot.trades,
    signals: progress.signals ?? snapshot.signals,
    tradeCostSummary: progress.tradeCostSummary ?? snapshot.tradeCostSummary,
  };
}

function parseReplayStageLabel(stage: string) {
  const text = String(stage || "").trim();
  const match = text.match(/^检查点\s+(.+?)：\s*(.+)$/);
  if (!match) {
    return { checkpoint: "", detail: text || "--" };
  }
  return {
    checkpoint: `检查点 ${match[1]}`,
    detail: match[2],
  };
}

type HisReplayPageProps = {
  client?: ApiClient;
};

const PAGE_SIZE = 20;

function localizeTaskStatus(status: string) {
  const normalized = String(status || "").trim().toLowerCase();
  if (normalized === "completed") return "已完成";
  if (normalized === "running") return "进行中";
  if (normalized === "queued") return "排队中";
  if (normalized === "cancelled" || normalized === "canceled") return "已取消";
  if (normalized === "failed") return "失败";
  return status || "--";
}

function normalizeAction(cell: string) {
  return String(cell || "").trim().toUpperCase();
}

function withCodeName(rows: TableRow[], codeColumnIndex: number): TableRow[] {
  return rows.map((row) => {
    const code = String(row.code ?? row.cells[codeColumnIndex] ?? "").trim();
    const name = String(row.name ?? "").trim();
    const merged = name && name !== code ? `${code} ${name}` : code;
    const cells = row.cells.map((cell, index) => (index === codeColumnIndex ? merged : cell));
    return { ...row, cells };
  });
}

function removeExecutionResultColumn(table: TableSection): TableSection {
  const targetIndex = table.columns.findIndex((column) => {
    const normalized = String(column || "").trim().toLowerCase();
    return normalized === "执行结果" || normalized === "execution result";
  });
  if (targetIndex < 0) {
    return table;
  }
  return {
    ...table,
    columns: table.columns.filter((_, index) => index !== targetIndex),
    rows: table.rows.map((row) => ({
      ...row,
      cells: row.cells.filter((_, index) => index !== targetIndex),
    })),
  };
}

export function HisReplayPage({ client }: HisReplayPageProps) {
  const navigate = useNavigate();
  const activeClient = client ?? apiClient;
  const loadReplayCapitalPool = useCallback(
    (query: Record<string, string | number>) => activeClient.getReplayCapitalPool<ReplayCapitalPoolSnapshot>(query),
    [activeClient],
  );
  const resource = usePageData("his-replay", activeClient);
  const rawSnapshot = resource.data;
  const snapshotVersion = rawSnapshot?.updatedAt ?? "loading";
  const [progressSnapshot, setProgressSnapshot] = useState<ReplayProgressSnapshot | null>(null);
  const snapshot = rawSnapshot ? mergeReplayProgress(rawSnapshot, progressSnapshot) : rawSnapshot;
  const [replayMode, setReplayMode] = useState("historical_range");
  const [startDate, setStartDate] = useState("2026-03-11");
  const [endDate, setEndDate] = useState("2026-04-10");
  const [startTime, setStartTime] = useState("09:30");
  const [endTime, setEndTime] = useState("15:00");
  const [timeframe, setTimeframe] = useState("30m");
  const [market, setMarket] = useState<(typeof MARKET_OPTIONS)[number]>("CN");
  const [strategyProfileId, setStrategyProfileId] = useState("");
  const [aiDynamicStrategy, setAiDynamicStrategy] = useState("off");
  const [aiDynamicStrength, setAiDynamicStrength] = useState(0.5);
  const [aiDynamicLookback, setAiDynamicLookback] = useState(48);
  const [initialCash, setInitialCash] = useState(50000);
  const [commissionRatePct, setCommissionRatePct] = useState(0.03);
  const [sellTaxRatePct, setSellTaxRatePct] = useState(0.1);
  const [replayUntilNow, setReplayUntilNow] = useState(false);
  const [overwriteLive, setOverwriteLive] = useState(false);
  const [autoStartScheduler, setAutoStartScheduler] = useState(true);
  const [selectedTaskId, setSelectedTaskId] = useState("");
  const [tradeStockFilter, setTradeStockFilter] = useState("");
  const [tradeActionFilter, setTradeActionFilter] = useState("ALL");
  const [signalStockFilter, setSignalStockFilter] = useState("");
  const [signalActionFilter, setSignalActionFilter] = useState("ALL");
  const [tradePage, setTradePage] = useState(1);
  const [signalPage, setSignalPage] = useState(1);
  const [isReplayStarting, setIsReplayStarting] = useState(false);
  const [replayStartStatus, setReplayStartStatus] = useState<"idle" | "submitting" | "submitted" | "error">("idle");
  const selectedTaskForCheckpoint = snapshot?.tasks.find((task) => task.id === selectedTaskId) ?? snapshot?.tasks[0] ?? null;
  const selectedTaskRunId = selectedTaskForCheckpoint?.runId ?? "";
  const hasReplayCheckpointLoader = Boolean(selectedTaskForCheckpoint?.capitalPool && typeof activeClient.getReplayCapitalPool === "function");
  const [checkpointSnapshot, setCheckpointSnapshot] = useState<ReplayCapitalPoolSnapshot | null>(null);
  const [checkpointPage, setCheckpointPage] = useState(1);
  const [checkpointLoading, setCheckpointLoading] = useState(false);
  const [checkpointError, setCheckpointError] = useState("");

  const loadReplayCheckpointPage = useCallback(
    async (page: number, checkpointAt?: string) => {
      if (!selectedTaskRunId || typeof activeClient.getReplayCapitalPool !== "function") {
        return;
      }
      setCheckpointLoading(true);
      setCheckpointError("");
      try {
        const next = await loadReplayCapitalPool({
          runId: selectedTaskRunId,
          checkpointPage: page,
          checkpointPageSize: REPLAY_CHECKPOINT_PAGE_SIZE,
          ...(checkpointAt ? { checkpointAt } : {}),
        });
        setCheckpointSnapshot(next);
        setCheckpointPage(next.checkpoints.pagination.page);
      } catch (error) {
        setCheckpointError(error instanceof Error ? error.message : "检查点资金池加载失败");
      } finally {
        setCheckpointLoading(false);
      }
    },
    [activeClient, loadReplayCapitalPool, selectedTaskRunId],
  );

  useEffect(() => {
    if (!snapshot) {
      return;
    }

    const { startDate: nextStartDate, endDate: nextEndDate } = parseDateRange(snapshot.config.range);
    setReplayMode(parseReplayMode(snapshot.config.mode));
    setStartDate(nextStartDate);
    setEndDate(nextEndDate);
    setStartTime("09:30");
    setEndTime("15:00");
    setTimeframe(normalizeTimeframe(snapshot.config.timeframe));
    setMarket(normalizeMarket(snapshot.config.market) as (typeof MARKET_OPTIONS)[number]);
    setStrategyProfileId(String(snapshot.config.strategyProfileId ?? snapshot.config.strategyProfiles?.[0]?.id ?? ""));
    setAiDynamicStrategy(normalizeAiDynamicStrategy(snapshot.config.aiDynamicStrategy ?? "off"));
    setAiDynamicStrength(parseDynamicStrength(snapshot.config.aiDynamicStrength, 0.5));
    setAiDynamicLookback(parseDynamicLookback(snapshot.config.aiDynamicLookback, 48));
    setInitialCash(parseMoney(snapshot.config.initialCapital, 50000));
    setCommissionRatePct(parseRatePercent(snapshot.config.commissionRatePct, 0.03));
    setSellTaxRatePct(parseRatePercent(snapshot.config.sellTaxRatePct, 0.1));
    setReplayUntilNow(false);
    setOverwriteLive(false);
    setAutoStartScheduler(true);
    setSelectedTaskId((prev) => pickPreferredReplayTaskId(snapshot.tasks, prev));
  }, [snapshotVersion]);

  useEffect(() => {
    if (!rawSnapshot) {
      return;
    }
    setTradePage(1);
    setSignalPage(1);
  }, [snapshotVersion, rawSnapshot]);

  useEffect(() => {
    setProgressSnapshot(null);
  }, [snapshotVersion]);

  useEffect(() => {
    setCheckpointSnapshot(null);
    setCheckpointPage(1);
    setCheckpointError("");
  }, [selectedTaskRunId]);

  useEffect(() => {
    if (!hasReplayCheckpointLoader || !selectedTaskRunId) {
      return;
    }
    void loadReplayCheckpointPage(1);
  }, [hasReplayCheckpointLoader, loadReplayCheckpointPage, selectedTaskRunId]);

  useEffect(() => {
    if (!rawSnapshot || typeof activeClient.getReplayProgress !== "function") {
      return;
    }
    const hasPollingTask = rawSnapshot.tasks.some((task) => {
      const normalized = String(task.status || "").trim().toLowerCase();
      return normalized === "running" || normalized === "queued";
    });
    if (!hasPollingTask) {
      return;
    }

    let cancelled = false;
    const replayQuery = {
      pageSize: PAGE_SIZE,
      tradePage,
      tradeAction: tradeActionFilter,
      tradeStock: tradeStockFilter.trim(),
      signalPage,
      signalAction: signalActionFilter,
      signalStock: signalStockFilter.trim(),
    };
    const refreshProgress = async () => {
      try {
        const next = await activeClient.getReplayProgress<ReplayProgressSnapshot>(replayQuery);
        if (!cancelled) {
          setProgressSnapshot(next);
        }
      } catch {
        // Keep the current snapshot visible when lightweight polling is temporarily unavailable.
      }
    };

    void refreshProgress();
    const timer = window.setInterval(refreshProgress, REPLAY_PROGRESS_REFRESH_MS);

    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [
    activeClient,
    snapshotVersion,
    rawSnapshot,
    tradePage,
    tradeActionFilter,
    tradeStockFilter,
    signalPage,
    signalActionFilter,
    signalStockFilter,
  ]);

  useEffect(() => {
    setTradePage(1);
  }, [tradeStockFilter, tradeActionFilter]);

  useEffect(() => {
    setSignalPage(1);
  }, [signalStockFilter, signalActionFilter]);

  if (resource.status === "loading" && !resource.data) {
    return <PageLoadingState title="历史回放加载中" description="正在读取回放任务、候选池和交易结果。" />;
  }

  if (resource.status === "error" && !resource.data) {
    return (
      <PageErrorState
        title="历史回放加载失败"
        description={resource.error ?? "无法加载历史回放数据，请稍后重试。"}
        actionLabel="重新加载"
        onAction={resource.refresh}
      />
    );
  }

  if (!snapshot) {
    return <PageEmptyState title="历史回放暂无数据" description="后台尚未返回历史回放快照。" actionLabel="刷新" onAction={resource.refresh} />;
  }

  const taskSummary = summarizeTaskStatuses(snapshot.tasks);
  const replayTaskLabel = taskSummary.running > 0 ? `进行中 ${taskSummary.running}` : `已完成 ${taskSummary.completed}`;
  const runningTask = snapshot.tasks.find((task) => String(task.status).toLowerCase() === "running") ?? null;
  const hasActiveReplayTask = snapshot.tasks.some((task) => {
    const normalized = String(task.status || "").trim().toLowerCase();
    return normalized === "running" || normalized === "queued";
  });
  const replayActionError = resource.status === "error" && resource.data ? resource.error : null;
  const runningProgress = Math.max(0, Math.min(Number(runningTask?.progress ?? 0), 100));
  const selectedTask = snapshot.tasks.find((task) => task.id === selectedTaskId) ?? snapshot.tasks[0] ?? null;
  const selectedTaskCapitalPool = checkpointSnapshot?.capitalPool ?? selectedTask?.capitalPool;
  const checkpointItems = checkpointSnapshot?.checkpoints.items ?? [];
  const checkpointPagination = checkpointSnapshot?.checkpoints.pagination;
  const selectedCheckpointAt = checkpointSnapshot?.selectedCheckpointAt ?? selectedTaskCapitalPool?.task.checkpoint ?? "";
  const selectedTaskRange = selectedTask?.range || snapshot.config.range;
  const selectedTaskStatusLabel = selectedTask ? localizeTaskStatus(selectedTask.status) : "--";
  const selectedTaskStageLabel = selectedTask?.stage || "--";
  const selectedTaskStageParts = parseReplayStageLabel(selectedTaskStageLabel);
  const selectedTaskStartedAt = selectedTask?.startAt || "--";
  const selectedTaskEndedAt = selectedTask?.endAt || "--";
  const selectedTaskModeLabel = localizeReplayMode(selectedTask?.mode || snapshot.config.mode);
  const selectedTaskTimeframe = toDisplayText(selectedTask?.timeframe || snapshot.config.timeframe, "--");
  const selectedTaskMarket = toDisplayText(selectedTask?.market || snapshot.config.market, "--");
  const selectedTaskCheckpointCount = Number.isFinite(Number(selectedTask?.checkpointCount)) ? String(selectedTask?.checkpointCount ?? 0) : "--";
  const selectedTaskProgressCurrent = Number.isFinite(Number(selectedTask?.progressCurrent)) ? Number(selectedTask?.progressCurrent ?? 0) : 0;
  const selectedTaskProgressTotal = Number.isFinite(Number(selectedTask?.progressTotal)) ? Number(selectedTask?.progressTotal ?? 0) : 0;
  const selectedTaskProgressPct = Math.max(0, Math.min(Number(selectedTask?.progress ?? 0), 100));
  const selectedTaskProgressText =
    selectedTaskProgressTotal > 0 ? `${selectedTaskProgressCurrent}/${selectedTaskProgressTotal}` : "--";
  const selectedTaskLatestCheckpointAt = selectedTask?.latestCheckpointAt || "--";
  const selectedTaskLiquidation = selectedTask?.terminalLiquidation ?? {};
  const selectedTaskLiquidationMetrics = [
    {
      label: "清算后现金",
      value: formatSummaryNumber(selectedTaskLiquidation.liquidation_cash ?? findMetricValue(snapshot.tradeCostSummary, "清算后现金")),
    },
    {
      label: "清算后总盈亏",
      value: formatSummaryNumber(selectedTaskLiquidation.liquidation_total_pnl ?? findMetricValue(snapshot.tradeCostSummary, "清算后总盈亏")),
    },
    {
      label: "期末清算费用",
      value: formatSummaryNumber(selectedTaskLiquidation.fee_total ?? findMetricValue(snapshot.tradeCostSummary, "期末清算费用")),
    },
    {
      label: "清算后收益率",
      value: formatSummaryPercent(selectedTaskLiquidation.liquidation_return_pct ?? findMetricValue(snapshot.tradeCostSummary, "清算后收益率")),
    },
  ];
  const selectedTaskMetrics = selectedTask
    ? [
        { label: "收益率", value: selectedTask.returnPct || "--" },
        { label: "总权益", value: selectedTask.finalEquity || "--" },
        { label: "现金", value: selectedTask.cashValue || "--" },
        { label: "持仓市值", value: selectedTask.marketValue || "--" },
        { label: "已实现", value: selectedTask.realizedPnl || "--" },
        { label: "浮动盈亏", value: selectedTask.unrealizedPnl || "--" },
        ...selectedTaskLiquidationMetrics,
      ]
    : [];
  const executionCostSummary = (snapshot.tradeCostSummary ?? []).filter((metric) => !REPLAY_SUMMARY_METRIC_LABELS.has(metric.label));
  const selectedTaskTopWinningTrades: TableSection = {
    columns: ["时间", "信号ID", "代码", "卖出价", "净盈亏", "盈亏率", "执行明细"],
    rows: withCodeName(selectedTask?.topWinningTrades ?? [], 2),
    emptyLabel: "暂无盈利交易",
    emptyMessage: "选中任务里还没有已兑现的盈利卖出交易。",
  };
  const selectedTaskTopLosingTrades: TableSection = {
    columns: ["时间", "信号ID", "代码", "卖出价", "净盈亏", "盈亏率", "执行明细"],
    rows: withCodeName(selectedTask?.topLosingTrades ?? [], 2),
    emptyLabel: "暂无亏损交易",
    emptyMessage: "选中任务里还没有已兑现的亏损卖出交易。",
  };
  const tradeRows = withCodeName(snapshot.trades.rows, 2);
  const signalTable = removeExecutionResultColumn(snapshot.signals);
  const signalRows = withCodeName(signalTable.rows, 2);
  const tradeActionOptions = Array.from(
    new Set(
      snapshot.trades.rows
        .map((row) => normalizeAction(String(row.cells[3] ?? "")))
        .filter(Boolean),
    ),
  );
  const signalActionOptions = Array.from(
    new Set(
      signalTable.rows
        .map((row) => normalizeAction(String(row.cells[3] ?? "")))
        .filter(Boolean),
    ),
  );
  const tradePages = Math.max(1, Number(snapshot.trades.pagination?.totalPages ?? 1));
  const signalPages = Math.max(1, Number(snapshot.signals.pagination?.totalPages ?? 1));
  const effectiveTradePage = Math.max(1, Number(snapshot.trades.pagination?.page ?? tradePage));
  const effectiveSignalPage = Math.max(1, Number(snapshot.signals.pagination?.page ?? signalPage));
  const tradeTotalRows = Number(snapshot.trades.pagination?.totalRows ?? tradeRows.length);
  const signalTotalRows = Number(snapshot.signals.pagination?.totalRows ?? signalRows.length);
  const pagedTrades = {
    ...snapshot.trades,
    rows: tradeRows,
  };
  const pagedSignals = {
    ...signalTable,
    rows: signalRows,
  };
  const toolbarControlHeight = "40px";
  const renderPager = (page: number, pages: number, setPage: (value: number) => void) => (
    <div className="table-toolbar-compact__pager" aria-label="分页控制">
      <button
        className="icon-button icon-button--neutral table-toolbar-compact__pager-button"
        type="button"
        style={{ height: toolbarControlHeight, minHeight: toolbarControlHeight, width: toolbarControlHeight, minWidth: toolbarControlHeight }}
        aria-label="上一页"
        title="上一页"
        disabled={page <= 1}
        onClick={() => setPage(page - 1)}
      >
        <span aria-hidden="true">←</span>
      </button>
      <span
        className="badge badge--neutral table-toolbar-compact__pager-status"
        style={{
          height: toolbarControlHeight,
          minHeight: toolbarControlHeight,
          display: "inline-flex",
          alignItems: "center",
          justifyContent: "center",
          padding: "0 16px",
        }}
      >
        {`第 ${page} / ${pages} 页`}
      </span>
      <button
        className="icon-button icon-button--neutral table-toolbar-compact__pager-button"
        type="button"
        style={{ height: toolbarControlHeight, minHeight: toolbarControlHeight, width: toolbarControlHeight, minWidth: toolbarControlHeight }}
        aria-label="下一页"
        title="下一页"
        disabled={page >= pages}
        onClick={() => setPage(page + 1)}
      >
        <span aria-hidden="true">→</span>
      </button>
    </div>
  );
  const renderFilterToolbar = (
    stockFilter: string,
    setStockFilter: (value: string) => void,
    actionFilter: string,
    setActionFilter: (value: string) => void,
    actionOptions: string[],
    page: number,
    pages: number,
    setPage: (value: number) => void,
    filteredCountText: string,
    includeTradePreset: boolean = false,
  ) => (
    <div className="table-toolbar-compact">
      <input
        className="input"
        style={{ height: toolbarControlHeight, minHeight: toolbarControlHeight, padding: "0 10px" }}
        data-size="compact-input"
        placeholder="按代码/名称过滤"
        value={stockFilter}
        onChange={(event) => setStockFilter(event.target.value)}
      />
      <select
        className="input"
        style={{ height: toolbarControlHeight, minHeight: toolbarControlHeight, padding: "0 10px" }}
        data-size="compact-select"
        value={actionFilter}
        onChange={(event) => setActionFilter(event.target.value)}
      >
        {includeTradePreset ? <option value="TRADE">BUY/SELL</option> : null}
        <option value="ALL">全部动作</option>
        {actionOptions.map((option) => (
          <option key={option} value={option}>
            {option}
          </option>
        ))}
      </select>
      {renderPager(page, pages, setPage)}
      <span className="summary-item__body table-toolbar-compact__count" style={{ margin: 0 }}>
        {filteredCountText}
      </span>
    </div>
  );
  const handleSignalRowAction = (row: TableRow, action: TableAction) => {
    const actionKey = String(action.action ?? "").trim().toLowerCase();
    const actionLabel = String(action.label ?? "").trim().toLowerCase();
    if (!(actionKey === "show-signal-detail" || actionLabel === "详情" || actionLabel === "detail")) {
      return;
    }
    navigate(`/signal-detail/${encodeURIComponent(row.id)}?source=replay`);
  };
  const handleReplayStart = async () => {
    setIsReplayStarting(true);
    setReplayStartStatus("submitting");
    try {
      const nextSnapshot = await resource.runAction(replayMode === "continuous_to_live" ? "continue" : "start", {
        startDateTime: `${startDate} ${startTime}:00`,
        endDateTime: replayUntilNow ? null : `${endDate} ${endTime}:00`,
        timeframe,
        market,
        strategyMode: "auto",
        strategyProfileId,
        initialCash,
        aiDynamicStrategy,
        aiDynamicStrength,
        aiDynamicLookback,
        commissionRatePct,
        sellTaxRatePct,
        overwriteLive,
        autoStartScheduler,
      });
      if (!nextSnapshot) {
        setReplayStartStatus("idle");
      } else if (nextSnapshot.tasks?.length) {
        setSelectedTaskId(pickPreferredReplayTaskId(nextSnapshot.tasks, ""));
        setReplayStartStatus("submitted");
      } else {
        setReplayStartStatus("error");
      }
    } finally {
      setIsReplayStarting(false);
    }
  };

  return (
    <div>
      <PageHeader
        eyebrow="Replay"
        title="历史回放"
        description="围绕同一批量化候选池回放历史区间，核对任务、成交、费用和信号落库结果。"
        actions={
          <div className="chip-row">
            <span className="badge badge--neutral">快照 {snapshot.updatedAt}</span>
            <span className="badge badge--accent">任务 {snapshot.tasks.length}</span>
            <span className={`badge ${runningTask ? "badge--accent" : "badge--success"}`}>
              {runningTask ? `执行中 ${runningProgress}%` : replayTaskLabel}
            </span>
            {runningTask?.stage ? <span className="badge badge--neutral">{runningTask.stage}</span> : null}
          </div>
        }
      />
      <div className="section-grid section-grid--sidebar">
        <div className="stack">
          <WorkbenchCard>
            <h2 className="section-card__title">回放配置</h2>
            <div className="summary-list">
              <label className="field">
                <span className="field__label">回放模式</span>
                <select className="input" value={replayMode} onChange={(event) => setReplayMode(event.target.value)}>
                  {REPLAY_MODE_OPTIONS.map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                </select>
              </label>
              <div className="section-grid">
                <label className="field">
                  <span className="field__label">开始日期</span>
                  <input className="input" type="date" value={startDate} onChange={(event) => setStartDate(event.target.value)} />
                </label>
                {replayUntilNow ? (
                  <div className="summary-item summary-item--accent">
                    <div className="summary-item__title">结束日期</div>
                    <div className="summary-item__body">当前模式下结束日期自动取当前日期时间。</div>
                  </div>
                ) : (
                  <label className="field">
                    <span className="field__label">结束日期</span>
                    <input className="input" type="date" value={endDate} onChange={(event) => setEndDate(event.target.value)} />
                  </label>
                )}
              </div>
              <div className="section-grid">
                <label className="field">
                  <span className="field__label">开始时间</span>
                  <input className="input" type="time" value={startTime} onChange={(event) => setStartTime(event.target.value)} />
                </label>
                {replayUntilNow ? (
                  <div className="summary-item summary-item--accent">
                    <div className="summary-item__title">结束时间</div>
                    <div className="summary-item__body">结束时间将自动取当前时刻。</div>
                  </div>
                ) : (
                  <label className="field">
                    <span className="field__label">结束时间</span>
                    <input className="input" type="time" value={endTime} onChange={(event) => setEndTime(event.target.value)} />
                  </label>
                )}
              </div>
              <label className="field">
                <span className="field__label">回放粒度</span>
                <select className="input" value={timeframe} onChange={(event) => setTimeframe(event.target.value)}>
                  {TIMEFRAME_OPTIONS.map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                </select>
              </label>
              <label className="field">
                <span className="field__label">市场</span>
                <select className="input" value={market} onChange={(event) => setMarket(event.target.value as (typeof MARKET_OPTIONS)[number])}>
                  {MARKET_OPTIONS.map((option) => (
                    <option key={option} value={option}>
                      {option}
                    </option>
                  ))}
                </select>
              </label>
              <label className="field">
                <span className="field__label">策略配置</span>
                <select className="input" value={strategyProfileId} onChange={(event) => setStrategyProfileId(event.target.value)}>
                  {(snapshot.config.strategyProfiles ?? []).map((item) => (
                    <option key={item.id} value={item.id}>
                      {item.name}
                    </option>
                  ))}
                </select>
              </label>
              <label className="field">
                <span className="field__label">回放资金池(元)</span>
                <input
                  className="input"
                  min={20000}
                  step={10000}
                  type="number"
                  value={initialCash}
                  onChange={(event) => setInitialCash(Math.max(20000, Math.round(Number(event.target.value) || 20000)))}
                />
              </label>
              <label className="field">
                <span className="field__label">AI动态策略</span>
                <select className="input" value={aiDynamicStrategy} onChange={(event) => setAiDynamicStrategy(event.target.value)}>
                  {AI_DYNAMIC_STRATEGY_OPTIONS.map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                </select>
              </label>
              <label className="field">
                <span className="field__label">手续费率(%)</span>
                <input
                  className="input"
                  min={0}
                  max={5}
                  step={0.001}
                  type="number"
                  value={commissionRatePct}
                  onChange={(event) => setCommissionRatePct(Math.max(0, Number(event.target.value) || 0))}
                />
              </label>
              <label className="field">
                <span className="field__label">卖出税费率(%)</span>
                <input
                  className="input"
                  min={0}
                  max={10}
                  step={0.001}
                  type="number"
                  value={sellTaxRatePct}
                  onChange={(event) => setSellTaxRatePct(Math.max(0, Number(event.target.value) || 0))}
                />
              </label>
              <label className="field" style={{ flexDirection: "row", alignItems: "center", gap: "10px" }}>
                <input type="checkbox" checked={replayUntilNow} onChange={(event) => setReplayUntilNow(event.target.checked)} />
                <span className="field__label" style={{ marginBottom: 0 }}>
                  结束时间留空则回放到当前时刻
                </span>
              </label>
              {replayMode === "continuous_to_live" ? (
                <>
                  <label className="field" style={{ flexDirection: "row", alignItems: "center", gap: "10px" }}>
                    <input type="checkbox" checked={overwriteLive} onChange={(event) => setOverwriteLive(event.target.checked)} />
                    <span className="field__label" style={{ marginBottom: 0 }}>
                      覆盖当前实时模拟账户
                    </span>
                  </label>
                  <label className="field" style={{ flexDirection: "row", alignItems: "center", gap: "10px" }}>
                    <input type="checkbox" checked={autoStartScheduler} onChange={(event) => setAutoStartScheduler(event.target.checked)} />
                    <span className="field__label" style={{ marginBottom: 0 }}>
                      回放完成后自动启动定时分析
                    </span>
                  </label>
                </>
              ) : null}
            </div>
            <div className="card-divider" />
            <div className="toolbar toolbar--compact">
              <button
                className="button button--primary"
                type="button"
                disabled={isReplayStarting || resource.status === "loading" || hasActiveReplayTask}
                onClick={() => void handleReplayStart()}
              >
                {isReplayStarting ? "提交中..." : replayMode === "continuous_to_live" ? "接续" : "开始回溯"}
              </button>
              <button
                className="button button--secondary"
                type="button"
                disabled={resource.status === "loading"}
                onClick={() => void resource.runAction("cancel")}
              >
                取消
              </button>
              <span className="toolbar__spacer" />
              <button
                className="button button--secondary"
                type="button"
                disabled={resource.status === "loading"}
                onClick={() => void resource.runAction("delete")}
              >
                删除
              </button>
            </div>
            {hasActiveReplayTask ? (
              <div className="summary-item summary-item--accent" style={{ marginTop: "12px" }}>
                <div className="summary-item__title">已有回放任务在执行</div>
                <div className="summary-item__body">当前存在进行中或排队中的回放任务。请先等待完成，或取消后再开始新的回放。</div>
              </div>
            ) : null}
            {replayStartStatus === "submitting" ? (
              <div className="summary-item summary-item--accent" style={{ marginTop: "12px" }}>
                <div className="summary-item__title">回放任务正在提交</div>
                <div className="summary-item__body">后台已接收请求前，前端会保持提交状态；任务创建后会自动切到最新任务进度。</div>
              </div>
            ) : null}
            {replayStartStatus === "submitted" ? (
              <div className="summary-item summary-item--success" style={{ marginTop: "12px" }}>
                <div className="summary-item__title">回放任务已提交</div>
                <div className="summary-item__body">已切换到最新回放任务；运行期间进度会每 1 分钟自动刷新一次。</div>
              </div>
            ) : null}
            {replayStartStatus === "error" ? (
              <div className="summary-item summary-item--danger" style={{ marginTop: "12px" }}>
                <div className="summary-item__title">回放任务提交失败</div>
                <div className="summary-item__body">后台没有返回新的任务快照，请查看操作失败信息或稍后重试。</div>
              </div>
            ) : null}
            {replayActionError ? (
              <div className="summary-item summary-item--danger" style={{ marginTop: "12px" }}>
                <div className="summary-item__title">操作失败</div>
                <div className="summary-item__body">{replayActionError}</div>
              </div>
            ) : null}
          </WorkbenchCard>

          <QuantTableSectionCard
            title="量化候选池"
            description="历史回放和实时模拟共用同一批量化候选池，因此这里看到的股票就是后续对照对象。"
            table={snapshot.candidatePool}
            emptyTitle={snapshot.candidatePool.emptyLabel ?? "候选池暂无数据"}
            emptyDescription={snapshot.candidatePool.emptyMessage ?? "先从我的关注或发现 / 研究页补入候选，再重新发起回放。"}
            meta={[`表内 ${snapshot.candidatePool.rows.length} 只`, `区间 ${snapshot.config.range}`]}
          />

        </div>

        <div className="stack">
          <WorkbenchCard>
            <div className="replay-task-card-header">
              <h2 className="section-card__title replay-task-card-title">回放任务</h2>
              <div className="replay-task-card-controls">
                <div className="chip-row replay-task-card-badges">
                  <span className="badge badge--neutral">已完成 {taskSummary.completed}</span>
                  <span className="badge badge--accent">进行中 {taskSummary.running}</span>
                  <span className="badge badge--neutral">排队 {taskSummary.queued}</span>
                </div>
                {snapshot.tasks.length > 0 ? (
                  <label className="field replay-task-selector">
                    <span className="field__label replay-task-selector__label">选择任务</span>
                    <select className="input replay-task-selector__input" value={selectedTask?.id ?? ""} onChange={(event) => setSelectedTaskId(event.target.value)}>
                      {snapshot.tasks.map((task) => (
                        <option key={task.id} value={task.id}>
                          {`${task.id} · ${localizeTaskStatus(task.status)}`}
                        </option>
                      ))}
                    </select>
                  </label>
                ) : null}
              </div>
            </div>
            {snapshot.tasks.length > 0 ? (
              <div className="summary-list">
                {selectedTask ? (
                  <div className="summary-list" aria-label="已选回放任务详情">
                    <div className="summary-item replay-task-overview">
                      <div className="replay-task-overview__topline">
                        <div>
                          <div className="summary-item__title">回放结论与进度</div>
                          <div className="summary-item__body">{`${selectedTask.id} · ${selectedTaskStatusLabel}`}</div>
                        </div>
                        <span className="badge badge--accent">{`${selectedTaskProgressPct}%`}</span>
                      </div>
                      <div className="replay-task-stage">
                        {selectedTaskStageParts.checkpoint ? (
                          <div className="replay-task-stage__checkpoint">{selectedTaskStageParts.checkpoint}</div>
                        ) : null}
                        <div className="replay-task-stage__detail">{selectedTaskStageParts.detail}</div>
                      </div>
                      <div className="replay-task-progress" aria-label={`回放进度 ${selectedTaskProgressPct}%`}>
                        <div className="replay-task-progress__bar">
                          <div className="replay-task-progress__fill" style={{ width: `${selectedTaskProgressPct}%` }} />
                        </div>
                        <div className="replay-task-progress__meta">
                          <span>{`检查点进度：${selectedTaskProgressText} · ${selectedTaskProgressPct}%`}</span>
                          <span>{`已写入：${selectedTaskCheckpointCount}`}</span>
                        </div>
                        {hasReplayCheckpointLoader ? (
                          <div className="replay-task-checkpoint-controls">
                            <label className="field replay-task-checkpoint-controls__select">
                              <span className="field__label">检查点</span>
                              <select
                                className="input"
                                value={selectedCheckpointAt}
                                aria-label="检查点"
                                disabled={checkpointLoading || !checkpointItems.length}
                                onChange={(event) => void loadReplayCheckpointPage(checkpointPage, event.target.value)}
                              >
                                {checkpointItems.length ? (
                                  checkpointItems.map((item) => (
                                    <option key={item.id} value={item.checkpointAt}>
                                      {`${item.label} · 权益 ${item.totalEquity ?? "--"}`}
                                    </option>
                                  ))
                                ) : (
                                  <option value={selectedCheckpointAt}>{selectedCheckpointAt || "暂无检查点"}</option>
                                )}
                              </select>
                            </label>
                            <div className="replay-task-checkpoint-controls__pager">
                              <button
                                type="button"
                                className="icon-button icon-button--neutral"
                                aria-label="上一组检查点"
                                disabled={checkpointLoading || !checkpointPagination || checkpointPagination.page <= 1}
                                onClick={() => void loadReplayCheckpointPage(Math.max(1, checkpointPage - 1))}
                              >
                                ←
                              </button>
                              <span>{checkpointPagination ? `第 ${checkpointPagination.page} / ${checkpointPagination.totalPages} 页` : "第 -- / -- 页"}</span>
                              <button
                                type="button"
                                className="icon-button icon-button--neutral"
                                aria-label="下一组检查点"
                                disabled={checkpointLoading || !checkpointPagination || checkpointPagination.page >= checkpointPagination.totalPages}
                                onClick={() => void loadReplayCheckpointPage(checkpointPage + 1)}
                              >
                                →
                              </button>
                            </div>
                            {checkpointLoading ? <span className="badge badge--neutral">加载中</span> : null}
                            {checkpointError ? <span className="badge badge--danger">{checkpointError}</span> : null}
                          </div>
                        ) : null}
                      </div>
                      <div className="replay-task-overview__grid">
                        <div className="summary-item__body">{`开始时间：${selectedTaskStartedAt}`}</div>
                        <div className="summary-item__body">{`结束时间：${selectedTaskEndedAt}`}</div>
                        <div className="summary-item__body">{`最近检查点：${selectedTaskLatestCheckpointAt}`}</div>
                        <div className="summary-item__body">{`已写入检查点：${selectedTaskCheckpointCount}`}</div>
                        <div className="summary-item__body">{`回放节点：${selectedTaskProgressTotal > 0 ? selectedTaskProgressTotal : selectedTaskCheckpointCount}`}</div>
                        <div className="summary-item__body">{`区间：${selectedTaskRange}`}</div>
                        <div className="summary-item__body">{`模式：${selectedTaskModeLabel} · 粒度：${selectedTaskTimeframe} · 市场：${selectedTaskMarket}`}</div>
                        <div className="summary-item__body replay-task-overview__wide">
                          {`策略配置：${selectedTask.strategyProfileName || selectedTask.strategyProfileId || strategyProfileId || "--"}${selectedTask.strategyProfileVersionId ? ` · 版本#${selectedTask.strategyProfileVersionId}` : ""}`}
                        </div>
                      </div>
                    </div>
                    <div className="mini-metric-grid replay-task-metrics-grid">
                      {selectedTaskMetrics.map((metric) => (
                        <div className="mini-metric replay-task-metric" key={metric.label}>
                          <div className="mini-metric__label">{metric.label}</div>
                          <div className="mini-metric__value" title={String(metric.value)}>{metric.value}</div>
                        </div>
                      ))}
                    </div>
                  </div>
                ) : null}
              </div>
            ) : (
              <div className="summary-item summary-item--accent">
                <div className="summary-item__title">暂无回放任务</div>
                <div className="summary-item__body">当前没有排队中的历史回放任务，点击“开始回溯”后会在这里创建新任务。</div>
              </div>
            )}
          </WorkbenchCard>

          {selectedTaskCapitalPool ? (
            <ReplayCapitalPoolPanel capitalPool={selectedTaskCapitalPool} />
          ) : null}

          {executionCostSummary.length ? (
            <WorkbenchCard>
              <h2 className="section-card__title">费用与执行统计</h2>
              <p className="section-card__description">回放成交按每笔毛额、手续费、印花税、净额、lot和slot归集，避免只看买卖价格误判收益。</p>
              <div className="mini-metric-grid">
                {executionCostSummary.map((metric) => (
                  <div className="mini-metric" key={metric.label}>
                    <div className="mini-metric__label">{metric.label}</div>
                    <div className="mini-metric__value">{metric.value}</div>
                  </div>
                ))}
              </div>
            </WorkbenchCard>
          ) : null}

          <div className="section-grid">
            <QuantTableSectionCard
              title="Top 5 盈利交易"
              description="只统计本次回放中已卖出并兑现盈利的交易，按净盈亏从高到低排序。"
              table={selectedTaskTopWinningTrades}
              emptyTitle={selectedTaskTopWinningTrades.emptyLabel ?? "暂无盈利交易"}
              emptyDescription={selectedTaskTopWinningTrades.emptyMessage ?? "选中任务没有盈利交易。"}
              tableLayout="auto"
              compactConfig={{ coreColumnIndexes: [2, 4, 5], detailColumnIndexes: [0, 1, 3, 6] }}
              signalDetailSource="replay"
            />

            <QuantTableSectionCard
              title="Top 5 亏损交易"
              description="只统计本次回放中已卖出并兑现亏损的交易，按净亏损从大到小排序。"
              table={selectedTaskTopLosingTrades}
              emptyTitle={selectedTaskTopLosingTrades.emptyLabel ?? "暂无亏损交易"}
              emptyDescription={selectedTaskTopLosingTrades.emptyMessage ?? "选中任务没有亏损交易。"}
              tableLayout="auto"
              compactConfig={{ coreColumnIndexes: [2, 4, 5], detailColumnIndexes: [0, 1, 3, 6] }}
              signalDetailSource="replay"
            />
          </div>

          <QuantTableSectionCard
            title="成交明细"
            table={pagedTrades}
            emptyTitle={snapshot.trades.emptyLabel ?? "成交明细暂无数据"}
            emptyDescription={snapshot.trades.emptyMessage ?? "历史回放执行后，所有成交会统一落在这里。"}
            tableLayout="auto"
            compactConfig={{ coreColumnIndexes: [0, 2, 3, 11], detailColumnIndexes: [1, 4, 5, 6, 7, 8, 9, 10, 12, 13, 14, 15] }}
            signalDetailSource="replay"
            toolbar={renderFilterToolbar(
              tradeStockFilter,
              setTradeStockFilter,
              tradeActionFilter,
              setTradeActionFilter,
              tradeActionOptions,
              effectiveTradePage,
              tradePages,
              setTradePage,
              `DB筛选 ${tradeTotalRows} 条`,
              false,
            )}
          />

          <WorkbenchCard>
            <h2 className="section-card__title">资金曲线</h2>
            <Sparkline points={snapshot.curve} />
          </WorkbenchCard>

          <QuantTableSectionCard
            title="信号记录"
            table={pagedSignals}
            emptyTitle={snapshot.signals.emptyLabel ?? "信号记录暂无数据"}
            emptyDescription={snapshot.signals.emptyMessage ?? "回放过程中生成的信号会展示在这里，便于快速核对执行结果。"}
            actionsHead="操作"
            actionVariant="chip"
            tableLayout="auto"
            compactConfig={{ coreColumnIndexes: [0, 2, 3, 4], detailColumnIndexes: [1, 5] }}
            toolbar={renderFilterToolbar(
              signalStockFilter,
              setSignalStockFilter,
              signalActionFilter,
              setSignalActionFilter,
              signalActionOptions,
              effectiveSignalPage,
              signalPages,
              setSignalPage,
              `DB筛选 ${signalTotalRows} 条`,
              true,
            )}
            onRowAction={handleSignalRowAction}
          />
        </div>
      </div>
    </div>
  );
}
