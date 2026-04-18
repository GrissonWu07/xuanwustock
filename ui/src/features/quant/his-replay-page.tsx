import { useEffect, useState } from "react";
import type { ApiClient } from "../../lib/api-client";
import { PageHeader } from "../../components/ui/page-header";
import { StrategyNarrativeCard } from "../../components/ui/strategy-narrative";
import { WorkbenchCard } from "../../components/ui/workbench-card";
import { PageEmptyState, PageErrorState, PageLoadingState } from "../../components/ui/page-state";
import { Sparkline } from "../../components/ui/sparkline";
import { usePageData } from "../../lib/use-page-data";
import type { TableAction, TableRow } from "../../lib/page-models";
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

type ReplaySignalRow = TableRow & {
  analysis?: string;
  votes?: string;
  signalStatus?: string;
  decisionType?: string;
  confidence?: string;
  techScore?: string;
  contextScore?: string;
  checkpointAt?: string;
};

export function HisReplayPage({ client }: HisReplayPageProps) {
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
  const [activeSignal, setActiveSignal] = useState<ReplaySignalRow | null>(null);

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
  }, [snapshotVersion]);

  useEffect(() => {
    if (!snapshot) {
      setActiveSignal(null);
      return;
    }
    const signalRows = snapshot.signals.rows as ReplaySignalRow[];
    if (signalRows.length === 0) {
      setActiveSignal(null);
      return;
    }
    setActiveSignal((prev) => {
      if (prev && signalRows.some((item) => item.id === prev.id)) {
        return signalRows.find((item) => item.id === prev.id) ?? signalRows[0];
      }
      return signalRows[0];
    });
  }, [snapshotVersion, snapshot]);

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
  const handleSignalRowAction = (row: TableRow, action: TableAction) => {
    if (action.action !== "show-signal-detail") {
      return;
    }
    setActiveSignal(row as ReplaySignalRow);
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
            <span className="badge badge--success">{replayTaskLabel}</span>
          </div>
        }
      />
      <div className="section-grid section-grid--sidebar">
        <div className="stack">
          <WorkbenchCard>
            <h2 className="section-card__title">回放配置</h2>
            <p className="section-card__description">直接选择模式、时间范围和粒度，然后对当前量化候选池发起回放任务。</p>
            <div className="mini-metric-grid">
              <div className="mini-metric">
                <div className="mini-metric__label">模式</div>
                <div className="mini-metric__value">{replayModeLabel}</div>
              </div>
              <div className="mini-metric">
                <div className="mini-metric__label">粒度</div>
                <div className="mini-metric__value">{snapshot.config.timeframe}</div>
              </div>
              <div className="mini-metric">
                <div className="mini-metric__label">策略模式</div>
                <div className="mini-metric__value">{snapshot.config.strategyMode}</div>
              </div>
            </div>
            <div className="card-divider" />
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
                {replayMode === "continuous_to_live" ? "接续" : "回放"}
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

          <StrategyNarrativeCard
            title="回放结论"
            summary={`历史回放围绕 ${snapshot.config.timeframe} 粒度和 ${snapshot.config.strategyMode} 策略复现 ${snapshot.config.range} 区间表现。`}
            recommendation="优先查看交易分析和成交明细，再决定是否沿用当前策略模式进入实时模拟。"
            reasons={[
              `模式 ${snapshot.config.mode}`,
              `区间 ${snapshot.config.range}`,
              `粒度 ${snapshot.config.timeframe}`,
              `策略模式 ${snapshot.config.strategyMode}`,
            ]}
            evidence={[
              { label: "回放结果", value: snapshot.metrics[0]?.value ?? "-" },
              { label: "最终总权益", value: snapshot.metrics[1]?.value ?? "-" },
              { label: "交易笔数", value: snapshot.metrics[2]?.value ?? "-" },
              { label: "胜率", value: snapshot.metrics[3]?.value ?? "-" },
            ]}
          />

          <WorkbenchCard>
            <h2 className="section-card__title">回放任务</h2>
            <div className="chip-row" style={{ marginBottom: "12px" }}>
              <span className="badge badge--neutral">已完成 {taskSummary.completed}</span>
              <span className="badge badge--accent">进行中 {taskSummary.running}</span>
              <span className="badge badge--neutral">排队 {taskSummary.queued}</span>
            </div>
            {snapshot.tasks.length > 0 ? (
              <div className="summary-list">
                {snapshot.tasks.map((task) => (
                  <div className="summary-item" key={task.id}>
                    <div className="summary-item__title">
                      {task.id} · <span className={`badge badge--${taskBadgeTone[task.status] ?? "neutral"}`}>{task.status}</span>
                    </div>
                    <div className="summary-item__body">{task.range}</div>
                    <div className="card-divider" />
                    <div className="summary-item__body">{task.note}</div>
                  </div>
                ))}
              </div>
            ) : (
              <div className="summary-item summary-item--accent">
                <div className="summary-item__title">暂无回放任务</div>
                <div className="summary-item__body">当前没有排队中的历史回放任务，点击“回放”后会在这里创建新任务。</div>
              </div>
            )}
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

          <WorkbenchCard>
            <h2 className="section-card__title">{snapshot.tradingAnalysis.title}</h2>
            <p className="section-card__description">{snapshot.tradingAnalysis.body}</p>
            <div className="chip-row">
              {snapshot.tradingAnalysis.chips.map((chip) => (
                <span className="chip chip--active" key={chip}>
                  {chip}
                </span>
              ))}
            </div>
          </WorkbenchCard>

          <div className="section-grid">
            <WorkbenchCard>
              <h2 className="section-card__title">资金曲线</h2>
              <Sparkline points={snapshot.curve} />
            </WorkbenchCard>
            <QuantTableSectionCard
              title="结束持仓"
              table={snapshot.holdings}
              emptyTitle={snapshot.holdings.emptyLabel ?? "结束持仓暂无数据"}
              emptyDescription={snapshot.holdings.emptyMessage ?? "如果回放还没有收盘，这里会等任务完成后再补齐。"}
            />
          </div>

          <div className="stack">
            <QuantTableSectionCard
              title="成交明细"
              table={snapshot.trades}
              emptyTitle={snapshot.trades.emptyLabel ?? "成交明细暂无数据"}
              emptyDescription={snapshot.trades.emptyMessage ?? "历史回放执行后，所有成交会统一落在这里。"}
              tableLayout="auto"
            />
            <QuantTableSectionCard
              title="信号记录"
              table={snapshot.signals}
              emptyTitle={snapshot.signals.emptyLabel ?? "信号记录暂无数据"}
              emptyDescription={snapshot.signals.emptyMessage ?? "回放过程中生成的信号会展示在这里，便于快速核对执行结果。"}
              actionsHead="操作"
              actionVariant="chip"
              tableLayout="auto"
              onRowAction={handleSignalRowAction}
            />
            <WorkbenchCard>
              <h2 className="section-card__title">信号详情</h2>
              {activeSignal ? (
                <div className="summary-list">
                  <div className="summary-item">
                    <div className="summary-item__title">{`信号 ${activeSignal.id}`}</div>
                    <div className="summary-item__body">{`代码 ${activeSignal.code ?? "--"} · 动作 ${activeSignal.cells[3] ?? "--"} · 执行结果 ${activeSignal.signalStatus ?? activeSignal.cells[5] ?? "--"}`}</div>
                    <div className="summary-item__body">{`策略 ${activeSignal.decisionType ?? activeSignal.cells[4] ?? "--"} · 置信度 ${activeSignal.confidence ?? "--"} · 技术分 ${activeSignal.techScore ?? "--"} · 环境分 ${activeSignal.contextScore ?? "--"}`}</div>
                    <div className="summary-item__body">{`时间 ${activeSignal.checkpointAt ?? activeSignal.cells[1] ?? "--"}`}</div>
                  </div>
                  <div className="summary-item">
                    <div className="summary-item__title">分析数据</div>
                    <div className="summary-item__body markdown-body">{activeSignal.analysis ?? "暂无分析数据"}</div>
                  </div>
                  <div className="summary-item">
                    <div className="summary-item__title">投票数据</div>
                    <div className="summary-item__body markdown-body">{activeSignal.votes ?? "暂无投票数据"}</div>
                  </div>
                </div>
              ) : (
                <div className="summary-item summary-item--accent">
                  <div className="summary-item__title">暂无可查看信号</div>
                  <div className="summary-item__body">当信号记录有数据时，点击“详情”即可查看对应分析与投票结果。</div>
                </div>
              )}
            </WorkbenchCard>
          </div>
        </div>
      </div>
    </div>
  );
}
