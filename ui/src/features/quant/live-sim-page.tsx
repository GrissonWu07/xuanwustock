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
  }, [snapshotVersion]);

  useEffect(() => {
    let mounted = true;
    async function loadSignals() {
      setSignalLoading(true);
      try {
        const response = await fetch("/api/v1/quant/live-sim/signals?limit=200", {
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
  }, [snapshotVersion]);

  useEffect(() => {
    setSignalPage(1);
  }, [signalStockFilter, signalActionFilter, snapshotVersion]);

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
  const filteredSignalRows = signalTable.rows.filter((row) => {
    const keyword = signalStockFilter.trim().toLowerCase();
    const code = String(row.code ?? row.cells[2] ?? "").toLowerCase();
    const name = String(row.name ?? "").toLowerCase();
    const codeCell = String(row.cells[2] ?? "").toLowerCase();
    const action = normalizeSignalAction(String(row.cells[3] ?? ""));
    const stockMatched = !keyword || code.includes(keyword) || name.includes(keyword) || codeCell.includes(keyword);
    const actionMatched =
      signalActionFilter === "ALL"
      || (signalActionFilter === "TRADE" && (action === "BUY" || action === "BUG" || action === "SELL"))
      || action === signalActionFilter;
    return stockMatched && actionMatched;
  });
  const signalPages = Math.max(1, Math.ceil(filteredSignalRows.length / SIGNAL_PAGE_SIZE));
  const currentSignalPage = Math.min(signalPage, signalPages);
  const pagedSignalTable: TableSection = {
    ...signalTable,
    rows: filteredSignalRows.slice((currentSignalPage - 1) * SIGNAL_PAGE_SIZE, currentSignalPage * SIGNAL_PAGE_SIZE),
  };
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
        {signalLoading ? "加载中..." : `筛选后 ${filteredSignalRows.length} 条`}
      </span>
    </div>
  );

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
                    await resource.runAction("save", {
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
                    });
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
                    await resource.runAction("start", {
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
                    });
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
            table={snapshot.trades}
            emptyTitle={snapshot.trades.emptyLabel ?? "成交记录暂无数据"}
            emptyDescription={snapshot.trades.emptyMessage ?? "如果调度还没有生成新的成交，这里会先保持为空。"}
            compactConfig={{ coreColumnIndexes: [0, 2, 3, 5], detailColumnIndexes: [1, 4, 6] }}
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
