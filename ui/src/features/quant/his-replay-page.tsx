import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { apiClient, type ApiClient } from "../../lib/api-client";
import { PageHeader } from "../../components/ui/page-header";
import { WorkbenchCard } from "../../components/ui/workbench-card";
import { PageEmptyState, PageErrorState, PageLoadingState } from "../../components/ui/page-state";
import { usePageData } from "../../lib/use-page-data";
import type { ReplayCapitalPoolSnapshot, ReplaySnapshot, SummaryMetric, TableRow, TableSection } from "../../lib/page-models";
import { summarizeTaskStatuses, toDisplayText } from "./quant-display";
import { QuantTableSectionCard } from "./quant-table-section";
import { OutcomeSummaryCard } from "./outcome-summary-card";
import { ReplayCapitalPoolPanel } from "./replay-capital-pool-panel";
import { t } from "../../lib/i18n";

const REPLAY_MODE_OPTIONS = [
  { value: "historical_range", label: t("历史区间回放") },
];

const TIMEFRAME_OPTIONS = [
  { value: "30m", label: t("30分钟") },
  { value: "1d", label: t("日线") },
  { value: "1d+30m", label: t("日线方向 + 30分钟确认") },
];

const AI_DYNAMIC_STRATEGY_OPTIONS = [
  { value: "off", label: t("关闭") },
  { value: "hybrid", label: t("开启") },
];

const PROFIT_GAP_LABEL_OPTIONS = [
  "entry_too_late",
  "size_too_small",
  "bad_extra_buy",
  "sell_blocked_or_late",
  "same_entry_exit_gap",
  "mark_to_market_gap",
  "missing_evidence",
  "drill_better",
];

const PROFIT_GAP_SEVERITY_OPTIONS = ["high", "medium", "low", "none"];

const MARKET_OPTIONS = ["CN", "HK", "US"] as const;
const REPLAY_PROGRESS_REFRESH_MS = 10 * 1000;
const REPLAY_CHECKPOINT_PAGE_SIZE = 50;
const TRADE_PAGE_SIZE = 20;
const SIGNAL_PAGE_SIZE = 10;
const DEFAULT_SIGNAL_ACTION_FILTER = "TRADE";
const INITIAL_REPLAY_TABLE_QUERY = {
  pageSize: TRADE_PAGE_SIZE,
  tradePageSize: TRADE_PAGE_SIZE,
  tradePage: 1,
  tradeAction: "ALL",
  tradeStock: "",
  signalPageSize: SIGNAL_PAGE_SIZE,
  signalPage: 1,
  signalAction: DEFAULT_SIGNAL_ACTION_FILTER,
  signalStock: "",
};
const REPLAY_SUMMARY_METRIC_LABELS = new Set([
  t("初始资金"),
  t("最终权益"),
  t("最终现金"),
  t("持仓市值"),
  t("浮动盈亏"),
  t("总盈亏"),
  t("总收益率"),
  t("期末持仓数"),
  t("期末清算毛额"),
  t("期末清算费用"),
  t("期末清算盈亏"),
  t("清算后现金"),
  t("清算后总盈亏"),
  t("清算后收益率"),
]);
const EXECUTION_HERO_METRIC_LABELS = [t("实现盈亏"), t("买入总成本"), t("卖出到账"), t("总费用")];
const EXECUTION_STAT_GROUPS = [
  { title: t("成本拆解"), labels: [t("买入毛额"), t("手续费")] },
  { title: t("收入拆解"), labels: [t("卖出毛额"), t("印花税")] },
  { title: t("交易背景"), labels: [t("交易笔数"), t("胜率"), t("买入笔数"), t("卖出笔数"), t("加仓次数")] },
  { title: t("信号执行"), labels: [t("交易信号"), t("BUY信号"), t("SELL信号"), t("已执行信号"), t("忽略信号"), t("忽略BUY"), t("忽略SELL"), t("待执行信号")] },
  { title: "Lot / Slot", labels: [t("买入lot"), t("卖出lot"), t("剩余lot"), t("占用slot"), t("释放slot"), t("最大占用slot"), t("平均占用slot")] },
  { title: t("期末资金"), labels: [t("Slot数量"), t("单Slot预算"), t("最大Slot"), t("高价双Slot线"), t("最终空闲"), t("最终占用"), t("最终待结算")] },
];
type ReplayProgressSnapshot = Pick<ReplaySnapshot, "updatedAt" | "tasks"> &
  Partial<Pick<ReplaySnapshot, "holdings" | "trades" | "signals" | "tradeCostSummary">>;

type ProfitGapAttributionItem = {
  stock_code?: string;
  stock_name?: string;
  historical_total_pnl?: number | string;
  drill_total_pnl?: number | string;
  pnl_gap?: number | string;
  attribution_labels?: string[];
  primary_label?: string;
  sub_reason?: string;
  severity?: string;
  actionable?: boolean;
  recommended_action?: string;
  primary_reason?: string;
};

type ProfitGapAttributionResponse = {
  historical_run_id: number;
  drill_run_id: number;
  summary?: {
    total?: number;
    by_label?: Record<string, number>;
    by_sub_reason?: Record<string, number>;
    by_severity?: Record<string, number>;
    actionable_count?: number;
    large_unclassified_count?: number;
  };
  items: ProfitGapAttributionItem[];
};

function parseDateRange(range: string) {
  const match = String(range).match(/(\d{4}-\d{2}-\d{2})\s*->\s*(\d{4}-\d{2}-\d{2}|now)/);
  return {
    startDate: match?.[1] ?? "2026-03-11",
    endDate: match?.[2] && match[2] !== "now" ? match[2] : "2026-04-10",
  };
}

function parseReplayMode(value: string) {
  void value;
  return "historical_range";
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
  if (!normalized || normalized === "off" || normalized.includes(t("关"))) return "off";
  if (normalized === "template" || normalized === "weights" || normalized === "hybrid" || normalized.includes(t("开"))) return "hybrid";
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

function isLiveQuantDrillTask(task: ReplaySnapshot["tasks"][number] | null | undefined) {
  const runType = String(task?.runType ?? "").toLowerCase();
  const mode = String(task?.mode ?? "").toLowerCase();
  return runType === "live_quant_drill" || mode === "live_quant_drill";
}

function pickComparableHistoricalTask(
  tasks: ReplaySnapshot["tasks"],
  drillTask: ReplaySnapshot["tasks"][number] | null | undefined,
) {
  if (!drillTask || !isLiveQuantDrillTask(drillTask)) return null;
  return (
    tasks.find((task) => {
      if (!task.runId || task.runId === drillTask.runId || isLiveQuantDrillTask(task)) return false;
      if (String(task.status).toLowerCase() !== "completed") return false;
      return (
        task.range === drillTask.range
        && task.timeframe === drillTask.timeframe
        && task.market === drillTask.market
        && task.strategyProfileId === drillTask.strategyProfileId
      );
    }) ?? null
  );
}

function profitGapRows(items: ProfitGapAttributionItem[]): TableRow[] {
  return items.map((item, index) => {
    const code = toDisplayText(item.stock_code, "--");
    const name = toDisplayText(item.stock_name, code);
    return {
      id: `${code}-${index}`,
      code,
      name,
      cells: [
        code,
        name,
        formatSummaryNumber(item.historical_total_pnl),
        formatSummaryNumber(item.drill_total_pnl),
        formatSummaryNumber(item.pnl_gap),
        toDisplayText(item.primary_label ?? (item.attribution_labels ?? [])[0], "--"),
        toDisplayText(item.sub_reason, "--"),
        toDisplayText(item.severity, "--"),
        item.actionable ? t("需要处理") : t("观察"),
        toDisplayText(item.recommended_action, "--"),
        toDisplayText(item.primary_reason, "--"),
      ],
    };
  });
}

function findMetric(metrics: ReplaySnapshot["tradeCostSummary"], label: string) {
  return metrics?.find((metric) => metric.label === label);
}

function pickMetrics(metrics: SummaryMetric[], labels: string[]) {
  const byLabel = new Map(metrics.map((metric) => [metric.label, metric]));
  return labels.map((label) => byLabel.get(label)).filter((metric): metric is SummaryMetric => Boolean(metric));
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

function isReplayTaskPollingStatus(status: unknown) {
  const normalized = String(status || "").trim().toLowerCase();
  return normalized === "running" || normalized === "queued";
}

function replayPollingTaskKey(tasks: Array<{ id: string; status?: string }> | undefined) {
  return (tasks ?? [])
    .filter((task) => isReplayTaskPollingStatus(task.status))
    .map((task) => `${task.id}:${String(task.status || "").trim().toLowerCase()}`)
    .join("|");
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
    checkpoint: t("检查点 {v0}", { v0: match[1] }),
    detail: match[2],
  };
}

type HisReplayPageProps = {
  client?: ApiClient;
};

function localizeTaskStatus(status: string) {
  const normalized = String(status || "").trim().toLowerCase();
  if (normalized === "completed") return t("已完成");
  if (normalized === "running") return t("进行中");
  if (normalized === "queued") return t("排队中");
  if (normalized === "cancelled" || normalized === "canceled") return t("已取消");
  if (normalized === "failed") return t("失败");
  return status || "--";
}

function normalizeAction(cell: string) {
  return String(cell || "").trim().toUpperCase();
}

function findColumnIndex(table: TableSection, candidates: string[], fallback: number) {
  const normalizedCandidates = candidates.map((item) => item.trim().toLowerCase());
  const index = table.columns.findIndex((column) => normalizedCandidates.includes(String(column ?? "").trim().toLowerCase()));
  return index >= 0 ? index : fallback;
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

function stockDetailPath(code: string) {
  return `/portfolio/position/${encodeURIComponent(code)}`;
}

function replayStockScopeLabel(row: TableRow) {
  const code = String(row.code ?? row.cells[0] ?? "").trim();
  const name = String(row.name ?? row.cells[1] ?? "").trim();
  if (name && code && name !== code) {
    return `${name}（${code}）`;
  }
  return code || name || "--";
}

function ReplayStockScopeCard({ rows }: { rows: TableRow[] }) {
  return (
    <WorkbenchCard>
      <div className="replay-stock-scope__header">
        <div>
          <h2 className="section-card__title replay-stock-scope__title">{t("当前任务量化股票")}</h2>
          <p className="section-card__description replay-stock-scope__description">
            {t("回放任务启动时记录的量化股票范围，任务内只处理这些股票。")}
          </p>
        </div>
        <span className="badge badge--neutral">{t("共 {v0} 只", { v0: rows.length })}</span>
      </div>
      {rows.length ? (
        <div className="replay-stock-scope__list" aria-label={t("当前任务量化股票")}>
          {rows.map((row, index) => {
            const code = String(row.code ?? row.cells[0] ?? "").trim();
            const label = replayStockScopeLabel(row);
            return (
              <Link
                className="replay-stock-scope__chip"
                key={`${code || row.id || "stock"}-${index}`}
                to={stockDetailPath(code || label)}
              >
                {label}
              </Link>
            );
          })}
        </div>
      ) : (
        <div className="summary-item summary-item--accent">
          <div className="summary-item__title">{t("暂无任务量化股票")}</div>
          <div className="summary-item__body">{t("新回放任务会在启动时记录当时已启用量化的股票范围。")}</div>
        </div>
      )}
    </WorkbenchCard>
  );
}

function removeExecutionResultColumn(table: TableSection): TableSection {
  const targetIndex = table.columns.findIndex((column) => {
    const normalized = String(column || "").trim().toLowerCase();
    return normalized === t("执行结果") || normalized === "execution result";
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
  const activeClient = client ?? apiClient;
  const loadReplayCapitalPool = useCallback(
    (query: Record<string, string | number>) => activeClient.getReplayCapitalPool<ReplayCapitalPoolSnapshot>(query),
    [activeClient],
  );
  const resource = usePageData("his-replay", activeClient, INITIAL_REPLAY_TABLE_QUERY);
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
  const [selectedTaskId, setSelectedTaskId] = useState("");
  const [tradeStockFilter, setTradeStockFilter] = useState("");
  const [tradeActionFilter, setTradeActionFilter] = useState("ALL");
  const [signalStockFilter, setSignalStockFilter] = useState("");
  const [signalActionFilter, setSignalActionFilter] = useState(DEFAULT_SIGNAL_ACTION_FILTER);
  const [tradePage, setTradePage] = useState(1);
  const [signalPage, setSignalPage] = useState(1);
  const [isReplayStarting, setIsReplayStarting] = useState(false);
  const [replayStartStatus, setReplayStartStatus] = useState<"idle" | "submitting" | "submitted" | "error">("idle");
  const selectedTaskForCheckpoint = snapshot?.tasks.find((task) => task.id === selectedTaskId) ?? snapshot?.tasks[0] ?? null;
  const selectedTaskRunId = selectedTaskForCheckpoint?.runId ?? "";
  const checkpointTaskLatestCheckpointAt = selectedTaskForCheckpoint?.latestCheckpointAt ?? "";
  const hasReplayCheckpointLoader = Boolean(selectedTaskRunId && typeof activeClient.getReplayCapitalPool === "function");
  const [checkpointSnapshot, setCheckpointSnapshot] = useState<ReplayCapitalPoolSnapshot | null>(null);
  const [checkpointPage, setCheckpointPage] = useState(1);
  const [checkpointLoading, setCheckpointLoading] = useState(false);
  const [checkpointError, setCheckpointError] = useState("");
  const [profitGapRowsState, setProfitGapRowsState] = useState<TableRow[]>([]);
  const [profitGapSummary, setProfitGapSummary] = useState<ProfitGapAttributionResponse["summary"] | null>(null);
  const [profitGapLoading, setProfitGapLoading] = useState(false);
  const [profitGapError, setProfitGapError] = useState("");
  const [profitGapLabelFilter, setProfitGapLabelFilter] = useState("ALL");
  const [profitGapSeverityFilter, setProfitGapSeverityFilter] = useState("ALL");
  const [profitGapActionableOnly, setProfitGapActionableOnly] = useState(false);
  const [profitGapMinAbsGap, setProfitGapMinAbsGap] = useState(500);
  const runningReplayTaskKey = replayPollingTaskKey(snapshot?.tasks);
  const selectedTaskForProfitGap = snapshot?.tasks.find((task) => task.id === selectedTaskId) ?? snapshot?.tasks[0] ?? null;
  const comparableHistoricalTask = snapshot ? pickComparableHistoricalTask(snapshot.tasks, selectedTaskForProfitGap) : null;

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
        setCheckpointError(error instanceof Error ? error.message : t("检查点资金池加载失败"));
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
    const checkpointAt = checkpointTaskLatestCheckpointAt && checkpointTaskLatestCheckpointAt !== "--" ? checkpointTaskLatestCheckpointAt : undefined;
    void loadReplayCheckpointPage(1, checkpointAt);
  }, [checkpointTaskLatestCheckpointAt, hasReplayCheckpointLoader, loadReplayCheckpointPage, selectedTaskRunId]);

  useEffect(() => {
    if (!rawSnapshot || typeof activeClient.getReplayProgress !== "function" || !runningReplayTaskKey) {
      return;
    }

    let cancelled = false;
    const replayQuery = {
      runId: selectedTaskRunId,
      pageSize: TRADE_PAGE_SIZE,
      tradePageSize: TRADE_PAGE_SIZE,
      tradePage,
      tradeAction: tradeActionFilter,
      tradeStock: tradeStockFilter.trim(),
      signalPageSize: SIGNAL_PAGE_SIZE,
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
    runningReplayTaskKey,
    selectedTaskRunId,
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

  useEffect(() => {
    if (
      !selectedTaskForProfitGap?.runId
      || !comparableHistoricalTask?.runId
      || typeof activeClient.getReplayProfitGap !== "function"
    ) {
      setProfitGapRowsState([]);
      setProfitGapSummary(null);
      setProfitGapError("");
      setProfitGapLoading(false);
      return;
    }

    let cancelled = false;
    setProfitGapLoading(true);
    setProfitGapError("");
    void activeClient
      .getReplayProfitGap<ProfitGapAttributionResponse>(
        selectedTaskForProfitGap.runId,
        comparableHistoricalTask.runId,
        200,
        {
          label: profitGapLabelFilter === "ALL" ? undefined : profitGapLabelFilter,
          severity: profitGapSeverityFilter === "ALL" ? undefined : profitGapSeverityFilter,
          actionableOnly: profitGapActionableOnly || undefined,
          minAbsGap: profitGapMinAbsGap || undefined,
        },
      )
      .then((payload) => {
        if (!cancelled) {
          setProfitGapRowsState(profitGapRows(payload.items ?? []));
          setProfitGapSummary(payload.summary ?? null);
        }
      })
      .catch((error) => {
        if (!cancelled) {
          setProfitGapRowsState([]);
          setProfitGapSummary(null);
          setProfitGapError(error instanceof Error ? error.message : t("收益差异归因加载失败"));
        }
      })
      .finally(() => {
        if (!cancelled) {
          setProfitGapLoading(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [
    activeClient,
    comparableHistoricalTask?.runId,
    profitGapActionableOnly,
    profitGapLabelFilter,
    profitGapMinAbsGap,
    profitGapSeverityFilter,
    selectedTaskForProfitGap?.runId,
  ]);

  if (resource.status === "loading" && !resource.data) {
    return <PageLoadingState title={t("历史回放加载中")} description={t("正在读取回放任务、候选池和交易结果。")} />;
  }

  if (resource.status === "error" && !resource.data) {
    return (
      <PageErrorState
        title={t("历史回放加载失败")}
        description={resource.error ?? t("无法加载历史回放数据，请稍后重试。")}
        actionLabel={t("重新加载")}
        onAction={resource.refresh}
      />
    );
  }

  if (!snapshot) {
    return <PageEmptyState title={t("历史回放暂无数据")} description={t("后台尚未返回历史回放快照。")} actionLabel={t("刷新")} onAction={resource.refresh} />;
  }

  const taskSummary = summarizeTaskStatuses(snapshot.tasks);
  const replayTaskLabel = taskSummary.running > 0 ? t("进行中 {v0}", { v0: taskSummary.running }) : t("已完成 {v0}", { v0: taskSummary.completed });
  const runningTask = snapshot.tasks.find((task) => String(task.status).toLowerCase() === "running") ?? null;
  const hasActiveReplayTask = snapshot.tasks.some((task) => {
    const normalized = String(task.status || "").trim().toLowerCase();
    return normalized === "running" || normalized === "queued";
  });
  const replayActionError = resource.status === "error" && resource.data ? resource.error : null;
  const runningProgress = Math.max(0, Math.min(Number(runningTask?.progress ?? 0), 100));
  const selectedTask = snapshot.tasks.find((task) => task.id === selectedTaskId) ?? snapshot.tasks[0] ?? null;
  const selectedTaskStockScope = selectedTask ? (selectedTask.stockScope?.length ? selectedTask.stockScope : snapshot.candidatePool.rows) : [];
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
      label: t("清算后现金"),
      value: formatSummaryNumber(selectedTaskLiquidation.liquidation_cash ?? findMetricValue(snapshot.tradeCostSummary, t("清算后现金"))),
    },
    {
      label: t("清算后总盈亏"),
      value: formatSummaryNumber(selectedTaskLiquidation.liquidation_total_pnl ?? findMetricValue(snapshot.tradeCostSummary, t("清算后总盈亏"))),
    },
    {
      label: t("期末清算费用"),
      value: formatSummaryNumber(selectedTaskLiquidation.fee_total ?? findMetricValue(snapshot.tradeCostSummary, t("期末清算费用"))),
    },
    {
      label: t("清算后收益率"),
      value: formatSummaryPercent(selectedTaskLiquidation.liquidation_return_pct ?? findMetricValue(snapshot.tradeCostSummary, t("清算后收益率"))),
    },
  ];
  const selectedTaskMetrics = selectedTask
    ? [
        { label: t("收益率"), value: selectedTask.returnPct || "--" },
        { label: t("总权益"), value: selectedTask.finalEquity || "--" },
        { label: t("现金"), value: selectedTask.cashValue || "--" },
        { label: t("持仓市值"), value: selectedTask.marketValue || "--" },
        { label: t("已实现"), value: selectedTask.realizedPnl || "--" },
        { label: t("浮动盈亏"), value: selectedTask.unrealizedPnl || "--" },
        { label: t("BUY信号"), value: toDisplayText(selectedTask.buySignalCount, "0") },
        { label: t("忽略BUY"), value: toDisplayText(selectedTask.ignoredBuySignalCount, "0") },
        { label: t("忽略SELL"), value: toDisplayText(selectedTask.ignoredSellSignalCount, "0") },
        ...selectedTaskLiquidationMetrics,
      ]
    : [];
  const executionCostSummary = (snapshot.tradeCostSummary ?? []).filter((metric) => !REPLAY_SUMMARY_METRIC_LABELS.has(metric.label));
  const executionHeroMetrics = pickMetrics(executionCostSummary, EXECUTION_HERO_METRIC_LABELS);
  const realizedExecutionMetric = executionHeroMetrics.find((metric) => metric.label === t("实现盈亏"));
  const primaryExecutionMetric =
    findMetric(snapshot.tradeCostSummary, t("清算后总盈亏"))
    ?? findMetric(snapshot.tradeCostSummary, t("总盈亏"))
    ?? realizedExecutionMetric;
  const primaryExecutionBasisLabel =
    primaryExecutionMetric?.label === t("清算后总盈亏")
      ? t("清算后总盈亏口径")
      : primaryExecutionMetric?.label === t("总盈亏")
        ? t("总盈亏口径")
        : t("实现盈亏口径");
  const executionWinRateMetric = executionCostSummary.find((metric) => metric.label === t("胜率"));
  const executionTradeCountMetric = executionCostSummary.find((metric) => metric.label === t("交易笔数"));
  const secondaryExecutionHeroMetrics = executionHeroMetrics.filter((metric) => metric.label !== primaryExecutionMetric?.label);
  const executionHeroMetricLabels = new Set(executionHeroMetrics.map((metric) => metric.label));
  const executionGroupMetricLabels = new Set(EXECUTION_STAT_GROUPS.flatMap((group) => group.labels));
  const executionStatGroups = EXECUTION_STAT_GROUPS.map((group) => ({
    ...group,
    metrics: pickMetrics(executionCostSummary, group.labels).filter((metric) => !executionHeroMetricLabels.has(metric.label)),
  })).filter((group) => group.metrics.length > 0);
  const executionOtherMetrics = executionCostSummary.filter(
    (metric) => !executionHeroMetricLabels.has(metric.label) && !executionGroupMetricLabels.has(metric.label),
  );
  const selectedTaskTopWinningTrades: TableSection = {
    columns: [t("时间"), t("信号ID"), t("代码"), t("卖出价"), t("净盈亏"), t("盈亏率"), t("执行明细")],
    rows: withCodeName(selectedTask?.topWinningTrades ?? [], 2),
    emptyLabel: t("暂无盈利交易"),
    emptyMessage: t("选中任务里还没有已兑现的盈利卖出交易。"),
  };
  const selectedTaskTopLosingTrades: TableSection = {
    columns: [t("时间"), t("信号ID"), t("代码"), t("卖出价"), t("净盈亏"), t("盈亏率"), t("执行明细")],
    rows: withCodeName(selectedTask?.topLosingTrades ?? [], 2),
    emptyLabel: t("暂无亏损交易"),
    emptyMessage: t("选中任务里还没有已兑现的亏损卖出交易。"),
  };
  const selectedTaskProfitLossByStock: TableSection = {
    columns: [t("代码"), t("名称"), t("合计盈亏"), t("已实现"), t("浮动盈亏"), t("买入成本"), t("卖出到账"), t("费用"), t("成交")],
    rows: selectedTask?.profitLossByStock ?? [],
    emptyLabel: t("暂无盈亏构成"),
    emptyMessage: t("选中任务还没有可归集到股票的成交或期末持仓。"),
  };
  const selectedTaskProfitGapAttributions: TableSection = {
    columns: [t("代码"), t("名称"), t("历史盈亏"), t("演练盈亏"), t("差额"), t("归因"), t("子原因"), t("严重级别"), t("处理状态"), t("建议动作"), t("主要原因")],
    rows: selectedTask?.profitGapAttributions?.length ? selectedTask.profitGapAttributions : profitGapRowsState,
    emptyLabel: profitGapLoading ? t("收益差异归因加载中") : t("暂无收益差异归因"),
    emptyMessage: profitGapError
      || (comparableHistoricalTask
        ? t("当前对比任务还没有生成收益差异归因。")
        : t("需要选择同区间的实时量化演练和历史回放任务后才会展示。")),
  };
  const tradeRows = withCodeName(snapshot.trades.rows, 2);
  const signalTable = removeExecutionResultColumn(snapshot.signals);
  const signalRows = signalTable.rows;
  const signalActionColumnIndex = findColumnIndex(signalTable, [t("动作"), "action"], 4);
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
        .map((row) => normalizeAction(String(row.cells[signalActionColumnIndex] ?? "")))
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
    <div className="table-toolbar-compact__pager" aria-label={t("分页控制")}>
      <button
        className="icon-button icon-button--neutral table-toolbar-compact__pager-button"
        type="button"
        style={{ height: toolbarControlHeight, minHeight: toolbarControlHeight, width: toolbarControlHeight, minWidth: toolbarControlHeight }}
        aria-label={t("上一页")}
        title={t("上一页")}
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
        {t("第 {v0} / {v1} 页", { v0: page, v1: pages })}
      </span>
      <button
        className="icon-button icon-button--neutral table-toolbar-compact__pager-button"
        type="button"
        style={{ height: toolbarControlHeight, minHeight: toolbarControlHeight, width: toolbarControlHeight, minWidth: toolbarControlHeight }}
        aria-label={t("下一页")}
        title={t("下一页")}
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
        placeholder={t("按代码/名称过滤")}
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
        <option value="ALL">{t("全部动作")}</option>
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
  const renderProfitGapToolbar = () => (
    <div className="table-toolbar-compact" style={{ alignItems: "center" }}>
      <select
        className="input"
        style={{ height: toolbarControlHeight, minHeight: toolbarControlHeight, padding: "0 10px" }}
        value={profitGapLabelFilter}
        onChange={(event) => setProfitGapLabelFilter(event.target.value)}
        aria-label={t("归因筛选")}
      >
        <option value="ALL">{t("全部归因")}</option>
        {PROFIT_GAP_LABEL_OPTIONS.map((option) => (
          <option key={option} value={option}>
            {option}
          </option>
        ))}
      </select>
      <select
        className="input"
        style={{ height: toolbarControlHeight, minHeight: toolbarControlHeight, padding: "0 10px" }}
        value={profitGapSeverityFilter}
        onChange={(event) => setProfitGapSeverityFilter(event.target.value)}
        aria-label={t("严重级别筛选")}
      >
        <option value="ALL">{t("全部级别")}</option>
        {PROFIT_GAP_SEVERITY_OPTIONS.map((option) => (
          <option key={option} value={option}>
            {option}
          </option>
        ))}
      </select>
      <label className="badge badge--neutral" style={{ height: toolbarControlHeight, minHeight: toolbarControlHeight, display: "inline-flex", alignItems: "center", gap: 6 }}>
        <input
          type="checkbox"
          checked={profitGapActionableOnly}
          onChange={(event) => setProfitGapActionableOnly(event.target.checked)}
        />
        {t("仅看需处理")}
      </label>
      <input
        className="input"
        type="number"
        min={0}
        step={100}
        style={{ height: toolbarControlHeight, minHeight: toolbarControlHeight, padding: "0 10px", width: 120 }}
        value={profitGapMinAbsGap}
        onChange={(event) => setProfitGapMinAbsGap(Math.max(0, Number(event.target.value) || 0))}
        aria-label={t("最小差额")}
      />
      <span className="summary-item__body table-toolbar-compact__count" style={{ margin: 0 }}>
        {t("合计 {v0} 条 · 需处理 {v1} 条 · 大额未分类 {v2} 条", {
          v0: profitGapSummary?.total ?? selectedTaskProfitGapAttributions.rows.length,
          v1: profitGapSummary?.actionable_count ?? 0,
          v2: profitGapSummary?.large_unclassified_count ?? 0,
        })}
      </span>
    </div>
  );
  const handleReplayStart = async () => {
    setIsReplayStarting(true);
    setReplayStartStatus("submitting");
    try {
      const nextSnapshot = await resource.runAction("start", {
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
        title={t("历史回放")}
        description={t("围绕统一股票池中启用量化的股票回放历史区间，核对任务、成交、费用和信号落库结果。")}
        actions={
          <div className="chip-row">
            <span className="badge badge--neutral">{t("快照")}{snapshot.updatedAt}</span>
            <span className="badge badge--accent">{t("任务")}{snapshot.tasks.length}</span>
            <span className={`badge ${runningTask ? "badge--accent" : "badge--success"}`}>
              {runningTask ? t("执行中 {v0}%", { v0: runningProgress }) : replayTaskLabel}
            </span>
            {runningTask?.stage ? <span className="badge badge--neutral">{runningTask.stage}</span> : null}
          </div>
        }
      />
      <div className="section-grid section-grid--sidebar">
        <div className="stack">
          <WorkbenchCard>
            <h2 className="section-card__title">{t("回放配置")}</h2>
            <div className="summary-list">
              <label className="field">
                <span className="field__label">{t("回放模式")}</span>
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
                  <span className="field__label">{t("开始日期")}</span>
                  <input className="input" type="date" value={startDate} onChange={(event) => setStartDate(event.target.value)} />
                </label>
                {replayUntilNow ? (
                  <div className="summary-item summary-item--accent">
                    <div className="summary-item__title">{t("结束日期")}</div>
                    <div className="summary-item__body">{t("当前模式下结束日期自动取当前日期时间。")}</div>
                  </div>
                ) : (
                  <label className="field">
                    <span className="field__label">{t("结束日期")}</span>
                    <input className="input" type="date" value={endDate} onChange={(event) => setEndDate(event.target.value)} />
                  </label>
                )}
              </div>
              <div className="section-grid">
                <label className="field">
                  <span className="field__label">{t("开始时间")}</span>
                  <input className="input" type="time" value={startTime} onChange={(event) => setStartTime(event.target.value)} />
                </label>
                {replayUntilNow ? (
                  <div className="summary-item summary-item--accent">
                    <div className="summary-item__title">{t("结束时间")}</div>
                    <div className="summary-item__body">{t("结束时间将自动取当前时刻。")}</div>
                  </div>
                ) : (
                  <label className="field">
                    <span className="field__label">{t("结束时间")}</span>
                    <input className="input" type="time" value={endTime} onChange={(event) => setEndTime(event.target.value)} />
                  </label>
                )}
              </div>
              <label className="field">
                <span className="field__label">{t("回放粒度")}</span>
                <select className="input" value={timeframe} onChange={(event) => setTimeframe(event.target.value)}>
                  {TIMEFRAME_OPTIONS.map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                </select>
              </label>
              <label className="field">
                <span className="field__label">{t("市场")}</span>
                <select className="input" value={market} onChange={(event) => setMarket(event.target.value as (typeof MARKET_OPTIONS)[number])}>
                  {MARKET_OPTIONS.map((option) => (
                    <option key={option} value={option}>
                      {option}
                    </option>
                  ))}
                </select>
              </label>
              <label className="field">
                <span className="field__label">{t("策略配置")}</span>
                <select className="input" value={strategyProfileId} onChange={(event) => setStrategyProfileId(event.target.value)}>
                  {(snapshot.config.strategyProfiles ?? []).map((item) => (
                    <option key={item.id} value={item.id}>
                      {item.name}
                    </option>
                  ))}
                </select>
              </label>
              <label className="field">
                <span className="field__label">{t("回放资金池(元)")}</span>
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
                <span className="field__label">{t("AI动态策略")}</span>
                <select className="input" value={aiDynamicStrategy} onChange={(event) => setAiDynamicStrategy(event.target.value)}>
                  {AI_DYNAMIC_STRATEGY_OPTIONS.map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                </select>
              </label>
              <label className="field">
                <span className="field__label">{t("手续费率(%)")}</span>
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
                <span className="field__label">{t("卖出税费率(%)")}</span>
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
                  {t("结束时间留空则回放到当前时刻")}</span>
              </label>
            </div>
            <div className="card-divider" />
            <div className="toolbar toolbar--compact">
              <button
                className="button button--primary"
                type="button"
                disabled={isReplayStarting || resource.status === "loading" || hasActiveReplayTask}
                onClick={() => void handleReplayStart()}
              >
                {isReplayStarting ? t("提交中...") : t("开始回溯")}
              </button>
              <button
                className="button button--secondary"
                type="button"
                disabled={resource.status === "loading"}
                onClick={() => void resource.runAction("cancel")}
              >
                {t("取消")}</button>
              <span className="toolbar__spacer" />
              <button
                className="button button--secondary"
                type="button"
                disabled={resource.status === "loading"}
                onClick={() => void resource.runAction("delete")}
              >
                {t("删除")}</button>
            </div>
            {hasActiveReplayTask ? (
              <div className="summary-item summary-item--accent" style={{ marginTop: "12px" }}>
                <div className="summary-item__title">{t("已有回放任务在执行")}</div>
                <div className="summary-item__body">{t("当前存在进行中或排队中的回放任务。请先等待完成，或取消后再开始新的回放。")}</div>
              </div>
            ) : null}
            {replayStartStatus === "submitting" ? (
              <div className="summary-item summary-item--accent" style={{ marginTop: "12px" }}>
                <div className="summary-item__title">{t("回放任务正在提交")}</div>
                <div className="summary-item__body">{t("后台已接收请求前，前端会保持提交状态；任务创建后会自动切到最新任务进度。")}</div>
              </div>
            ) : null}
            {replayStartStatus === "submitted" ? (
              <div className="summary-item summary-item--success" style={{ marginTop: "12px" }}>
                <div className="summary-item__title">{t("回放任务已提交")}</div>
                <div className="summary-item__body">{t("已切换到最新回放任务；运行期间进度会每 1 分钟自动刷新一次。")}</div>
              </div>
            ) : null}
            {replayStartStatus === "error" ? (
              <div className="summary-item summary-item--danger" style={{ marginTop: "12px" }}>
                <div className="summary-item__title">{t("回放任务提交失败")}</div>
                <div className="summary-item__body">{t("后台没有返回新的任务快照，请查看操作失败信息或稍后重试。")}</div>
              </div>
            ) : null}
            {replayActionError ? (
              <div className="summary-item summary-item--danger" style={{ marginTop: "12px" }}>
                <div className="summary-item__title">{t("操作失败")}</div>
                <div className="summary-item__body">{replayActionError}</div>
              </div>
            ) : null}
          </WorkbenchCard>

        </div>

        <div className="stack">
          <WorkbenchCard>
            <div className="replay-task-card-header">
              <h2 className="section-card__title replay-task-card-title">{t("回放任务")}</h2>
              <div className="replay-task-card-controls">
                <div className="chip-row replay-task-card-badges">
                  <span className="badge badge--neutral">{t("已完成")}{taskSummary.completed}</span>
                  <span className="badge badge--accent">{t("进行中")}{taskSummary.running}</span>
                  <span className="badge badge--neutral">{t("排队")}{taskSummary.queued}</span>
                </div>
                {snapshot.tasks.length > 0 ? (
                  <label className="field replay-task-selector">
                    <span className="field__label replay-task-selector__label">{t("选择任务")}</span>
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
                  <div className="summary-list" aria-label={t("已选回放任务详情")}>
                    <div className="summary-item replay-task-overview">
                      <div className="replay-task-overview__topline">
                        <div>
                          <div className="summary-item__title">{t("回放结论与进度")}</div>
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
                      <div className="replay-task-progress" aria-label={t("回放进度 {v0}%", { v0: selectedTaskProgressPct })}>
                        <div className="replay-task-progress__bar">
                          <div className="replay-task-progress__fill" style={{ width: `${selectedTaskProgressPct}%` }} />
                        </div>
                        <div className="replay-task-progress__meta">
                          <span>{t("检查点进度：{v0} · {v1}%", { v0: selectedTaskProgressText, v1: selectedTaskProgressPct })}</span>
                          <span>{t("已写入：{v0}", { v0: selectedTaskCheckpointCount })}</span>
                        </div>
                        {hasReplayCheckpointLoader ? (
                          <div className="replay-task-checkpoint-controls">
                            <label className="field replay-task-checkpoint-controls__select">
                              <span className="field__label">{t("检查点")}</span>
                              <select
                                className="input"
                                value={selectedCheckpointAt}
                                aria-label={t("检查点")}
                                disabled={checkpointLoading || !checkpointItems.length}
                                onChange={(event) => void loadReplayCheckpointPage(checkpointPage, event.target.value)}
                              >
                                {checkpointItems.length ? (
                                  checkpointItems.map((item) => (
                                    <option key={item.id} value={item.checkpointAt}>
                                      {t("{v0} · 权益 {v1}", { v0: item.label, v1: item.totalEquity ?? "--" })}
                                    </option>
                                  ))
                                ) : (
                                  <option value={selectedCheckpointAt}>{selectedCheckpointAt || t("暂无检查点")}</option>
                                )}
                              </select>
                            </label>
                            <div className="replay-task-checkpoint-controls__pager">
                              <button
                                type="button"
                                className="icon-button icon-button--neutral"
                                aria-label={t("上一组检查点")}
                                disabled={checkpointLoading || !checkpointPagination || checkpointPagination.page <= 1}
                                onClick={() => void loadReplayCheckpointPage(Math.max(1, checkpointPage - 1))}
                              >
                                ←
                              </button>
                              <span>{checkpointPagination ? `第 ${checkpointPagination.page} / ${checkpointPagination.totalPages} 页` : t("第 -- / -- 页")}</span>
                              <button
                                type="button"
                                className="icon-button icon-button--neutral"
                                aria-label={t("下一组检查点")}
                                disabled={checkpointLoading || !checkpointPagination || checkpointPagination.page >= checkpointPagination.totalPages}
                                onClick={() => void loadReplayCheckpointPage(checkpointPage + 1)}
                              >
                                →
                              </button>
                            </div>
                            {checkpointLoading ? <span className="badge badge--neutral">{t("加载中")}</span> : null}
                            {checkpointError ? <span className="badge badge--danger">{checkpointError}</span> : null}
                          </div>
                        ) : null}
                      </div>
                      <div className="replay-task-overview__grid">
                        <div className="summary-item__body">{t("开始时间：{v0}", { v0: selectedTaskStartedAt })}</div>
                        <div className="summary-item__body">{t("结束时间：{v0}", { v0: selectedTaskEndedAt })}</div>
                        <div className="summary-item__body">{t("最近检查点：{v0}", { v0: selectedTaskLatestCheckpointAt })}</div>
                        <div className="summary-item__body">{t("已写入检查点：{v0}", { v0: selectedTaskCheckpointCount })}</div>
                        {selectedTask.checkpointCoverage ? (
                          <div className="summary-item__body">
                            {t("数据覆盖：精确 {v0} · 最近 {v1} · 缺失 {v2} · 跳过 {v3}", {
                              v0: String(selectedTask.checkpointCoverage.exactCount ?? 0),
                              v1: String(selectedTask.checkpointCoverage.nearestCount ?? 0),
                              v2: String(selectedTask.checkpointCoverage.missingCount ?? 0),
                              v3: String(selectedTask.checkpointCoverage.skippedCount ?? 0),
                            })}
                          </div>
                        ) : null}
                        {selectedTask.contextParity?.stockAnalysisContext ? (
                          <div className="summary-item__body">
                            {t("上下文差异：研究上下文 {v0} · {v1}", {
                              v0: selectedTask.contextParity.stockAnalysisContext.status ?? "--",
                              v1: selectedTask.contextParity.stockAnalysisContext.omittedReason ?? "--",
                            })}
                          </div>
                        ) : null}
                        <div className="summary-item__body">{t("回放节点：{v0}", { v0: selectedTaskProgressTotal > 0 ? selectedTaskProgressTotal : selectedTaskCheckpointCount })}</div>
                        <div className="summary-item__body">{t("区间：{v0}", { v0: selectedTaskRange })}</div>
                        <div className="summary-item__body">{t("模式：{v0} · 粒度：{v1} · 市场：{v2}", { v0: selectedTaskModeLabel, v1: selectedTaskTimeframe, v2: selectedTaskMarket })}</div>
                        <div className="summary-item__body replay-task-overview__wide">
                          {t("策略配置：{profile}{version}", {
                            profile: selectedTask.strategyProfileName || selectedTask.strategyProfileId || strategyProfileId || "--",
                            version: selectedTask.strategyProfileVersionId ? t(" · 版本#{id}", { id: selectedTask.strategyProfileVersionId }) : "",
                          })}
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
                <div className="summary-item__title">{t("暂无回放任务")}</div>
                <div className="summary-item__body">{t("当前没有排队中的历史回放任务，点击“开始回溯”后会在这里创建新任务。")}</div>
              </div>
            )}
          </WorkbenchCard>

          <ReplayStockScopeCard rows={selectedTaskStockScope} />

          {selectedTaskCapitalPool ? (
            <ReplayCapitalPoolPanel capitalPool={selectedTaskCapitalPool} />
          ) : null}

          <OutcomeSummaryCard summary={selectedTask?.outcomeSummary} />

          {executionCostSummary.length ? (
            <WorkbenchCard>
              <h2 className="section-card__title">{t("费用与执行统计")}</h2>
              <p className="section-card__description">{t("按买入成本、卖出到账、费用和实现盈亏归集，成交笔数仅作为执行背景。")}</p>
              <div className="execution-summary execution-summary--finance" aria-label={t("费用与执行统计")}>
                {executionHeroMetrics.length ? (
                  <div className="execution-summary__hero">
                    {primaryExecutionMetric ? (
                      <div className="execution-summary__hero-card execution-summary__hero-card--primary" key={primaryExecutionMetric.label}>
                        <span>{t("收益结果")}</span>
                        <strong>{primaryExecutionMetric.value}</strong>
                        <em>
                          {primaryExecutionBasisLabel} · {t("已扣手续费与印花税")}{executionTradeCountMetric ? ` · ${executionTradeCountMetric.label} ${executionTradeCountMetric.value}` : ""}
                          {executionWinRateMetric ? t(" · 胜率 {v0}", { v0: executionWinRateMetric.value }) : ""}
                        </em>
                      </div>
                    ) : null}
                    {secondaryExecutionHeroMetrics.map((metric) => (
                      <div className="execution-summary__hero-card" key={metric.label}>
                        <span>{metric.label}</span>
                        <strong>{metric.value}</strong>
                      </div>
                    ))}
                  </div>
                ) : null}
                <div className="execution-summary__groups">
                  {executionStatGroups.map((group) => (
                    <section className="execution-summary__group" key={group.title}>
                      <h3>{group.title}</h3>
                      <div className="execution-summary__rows">
                        {group.metrics.map((metric) => (
                          <div className="execution-summary__row" key={metric.label}>
                            <span>{metric.label}</span>
                            <strong>{metric.value}</strong>
                          </div>
                        ))}
                      </div>
                    </section>
                  ))}
                  {executionOtherMetrics.length ? (
                    <section className="execution-summary__group">
                      <h3>{t("其他")}</h3>
                      <div className="execution-summary__rows">
                        {executionOtherMetrics.map((metric) => (
                          <div className="execution-summary__row" key={metric.label}>
                            <span>{metric.label}</span>
                            <strong>{metric.value}</strong>
                          </div>
                        ))}
                      </div>
                    </section>
                  ) : null}
                </div>
              </div>
            </WorkbenchCard>
          ) : null}

          <QuantTableSectionCard
            title={t("盈亏构成")}
            description={t("按股票归集本次任务的已实现盈亏、期末浮动盈亏、成本、到账和费用，用来判断收益主要来自哪些标的。")}
            table={selectedTaskProfitLossByStock}
            emptyTitle={selectedTaskProfitLossByStock.emptyLabel ?? t("暂无盈亏构成")}
            emptyDescription={selectedTaskProfitLossByStock.emptyMessage ?? t("选中任务还没有可归集到股票的成交或期末持仓。")}
            tableLayout="auto"
            compactConfig={{ coreColumnIndexes: [0, 2, 3, 4], detailColumnIndexes: [1, 5, 6, 7, 8] }}
            signalDetailSource="replay"
          />

          {isLiveQuantDrillTask(selectedTask) || selectedTaskProfitGapAttributions.rows.length ? (
            <QuantTableSectionCard
              title={t("收益差异归因")}
              description={t("对比同区间历史回放和实时量化演练，标记买太小、买太晚、误买、probe亏损和SELL阻断。")}
              table={selectedTaskProfitGapAttributions}
              emptyTitle={selectedTaskProfitGapAttributions.emptyLabel ?? t("暂无收益差异归因")}
              emptyDescription={selectedTaskProfitGapAttributions.emptyMessage ?? t("需要选择同区间的实时量化演练和历史回放任务后才会展示。")}
              toolbar={renderProfitGapToolbar()}
              tableLayout="auto"
              compactConfig={{ coreColumnIndexes: [0, 4, 5, 6], detailColumnIndexes: [1, 2, 3, 7, 8, 9, 10] }}
              signalDetailSource="replay"
            />
          ) : null}

          <div className="section-grid">
            <QuantTableSectionCard
              title={t("Top 5 盈利交易")}
              description={t("只统计本次回放中已卖出并兑现盈利的交易，按净盈亏从高到低排序。")}
              table={selectedTaskTopWinningTrades}
              emptyTitle={selectedTaskTopWinningTrades.emptyLabel ?? t("暂无盈利交易")}
              emptyDescription={selectedTaskTopWinningTrades.emptyMessage ?? t("选中任务没有盈利交易。")}
              tableLayout="auto"
              compactConfig={{ coreColumnIndexes: [2, 4, 5], detailColumnIndexes: [0, 1, 3, 6] }}
              signalDetailSource="replay"
            />

            <QuantTableSectionCard
              title={t("Top 5 亏损交易")}
              description={t("只统计本次回放中已卖出并兑现亏损的交易，按净亏损从大到小排序。")}
              table={selectedTaskTopLosingTrades}
              emptyTitle={selectedTaskTopLosingTrades.emptyLabel ?? t("暂无亏损交易")}
              emptyDescription={selectedTaskTopLosingTrades.emptyMessage ?? t("选中任务没有亏损交易。")}
              tableLayout="auto"
              compactConfig={{ coreColumnIndexes: [2, 4, 5], detailColumnIndexes: [0, 1, 3, 6] }}
              signalDetailSource="replay"
            />
          </div>

          <QuantTableSectionCard
            title={t("成交明细")}
            table={pagedTrades}
            emptyTitle={snapshot.trades.emptyLabel ?? t("成交明细暂无数据")}
            emptyDescription={snapshot.trades.emptyMessage ?? t("历史回放执行后，所有成交会统一落在这里。")}
            tableLayout="auto"
            compactConfig={{ coreColumnIndexes: [0, 2, 3, 11], detailColumnIndexes: [1, 4, 5, 6, 7, 8, 9, 10, 12, 13, 14] }}
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
              t("DB筛选 {v0} 条", { v0: tradeTotalRows }),
              false,
            )}
          />

          <QuantTableSectionCard
            title={t("信号记录")}
            table={pagedSignals}
            emptyTitle={snapshot.signals.emptyLabel ?? t("信号记录暂无数据")}
            emptyDescription={snapshot.signals.emptyMessage ?? t("回放过程中生成的信号会展示在这里，便于快速核对执行结果。")}
            tableLayout="auto"
            compactConfig={{ coreColumnIndexes: [0, 2, 3, 4], detailColumnIndexes: [1, 5, 6, 7, 8, 9, 10, 11, 12] }}
            toolbar={renderFilterToolbar(
              signalStockFilter,
              setSignalStockFilter,
              signalActionFilter,
              setSignalActionFilter,
              signalActionOptions,
              effectiveSignalPage,
              signalPages,
              setSignalPage,
              t("DB筛选 {v0} 条", { v0: signalTotalRows }),
              true,
            )}
            signalDetailSource="replay"
          />
        </div>
      </div>
    </div>
  );
}
