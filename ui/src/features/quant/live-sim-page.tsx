import { useEffect, useState } from "react";
import type { ApiClient } from "../../lib/api-client";
import { PageHeader } from "../../components/ui/page-header";
import { WorkbenchCard } from "../../components/ui/workbench-card";
import { PageEmptyState, PageErrorState, PageLoadingState } from "../../components/ui/page-state";
import { usePageData } from "../../lib/use-page-data";
import type { SummaryMetric, TableSection } from "../../lib/page-models";
import { toDisplayCount, toDisplayText } from "./quant-display";
import { QuantTableSectionCard } from "./quant-table-section";
import { ReplayCapitalPoolPanel } from "./replay-capital-pool-panel";

const ANALYSIS_TIMEFRAME_OPTIONS = [
  { value: "30m", label: "30分钟" },
  { value: "1d", label: "日线" },
  { value: "1d+30m", label: "日线方向 + 30分钟确认" },
];

const AI_DYNAMIC_STRATEGY_OPTIONS = [
  { value: "off", label: "关闭" },
  { value: "hybrid", label: "开启" },
];

const MARKET_OPTIONS = ["CN", "HK", "US"] as const;
const SIGNAL_PAGE_SIZE = 20;
const EXECUTION_HERO_METRIC_LABELS = ["交易笔数", "买入总成本", "卖出到账", "总费用", "实现盈亏"];
const EXECUTION_STAT_GROUPS = [
  { title: "交易结构", labels: ["买入笔数", "卖出笔数", "加仓次数"] },
  { title: "资金流", labels: ["买入毛额", "卖出毛额", "买入总成本", "卖出到账"] },
  { title: "成本费用", labels: ["手续费", "印花税", "总费用"] },
  { title: "Lot / Slot", labels: ["买入lot", "卖出lot", "剩余lot", "占用slot", "释放slot", "最大占用slot", "平均占用slot"] },
];

function parseIntervalMinutes(value: string) {
  const match = String(value).match(/(\d+)/);
  return match ? Number(match[1]) : 15;
}

function normalizeAnalysisTimeframe(value: string) {
  const normalized = String(value).trim().toLowerCase();
  if (normalized === "日线") return "1d";
  if (normalized.includes("30分钟")) return "1d+30m";
  return ANALYSIS_TIMEFRAME_OPTIONS.find((option) => option.value === normalized)?.value ?? "30m";
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
    .filter(({ normalized }) => normalized.includes("策略") || normalized === "strategy")
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
    return normalized === "备注" || normalized === "note";
  });
  if (remarkIndex < 0) {
    return table;
  }
  const detailIndex = table.columns.findIndex((column) => String(column ?? "").includes("执行明细"));
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

type LiveSimPageProps = {
  client?: ApiClient;
};

export function LiveSimPage({ client }: LiveSimPageProps) {
  const resource = usePageData("live-sim", client);
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
  const [actionPending, setActionPending] = useState<"save" | "reset" | "start" | "stop" | null>(null);
  const [signalTable, setSignalTable] = useState<TableSection>({
    columns: ["信号ID", "时间", "股票代码", "股票名称", "动作", "执行状态"],
    rows: [],
    emptyLabel: "暂无信号",
  });
  const [signalLoading, setSignalLoading] = useState(false);
  const [signalStockFilter, setSignalStockFilter] = useState("");
  const [signalActionFilter, setSignalActionFilter] = useState("TRADE");
  const [signalPage, setSignalPage] = useState(1);
  const [tradeTable, setTradeTable] = useState<TableSection>({
    columns: ["时间", "代码", "动作", "数量", "价格", "备注"],
    rows: [],
    emptyLabel: "暂无交易记录",
  });
  const [tradeLoading, setTradeLoading] = useState(false);
  const [tradeStockFilter, setTradeStockFilter] = useState("");
  const [tradeActionFilter, setTradeActionFilter] = useState("ALL");
  const [tradePage, setTradePage] = useState(1);

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
          setSignalTable({
            columns: ["信号ID", "时间", "代码", "动作", "状态"],
            rows: [],
            emptyLabel: "暂无信号",
            emptyMessage: "信号加载失败，请稍后重试。",
          });
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
          setTradeTable({
            columns: ["时间", "代码", "动作", "数量", "价格", "备注"],
            rows: [],
            emptyLabel: "暂无交易记录",
            emptyMessage: "成交记录加载失败，请稍后重试。",
          });
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
    return <PageLoadingState title="实时模拟加载中" description="正在读取定时任务配置、候选池和账户结果。" />;
  }

  if (resource.status === "error" && !resource.data) {
    return (
      <PageErrorState
        title="实时模拟加载失败"
        description={resource.error ?? "无法加载实时模拟数据，请稍后重试。"}
        actionLabel="重新加载"
        onAction={resource.refresh}
      />
    );
  }

  if (!snapshot) {
    return <PageEmptyState title="实时模拟暂无数据" description="后台尚未返回实时模拟快照。" actionLabel="刷新" onAction={resource.refresh} />;
  }

  const candidateCount = toDisplayCount(snapshot.status.candidateCount, snapshot.candidatePool.rows.length);
  const runningState = toDisplayText(snapshot.status.running, "未知");
  const runningNormalized = String(snapshot.status.running ?? "").trim().toLowerCase();
  const isRunning = runningNormalized.includes("运行中") || runningNormalized.includes("running");
  const candidatePoolBaseTable = withoutTableColumns(snapshot.candidatePool, (column) => {
    const normalized = column.trim().toLowerCase();
    return normalized === "来源" || normalized === "source";
  });
  const candidatePoolTable: TableSection = {
    ...candidatePoolBaseTable,
    rows: snapshot.candidatePool.rows.map((row) => ({
      ...row,
      cells: candidatePoolBaseTable.rows.find((candidateRow) => candidateRow.id === row.id)?.cells ?? row.cells,
      actions: (row.actions ?? []).filter((action) => action.action === "delete-candidate"),
    })),
  };
  const signalActionColumnIndex = findColumnIndex(signalTable, ["动作", "action"], 4);
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
  const primaryExecutionMetric = executionHeroMetrics.find((metric) => metric.label === "交易笔数");
  const secondaryExecutionHeroMetrics = executionHeroMetrics.filter((metric) => metric.label !== "交易笔数");
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
        上一页
      </button>
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
        {`第 ${currentSignalPage} / ${signalPages} 页`}
      </span>
      <button
        className="button button--secondary button--small"
        type="button"
        style={{ height: toolbarControlHeight, minHeight: toolbarControlHeight, padding: "0 18px" }}
        disabled={currentSignalPage >= signalPages}
        onClick={() => setSignalPage((page) => Math.min(signalPages, page + 1))}
      >
        下一页
      </button>
    </div>
  );
  const renderSignalToolbar = () => (
    <div className="table-toolbar-compact" style={{ flexWrap: "nowrap", overflowX: "auto" }}>
      <input
        className="input"
        style={{ height: toolbarControlHeight, minHeight: toolbarControlHeight, padding: "0 10px" }}
        data-size="compact-input"
        placeholder="按代码/名称过滤"
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
        <option value="ALL">全部动作</option>
        {signalActionOptions.map((option) => (
          <option key={option} value={option}>
            {option}
          </option>
        ))}
      </select>
      {renderSignalPager()}
      <span className="summary-item__body table-toolbar-compact__count" style={{ margin: 0 }}>
        {signalLoading ? "加载中..." : `DB筛选 ${signalTotalRows} 条`}
      </span>
    </div>
  );
  const renderTradeToolbar = () => (
    <div className="table-toolbar-compact" style={{ flexWrap: "nowrap", overflowX: "auto" }}>
      <input
        className="input"
        style={{ height: toolbarControlHeight, minHeight: toolbarControlHeight, padding: "0 10px" }}
        data-size="compact-input"
        placeholder="按代码/名称过滤"
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
        <option value="ALL">全部动作</option>
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
          {`第 ${currentTradePage} / ${tradePages} 页`}
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
        {tradeLoading ? "加载中..." : `DB筛选 ${tradeTotalRows} 条`}
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

  return (
    <div>
      <PageHeader
        eyebrow="实时模拟"
        title={`运行状态：${runningState}`}
        description={`最近执行：${snapshot.status.lastRun}；下次执行：${snapshot.status.nextRun}。`}
        actions={
          <div className="chip-row">
            <span className="badge badge--neutral">快照 {snapshot.updatedAt}</span>
            <span className="badge badge--accent">候选 {candidateCount}</span>
            <span className={isRunning ? "badge badge--success" : "badge badge--neutral"}>{runningState}</span>
          </div>
        }
      />
      <div className="section-grid section-grid--sidebar">
        <div className="stack">
          <WorkbenchCard>
            <h2 className="section-card__title">定时任务配置</h2>
            <p className="section-card__description">
              {`资金池、粒度和自动执行统一放在这里配置。启动后会从当前时点开始做真实模拟。`}
            </p>
            <div className="mini-metric-grid">
              <div className="mini-metric">
                <div className="mini-metric__label">间隔</div>
                <div className="mini-metric__value">{snapshot.config.interval}</div>
              </div>
              <div className="mini-metric">
                <div className="mini-metric__label">分析粒度</div>
                <div className="mini-metric__value">{snapshot.config.timeframe}</div>
              </div>
              <div className="mini-metric">
                <div className="mini-metric__label">手续费</div>
                <div className="mini-metric__value">{`${parseRatePercent(snapshot.config.commissionRatePct, commissionRatePct).toFixed(4)}%`}</div>
              </div>
              <div className="mini-metric">
                <div className="mini-metric__label">卖出税费</div>
                <div className="mini-metric__value">{`${parseRatePercent(snapshot.config.sellTaxRatePct, sellTaxRatePct).toFixed(4)}%`}</div>
              </div>
              <div className="mini-metric">
                <div className="mini-metric__label">最大Slot</div>
                <div className="mini-metric__value">{capitalMaxSlots}</div>
              </div>
            </div>
            <div className="card-divider" />
            <div className="summary-list">
              <label className="field">
                <span className="field__label">间隔(分钟)</span>
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
                <span className="field__label">分析粒度</span>
                <select className="input" value={analysisTimeframe} onChange={(event) => setAnalysisTimeframe(event.target.value)}>
                  {ANALYSIS_TIMEFRAME_OPTIONS.map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}
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
                <span className="field__label">市场</span>
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
                <span className="field__label">初始资金池(元)</span>
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
              <label className="field">
                <span className="field__label">最大Slot数</span>
                <input className="input" min={1} step={1} type="number" value={capitalMaxSlots} onChange={(event) => setCapitalMaxSlots(Number(event.target.value) || 25)} />
              </label>
              <label className="field">
                <span className="field__label">满Slot分数边际</span>
                <input className="input" min={0.01} max={1} step={0.01} type="number" value={capitalFullBuyEdge} onChange={(event) => setCapitalFullBuyEdge(Number(event.target.value) || 0.25)} />
              </label>
              <label className="field">
                <span className="field__label">置信度权重</span>
                <input className="input" min={0} max={1} step={0.05} type="number" value={capitalConfidenceWeight} onChange={(event) => setCapitalConfidenceWeight(Number(event.target.value) || 0.35)} />
              </label>
              <label className="field">
                <span className="field__label">高价股阈值(元)</span>
                <input className="input" min={0} step={1} type="number" value={capitalHighPriceThreshold} onChange={(event) => setCapitalHighPriceThreshold(Number(event.target.value) || 100)} />
              </label>
              <label className="field">
                <span className="field__label">高价股最大Slot</span>
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
                {actionPending === "save" ? "保存中..." : "保存"}
              </button>
              <button
                className="button button--secondary"
                type="button"
                disabled={actionPending !== null}
                onClick={async () => {
                  setActionPending("reset");
                  try {
                    await resource.runAction("reset", { initialCash });
                  } finally {
                    setActionPending(null);
                  }
                }}
              >
                {actionPending === "reset" ? "重置中..." : "重置"}
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
                {actionPending === "stop" ? "停止中..." : "停止模拟"}
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
                {actionPending === "start" ? "启动中..." : isRunning ? "运行中" : "启动模拟"}
              </button>
            </div>
          </WorkbenchCard>

          <QuantTableSectionCard
            title="量化候选池"
            description="实时模拟和历史回放共用同一批量化候选池，因此这里看到的股票就是后续扫描对象。"
            table={candidatePoolTable}
            emptyTitle={candidatePoolTable.emptyLabel ?? "候选池暂无数据"}
            emptyDescription={candidatePoolTable.emptyMessage ?? "先从我的关注或发现 / 研究页补入候选，再启动实时模拟。"}
            meta={[`表内 ${candidatePoolTable.rows.length} 只`, `待量化 ${candidateCount}`]}
            actionsHead="操作"
            actionsColumnSize="icon"
            compactConfig={{ coreColumnIndexes: [0, 1, 2], detailColumnIndexes: [] }}
            onRowAction={(row, action) => {
              if (action.action !== "delete-candidate") {
                return;
              }
              void resource.runAction("delete-candidate", row.id);
            }}
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
            title="信号记录"
            description="点击信号ID进入统一信号详情页，股票代码和名称进入股票详情。"
            table={pagedSignalTable}
            emptyTitle={signalTable.emptyLabel ?? "暂无信号"}
            emptyDescription={signalTable.emptyMessage ?? "当前没有可查看的信号记录。"}
            tableLayout="auto"
            compactConfig={{ coreColumnIndexes: [0, 2, 3, 4], detailColumnIndexes: [1, 5, 6, 7, 8, 9, 10, 11, 12] }}
            signalDetailSource="live"
            toolbar={renderSignalToolbar()}
          />

          {snapshot.capitalPool ? <ReplayCapitalPoolPanel capitalPool={snapshot.capitalPool} showPositionSummary /> : null}

          <QuantTableSectionCard
            title="成交记录"
            table={tradeTable}
            emptyTitle={tradeTable.emptyLabel ?? "成交记录暂无数据"}
            emptyDescription={tradeTable.emptyMessage ?? "如果调度还没有生成新的成交，这里会先保持为空。"}
            compactConfig={{ coreColumnIndexes: [0, 1, 2, 10], detailColumnIndexes: [3, 4, 5, 6, 7, 8, 9, 11, 12, 13, 14] }}
            shellClassName="table-shell--trade-details"
            toolbar={renderTradeToolbar()}
          />

          {tradeCostSummary.length ? (
            <WorkbenchCard>
              <h2 className="section-card__title">费用与执行统计</h2>
              <p className="section-card__description">实时模拟成交按A股手续费、印花税、lot和slot账本计算，净额才是实际现金变化。</p>
              <div className="execution-summary" aria-label="费用与执行统计">
                {executionHeroMetrics.length ? (
                  <div className="execution-summary__hero">
                    {primaryExecutionMetric ? (
                      <div className="execution-summary__hero-card execution-summary__hero-card--primary" key={primaryExecutionMetric.label}>
                        <span>关键成交</span>
                        <strong>{primaryExecutionMetric.value}</strong>
                        <em>{primaryExecutionMetric.label}</em>
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
                      <h3>其他</h3>
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
