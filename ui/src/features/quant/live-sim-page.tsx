import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import type { ApiClient } from "../../lib/api-client";
import { PageHeader } from "../../components/ui/page-header";
import { WorkbenchCard } from "../../components/ui/workbench-card";
import { PageEmptyState, PageErrorState, PageLoadingState } from "../../components/ui/page-state";
import { usePageData } from "../../lib/use-page-data";
import type { TableSection } from "../../lib/page-models";
import { toDisplayCount, toDisplayText } from "./quant-display";
import { QuantTableSectionCard } from "./quant-table-section";

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

function parseAutoExecute(value: string) {
  const normalized = String(value).trim().toLowerCase();
  return normalized === "true" || normalized === "1" || normalized.includes("开");
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

function normalizeSignalAction(value: string) {
  return String(value ?? "").trim().toUpperCase();
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

type LiveSimPageProps = {
  client?: ApiClient;
};

export function LiveSimPage({ client }: LiveSimPageProps) {
  const navigate = useNavigate();
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
  const [autoExecute, setAutoExecute] = useState(true);
  const [initialCash, setInitialCash] = useState(100000);
  const [commissionRatePct, setCommissionRatePct] = useState(0.03);
  const [sellTaxRatePct, setSellTaxRatePct] = useState(0.1);
  const [capitalSlotEnabled, setCapitalSlotEnabled] = useState(true);
  const [capitalPoolMinCash, setCapitalPoolMinCash] = useState(20000);
  const [capitalPoolMaxCash, setCapitalPoolMaxCash] = useState(1000000);
  const [capitalSlotMinCash, setCapitalSlotMinCash] = useState(20000);
  const [capitalMaxSlots, setCapitalMaxSlots] = useState(25);
  const [capitalMinBuySlotFraction, setCapitalMinBuySlotFraction] = useState(0.25);
  const [capitalFullBuyEdge, setCapitalFullBuyEdge] = useState(0.25);
  const [capitalConfidenceWeight, setCapitalConfidenceWeight] = useState(0.35);
  const [capitalHighPriceThreshold, setCapitalHighPriceThreshold] = useState(100);
  const [capitalHighPriceMaxSlotUnits, setCapitalHighPriceMaxSlotUnits] = useState(2);
  const [capitalSellCashReusePolicy, setCapitalSellCashReusePolicy] = useState("next_batch");
  const [actionPending, setActionPending] = useState<"save" | "reset" | "start" | "stop" | null>(null);
  const [signalTable, setSignalTable] = useState<TableSection>({
    columns: ["信号ID", "时间", "代码", "动作", "状态"],
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
    setAutoExecute(parseAutoExecute(snapshot.config.autoExecute));
    setInitialCash(Number.parseFloat(String(snapshot.config.initialCapital)) || 100000);
    setCommissionRatePct(parseRatePercent(snapshot.config.commissionRatePct, 0.03));
    setSellTaxRatePct(parseRatePercent(snapshot.config.sellTaxRatePct, 0.1));
    setCapitalSlotEnabled(snapshot.config.capitalSlotEnabled ?? true);
    setCapitalPoolMinCash(parseNumberConfig(snapshot.config.capitalPoolMinCash, 20000));
    setCapitalPoolMaxCash(parseNumberConfig(snapshot.config.capitalPoolMaxCash, 1000000));
    setCapitalSlotMinCash(parseNumberConfig(snapshot.config.capitalSlotMinCash, 20000));
    setCapitalMaxSlots(parseNumberConfig(snapshot.config.capitalMaxSlots, 25));
    setCapitalMinBuySlotFraction(parseNumberConfig(snapshot.config.capitalMinBuySlotFraction, 0.25));
    setCapitalFullBuyEdge(parseNumberConfig(snapshot.config.capitalFullBuyEdge, 0.25));
    setCapitalConfidenceWeight(parseNumberConfig(snapshot.config.capitalConfidenceWeight, 0.35));
    setCapitalHighPriceThreshold(parseNumberConfig(snapshot.config.capitalHighPriceThreshold, 100));
    setCapitalHighPriceMaxSlotUnits(parseNumberConfig(snapshot.config.capitalHighPriceMaxSlotUnits, 2));
    setCapitalSellCashReusePolicy(String(snapshot.config.capitalSellCashReusePolicy ?? "next_batch"));
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
          setTradeTable(removeStrategyColumn(payload.table));
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

  const candidateCodes = snapshot.candidatePool.rows.map((row) => row.id);
  const candidateCount = toDisplayCount(snapshot.status.candidateCount, snapshot.candidatePool.rows.length);
  const runningState = toDisplayText(snapshot.status.running, "未知");
  const runningNormalized = String(snapshot.status.running ?? "").trim().toLowerCase();
  const isRunning = runningNormalized.includes("运行中") || runningNormalized.includes("running");
  const signalActionOptions = Array.from(new Set(signalTable.rows.map((row) => normalizeSignalAction(String(row.cells[3] ?? ""))).filter(Boolean)));
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
    autoExecute,
    commissionRatePct,
    sellTaxRatePct,
    capitalSlotEnabled,
    capitalPoolMinCash,
    capitalPoolMaxCash,
    capitalSlotMinCash,
    capitalMaxSlots,
    capitalMinBuySlotFraction,
    capitalFullBuyEdge,
    capitalConfidenceWeight,
    capitalHighPriceThreshold,
    capitalHighPriceMaxSlotUnits,
    capitalSellCashReusePolicy,
  };

  return (
    <div>
      <PageHeader
        eyebrow="Quant"
        title="实时模拟"
        description="围绕共享量化候选池运行模拟账户、策略信号、自动执行和账户结果。"
        actions={
          <div className="chip-row">
            <span className="badge badge--neutral">快照 {snapshot.updatedAt}</span>
            <span className="badge badge--accent">候选 {candidateCount}</span>
            <span className="badge badge--success">{runningState}</span>
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
                <div className="mini-metric__label">Slot下限</div>
                <div className="mini-metric__value">{`${capitalSlotMinCash.toLocaleString()} 元`}</div>
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
              <label className="field" style={{ flexDirection: "row", alignItems: "center", gap: "10px" }}>
                <input type="checkbox" checked={autoExecute} onChange={(event) => setAutoExecute(event.target.checked)} />
                <span className="field__label" style={{ marginBottom: 0 }}>
                  自动执行模拟交易
                </span>
              </label>
              <label className="field" style={{ flexDirection: "row", alignItems: "center", gap: "10px" }}>
                <input type="checkbox" checked={capitalSlotEnabled} onChange={(event) => setCapitalSlotEnabled(event.target.checked)} />
                <span className="field__label" style={{ marginBottom: 0 }}>
                  启用Slot资金管理
                </span>
              </label>
              <label className="field">
                <span className="field__label">资金池最低(元)</span>
                <input className="input" min={20000} step={1000} type="number" value={capitalPoolMinCash} onChange={(event) => setCapitalPoolMinCash(Math.max(20000, Number(event.target.value) || 20000))} />
              </label>
              <label className="field">
                <span className="field__label">资金池最高(元)</span>
                <input className="input" min={capitalPoolMinCash} step={10000} type="number" value={capitalPoolMaxCash} onChange={(event) => setCapitalPoolMaxCash(Number(event.target.value) || 1000000)} />
              </label>
              <label className="field">
                <span className="field__label">单Slot最低(元)</span>
                <input className="input" min={20000} step={1000} type="number" value={capitalSlotMinCash} onChange={(event) => setCapitalSlotMinCash(Math.max(20000, Number(event.target.value) || 20000))} />
              </label>
              <label className="field">
                <span className="field__label">最大Slot数</span>
                <input className="input" min={1} step={1} type="number" value={capitalMaxSlots} onChange={(event) => setCapitalMaxSlots(Number(event.target.value) || 25)} />
              </label>
              <label className="field">
                <span className="field__label">弱BUY最小Slot比例</span>
                <input className="input" min={0} max={1} step={0.05} type="number" value={capitalMinBuySlotFraction} onChange={(event) => setCapitalMinBuySlotFraction(Number(event.target.value) || 0.25)} />
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
              <label className="field">
                <span className="field__label">卖出资金复用</span>
                <select className="input" value={capitalSellCashReusePolicy} onChange={(event) => setCapitalSellCashReusePolicy(event.target.value)}>
                  <option value="next_batch">下一批次可用</option>
                  <option value="same_batch">同批次可用</option>
                </select>
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

          <WorkbenchCard>
            <h2 className="section-card__title">运行状态</h2>
            <p className="section-card__description">{`定时状态：${snapshot.status.running}；最近执行：${snapshot.status.lastRun}；下次执行：${snapshot.status.nextRun}。`}</p>
          </WorkbenchCard>
        </div>

        <div className="stack">
          <div className="metric-grid">
            {snapshot.metrics.map((metric) => (
              <WorkbenchCard className="metric-card" key={metric.label}>
                <div className="metric-card__label">{metric.label}</div>
                <div className="metric-card__value">{metric.value}</div>
              </WorkbenchCard>
            ))}
          </div>

          {snapshot.tradeCostSummary?.length ? (
            <WorkbenchCard>
              <h2 className="section-card__title">交易成本汇总</h2>
              <p className="section-card__description">实时模拟成交按A股手续费、印花税、lot和slot账本计算，净额才是实际现金变化。</p>
              <div className="mini-metric-grid">
                {snapshot.tradeCostSummary.map((metric) => (
                  <div className="mini-metric" key={metric.label}>
                    <div className="mini-metric__label">{metric.label}</div>
                    <div className="mini-metric__value">{metric.value}</div>
                  </div>
                ))}
              </div>
            </WorkbenchCard>
          ) : null}

          {snapshot.capitalSlots ? (
            <QuantTableSectionCard
              title="Slot资金池"
              description="Slot只控制每次自动买入的预算，实际持仓和T+1仍以lot为准。"
              table={snapshot.capitalSlots}
              emptyTitle={snapshot.capitalSlots.emptyLabel ?? "暂无资金槽"}
              emptyDescription={snapshot.capitalSlots.emptyMessage ?? "资金池低于最低额度或尚未同步slot账本。"}
              compactConfig={{ coreColumnIndexes: [0, 1, 2], detailColumnIndexes: [3, 4] }}
            />
          ) : null}

          <QuantTableSectionCard
            title="量化候选池"
            description="候选池由“我的关注”人工推进到这里，再进入实时模拟和历史回放。"
            table={snapshot.candidatePool}
            emptyTitle={snapshot.candidatePool.emptyLabel ?? "候选池暂无数据"}
            emptyDescription={
              snapshot.candidatePool.emptyMessage ?? "先从我的关注加入股票，或者等待定时任务把新的候选推进到这里。"
            }
            meta={[`表内 ${snapshot.candidatePool.rows.length} 只`, `待量化 ${candidateCount}`]}
            actionsHead="操作"
            compactConfig={{ coreColumnIndexes: [0, 1, 3], detailColumnIndexes: [2] }}
            onRowAction={(row, action) => {
              void resource.runAction(action.action ?? "analyze-candidate", row.id);
            }}
          />

          <QuantTableSectionCard
            title="当前持仓"
            table={snapshot.holdings}
            emptyTitle={snapshot.holdings.emptyLabel ?? "当前持仓暂无数据"}
            emptyDescription={snapshot.holdings.emptyMessage ?? "模拟账户当前还没有形成持仓，待下一轮信号触发后会在这里补充。"}
            actionsHead="操作"
            compactConfig={{ coreColumnIndexes: [0, 1, 4], detailColumnIndexes: [2, 3, 5, 6] }}
            onRowAction={(row, action) => {
              void resource.runAction(action.action ?? "delete-position", row.id);
            }}
          />
          <QuantTableSectionCard
            title="成交记录"
            table={tradeTable}
            emptyTitle={tradeTable.emptyLabel ?? "成交记录暂无数据"}
            emptyDescription={tradeTable.emptyMessage ?? "如果调度还没有生成新的成交，这里会先保持为空。"}
            compactConfig={{ coreColumnIndexes: [0, 1, 2, 7], detailColumnIndexes: [3, 4, 5, 6, 8, 9, 10] }}
            toolbar={renderTradeToolbar()}
          />

          <WorkbenchCard>
            <h2 className="section-card__title">{snapshot.executionCenter.title}</h2>
            <p className="section-card__description">{snapshot.executionCenter.body}</p>
            <div className="chip-row">
              {snapshot.executionCenter.chips.map((chip) => (
                <span className="chip chip--active" key={chip}>
                  {chip}
                </span>
              ))}
            </div>
            {snapshot.pendingSignals.length > 0 ? (
              <div className="summary-list" style={{ marginTop: "16px" }}>
                {snapshot.pendingSignals.map((item) => (
                  <div className="summary-item" key={item.title}>
                    <div className="summary-item__title">{item.title}</div>
                    <div className="summary-item__body">{item.body}</div>
                  </div>
                ))}
              </div>
            ) : (
              <div className="summary-item summary-item--accent" style={{ marginTop: "16px" }}>
                <div className="summary-item__title">暂无待执行信号</div>
                <div className="summary-item__body">当前没有新的 BUY / SELL 信号，系统会继续观察候选池并等待下一轮调度。</div>
              </div>
            )}
          </WorkbenchCard>

          <QuantTableSectionCard
            title="信号记录"
            description="点击详情进入统一信号详情页，查看投票、决策依据和技术指标快照。"
            table={pagedSignalTable}
            emptyTitle={signalTable.emptyLabel ?? "暂无信号"}
            emptyDescription={signalTable.emptyMessage ?? "当前没有可查看的信号记录。"}
            actionsHead="操作"
            actionVariant="chip"
            tableLayout="auto"
            compactConfig={{ coreColumnIndexes: [1, 2, 3, 4], detailColumnIndexes: [0] }}
            toolbar={renderSignalToolbar()}
            onRowAction={(row, action) => {
              const actionKey = String(action.action ?? "").trim().toLowerCase();
              const actionLabel = String(action.label ?? "").trim().toLowerCase();
              if (!(actionKey === "show-signal-detail" || actionLabel === "详情" || actionLabel === "detail")) {
                return;
              }
              navigate(`/signal-detail/${encodeURIComponent(row.id)}?source=live`);
            }}
          />
        </div>
      </div>
    </div>
  );
}
