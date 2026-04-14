import { useEffect, useState } from "react";
import type { ApiClient } from "../../lib/api-client";
import { SectionEmptyState } from "../../components/ui/section-empty";
import { PageHeader } from "../../components/ui/page-header";
import { WorkbenchCard } from "../../components/ui/workbench-card";
import { PageEmptyState, PageErrorState, PageLoadingState } from "../../components/ui/page-state";
import { Sparkline } from "../../components/ui/sparkline";
import { usePageData } from "../../lib/use-page-data";

const SCHEDULE_MODE_OPTIONS = [
  { value: "sequential", label: "顺序分析" },
  { value: "parallel", label: "并行分析" },
];

const DEFAULT_SCHEDULE_TIME = "09:30";

type PortfolioPageProps = {
  client?: ApiClient;
};

export function PortfolioPage({ client }: PortfolioPageProps) {
  const resource = usePageData("portfolio", client);
  const snapshot = resource.data;
  const snapshotVersion = snapshot?.updatedAt ?? "loading";
  const [scheduleTime, setScheduleTime] = useState(DEFAULT_SCHEDULE_TIME);
  const [analysisMode, setAnalysisMode] = useState("sequential");
  const [maxWorkers, setMaxWorkers] = useState(1);
  const [autoSyncMonitor, setAutoSyncMonitor] = useState(true);
  const [sendNotification, setSendNotification] = useState(true);

  useEffect(() => {
    setScheduleTime(DEFAULT_SCHEDULE_TIME);
    setAnalysisMode("sequential");
    setMaxWorkers(1);
    setAutoSyncMonitor(true);
    setSendNotification(true);
  }, [snapshotVersion]);

  if (resource.status === "loading" && !resource.data) {
    return <PageLoadingState title="持仓分析加载中" description="正在读取当前持仓、收益归因和组合曲线。" />;
  }

  if (resource.status === "error" && !resource.data) {
    return (
      <PageErrorState
        title="持仓分析加载失败"
        description={resource.error ?? "无法加载持仓分析数据，请稍后重试。"}
        actionLabel="重新加载"
        onAction={resource.refresh}
      />
    );
  }

  if (!snapshot) {
    return <PageEmptyState title="持仓分析暂无数据" description="后台尚未返回持仓分析快照。" actionLabel="刷新" onAction={resource.refresh} />;
  }

  return (
    <div>
      <PageHeader eyebrow="Portfolio" title="持仓分析" description="持仓跟踪、组合分析和定时任务都在这里统一查看与操作。" />
      <div className="stack">
        <WorkbenchCard>
          <h2 className="section-card__title">快照概览</h2>
          <p className="section-card__description">
            当前持仓、收益归因、组合曲线和动作入口都来自同一份快照，页面会在刷新后同步回写最新状态。
          </p>
          <div className="mini-metric-grid">
            <div className="mini-metric">
              <div className="mini-metric__label">快照更新时间</div>
              <div className="mini-metric__value">{snapshot.updatedAt}</div>
            </div>
            <div className="mini-metric">
              <div className="mini-metric__label">当前持仓</div>
              <div className="mini-metric__value">{snapshot.holdings.rows.length}</div>
            </div>
            <div className="mini-metric">
              <div className="mini-metric__label">收益归因</div>
              <div className="mini-metric__value">{snapshot.attribution.length}</div>
            </div>
          </div>
          <div className="card-divider" />
          <div className="summary-list">
            <SectionEmptyState
              title="组合动作"
              description={snapshot.actions.length > 0 ? "这些动作代表当前组合页支持的后续操作。" : "当前没有可展示的组合动作。"}
            >
              {snapshot.actions.length > 0 ? (
                snapshot.actions.map((action) => (
                  <span className="badge badge--neutral" key={action}>
                    {action}
                  </span>
                ))
              ) : (
                <span className="badge badge--neutral">暂无动作</span>
              )}
            </SectionEmptyState>
          </div>
        </WorkbenchCard>
        <WorkbenchCard>
          <div className="toolbar">
            <div>
              <h2 className="section-card__title">组合操作</h2>
              <p className="section-card__description" style={{ marginBottom: 0 }}>
                这里直接调用后端的组合刷新和调度动作，避免把刷新和页面重新拉取混在一起。
              </p>
            </div>
            <span className="toolbar__spacer" />
            <button className="button button--secondary" type="button" onClick={() => void resource.runAction("refresh-portfolio")}>
              刷新组合
            </button>
          </div>
          <div className="card-divider" />
          <div className="summary-list">
            <label className="field">
              <span className="field__label">定时执行时间</span>
              <input className="input" type="time" value={scheduleTime} onChange={(event) => setScheduleTime(event.target.value)} />
            </label>
            <label className="field">
              <span className="field__label">分析模式</span>
              <select className="input" value={analysisMode} onChange={(event) => setAnalysisMode(event.target.value)}>
                {SCHEDULE_MODE_OPTIONS.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            </label>
            <label className="field">
              <span className="field__label">并行线程数</span>
              <input
                className="input"
                disabled={analysisMode !== "parallel"}
                min={1}
                max={16}
                step={1}
                type="number"
                value={maxWorkers}
                onChange={(event) => setMaxWorkers(Number(event.target.value) || 1)}
              />
            </label>
            <label className="field" style={{ flexDirection: "row", alignItems: "center", gap: "10px" }}>
              <input type="checkbox" checked={autoSyncMonitor} onChange={(event) => setAutoSyncMonitor(event.target.checked)} />
              <span className="field__label" style={{ marginBottom: 0 }}>
                自动同步到监测
              </span>
            </label>
            <label className="field" style={{ flexDirection: "row", alignItems: "center", gap: "10px" }}>
              <input type="checkbox" checked={sendNotification} onChange={(event) => setSendNotification(event.target.checked)} />
              <span className="field__label" style={{ marginBottom: 0 }}>
                发送完成通知
              </span>
            </label>
          </div>
          <div className="card-divider" />
          <div className="toolbar toolbar--compact">
            <button
              className="button button--secondary"
              type="button"
              onClick={() =>
                void resource.runAction("schedule-save", {
                  scheduleTime,
                  analysisMode,
                  maxWorkers: analysisMode === "parallel" ? maxWorkers : 1,
                  autoSyncMonitor,
                  sendNotification,
                })
              }
            >
              保存调度
            </button>
            <button className="button button--secondary" type="button" onClick={() => void resource.runAction("schedule-start")}>
              启动调度
            </button>
            <button className="button button--secondary" type="button" onClick={() => void resource.runAction("schedule-stop")}>
              停止调度
            </button>
          </div>
        </WorkbenchCard>
        <div className="metric-grid">
          {snapshot.metrics.map((metric) => (
            <WorkbenchCard className="metric-card" key={metric.label}>
              <div className="metric-card__label">{metric.label}</div>
              <div className="metric-card__value">{metric.value}</div>
            </WorkbenchCard>
          ))}
        </div>
        <div className="section-grid">
          <WorkbenchCard>
            <h2 className="section-card__title">当前持仓</h2>
            {snapshot.holdings.rows.length === 0 ? (
              <SectionEmptyState
                title="当前没有持仓明细"
                description="当组合里出现新的持仓后，这里会自动回填代码、仓位、浮盈亏和建议动作。"
              />
            ) : null}
            <div className="table-shell">
              <table className="table">
                <thead>
                  <tr>
                    {snapshot.holdings.columns.map((column) => (
                      <th key={column}>{column}</th>
                    ))}
                    <th className="table__actions-head">操作</th>
                  </tr>
                </thead>
                <tbody>
                  {snapshot.holdings.rows.map((row) => (
                    <tr key={row.id}>
                      {row.cells.map((cell, index) => (
                        <td key={`${row.id}-${index}`} className={index === 0 ? "table__cell-strong" : undefined}>
                          {cell}
                        </td>
                      ))}
                      <td>
                        <div className="table__actions">
                          {row.actions?.map((action) => (
                            <button
                              key={`${row.id}-${action.label}`}
                              className="chip chip--active"
                              type="button"
                              onClick={() => void resource.runAction(action.action ?? "analyze", row.id)}
                            >
                              {action.icon ?? action.label}
                              <span>{action.label}</span>
                            </button>
                          ))}
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </WorkbenchCard>
          <WorkbenchCard>
            <h2 className="section-card__title">收益归因</h2>
            {snapshot.attribution.length === 0 ? (
              <SectionEmptyState
                title="收益归因暂无数据"
                description="等待新的持仓分析结果写回后，这里会展示盈利来源、回撤来源和风险协同。"
              />
            ) : (
              <div className="summary-list">
                {snapshot.attribution.map((item) => (
                  <div className="summary-item" key={item.title}>
                    <div className="summary-item__title">{item.title}</div>
                    <div className="summary-item__body">{item.body}</div>
                  </div>
                ))}
              </div>
            )}
            <div className="card-divider" />
            <h2 className="section-card__title" style={{ fontSize: "1.2rem" }}>
              组合曲线
            </h2>
            <Sparkline points={snapshot.curve} />
            <div className="card-divider" />
            <h2 className="section-card__title" style={{ fontSize: "1.2rem" }}>
              组合动作
            </h2>
            {snapshot.actions.length === 0 ? (
              <SectionEmptyState
                title="组合动作暂无数据"
                description="当前没有动作标签可展示，刷新组合或执行调度后会同步回填。"
              />
            ) : (
              <div className="chip-row">
                {snapshot.actions.map((action) => (
                  <span className="chip chip--active" key={action}>
                    {action}
                  </span>
                ))}
              </div>
            )}
          </WorkbenchCard>
        </div>
      </div>
    </div>
  );
}
