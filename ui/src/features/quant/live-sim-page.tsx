import { useEffect, useState, type ReactNode } from "react";
import { Link, useNavigate } from "react-router-dom";
import { apiClient, type ApiClient } from "../../lib/api-client";
import { PageHeader } from "../../components/ui/page-header";
import { WorkbenchCard } from "../../components/ui/workbench-card";
import { PageEmptyState, PageErrorState, PageLoadingState } from "../../components/ui/page-state";
import { usePageData } from "../../lib/use-page-data";
import type { SummaryMetric, TableRow, TableSection } from "../../lib/page-models";
import { toDisplayCount, toDisplayText } from "./quant-display";
import { QuantTableSectionCard } from "./quant-table-section";
import { ReplayCapitalPoolPanel } from "./replay-capital-pool-panel";
import { t } from "../../lib/i18n";
import {
  DEFAULT_LIFECYCLE_SETTINGS,
  DEFAULT_QUANT_STATUS_FILTERS,
  HealthScoreBar,
  LifecycleSummaryBadgeGroup,
  QUANT_STATUS_OPTIONS,
  QuantStatusBadge,
  StatusFilterChips,
  normalizeLifecycleSettings,
  type QuantLifecyclePayload,
  type QuantLifecycleSettings,
} from "./quant-lifecycle-controls";

const ANALYSIS_TIMEFRAME_OPTIONS = [
  { value: "30m", label: t("30分钟") },
  { value: "1d", label: t("日线") },
  { value: "1d+30m", label: t("日线方向 + 30分钟确认") },
];

const AI_DYNAMIC_STRATEGY_OPTIONS = [
  { value: "off", label: t("关闭") },
  { value: "hybrid", label: t("开启") },
];

const MARKET_OPTIONS = ["CN", "HK", "US"] as const;
const SIGNAL_PAGE_SIZE = 20;
const EXECUTION_HERO_METRIC_LABELS = [t("实现盈亏"), t("买入总成本"), t("卖出到账"), t("总费用")];
const EXECUTION_STAT_GROUPS = [
  { title: t("成本拆解"), labels: [t("买入毛额"), t("手续费")] },
  { title: t("收入拆解"), labels: [t("卖出毛额"), t("印花税")] },
  { title: t("交易背景"), labels: [t("交易笔数"), t("胜率"), t("买入笔数"), t("卖出笔数"), t("加仓次数")] },
  { title: "Lot / Slot", labels: [t("买入lot"), t("卖出lot"), t("剩余lot"), t("占用slot"), t("释放slot"), t("最大占用slot"), t("平均占用slot")] },
];

function parseIntervalMinutes(value: string) {
  const match = String(value).match(/(\d+)/);
  return match ? Number(match[1]) : 15;
}

function localDateInput(date = new Date()) {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function normalizeAnalysisTimeframe(value: string) {
  const normalized = String(value).trim().toLowerCase();
  if (normalized === t("日线")) return "1d";
  if (normalized.includes(t("30分钟"))) return "1d+30m";
  return ANALYSIS_TIMEFRAME_OPTIONS.find((option) => option.value === normalized)?.value ?? "30m";
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

function parseRatePercent(value: string | undefined, fallback: number) {
  const match = String(value ?? "").match(/-?\d+(\.\d+)?/);
  if (!match) return fallback;
  const parsed = Number(match[0]);
  if (!Number.isFinite(parsed)) return fallback;
  return Math.max(0, parsed);
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

function parseNumberConfig(value: string | number | undefined, fallback: number) {
  const parsed = Number.parseFloat(String(value ?? ""));
  return Number.isFinite(parsed) ? parsed : fallback;
}

function pickMetrics(metrics: SummaryMetric[], labels: string[]) {
  const byLabel = new Map(metrics.map((metric) => [metric.label, metric]));
  return labels.map((label) => byLabel.get(label)).filter((metric): metric is SummaryMetric => Boolean(metric));
}

function withoutTableColumns(table: TableSection, shouldOmit: (column: string) => boolean): TableSection {
  const visibleIndexes = table.columns
    .map((column, index) => ({ column, index }))
    .filter(({ column }) => !shouldOmit(String(column)))
    .map(({ index }) => index);
  return {
    ...table,
    columns: visibleIndexes.map((index) => table.columns[index]),
    rows: table.rows.map((row) => ({
      ...row,
      cells: visibleIndexes.map((index) => row.cells[index] ?? ""),
    })),
  };
}

function normalizeSignalAction(value: string) {
  return String(value ?? "").trim().toUpperCase();
}

function findColumnIndex(table: TableSection, candidates: string[], fallback: number) {
  const normalizedCandidates = candidates.map((item) => item.trim().toLowerCase());
  const index = table.columns.findIndex((column) => normalizedCandidates.includes(String(column ?? "").trim().toLowerCase()));
  return index >= 0 ? index : fallback;
}

function removeStrategyColumn(table: TableSection): TableSection {
  const strategyIndexes = table.columns
    .map((column, index) => ({ normalized: String(column ?? "").trim().toLowerCase(), index }))
    .filter(({ normalized }) => normalized.includes(t("策略")) || normalized === "strategy")
    .map(({ index }) => index);

  if (strategyIndexes.length === 0) {
    return table;
  }

  return {
    ...table,
    columns: table.columns.filter((_, index) => !strategyIndexes.includes(index)),
    rows: table.rows.map((row) => ({
      ...row,
      cells: row.cells.filter((_, index) => !strategyIndexes.includes(index)),
    })),
  };
}

function mergeTradeRemarksIntoDetails(table: TableSection): TableSection {
  const remarkIndex = table.columns.findIndex((column) => {
    const normalized = String(column ?? "").trim().toLowerCase();
    return normalized === t("备注") || normalized === "note";
  });
  if (remarkIndex < 0) {
    return table;
  }
  const detailIndex = table.columns.findIndex((column) => String(column ?? "").includes(t("执行明细")));
  return {
    ...table,
    columns: table.columns.filter((_, index) => index !== remarkIndex),
    rows: table.rows.map((row) => {
      const cells = [...row.cells];
      const remark = String(cells[remarkIndex] ?? "").trim();
      if (detailIndex >= 0 && remark && remark !== "--") {
        cells[detailIndex] = [cells[detailIndex], remark].filter(Boolean).join(" · ");
      }
      return {
        ...row,
        cells: cells.filter((_, index) => index !== remarkIndex),
      };
    }),
  };
}

function emptyLiveSignalTable(message = t("暂无信号")): TableSection {
  return {
    columns: [t("信号ID"), t("时间"), t("代码"), t("动作"), t("状态")],
    rows: [],
    emptyLabel: t("暂无信号"),
    emptyMessage: message,
  };
}

function emptyLiveTradeTable(message = t("暂无交易记录")): TableSection {
  return {
    columns: [t("时间"), t("代码"), t("动作"), t("数量"), t("价格"), t("备注")],
    rows: [],
    emptyLabel: t("暂无交易记录"),
    emptyMessage: message,
  };
}

type LifecycleTableRow = TableRow & {
  lifecycle?: QuantLifecyclePayload;
};

const lifecycleOf = (row: TableRow): QuantLifecyclePayload => (row as LifecycleTableRow).lifecycle ?? {};
const lifecycleStatusOf = (row: TableRow) => ((row as LifecycleTableRow).lifecycle ? String(lifecycleOf(row).quant_status || "active") : "active");
const stockDetailPath = (code: string) => `/portfolio/position/${encodeURIComponent(code)}`;

async function requestQuantUniverse<T>(path: string, payload?: unknown): Promise<T> {
  const response = await fetch(path, {
    method: payload === undefined ? "GET" : "POST",
    headers: { "Content-Type": "application/json" },
    body: payload === undefined ? undefined : JSON.stringify(payload),
  });
  if (!response.ok) {
    throw new Error(`Request failed: ${response.status}`);
  }
  return (await response.json()) as T;
}

type LiveSimPageProps = {
  client?: ApiClient;
};

type LiveQuantDrillResult = {
  runId?: number | string;
  runType?: string;
  status?: string;
  redirect?: string;
};

type LiveQuantStockListProps = {
  table: TableSection;
  title: string;
  description: string;
  emptyTitle: string;
  emptyDescription: string;
  meta: string[];
  toolbar: ReactNode;
};

function LiveQuantStockList({
  table,
  title,
  description,
  emptyTitle,
  emptyDescription,
  meta,
  toolbar,
}: LiveQuantStockListProps) {
  const codeIndex = findColumnIndex(table, [t("股票代码"), t("代码"), "code"], 0);
  const nameIndex = findColumnIndex(table, [t("股票名称"), t("名称"), "name"], 1);
  const priceIndex = findColumnIndex(table, [t("最新价格"), t("价格"), "price"], 2);

  return (
    <WorkbenchCard>
      <div className="toolbar">
        <div>
          <h2 className="section-card__title" style={{ margin: 0 }}>
            {title}
          </h2>
          <p className="table__caption" style={{ marginBottom: 0 }}>
            {description}
          </p>
          <div className="chip-row" style={{ marginTop: "10px" }}>
            {meta.map((item) => (
              <span className="badge badge--neutral" key={item}>
                {item}
              </span>
            ))}
          </div>
        </div>
        <span className="toolbar__spacer" />
        {toolbar}
      </div>
      {table.rows.length === 0 ? (
        <div className="summary-item summary-item--accent">
          <div className="summary-item__title">{emptyTitle}</div>
          <div className="summary-item__body">{emptyDescription}</div>
        </div>
      ) : (
        <div className="live-quant-stock-list">
          {table.rows.map((row) => {
            const lifecycle = lifecycleOf(row);
            const code = String(row.code || row.id || row.cells[codeIndex] || "");
            const name = String(row.cells[nameIndex] || "--");
            const price = String(row.cells[priceIndex] || "--");
            const status = lifecycleStatusOf(row);
            const showStatusBadge = status !== "trial" && status !== "active";
            return (
              <article className="live-quant-stock-card" key={row.id}>
                <div className="live-quant-stock-card__identity">
                  <Link className="stock-link live-quant-stock-card__code" to={stockDetailPath(code)}>
                    {code}
                  </Link>
                  <span className="live-quant-stock-card__name">{name}</span>
                </div>
                <div className="live-quant-stock-card__price">
                  <strong>{price}</strong>
                </div>
                <div className="live-quant-stock-card__state">
                  {showStatusBadge ? <QuantStatusBadge status={status} /> : null}
                  <HealthScoreBar value={lifecycle.health_score} compact />
                </div>
              </article>
            );
          })}
        </div>
      )}
    </WorkbenchCard>
  );
}

export function LiveSimPage({ client }: LiveSimPageProps) {
  const activeClient = client ?? apiClient;
  const navigate = useNavigate();
  const resource = usePageData("live-sim", activeClient);
  const snapshot = resource.data;
  const snapshotVersion = snapshot?.updatedAt ?? "loading";
  const [intervalMinutes, setIntervalMinutes] = useState(15);
  const [analysisTimeframe, setAnalysisTimeframe] = useState("30m");
  const [strategyProfileId, setStrategyProfileId] = useState("");
  const [aiDynamicStrategy, setAiDynamicStrategy] = useState("off");
  const [aiDynamicStrength, setAiDynamicStrength] = useState(0.5);
  const [aiDynamicLookback, setAiDynamicLookback] = useState(48);
  const [market, setMarket] = useState<(typeof MARKET_OPTIONS)[number]>("CN");
  const [initialCash, setInitialCash] = useState(100000);
  const [commissionRatePct, setCommissionRatePct] = useState(0.03);
  const [sellTaxRatePct, setSellTaxRatePct] = useState(0.1);
  const [capitalMaxSlots, setCapitalMaxSlots] = useState(25);
  const [capitalFullBuyEdge, setCapitalFullBuyEdge] = useState(0.25);
  const [capitalConfidenceWeight, setCapitalConfidenceWeight] = useState(0.35);
  const [capitalHighPriceThreshold, setCapitalHighPriceThreshold] = useState(100);
  const [capitalHighPriceMaxSlotUnits, setCapitalHighPriceMaxSlotUnits] = useState(2);
  const [lifecycleSettings, setLifecycleSettings] = useState<QuantLifecycleSettings>(DEFAULT_LIFECYCLE_SETTINGS);
  const [selectedQuantStatuses, setSelectedQuantStatuses] = useState<string[]>(DEFAULT_QUANT_STATUS_FILTERS);
  const [actionPending, setActionPending] = useState<"save" | "reset" | "start" | "stop" | null>(null);
  const [signalTable, setSignalTable] = useState<TableSection>(emptyLiveSignalTable());
  const [signalLoading, setSignalLoading] = useState(false);
  const [signalStockFilter, setSignalStockFilter] = useState("");
  const [signalActionFilter, setSignalActionFilter] = useState("TRADE");
  const [signalPage, setSignalPage] = useState(1);
  const [tradeTable, setTradeTable] = useState<TableSection>({
    columns: [t("时间"), t("代码"), t("动作"), t("数量"), t("价格"), t("备注")],
    rows: [],
    emptyLabel: t("暂无交易记录"),
  });
  const [tradeLoading, setTradeLoading] = useState(false);
  const [tradeStockFilter, setTradeStockFilter] = useState("");
  const [tradeActionFilter, setTradeActionFilter] = useState("ALL");
  const [tradePage, setTradePage] = useState(1);
  const [drillDialogOpen, setDrillDialogOpen] = useState(false);
  const [drillStartDate, setDrillStartDate] = useState("2026-01-01");
  const [drillEndDate, setDrillEndDate] = useState(localDateInput());
  const [drillFrequency, setDrillFrequency] = useState("daily_first_checkpoint");
  const [drillCheckpointInterval, setDrillCheckpointInterval] = useState(8);
  const [drillConfirmLongRunning, setDrillConfirmLongRunning] = useState(false);
  const [drillPending, setDrillPending] = useState(false);

  const startDrillPayload = {
    startDate: drillStartDate,
    endDate: drillEndDate,
    market,
    timeframe: analysisTimeframe,
    initialCash,
    strategyProfileId,
    autoEntryEnabled: true,
    autoExitEnabled: true,
    executeTrades: true,
    liquidateAtEnd: true,
    seedCurrentQuantUniverse: true,
    generateHistoricalCandidateEvents: true,
    candidateGenerationFrequency: drillFrequency,
    candidateGenerationCheckpointInterval: drillCheckpointInterval,
    confirmLongRunning: drillConfirmLongRunning,
  };
  const drillStrategyProfileLabel =
    snapshot?.config.strategyProfiles?.find((item) => String(item.id) === String(strategyProfileId))?.name ?? strategyProfileId;

  async function submitLiveQuantDrill() {
    if (drillPending) return;
    setDrillPending(true);
    try {
      const result = (await activeClient.runPageAction("live-sim", "start-drill", startDrillPayload)) as LiveQuantDrillResult;
      setDrillDialogOpen(false);
      if (result?.redirect) {
        navigate(result.redirect);
      }
    } finally {
      setDrillPending(false);
    }
  }

  useEffect(() => {
    if (!snapshot) {
      return;
    }

    setIntervalMinutes(parseIntervalMinutes(snapshot.config.interval));
    setAnalysisTimeframe(normalizeAnalysisTimeframe(snapshot.config.timeframe));
    setStrategyProfileId(String(snapshot.config.strategyProfileId ?? snapshot.config.strategyProfiles?.[0]?.id ?? ""));
    setAiDynamicStrategy(normalizeAiDynamicStrategy(snapshot.config.aiDynamicStrategy ?? "off"));
    setAiDynamicStrength(parseDynamicStrength(snapshot.config.aiDynamicStrength, 0.5));
    setAiDynamicLookback(parseDynamicLookback(snapshot.config.aiDynamicLookback, 48));
    setMarket(normalizeMarket(snapshot.config.market) as (typeof MARKET_OPTIONS)[number]);
    setInitialCash(Number.parseFloat(String(snapshot.config.initialCapital)) || 100000);
    setCommissionRatePct(parseRatePercent(snapshot.config.commissionRatePct, 0.03));
    setSellTaxRatePct(parseRatePercent(snapshot.config.sellTaxRatePct, 0.1));
    setCapitalMaxSlots(parseNumberConfig(snapshot.config.capitalMaxSlots, 25));
    setCapitalFullBuyEdge(parseNumberConfig(snapshot.config.capitalFullBuyEdge, 0.25));
    setCapitalConfidenceWeight(parseNumberConfig(snapshot.config.capitalConfidenceWeight, 0.35));
    setCapitalHighPriceThreshold(parseNumberConfig(snapshot.config.capitalHighPriceThreshold, 100));
    setCapitalHighPriceMaxSlotUnits(parseNumberConfig(snapshot.config.capitalHighPriceMaxSlotUnits, 2));
  }, [snapshotVersion]);

  useEffect(() => {
    let mounted = true;
    async function loadLifecycleSettings() {
      try {
        const payload = await requestQuantUniverse<Partial<QuantLifecycleSettings>>("/api/v1/quant/universe/settings");
        if (mounted) {
          setLifecycleSettings(normalizeLifecycleSettings(payload));
        }
      } catch {
        if (mounted) {
          setLifecycleSettings(DEFAULT_LIFECYCLE_SETTINGS);
        }
      }
    }
    void loadLifecycleSettings();
    return () => {
      mounted = false;
    };
  }, [snapshotVersion]);

  useEffect(() => {
    let mounted = true;
    async function loadSignals() {
      setSignalLoading(true);
      try {
        const params = new URLSearchParams({
          page: String(signalPage),
          pageSize: String(SIGNAL_PAGE_SIZE),
          action: signalActionFilter,
          stock: signalStockFilter.trim(),
        });
        const response = await fetch(`/api/v1/quant/live-sim/signals?${params.toString()}`, {
          headers: { Accept: "application/json" },
        });
        if (!response.ok) {
          throw new Error(`Request failed: ${response.status}`);
        }
        const payload = (await response.json()) as { table?: TableSection };
        if (mounted && payload.table) {
          setSignalTable(removeStrategyColumn(payload.table));
        }
      } catch {
        if (mounted) {
          setSignalTable(emptyLiveSignalTable(t("信号加载失败，请稍后重试。")));
        }
      } finally {
        if (mounted) {
          setSignalLoading(false);
        }
      }
    }
    void loadSignals();
    return () => {
      mounted = false;
    };
  }, [snapshotVersion, signalPage, signalActionFilter, signalStockFilter]);

  useEffect(() => {
    setSignalPage(1);
  }, [signalStockFilter, signalActionFilter, snapshotVersion]);

  useEffect(() => {
    let mounted = true;
    async function loadTrades() {
      setTradeLoading(true);
      try {
        const params = new URLSearchParams({
          page: String(tradePage),
          pageSize: String(SIGNAL_PAGE_SIZE),
          action: tradeActionFilter,
          stock: tradeStockFilter.trim(),
        });
        const response = await fetch(`/api/v1/quant/live-sim/trades?${params.toString()}`, {
          headers: { Accept: "application/json" },
        });
        if (!response.ok) {
          throw new Error(`Request failed: ${response.status}`);
        }
        const payload = (await response.json()) as { table?: TableSection };
        if (mounted && payload.table) {
          setTradeTable(mergeTradeRemarksIntoDetails(removeStrategyColumn(payload.table)));
        }
      } catch {
        if (mounted) {
          setTradeTable(emptyLiveTradeTable(t("成交记录加载失败，请稍后重试。")));
        }
      } finally {
        if (mounted) {
          setTradeLoading(false);
        }
      }
    }
    void loadTrades();
    return () => {
      mounted = false;
    };
  }, [snapshotVersion, tradePage, tradeActionFilter, tradeStockFilter]);

  useEffect(() => {
    setTradePage(1);
  }, [tradeStockFilter, tradeActionFilter, snapshotVersion]);

  if (resource.status === "loading" && !resource.data) {
    return <PageLoadingState title={t("实时量化加载中")} description={t("正在读取定时任务配置、量化股票和账户结果。")} />;
  }

  if (resource.status === "error" && !resource.data) {
    return (
      <PageErrorState
        title={t("实时量化加载失败")}
        description={resource.error ?? t("无法加载实时量化数据，请稍后重试。")}
        actionLabel={t("重新加载")}
        onAction={resource.refresh}
      />
    );
  }

  if (!snapshot) {
    return <PageEmptyState title={t("实时量化暂无数据")} description={t("后台尚未返回实时量化快照。")} actionLabel={t("刷新")} onAction={resource.refresh} />;
  }

  const candidateCount = toDisplayCount(snapshot.status.candidateCount, snapshot.candidatePool.rows.length);
  const runningState = toDisplayText(snapshot.status.running, t("未知"));
  const runningNormalized = String(snapshot.status.running ?? "").trim().toLowerCase();
  const isRunning = runningNormalized.includes(t("运行中")) || runningNormalized.includes("running");
  const candidatePoolBaseTable = withoutTableColumns(snapshot.candidatePool, (column) => {
    const normalized = column.trim().toLowerCase();
    return normalized === t("来源") || normalized === "source";
  });
  const availableQuantStatuses = (snapshot.quant_status_filters?.available ?? QUANT_STATUS_OPTIONS).filter((status) => QUANT_STATUS_OPTIONS.includes(status));
  const candidatePoolTable: TableSection = {
    ...candidatePoolBaseTable,
    columns: [...candidatePoolBaseTable.columns, t("状态"), t("健康度"), t("生命周期原因")],
    rows: snapshot.candidatePool.rows
      .filter((row) => selectedQuantStatuses.includes(lifecycleStatusOf(row)))
      .map((row) => {
        const lifecycle = lifecycleOf(row);
        const baseCells = candidatePoolBaseTable.rows.find((candidateRow) => candidateRow.id === row.id)?.cells ?? row.cells;
        return {
          ...row,
          cells: [
            ...baseCells,
            lifecycleStatusOf(row),
            t("健康 {v0}", { v0: Math.round(Number(lifecycle.health_score ?? 100)) }),
            String(lifecycle.latest_reason || "--"),
          ],
          actions: (row.actions ?? []).filter((action) => action.action === "delete-candidate"),
        };
      }),
  };
  const signalActionColumnIndex = findColumnIndex(signalTable, [t("动作"), "action"], 4);
  const signalActionOptions = Array.from(new Set(signalTable.rows.map((row) => normalizeSignalAction(String(row.cells[signalActionColumnIndex] ?? ""))).filter(Boolean)));
  const tradeActionOptions = Array.from(new Set(tradeTable.rows.map((row) => normalizeSignalAction(String(row.cells[2] ?? ""))).filter(Boolean)));
  const signalPages = Math.max(1, Number(signalTable.pagination?.totalPages ?? 1));
  const currentSignalPage = Math.min(Number(signalTable.pagination?.page ?? signalPage), signalPages);
  const signalTotalRows = Number(signalTable.pagination?.totalRows ?? signalTable.rows.length);
  const pagedSignalTable: TableSection = {
    ...signalTable,
    rows: signalTable.rows,
  };
  const tradePages = Math.max(1, Number(tradeTable.pagination?.totalPages ?? 1));
  const currentTradePage = Math.min(Number(tradeTable.pagination?.page ?? tradePage), tradePages);
  const tradeTotalRows = Number(tradeTable.pagination?.totalRows ?? tradeTable.rows.length);
  const tradeCostSummary = snapshot.tradeCostSummary ?? [];
  const executionHeroMetrics = pickMetrics(tradeCostSummary, EXECUTION_HERO_METRIC_LABELS);
  const primaryExecutionMetric = executionHeroMetrics.find((metric) => metric.label === t("实现盈亏"));
  const executionTradeCountMetric = tradeCostSummary.find((metric) => metric.label === t("交易笔数"));
  const executionWinRateMetric = tradeCostSummary.find((metric) => metric.label === t("胜率"));
  const secondaryExecutionHeroMetrics = executionHeroMetrics.filter((metric) => metric.label !== t("实现盈亏"));
  const executionHeroMetricLabels = new Set(executionHeroMetrics.map((metric) => metric.label));
  const executionGroupMetricLabels = new Set(EXECUTION_STAT_GROUPS.flatMap((group) => group.labels));
  const executionStatGroups = EXECUTION_STAT_GROUPS.map((group) => ({
    ...group,
    metrics: pickMetrics(tradeCostSummary, group.labels).filter((metric) => !executionHeroMetricLabels.has(metric.label)),
  })).filter((group) => group.metrics.length > 0);
  const executionOtherMetrics = tradeCostSummary.filter(
    (metric) => !executionHeroMetricLabels.has(metric.label) && !executionGroupMetricLabels.has(metric.label),
  );
  const toolbarControlHeight = "40px";
  const renderSignalPager = () => (
    <div style={{ display: "inline-flex", alignItems: "center", gap: "8px", flexWrap: "nowrap", whiteSpace: "nowrap" }}>
      <button
        className="button button--secondary button--small"
        type="button"
        style={{ height: toolbarControlHeight, minHeight: toolbarControlHeight, padding: "0 18px" }}
        disabled={currentSignalPage <= 1}
        onClick={() => setSignalPage((page) => Math.max(1, page - 1))}
      >
        {t("上一页")}</button>
      <span
        className="badge badge--neutral"
        style={{
          height: toolbarControlHeight,
          minHeight: toolbarControlHeight,
          display: "inline-flex",
          alignItems: "center",
          justifyContent: "center",
          padding: "0 16px",
        }}
      >
        {t("第 {v0} / {v1} 页", { v0: currentSignalPage, v1: signalPages })}
      </span>
      <button
        className="button button--secondary button--small"
        type="button"
        style={{ height: toolbarControlHeight, minHeight: toolbarControlHeight, padding: "0 18px" }}
        disabled={currentSignalPage >= signalPages}
        onClick={() => setSignalPage((page) => Math.min(signalPages, page + 1))}
      >
        {t("下一页")}</button>
    </div>
  );
  const renderSignalToolbar = () => (
    <div className="table-toolbar-compact" style={{ flexWrap: "nowrap", overflowX: "auto" }}>
      <input
        className="input"
        style={{ height: toolbarControlHeight, minHeight: toolbarControlHeight, padding: "0 10px" }}
        data-size="compact-input"
        placeholder={t("按代码/名称过滤")}
        value={signalStockFilter}
        onChange={(event) => setSignalStockFilter(event.target.value)}
      />
      <select
        className="input"
        style={{ height: toolbarControlHeight, minHeight: toolbarControlHeight, padding: "0 10px" }}
        data-size="compact-select"
        value={signalActionFilter}
        onChange={(event) => setSignalActionFilter(event.target.value)}
      >
        <option value="TRADE">BUY/SELL</option>
        <option value="ALL">{t("全部动作")}</option>
        {signalActionOptions.map((option) => (
          <option key={option} value={option}>
            {option}
          </option>
        ))}
      </select>
      {renderSignalPager()}
      <span className="summary-item__body table-toolbar-compact__count" style={{ margin: 0 }}>
        {signalLoading ? t("加载中...") : t("DB筛选 {v0} 条", { v0: signalTotalRows })}
      </span>
    </div>
  );
  const renderTradeToolbar = () => (
    <div className="table-toolbar-compact" style={{ flexWrap: "nowrap", overflowX: "auto" }}>
      <input
        className="input"
        style={{ height: toolbarControlHeight, minHeight: toolbarControlHeight, padding: "0 10px" }}
        data-size="compact-input"
        placeholder={t("按代码/名称过滤")}
        value={tradeStockFilter}
        onChange={(event) => setTradeStockFilter(event.target.value)}
      />
      <select
        className="input"
        style={{ height: toolbarControlHeight, minHeight: toolbarControlHeight, padding: "0 10px" }}
        data-size="compact-select"
        value={tradeActionFilter}
        onChange={(event) => setTradeActionFilter(event.target.value)}
      >
        <option value="ALL">{t("全部动作")}</option>
        {tradeActionOptions.map((option) => (
          <option key={option} value={option}>
            {option}
          </option>
        ))}
      </select>
      <div style={{ display: "inline-flex", alignItems: "center", gap: "8px", flexWrap: "nowrap", whiteSpace: "nowrap" }}>
        <button
          className="button button--secondary button--small"
          type="button"
          style={{ height: toolbarControlHeight, minHeight: toolbarControlHeight, padding: "0 18px" }}
          disabled={currentTradePage <= 1}
          onClick={() => setTradePage((page) => Math.max(1, page - 1))}
        >
          ←
        </button>
        <span className="badge badge--neutral" style={{ height: toolbarControlHeight, minHeight: toolbarControlHeight, display: "inline-flex", alignItems: "center", justifyContent: "center", padding: "0 16px" }}>
          {t("第 {v0} / {v1} 页", { v0: currentTradePage, v1: tradePages })}
        </span>
        <button
          className="button button--secondary button--small"
          type="button"
          style={{ height: toolbarControlHeight, minHeight: toolbarControlHeight, padding: "0 18px" }}
          disabled={currentTradePage >= tradePages}
          onClick={() => setTradePage((page) => Math.min(tradePages, page + 1))}
        >
          →
        </button>
      </div>
      <span className="summary-item__body table-toolbar-compact__count" style={{ margin: 0 }}>
        {tradeLoading ? t("加载中...") : t("DB筛选 {v0} 条", { v0: tradeTotalRows })}
      </span>
    </div>
  );
  const simConfigPayload = {
    intervalMinutes,
    analysisTimeframe,
    strategyMode: "auto",
    strategyProfileId,
    aiDynamicStrategy,
    aiDynamicStrength,
    aiDynamicLookback,
    market,
    initialCash,
    autoExecute: true,
    commissionRatePct,
    sellTaxRatePct,
    capitalSlotEnabled: true,
    capitalPoolMinCash: 20000,
    capitalPoolMaxCash: 1_000_000_000_000,
    capitalSlotMinCash: 20000,
    capitalMaxSlots,
    capitalMinBuySlotFraction: 0.25,
    capitalFullBuyEdge,
    capitalConfidenceWeight,
    capitalHighPriceThreshold,
    capitalHighPriceMaxSlotUnits,
    capitalSellCashReusePolicy: "next_batch",
  };
  const toggleQuantStatus = (status: string) => {
    setSelectedQuantStatuses((current) => {
      if (current.includes(status)) {
        const next = current.filter((item) => item !== status);
        return next.length ? next : current;
      }
      return [...current, status];
    });
  };
  const systemTimezone = snapshot.timeContext?.systemTimezone ?? "system";
  const snapshotTimeLabel = snapshot.timeContext?.updatedAtSystem ?? snapshot.updatedAt;
  const lastRunLabel = snapshot.status.lastRunSystem ?? snapshot.status.lastRun;
  const nextRunLabel = snapshot.status.nextRunSystem ?? snapshot.status.nextRun;

  return (
    <div>
      <PageHeader
        eyebrow={t("实时量化")}
        title={t("运行状态：{state}", { state: runningState })}
        description={t("最近执行：{lastRun}；下次执行：{nextRun}。", { lastRun: lastRunLabel, nextRun: nextRunLabel })}
        actions={
          <div className="chip-row">
            <span className="badge badge--neutral">{t("快照")}{snapshotTimeLabel}</span>
            <span className="badge badge--neutral">{t("系统时区")}{systemTimezone}</span>
            <span className="badge badge--accent">{t("候选")}{candidateCount}</span>
            <span className={isRunning ? "badge badge--success" : "badge badge--neutral"}>{runningState}</span>
          </div>
        }
      />
      <div className="section-grid section-grid--sidebar">
        <div className="stack">
          <WorkbenchCard>
            <h2 className="section-card__title">{t("定时任务配置")}</h2>
            <p className="section-card__description">
              {t("资金池、粒度和自动执行统一放在这里配置。启动后会从当前时点开始执行实时量化。")}
            </p>
            <div className="mini-metric-grid">
              <div className="mini-metric">
                <div className="mini-metric__label">{t("间隔")}</div>
                <div className="mini-metric__value">{snapshot.config.interval}</div>
              </div>
              <div className="mini-metric">
                <div className="mini-metric__label">{t("分析粒度")}</div>
                <div className="mini-metric__value">{snapshot.config.timeframe}</div>
              </div>
              <div className="mini-metric">
                <div className="mini-metric__label">{t("手续费")}</div>
                <div className="mini-metric__value">{`${parseRatePercent(snapshot.config.commissionRatePct, commissionRatePct).toFixed(4)}%`}</div>
              </div>
              <div className="mini-metric">
                <div className="mini-metric__label">{t("卖出税费")}</div>
                <div className="mini-metric__value">{`${parseRatePercent(snapshot.config.sellTaxRatePct, sellTaxRatePct).toFixed(4)}%`}</div>
              </div>
              <div className="mini-metric">
                <div className="mini-metric__label">{t("最大Slot")}</div>
                <div className="mini-metric__value">{capitalMaxSlots}</div>
              </div>
            </div>
            <div className="card-divider" />
            <LifecycleSummaryBadgeGroup settings={lifecycleSettings} />
            <p className="section-card__description">
              {t("基于评分的股票量化自动化为系统级设置：开启后会自动纳入量化并执行生命周期出池；这里仅展示实时量化读取到的当前口径。")}</p>
            <div className="card-divider" />
            <div className="summary-list">
              <label className="field">
                <span className="field__label">{t("间隔(分钟)")}</span>
                <input
                  className="input"
                  min={5}
                  max={240}
                  step={5}
                  type="number"
                  value={intervalMinutes}
                  onChange={(event) => setIntervalMinutes(Number(event.target.value) || 15)}
                />
              </label>
              <label className="field">
                <span className="field__label">{t("分析粒度")}</span>
                <select className="input" value={analysisTimeframe} onChange={(event) => setAnalysisTimeframe(event.target.value)}>
                  {ANALYSIS_TIMEFRAME_OPTIONS.map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}
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
                <span className="field__label">{t("市场")}</span>
                <select
                  className="input"
                  value={market}
                  onChange={(event) => setMarket(event.target.value as (typeof MARKET_OPTIONS)[number])}
                >
                  {MARKET_OPTIONS.map((option) => (
                    <option key={option} value={option}>
                      {option}
                    </option>
                  ))}
                </select>
              </label>
              <label className="field">
                <span className="field__label">{t("初始资金池(元)")}</span>
                <input
                  className="input"
                  min={10000}
                  step={1000}
                  type="number"
                  value={initialCash}
                  onChange={(event) => setInitialCash(Number(event.target.value) || 100000)}
                />
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
              <label className="field">
                <span className="field__label">{t("最大Slot数")}</span>
                <input className="input" min={1} step={1} type="number" value={capitalMaxSlots} onChange={(event) => setCapitalMaxSlots(Number(event.target.value) || 25)} />
              </label>
              <label className="field">
                <span className="field__label">{t("满Slot分数边际")}</span>
                <input className="input" min={0.01} max={1} step={0.01} type="number" value={capitalFullBuyEdge} onChange={(event) => setCapitalFullBuyEdge(Number(event.target.value) || 0.25)} />
              </label>
              <label className="field">
                <span className="field__label">{t("置信度权重")}</span>
                <input className="input" min={0} max={1} step={0.05} type="number" value={capitalConfidenceWeight} onChange={(event) => setCapitalConfidenceWeight(Number(event.target.value) || 0.35)} />
              </label>
              <label className="field">
                <span className="field__label">{t("高价股阈值(元)")}</span>
                <input className="input" min={0} step={1} type="number" value={capitalHighPriceThreshold} onChange={(event) => setCapitalHighPriceThreshold(Number(event.target.value) || 100)} />
              </label>
              <label className="field">
                <span className="field__label">{t("高价股最大Slot")}</span>
                <input className="input" min={1} max={5} step={0.5} type="number" value={capitalHighPriceMaxSlotUnits} onChange={(event) => setCapitalHighPriceMaxSlotUnits(Number(event.target.value) || 2)} />
              </label>
            </div>
            <div className="card-divider" />
            <div className="toolbar toolbar--compact">
              <button
                className="button button--secondary"
                type="button"
                disabled={actionPending !== null}
                onClick={async () => {
                  setActionPending("save");
                  try {
                    await resource.runAction("save", simConfigPayload);
                  } finally {
                    setActionPending(null);
                  }
                }}
              >
                {actionPending === "save" ? t("保存中...") : t("保存")}
              </button>
              <button
                className="button button--secondary"
                type="button"
                disabled={actionPending !== null}
                onClick={async () => {
                  setActionPending("reset");
                  try {
                    await resource.runAction("reset", { initialCash });
                    setSignalTable(emptyLiveSignalTable());
                    setTradeTable(emptyLiveTradeTable());
                    setSignalPage(1);
                    setTradePage(1);
                  } finally {
                    setActionPending(null);
                  }
                }}
              >
                {actionPending === "reset" ? t("重置中...") : t("重置")}
              </button>
              <button
                className="button button--secondary"
                type="button"
                disabled={drillPending}
                onClick={() => {
                  setDrillEndDate(localDateInput());
                  setDrillDialogOpen(true);
                }}
              >
                {t("历史演练")}
              </button>
              <span className="toolbar__spacer" />
              <button
                className="button button--secondary"
                type="button"
                disabled={actionPending !== null || !isRunning}
                onClick={async () => {
                  setActionPending("stop");
                  try {
                    await resource.runAction("stop");
                  } finally {
                    setActionPending(null);
                  }
                }}
              >
                {actionPending === "stop" ? t("停止中...") : t("停止量化")}
              </button>
              <button
                className="button button--primary button--hero"
                type="button"
                disabled={actionPending !== null || isRunning}
                onClick={async () => {
                  setActionPending("start");
                  try {
                    await resource.runAction("start", simConfigPayload);
                  } finally {
                    setActionPending(null);
                  }
                }}
              >
                {actionPending === "start" ? t("启动中...") : isRunning ? t("运行中") : t("启动量化")}
              </button>
            </div>
          </WorkbenchCard>

          {drillDialogOpen ? (
            <div
              className="modal-backdrop"
              style={{
                position: "fixed",
                inset: 0,
                zIndex: 40,
                display: "grid",
                placeItems: "center",
                background: "rgba(15, 23, 42, 0.28)",
                padding: "24px",
              }}
            >
              <section className="card section-card" role="dialog" aria-modal="true" aria-label={t("实时量化历史演练")}>
                <h2 className="section-card__title">{t("实时量化历史演练")}</h2>
                <p className="section-card__description">
                  {t("用历史 checkpoint 模拟实时量化从指定日期开始上线运行的完整过程，包括入池、出池、交易和生命周期。")}
                </p>
                <div className="section-grid">
                  <label className="field">
                    <span className="field__label">{t("开始日期")}</span>
                    <input className="input" type="date" value={drillStartDate} onChange={(event) => setDrillStartDate(event.target.value)} />
                  </label>
                  <label className="field">
                    <span className="field__label">{t("结束日期")}</span>
                    <input className="input" type="date" value={drillEndDate} onChange={(event) => setDrillEndDate(event.target.value)} />
                  </label>
                </div>
                <div className="section-grid">
                  <label className="field">
                    <span className="field__label">{t("候选生成频率")}</span>
                    <select className="input" value={drillFrequency} onChange={(event) => setDrillFrequency(event.target.value)}>
                      <option value="daily_first_checkpoint">{t("每日第一个检查点")}</option>
                      <option value="every_n_checkpoints">{t("每 N 个检查点")}</option>
                    </select>
                  </label>
                  <label className="field">
                    <span className="field__label">{t("检查点间隔")}</span>
                    <input
                      className="input"
                      min={1}
                      step={1}
                      type="number"
                      value={drillCheckpointInterval}
                      onChange={(event) => setDrillCheckpointInterval(Math.max(1, Number(event.target.value) || 8))}
                    />
                  </label>
                </div>
                <div className="chip-row">
                  <span className="badge badge--accent">{t("自动入池")}</span>
                  <span className="badge badge--accent">{t("自动出池")}</span>
                  <span className="badge badge--accent">{t("模拟交易")}</span>
                  <span className="badge badge--accent">{t("期末清算")}</span>
                  <span className="badge badge--accent">{t("使用当前实时量化股票")}</span>
                  <span className="badge badge--neutral">{t("市场 {v0}", { v0: market })}</span>
                  <span className="badge badge--neutral">{t("周期 {v0}", { v0: analysisTimeframe })}</span>
                  <span className="badge badge--neutral">{t("策略 {v0}", { v0: drillStrategyProfileLabel })}</span>
                  <span className="badge badge--neutral">
                    {t("资金 {v0}", { v0: Number(initialCash || 0).toLocaleString() })}
                  </span>
                </div>
                <label className="field" style={{ flexDirection: "row", alignItems: "center", gap: 8 }}>
                  <input
                    type="checkbox"
                    checked={drillConfirmLongRunning}
                    onChange={(event) => setDrillConfirmLongRunning(event.target.checked)}
                  />
                  <span className="field__label" style={{ margin: 0 }}>{t("确认长任务")}</span>
                </label>
                <div className="toolbar toolbar--compact">
                  <button className="button button--secondary" type="button" disabled={drillPending} onClick={() => setDrillDialogOpen(false)}>
                    {t("取消")}
                  </button>
                  <button className="button button--primary" type="button" disabled={drillPending} onClick={submitLiveQuantDrill}>
                    {drillPending ? t("启动中...") : t("开始演练")}
                  </button>
                </div>
              </section>
            </div>
          ) : null}

          <LiveQuantStockList
            title={t("实时量化股票")}
            description={t("来自统一股票池中已启用实时量化的股票，实时量化会按这批标的扫描。")}
            table={candidatePoolTable}
            emptyTitle={candidatePoolTable.emptyLabel ?? t("暂无实时量化股票")}
            emptyDescription={candidatePoolTable.emptyMessage ?? t("先在股票池中批量启用实时量化，再启动实时量化。")}
            meta={[t("表内 {v0} 只", { v0: candidatePoolTable.rows.length }), t("待量化 {v0}", { v0: candidateCount })]}
            toolbar={<StatusFilterChips available={availableQuantStatuses} selected={selectedQuantStatuses} onToggle={toggleQuantStatus} />}
          />
        </div>

        <div className="stack">
          <div className="metric-grid live-sim-metric-grid">
            {snapshot.metrics.map((metric) => (
              <WorkbenchCard className="metric-card" key={metric.label}>
                <div className="metric-card__label">{metric.label}</div>
                <div className="metric-card__value">{metric.value}</div>
              </WorkbenchCard>
            ))}
          </div>

          <QuantTableSectionCard
            title={t("信号记录")}
            description={t("点击信号ID进入统一信号详情页，股票代码和名称进入股票详情。")}
            table={pagedSignalTable}
            emptyTitle={signalTable.emptyLabel ?? t("暂无信号")}
            emptyDescription={signalTable.emptyMessage ?? t("当前没有可查看的信号记录。")}
            tableLayout="auto"
            compactConfig={{ coreColumnIndexes: [0, 2, 3, 4], detailColumnIndexes: [1, 5, 6, 7, 8, 9, 10, 11, 12] }}
            signalDetailSource="live"
            toolbar={renderSignalToolbar()}
          />

          {snapshot.capitalPool ? <ReplayCapitalPoolPanel capitalPool={snapshot.capitalPool} showPositionSummary /> : null}

          <QuantTableSectionCard
            title={t("成交记录")}
            table={tradeTable}
            emptyTitle={tradeTable.emptyLabel ?? t("成交记录暂无数据")}
            emptyDescription={tradeTable.emptyMessage ?? t("如果调度还没有生成新的成交，这里会先保持为空。")}
            compactConfig={{ coreColumnIndexes: [0, 1, 2, 10], detailColumnIndexes: [3, 4, 5, 6, 7, 8, 9, 11, 12, 13, 14] }}
            shellClassName="table-shell--trade-details"
            toolbar={renderTradeToolbar()}
          />

          {tradeCostSummary.length ? (
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
                          {t("实现盈亏口径")} · {t("已扣手续费与印花税")}{executionTradeCountMetric ? ` · ${executionTradeCountMetric.label} ${executionTradeCountMetric.value}` : ""}
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

        </div>
      </div>
    </div>
  );
}

