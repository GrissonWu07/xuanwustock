import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import type { ApiClient } from "../../lib/api-client";
import { PageHeader } from "../../components/ui/page-header";
import { WorkbenchCard } from "../../components/ui/workbench-card";
import { PageEmptyState, PageErrorState, PageLoadingState } from "../../components/ui/page-state";
import { Sparkline } from "../../components/ui/sparkline";
import { usePageData } from "../../lib/use-page-data";
import type { TableAction, TableRow, TableSection } from "../../lib/page-models";
import { summarizeTaskStatuses, toDisplayText } from "./quant-display";
import { QuantTableSectionCard } from "./quant-table-section";

const REPLAY_MODE_OPTIONS = [
  { value: "historical_range", label: "历史区间回放" },
  { value: "continuous_to_live", label: "从过去接续到实时自动模拟" },
];

const TIMEFRAME_OPTIONS = [
  { value: "30m", label: "30分钟" },
  { value: "1d", label: "日线" },
  { value: "1d+30m", label: "日线方向 + 30分钟确认" },
];

const STRATEGY_MODE_OPTIONS = [
  { value: "auto", label: "自动" },
  { value: "aggressive", label: "激进" },
  { value: "neutral", label: "中性" },
  { value: "defensive", label: "稳健" },
];

const MARKET_OPTIONS = ["CN", "HK", "US"] as const;

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

function normalizeTimeframe(value: string) {
  const normalized = String(value).trim().toLowerCase();
  return TIMEFRAME_OPTIONS.find((option) => option.value === normalized)?.value ?? "30m";
}

function normalizeStrategyMode(value: string) {
  const normalized = String(value).trim().toLowerCase();
  if (normalized === "aggressive" || normalized.includes("激进")) return "aggressive";
  if (normalized === "neutral" || normalized.includes("中性")) return "neutral";
  if (normalized === "defensive" || normalized.includes("稳健") || normalized.includes("防守")) return "defensive";
  return "auto";
}

function normalizeMarket(value: string) {
  const normalized = String(value).trim().toUpperCase();
  return MARKET_OPTIONS.includes(normalized as (typeof MARKET_OPTIONS)[number]) ? normalized : "CN";
}

type HisReplayPageProps = {
  client?: ApiClient;
};

const taskBadgeTone: Record<string, "neutral" | "success" | "warning" | "danger"> = {
  completed: "success",
  running: "warning",
  queued: "neutral",
  cancelled: "danger",
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

export function HisReplayPage({ client }: HisReplayPageProps) {
  const navigate = useNavigate();
  const resource = usePageData("his-replay", client);
  const snapshot = resource.data;
  const snapshotVersion = snapshot?.updatedAt ?? "loading";
  const [replayMode, setReplayMode] = useState("historical_range");
  const [startDate, setStartDate] = useState("2026-03-11");
  const [endDate, setEndDate] = useState("2026-04-10");
  const [startTime, setStartTime] = useState("09:30");
  const [endTime, setEndTime] = useState("15:00");
  const [timeframe, setTimeframe] = useState("30m");
  const [market, setMarket] = useState<(typeof MARKET_OPTIONS)[number]>("CN");
  const [strategyMode, setStrategyMode] = useState("auto");
  const [replayUntilNow, setReplayUntilNow] = useState(false);
  const [overwriteLive, setOverwriteLive] = useState(false);
  const [autoStartScheduler, setAutoStartScheduler] = useState(true);
  const [selectedTaskId, setSelectedTaskId] = useState("");
  const [tradeStockFilter, setTradeStockFilter] = useState("");
  const [tradeActionFilter, setTradeActionFilter] = useState("ALL");
  const [signalStockFilter, setSignalStockFilter] = useState("");
  const [signalActionFilter, setSignalActionFilter] = useState("TRADE");
  const [tradePage, setTradePage] = useState(1);
  const [signalPage, setSignalPage] = useState(1);

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
    setStrategyMode(normalizeStrategyMode(snapshot.config.strategyMode));
    setReplayUntilNow(false);
    setOverwriteLive(false);
    setAutoStartScheduler(true);
    setSelectedTaskId((prev) => {
      if (prev && snapshot.tasks.some((task) => task.id === prev)) {
        return prev;
      }
      const runningTask = snapshot.tasks.find((task) => String(task.status).toLowerCase() === "running");
      if (runningTask) {
        return runningTask.id;
      }
      return snapshot.tasks[0]?.id ?? "";
    });
  }, [snapshotVersion]);

  useEffect(() => {
    if (!snapshot) {
      return;
    }
    setTradePage(1);
    setSignalPage(1);
  }, [snapshotVersion, snapshot]);

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
  const replayModeLabel = toDisplayText(snapshot.config.mode, "未知");
  const replayTaskLabel = taskSummary.running > 0 ? `进行中 ${taskSummary.running}` : `已完成 ${taskSummary.completed}`;
  const runningTask = snapshot.tasks.find((task) => String(task.status).toLowerCase() === "running") ?? null;
  const runningProgress = Math.max(0, Math.min(Number(runningTask?.progress ?? 0), 100));
  const selectedTask = snapshot.tasks.find((task) => task.id === selectedTaskId) ?? snapshot.tasks[0] ?? null;
  const selectedTaskRange = selectedTask?.range || snapshot.config.range;
  const selectedTaskStatusLabel = selectedTask ? localizeTaskStatus(selectedTask.status) : "--";
  const selectedTaskStageLabel = selectedTask?.stage || "--";
  const selectedTaskStartedAt = selectedTask?.startAt || "--";
  const selectedTaskEndedAt = selectedTask?.endAt || "--";
  const selectedTaskHoldings: TableSection = {
    columns: ["代码", "名称", "数量", "成本", "现价", "浮盈亏(元)", "浮盈亏(%)"],
    rows: selectedTask?.holdings ?? [],
    emptyLabel: "暂无持仓",
    emptyMessage: "选中任务没有持仓记录，可能已清仓或尚未执行到持仓阶段。",
  };
  const tradeRows = withCodeName(snapshot.trades.rows, 2);
  const signalRows = withCodeName(snapshot.signals.rows, 2);
  const tradeActionOptions = Array.from(
    new Set(
      snapshot.trades.rows
        .map((row) => normalizeAction(String(row.cells[3] ?? "")))
        .filter(Boolean),
    ),
  );
  const signalActionOptions = Array.from(
    new Set(
      snapshot.signals.rows
        .map((row) => normalizeAction(String(row.cells[3] ?? "")))
        .filter(Boolean),
    ),
  );
  const filteredTradeRows = tradeRows.filter((row) => {
    const stockKeyword = tradeStockFilter.trim().toLowerCase();
    const code = String(row.code ?? "").toLowerCase();
    const name = String(row.name ?? "").toLowerCase();
    const codeCell = String(row.cells[2] ?? "").toLowerCase();
    const action = normalizeAction(String(row.cells[3] ?? ""));
    const stockMatched = !stockKeyword || code.includes(stockKeyword) || name.includes(stockKeyword) || codeCell.includes(stockKeyword);
    const actionMatched = tradeActionFilter === "ALL" || action === tradeActionFilter;
    return stockMatched && actionMatched;
  });
  const filteredSignalRows = signalRows.filter((row) => {
    const stockKeyword = signalStockFilter.trim().toLowerCase();
    const code = String(row.code ?? "").toLowerCase();
    const name = String(row.name ?? "").toLowerCase();
    const codeCell = String(row.cells[2] ?? "").toLowerCase();
    const action = normalizeAction(String(row.cells[3] ?? ""));
    const stockMatched = !stockKeyword || code.includes(stockKeyword) || name.includes(stockKeyword) || codeCell.includes(stockKeyword);
    const actionMatched =
      signalActionFilter === "ALL"
      || (signalActionFilter === "TRADE" && (action === "BUY" || action === "BUG" || action === "SELL"))
      || action === signalActionFilter;
    return stockMatched && actionMatched;
  });
  const tradePages = Math.max(1, Math.ceil(filteredTradeRows.length / PAGE_SIZE));
  const signalPages = Math.max(1, Math.ceil(filteredSignalRows.length / PAGE_SIZE));
  const pagedTrades = {
    ...snapshot.trades,
    rows: filteredTradeRows.slice((tradePage - 1) * PAGE_SIZE, tradePage * PAGE_SIZE),
  };
  const pagedSignals = {
    ...snapshot.signals,
    rows: filteredSignalRows.slice((signalPage - 1) * PAGE_SIZE, signalPage * PAGE_SIZE),
  };
  const toolbarControlHeight = "40px";
  const renderPager = (page: number, pages: number, setPage: (value: number) => void) => (
    <div className="chip-row">
      <button
        className="button button--secondary button--small"
        type="button"
        style={{ height: toolbarControlHeight, minHeight: toolbarControlHeight, padding: "0 18px" }}
        disabled={page <= 1}
        onClick={() => setPage(page - 1)}
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
        {`第 ${page} / ${pages} 页`}
      </span>
      <button
        className="button button--secondary button--small"
        type="button"
        style={{ height: toolbarControlHeight, minHeight: toolbarControlHeight, padding: "0 18px" }}
        disabled={page >= pages}
        onClick={() => setPage(page + 1)}
      >
        下一页
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
    <div style={{ display: "flex", gap: "8px", alignItems: "center", justifyContent: "flex-end", flexWrap: "nowrap" }}>
      <input
        className="input"
        style={{ width: "160px", height: toolbarControlHeight, minHeight: toolbarControlHeight, padding: "0 10px" }}
        placeholder="按代码/名称过滤"
        value={stockFilter}
        onChange={(event) => setStockFilter(event.target.value)}
      />
      <select
        className="input"
        style={{ width: "120px", height: toolbarControlHeight, minHeight: toolbarControlHeight, padding: "0 10px" }}
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
      <span className="summary-item__body" style={{ margin: 0, whiteSpace: "nowrap" }}>
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

  return (
    <div>
      <PageHeader
        eyebrow="Replay"
        title="历史回放"
        description="围绕同一批量化候选池回放历史区间，核对任务、成交、持仓和信号落库结果。"
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
                <span className="field__label">策略模式</span>
                <select className="input" value={strategyMode} onChange={(event) => setStrategyMode(event.target.value)}>
                  {STRATEGY_MODE_OPTIONS.map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                </select>
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
                disabled={resource.status === "loading"}
                onClick={() =>
                  void resource.runAction(replayMode === "continuous_to_live" ? "continue" : "start", {
                    startDateTime: `${startDate} ${startTime}:00`,
                    endDateTime: replayUntilNow ? null : `${endDate} ${endTime}:00`,
                    timeframe,
                    market,
                    strategyMode,
                    overwriteLive,
                    autoStartScheduler,
                  })
                }
              >
                {replayMode === "continuous_to_live" ? "接续" : "开始回溯"}
              </button>
              <button className="button button--secondary" type="button" onClick={() => void resource.runAction("cancel")}>
                取消
              </button>
              <span className="toolbar__spacer" />
              <button className="button button--secondary" type="button" onClick={() => void resource.runAction("delete")}>
                删除
              </button>
            </div>
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
            <h2 className="section-card__title">回放任务</h2>
            <div className="chip-row" style={{ marginBottom: "12px" }}>
              <span className="badge badge--neutral">已完成 {taskSummary.completed}</span>
              <span className="badge badge--accent">进行中 {taskSummary.running}</span>
              <span className="badge badge--neutral">排队 {taskSummary.queued}</span>
            </div>
            {snapshot.tasks.length > 0 ? (
              <div className="summary-list">
                <label className="field">
                  <span className="field__label">选择任务</span>
                  <select className="input" value={selectedTask?.id ?? ""} onChange={(event) => setSelectedTaskId(event.target.value)}>
                    {snapshot.tasks.map((task) => (
                      <option key={task.id} value={task.id}>
                        {`${task.id} · ${localizeTaskStatus(task.status)}`}
                      </option>
                    ))}
                  </select>
                </label>
                {selectedTask ? (
                  <>
                    <div className="summary-item">
                      <div className="summary-item__title">回放结论</div>
                      <div className="summary-item__body">{`${selectedTask.id} · ${selectedTaskStatusLabel}`}</div>
                      <div className="summary-item__body">{`执行阶段：${selectedTaskStageLabel}`}</div>
                      <div className="summary-item__body">{`开始时间：${selectedTaskStartedAt}`}</div>
                      <div className="summary-item__body">{`结束时间：${selectedTaskEndedAt}`}</div>
                      <div className="summary-item__body">{`区间：${selectedTaskRange}`}</div>
                      <div className="summary-item__body">{`模式：${replayModeLabel} · 粒度：${snapshot.config.timeframe} · 策略模式：${snapshot.config.strategyMode}`}</div>
                    </div>
                    <div className="mini-metric-grid" style={{ gridTemplateColumns: "repeat(4, minmax(0, 1fr))", gap: "8px" }}>
                      <div className="mini-metric">
                        <div className="mini-metric__label">最终盈亏比例</div>
                        <div className="mini-metric__value">{selectedTask.returnPct || "--"}</div>
                      </div>
                      <div className="mini-metric">
                        <div className="mini-metric__label">最终现金价值</div>
                        <div className="mini-metric__value">{selectedTask.finalEquity || "--"}</div>
                      </div>
                      <div className="mini-metric">
                        <div className="mini-metric__label">交易笔数</div>
                        <div className="mini-metric__value">{selectedTask.tradeCount || "0"}</div>
                      </div>
                      <div className="mini-metric">
                        <div className="mini-metric__label">胜率</div>
                        <div className="mini-metric__value">{selectedTask.winRate || "--"}</div>
                      </div>
                    </div>
                  </>
                ) : null}
              </div>
            ) : (
              <div className="summary-item summary-item--accent">
                <div className="summary-item__title">暂无回放任务</div>
                <div className="summary-item__body">当前没有排队中的历史回放任务，点击“开始回溯”后会在这里创建新任务。</div>
              </div>
            )}
          </WorkbenchCard>

          <QuantTableSectionCard
            title="历史持仓"
            table={selectedTaskHoldings}
            emptyTitle={selectedTaskHoldings.emptyLabel ?? "历史持仓暂无数据"}
            emptyDescription={selectedTaskHoldings.emptyMessage ?? "选中任务没有持仓记录。"}
            tableLayout="auto"
          />

          <QuantTableSectionCard
            title="成交明细"
            table={pagedTrades}
            emptyTitle={snapshot.trades.emptyLabel ?? "成交明细暂无数据"}
            emptyDescription={snapshot.trades.emptyMessage ?? "历史回放执行后，所有成交会统一落在这里。"}
            tableLayout="auto"
            toolbar={renderFilterToolbar(
              tradeStockFilter,
              setTradeStockFilter,
              tradeActionFilter,
              setTradeActionFilter,
              tradeActionOptions,
              tradePage,
              tradePages,
              setTradePage,
              `筛选后 ${filteredTradeRows.length} 条`,
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
            toolbar={renderFilterToolbar(
              signalStockFilter,
              setSignalStockFilter,
              signalActionFilter,
              setSignalActionFilter,
              signalActionOptions,
              signalPage,
              signalPages,
              setSignalPage,
              `筛选后 ${filteredSignalRows.length} 条`,
              true,
            )}
            onRowAction={handleSignalRowAction}
          />
        </div>
      </div>
    </div>
  );
}
