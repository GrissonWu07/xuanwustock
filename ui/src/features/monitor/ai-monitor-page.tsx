import { useEffect, useMemo, useState } from "react";
import type { ApiClient } from "../../lib/api-client";
import { IconButton } from "../../components/ui/icon-button";
import { PageHeader } from "../../components/ui/page-header";
import { SectionEmptyState } from "../../components/ui/section-empty";
import { WorkbenchCard } from "../../components/ui/workbench-card";
import { PageEmptyState, PageErrorState, PageLoadingState } from "../../components/ui/page-state";
import type { AiMonitorSnapshot, TableAction, TableRow, TimelineItem } from "../../lib/page-models";
import { usePageData } from "../../lib/use-page-data";

type AiMonitorPageProps = {
  client?: ApiClient;
};

export function AiMonitorPage({ client }: AiMonitorPageProps) {
  const resource = usePageData("ai-monitor", client);
  const snapshot = resource.data;
  const [queueRows, setQueueRows] = useState<TableRow[] | null>(null);
  const [visibleSignals, setVisibleSignals] = useState<AiMonitorSnapshot["signals"] | null>(null);
  const [visibleTimeline, setVisibleTimeline] = useState<TimelineItem[] | null>(null);

  useEffect(() => {
    if (!snapshot) {
      return;
    }

    setQueueRows(snapshot.queue.rows);
    setVisibleSignals(snapshot.signals ?? []);
    setVisibleTimeline(snapshot.timeline ?? []);
  }, [snapshot]);

  const queueRowActions = useMemo<TableAction[]>(
    () => [
      { label: "分析", icon: "🔎", tone: "accent", action: "analyze" },
      { label: "删除", icon: "🗑", tone: "danger", action: "delete" },
    ],
    [],
  );

  const topActions = useMemo(
    () => [
      { label: "启动盯盘", action: "start", icon: "▶", tone: "accent" as const },
      { label: "停止盯盘", action: "stop", icon: "⏸", tone: "neutral" as const },
      { label: "立即分析", action: "analyze", icon: "🧠", tone: "accent" as const },
      {
        label: "清空队列",
        action: "delete",
        icon: "🧹",
        tone: "danger" as const,
      },
    ],
    [],
  );

  const handleTopAction = async (action: string) => {
    if (action === "delete") {
      setQueueRows([]);
    }
    if (action === "analyze") {
      setVisibleTimeline((current) => [
        { time: "现在", title: "盯盘分析", body: "已手动触发一次新的 AI 盯盘结论。" },
        ...(current ?? []),
      ]);
      setVisibleSignals((current) => [
        { title: "手动分析", body: "已触发 AI 盯盘的即时分析流程。", tags: ["分析", "最新"] },
        ...(current ?? []),
      ]);
    }
    await resource.runAction(action);
  };

  const handleQueueAction = async (rowId: string, action: string) => {
    if (action === "delete") {
      setQueueRows((current) => (current ?? []).filter((row) => row.id !== rowId));
    }
    if (action === "analyze") {
      setVisibleTimeline((current) => [
        { time: "现在", title: `${rowId} 分析`, body: `${rowId} 已进入 AI 盯盘分析队列。` },
        ...(current ?? []),
      ]);
      setVisibleSignals((current) => [
        { title: `${rowId} 复核`, body: `已对 ${rowId} 执行一次盯盘复核。`, tags: ["队列", "复核"] },
        ...(current ?? []),
      ]);
    }
    await resource.runAction(action, { id: rowId });
  };

  const renderQueueRows = queueRows ?? snapshot?.queue.rows ?? [];
  const renderSignals = visibleSignals ?? snapshot?.signals ?? [];
  const renderTimeline = visibleTimeline ?? snapshot?.timeline ?? [];

  if (resource.status === "loading" && !resource.data) {
    return <PageLoadingState title="AI盯盘加载中" description="正在读取盯盘队列、策略信号和事件时间线。" />;
  }

  if (resource.status === "error" && !resource.data) {
    return (
      <PageErrorState
        title="AI盯盘加载失败"
        description={resource.error ?? "无法加载 AI 盯盘数据，请稍后重试。"}
        actionLabel="重新加载"
        onAction={resource.refresh}
      />
    );
  }

  if (!snapshot) {
    return <PageEmptyState title="AI盯盘暂无数据" description="后台尚未返回 AI 盯盘快照。" actionLabel="刷新" onAction={resource.refresh} />;
  }

  return (
    <div>
      <PageHeader eyebrow="Monitor" title="AI盯盘" description="AI 盯盘、信号生成和自动决策都在这里统一查看与操作。" />
      <div className="stack">
        <WorkbenchCard>
          <h2 className="section-card__title">快照概览</h2>
          <p className="section-card__description">
            盯盘队列、策略信号和时间线共用同一份快照，动作触发后会在这里同步回写最新状态。
          </p>
          <div className="mini-metric-grid">
            <div className="mini-metric">
              <div className="mini-metric__label">快照更新时间</div>
              <div className="mini-metric__value">{snapshot.updatedAt}</div>
            </div>
            <div className="mini-metric">
              <div className="mini-metric__label">盯盘队列</div>
              <div className="mini-metric__value">{renderQueueRows.length}</div>
            </div>
            <div className="mini-metric">
              <div className="mini-metric__label">策略信号</div>
              <div className="mini-metric__value">{renderSignals.length}</div>
            </div>
          </div>
          <div className="card-divider" />
          <SectionEmptyState
            title="可用动作"
            description={snapshot.actions && snapshot.actions.length > 0 ? "这些动作直接对应 AI 盯盘的启动、停止和分析入口。" : "当前没有可用动作。"}
          >
            {snapshot.actions && snapshot.actions.length > 0 ? (
              snapshot.actions.map((action) => (
                <span className="badge badge--neutral" key={action}>
                  {action}
                </span>
              ))
            ) : (
              <span className="badge badge--neutral">暂无动作</span>
            )}
          </SectionEmptyState>
        </WorkbenchCard>

        <div className="metric-grid">
          {snapshot.metrics.map((metric) => (
            <WorkbenchCard className="metric-card" key={metric.label}>
              <div className="metric-card__label">{metric.label}</div>
              <div className="metric-card__value">{metric.value}</div>
            </WorkbenchCard>
          ))}
        </div>
        <WorkbenchCard>
          <div className="toolbar">
            <div>
              <h2 className="section-card__title">动作中心</h2>
              <p className="section-card__description" style={{ marginBottom: 0 }}>
                这里保留 AI 盯盘的真实动作入口，启动、停止、立即分析和清空队列都直接对应后端动作语义。
              </p>
            </div>
            <span className="toolbar__spacer" />
            <div className="chip-row">
              {topActions.map((item) => (
                <button
                  key={item.action}
                  className={item.tone === "accent" ? "button button--primary" : item.tone === "danger" ? "button button--secondary" : "button button--secondary"}
                  type="button"
                  onClick={() => void handleTopAction(item.action)}
                >
                  <span aria-hidden="true" style={{ marginRight: 8 }}>
                    {item.icon}
                  </span>
                  {item.label}
                </button>
              ))}
            </div>
          </div>
        </WorkbenchCard>
        <div className="section-grid">
          <WorkbenchCard>
            <h2 className="section-card__title">盯盘队列</h2>
            <div className="table-shell">
              <table className="table">
                <thead>
                  <tr>
                    {snapshot.queue.columns.map((column) => (
                      <th key={column}>{column}</th>
                    ))}
                    <th className="table__actions-head">操作</th>
                  </tr>
                </thead>
                <tbody>
                  {renderQueueRows.length === 0 ? (
                    <tr>
                      <td className="table__empty" colSpan={snapshot.queue.columns.length + 1}>
                        盯盘队列暂无数据
                      </td>
                    </tr>
                  ) : (
                    renderQueueRows.map((row) => (
                      <tr key={row.id}>
                        {row.cells.map((cell, index) => (
                          <td key={`${row.id}-${index}`} className={index === 0 ? "table__cell-strong" : undefined}>
                            {cell}
                          </td>
                        ))}
                        <td>
                          <div className="table__actions">
                            {(row.actions?.length ? row.actions : queueRowActions).map((action) => (
                              <IconButton
                                key={`${row.id}-${action.action ?? action.label}`}
                                icon={action.icon ?? action.label}
                                label={action.label}
                                tone={action.tone ?? "neutral"}
                                onClick={() => void handleQueueAction(row.id, action.action ?? action.label)}
                              />
                            ))}
                          </div>
                        </td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          </WorkbenchCard>
          <WorkbenchCard>
            <h2 className="section-card__title">策略信号</h2>
            {renderSignals.length === 0 ? (
              <SectionEmptyState title="策略信号暂无数据" description="当前没有可展示的策略信号，等待新的分析结果或手动触发分析。" />
            ) : (
              <div className="summary-list">
                {renderSignals.map((signal) => (
                  <div className="summary-item" key={signal.title}>
                    <div className="summary-item__title">{signal.title}</div>
                    <div className="summary-item__body">{signal.body}</div>
                    <div className="card-divider" />
                    <div className="chip-row">
                      {signal.tags.map((tag) => (
                        <span className="badge badge--neutral" key={tag}>
                          {tag}
                        </span>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </WorkbenchCard>
        </div>
        <WorkbenchCard>
          <h2 className="section-card__title">事件时间线</h2>
          {renderTimeline.length === 0 ? (
            <SectionEmptyState title="事件时间线暂无数据" description="当前没有新的盯盘事件，后续分析、启动或删除操作会继续追加到这里。" />
          ) : (
            <div className="timeline">
              {renderTimeline.map((item) => (
                <div className="timeline__item" key={`${item.time}-${item.title}`}>
                  <div className="timeline__time">{item.time}</div>
                  <div className="timeline__content">
                    <strong>{item.title}</strong> · {item.body}
                  </div>
                </div>
              ))}
            </div>
          )}
        </WorkbenchCard>
      </div>
    </div>
  );
}
