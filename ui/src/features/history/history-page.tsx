import { useEffect, useState } from "react";
import type { ApiClient } from "../../lib/api-client";
import { apiClient } from "../../lib/api-client";
import { PageHeader } from "../../components/ui/page-header";
import { Sparkline } from "../../components/ui/sparkline";
import { SectionEmptyState } from "../../components/ui/section-empty";
import { WorkbenchCard } from "../../components/ui/workbench-card";
import { PageEmptyState, PageErrorState, PageLoadingState } from "../../components/ui/page-state";
import { usePageData } from "../../lib/use-page-data";

type HistoryPageProps = {
  client?: ApiClient;
};

export function HistoryPage({ client }: HistoryPageProps) {
  const resource = usePageData("history", client);
  const activeClient = client ?? apiClient;
  const [tableSnapshot, setTableSnapshot] = useState<typeof resource.data | null>(null);
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  const pageSize = 50;
  const snapshot = tableSnapshot ?? resource.data;

  useEffect(() => {
    setTableSnapshot(resource.data ?? null);
  }, [resource.data]);

  useEffect(() => {
    if (!resource.data) return;
    void activeClient
      .getPageSnapshot("history", { search: search.trim(), page, pageSize })
      .then((next) => setTableSnapshot(next as typeof resource.data))
      .catch(() => undefined);
  }, [activeClient, page, pageSize, resource.data, search]);

  if (resource.status === "loading" && !resource.data) {
    return <PageLoadingState title="历史记录加载中" description="正在读取分析记录、回放结果和操作轨迹。" />;
  }

  if (resource.status === "error" && !resource.data) {
    return (
      <PageErrorState
        title="历史记录加载失败"
        description={resource.error ?? "无法加载历史记录数据，请稍后重试。"}
        actionLabel="重新加载"
        onAction={resource.refresh}
      />
    );
  }

  if (!snapshot) {
    return <PageEmptyState title="历史记录暂无数据" description="后台尚未返回历史记录快照。" actionLabel="刷新" onAction={resource.refresh} />;
  }

  const curve = snapshot.curve ?? [];
  const hasRecords = snapshot.records.rows.length > 0;
  const totalRows = Number(snapshot.records.pagination?.totalRows ?? snapshot.records.rows.length);
  const totalPages = Math.max(1, Number(snapshot.records.pagination?.totalPages ?? 1));
  const currentPage = Math.min(Number(snapshot.records.pagination?.page ?? page), totalPages);

  return (
    <div>
      <PageHeader eyebrow="History" title="历史记录" description="分析记录、历史回放、工作流轨迹都会在这里统一沉淀，方便后续复盘。" />
      <div className="stack">
        <WorkbenchCard>
          <h2 className="section-card__title">快照概览</h2>
          <p className="section-card__description">
            历史记录、回放概况和时间线由同一份快照提供，刷新后会统一同步最新的分析轨迹。
          </p>
          <div className="mini-metric-grid">
            <div className="mini-metric">
              <div className="mini-metric__label">快照更新时间</div>
              <div className="mini-metric__value">{snapshot.updatedAt}</div>
            </div>
            <div className="mini-metric">
              <div className="mini-metric__label">分析记录</div>
              <div className="mini-metric__value">{snapshot.records.rows.length}</div>
            </div>
            <div className="mini-metric">
              <div className="mini-metric__label">工作流轨迹</div>
              <div className="mini-metric__value">{snapshot.timeline.length}</div>
            </div>
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
            <div className="toolbar">
              <div>
                <h2 className="section-card__title">分析记录</h2>
                <p className="section-card__description" style={{ marginBottom: 0 }}>
                  所有单股分析、量化模拟和回放结果都会保存在这里，便于统一回看。
                </p>
              </div>
              <span className="toolbar__spacer" />
              <input
                className="input input--compact"
                value={search}
                onChange={(event) => {
                  setSearch(event.target.value);
                  setPage(1);
                }}
                placeholder="按代码/名称/模式/结论搜索"
                style={{ maxWidth: 260 }}
              />
              <button className="button button--secondary" type="button" onClick={() => resource.runAction("rerun")}>
                重新整理
              </button>
            </div>
            {!hasRecords ? (
              <SectionEmptyState title="分析记录暂无数据" description="当前没有可展示的分析记录，稍后可点击重新整理或等待新的结果写入。" />
            ) : null}
            <div className="table-shell">
              <table className="table">
                <thead>
                  <tr>
                    {snapshot.records.columns.map((column) => (
                      <th key={column}>{column}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {hasRecords ? (
                    snapshot.records.rows.map((row) => (
                      <tr key={row.id}>
                        {row.cells.map((cell, index) => (
                          <td key={`${row.id}-${index}`} className={index === 0 ? "table__cell-strong" : undefined}>
                            {cell}
                          </td>
                        ))}
                      </tr>
                    ))
                  ) : (
                    <tr>
                      <td className="table__empty" colSpan={snapshot.records.columns.length}>
                        暂无记录
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
            <div className="toolbar toolbar--compact" style={{ marginTop: 12 }}>
              <span className="toolbar__status">DB筛选 {totalRows} 条 · 第 {currentPage} / {totalPages} 页</span>
              <span className="toolbar__spacer" />
              <button className="button button--secondary" type="button" disabled={currentPage <= 1} onClick={() => setPage((value) => Math.max(1, value - 1))}>
                上一页
              </button>
              <button className="button button--secondary" type="button" disabled={currentPage >= totalPages} onClick={() => setPage((value) => Math.min(totalPages, value + 1))}>
                下一页
              </button>
            </div>
          </WorkbenchCard>

          <WorkbenchCard>
            <h2 className="section-card__title">最近回放</h2>
            <div className="summary-item summary-item--accent">
              <div className="summary-item__title">{snapshot.recentReplay.title}</div>
              <div className="summary-item__body">{snapshot.recentReplay.body}</div>
            </div>
            <div className="chip-row" style={{ marginTop: "12px" }}>
              {snapshot.recentReplay.tags.map((tag) => (
                <span className="badge badge--neutral" key={tag}>
                  {tag}
                </span>
              ))}
            </div>
            <div className="card-divider" />
            <h2 className="section-card__title" style={{ fontSize: "1.2rem" }}>
              时间曲线
            </h2>
            <Sparkline points={curve} />
          </WorkbenchCard>
        </div>

          <WorkbenchCard>
            <h2 className="section-card__title">工作流轨迹</h2>
            {snapshot.timeline.length === 0 ? (
              <SectionEmptyState title="工作流轨迹暂无数据" description="当分析、回放或整理动作写回后，这里会继续展示时间线。" />
            ) : (
              <div className="timeline">
              {snapshot.timeline.map((item) => (
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
