import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { apiClient, type ApiClient } from "../../lib/api-client";
import { PageHeader } from "../../components/ui/page-header";
import { WorkbenchCard } from "../../components/ui/workbench-card";
import { PageEmptyState, PageErrorState, PageLoadingState } from "../../components/ui/page-state";
import { usePageData } from "../../lib/use-page-data";
import { t } from "../../lib/i18n";

type PortfolioPageProps = {
  client?: ApiClient;
};

const PAGE_SIZE_OPTIONS = [20, 50, 100];

export function PortfolioPage({ client }: PortfolioPageProps) {
  const activeClient = client ?? apiClient;
  const resource = usePageData("portfolio", activeClient);
  const [tableSnapshot, setTableSnapshot] = useState<typeof resource.data | null>(null);
  const snapshot = tableSnapshot ?? resource.data;
  const navigate = useNavigate();
  const [query, setQuery] = useState("");
  const [pageSize, setPageSize] = useState(50);
  const [pageIndex, setPageIndex] = useState(0);
  const safePageSize = PAGE_SIZE_OPTIONS.includes(pageSize) ? pageSize : 50;
  const pageRows = snapshot?.holdings.rows ?? [];
  const totalRows = Number(snapshot?.holdings.pagination?.totalRows ?? pageRows.length);
  const totalPages = Math.max(1, Number(snapshot?.holdings.pagination?.totalPages ?? 1));
  const safePage = Math.min(Number(snapshot?.holdings.pagination?.page ?? pageIndex + 1) - 1, totalPages - 1);
  const currentPageSymbols = useMemo(
    () => pageRows.map((row) => (row.code ?? row.id ?? "").trim()).filter(Boolean),
    [pageRows],
  );
  const job = snapshot?.portfolioAnalysisJob ?? null;
  const marketNews = snapshot?.marketNews ?? [];

  useEffect(() => {
    if (!resource.data) return;
    let cancelled = false;
    void activeClient.getPageSnapshot("portfolio", {
      search: query.trim(),
      page: pageIndex + 1,
      pageSize: safePageSize,
    }).then((next) => {
      if (!cancelled) setTableSnapshot(next as typeof resource.data);
    }).catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [activeClient, pageIndex, query, resource.data, safePageSize]);

  useEffect(() => {
    if (!job?.id || !(job.status === "queued" || job.status === "running")) {
      return;
    }
    const timer = window.setInterval(async () => {
      try {
        const status = await activeClient.getTaskStatus<{
          id: string;
          status: string;
          stage?: string;
          progress?: number;
          message?: string;
        }>(job.id);
        if (status.status === "completed" || status.status === "failed") {
          await resource.refresh();
        }
      } catch {
        // ignore polling error
      }
    }, 3000);
    return () => window.clearInterval(timer);
  }, [activeClient, job?.id, job?.status, resource]);

  useEffect(() => {
    const timer = window.setInterval(() => {
      void resource.refresh();
    }, 5 * 60 * 1000);
    return () => window.clearInterval(timer);
  }, [resource.refresh]);

  if (resource.status === "loading" && !snapshot) {
    return <PageLoadingState title={t("持仓列表加载中")} description={t("正在读取全部持仓股票列表与组合状态。")} />;
  }

  if (resource.status === "error" && !snapshot) {
    return (
      <PageErrorState
        title={t("持仓列表加载失败")}
        description={resource.error ?? t("无法加载持仓列表。")}
        actionLabel={t("重试")}
        onAction={resource.refresh}
      />
    );
  }

  if (!snapshot) {
    return <PageEmptyState title={t("暂无持仓数据")} description={t("后台尚未返回持仓列表。")} actionLabel={t("刷新")} onAction={resource.refresh} />;
  }

  return (
    <div>
      <PageHeader eyebrow="Portfolio v2" title={t("持仓列表")} description={t("全面查看所有持仓股票，点击任意股票进入详情页。")} />
      <div className="stack">
        <WorkbenchCard>
          {job ? (
            <div className="summary-item" style={{ marginBottom: 12 }}>
              <div className="summary-item__title">{t("仓位分析任务")}</div>
              <div className="summary-item__body">
                {job.message || t("任务已提交")}（{job.status} / {job.stage || "-"} / {job.progress ?? 0}%）
              </div>
            </div>
          ) : null}
          <div className="summary-item summary-item--accent">
            <div className="summary-item__title">{t("组合仓位建议")}</div>
            <div className="summary-item__body">{snapshot.portfolioDecision?.summary ?? t("暂无组合级仓位建议。")}</div>
            <div className="chip-row" style={{ marginTop: 8 }}>
              <span className="chip chip--active">{t("建议动作：")}{snapshot.portfolioDecision?.action ?? "--"}</span>
              <span className="chip chip--active">{t("目标仓位：")}{snapshot.portfolioDecision?.targetExposurePct ?? "--"}</span>
            </div>
            <div className="summary-item__body" style={{ marginTop: 8 }}>
              {t("看多")}{snapshot.portfolioDecision?.bullishCount ?? 0} {t("/ 中性")}{snapshot.portfolioDecision?.neutralCount ?? 0} {t("/ 看空")}{snapshot.portfolioDecision?.bearishCount ?? 0}
            </div>
            <div className="summary-item__body">
              {typeof snapshot.portfolioDecision?.score === "number"
                ? t("综合得分 {v0}{v1}（按仓位和置信度加权）", { v0: snapshot.portfolioDecision.score >= 0 ? "+" : "", v1: snapshot.portfolioDecision.score.toFixed(2) })
                : t("综合得分 --")}
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

        <WorkbenchCard>
          <div className="toolbar">
            <label className="field" style={{ minWidth: 220 }}>
              <input
                className="input"
                data-size="compact-input"
                placeholder={t("按代码/名称/板块搜索")}
                value={query}
                onChange={(event) => {
                  setQuery(event.target.value);
                  setPageIndex(0);
                }}
              />
            </label>
            <label className="field" style={{ width: 120 }}>
              <select
                className="input"
                data-size="compact-select"
                value={safePageSize}
                onChange={(event) => {
                  setPageSize(Number(event.target.value) || 50);
                  setPageIndex(0);
                }}
              >
                {PAGE_SIZE_OPTIONS.map((size) => (
                  <option value={size} key={size}>
                    {size}{t("/页")}</option>
                ))}
              </select>
            </label>
            <span className="toolbar__spacer" />
            <button className="button button--secondary" type="button" onClick={() => void resource.runAction("refresh-portfolio")}>
              {t("刷新组合")}</button>
            <button
              className="button button--secondary"
              type="button"
              disabled={currentPageSymbols.length === 0}
              onClick={() =>
                void resource.runAction("refresh-indicators", {
                  symbols: currentPageSymbols,
                  scope: "indicators_only",
                })
              }
            >
              {t("刷新技术指标")}</button>
            <button className="button button--secondary" type="button" onClick={() => void resource.runAction("analyze", { mode: "parallel" })}>
              {t("实时分析仓位")}</button>
          </div>

          <div className="table-shell">
            <table className="table">
              <thead>
                <tr>
                  {snapshot.holdings.columns.map((column) => (
                    <th key={column}>{column}</th>
                  ))}
                  <th className="table__actions-head">{t("操作")}</th>
                </tr>
              </thead>
              <tbody>
                {pageRows.length === 0 ? (
                  <tr>
                    <td colSpan={snapshot.holdings.columns.length + 1} className="table__empty">
                      {snapshot.holdings.emptyLabel ?? t("暂无持仓")}
                    </td>
                  </tr>
                ) : (
                  pageRows.map((row) => {
                    const symbol = (row.code ?? row.id ?? "").trim();
                    return (
                      <tr className="portfolio-stock-row" key={row.id} onClick={() => navigate(`/portfolio/position/${encodeURIComponent(symbol)}`)}>
                        {row.cells.map((cell, index) => (
                          <td key={`${row.id}-${index}`} className={index === 0 ? "table__cell-strong" : undefined}>
                            {cell}
                          </td>
                        ))}
                        <td className="table__actions-cell">
                          <div className="table__actions">
                            <button
                              className="chip chip--active"
                              type="button"
                              onClick={(event) => {
                                event.stopPropagation();
                                navigate(`/portfolio/position/${encodeURIComponent(symbol)}`);
                              }}
                            >
                              {t("详情")}</button>
                            <button
                              className="chip chip--danger"
                              type="button"
                              onClick={(event) => {
                                event.stopPropagation();
                                if (!symbol) return;
                                if (!window.confirm(t("确认删除持仓 {v0} ?", { v0: symbol }))) return;
                                void resource.runAction("delete-position", { code: symbol });
                              }}
                            >
                              {t("删除")}</button>
                          </div>
                        </td>
                      </tr>
                    );
                  })
                )}
              </tbody>
            </table>
          </div>
          <div className="watchlist-pagination" style={{ marginTop: 12 }}>
            <div className="watchlist-pagination__summary">
              {t("共")}{totalRows} {t("条 · 第")}{safePage + 1} / {totalPages} {t("页")}</div>
            <div className="watchlist-pagination__controls">
              <button className="button button--secondary" type="button" disabled={safePage <= 0} onClick={() => setPageIndex((value) => Math.max(0, value - 1))}>
                {t("上一页")}</button>
              <button
                className="button button--secondary"
                type="button"
                disabled={safePage >= totalPages - 1}
                onClick={() => setPageIndex((value) => Math.min(totalPages - 1, value + 1))}
              >
                {t("下一页")}</button>
            </div>
          </div>
        </WorkbenchCard>

        <WorkbenchCard>
          <h2 className="section-card__title">{t("市场重点实时新闻")}</h2>
          <div className="summary-list">
            {marketNews.length === 0 ? (
              <div className="summary-item">
                <div className="summary-item__title">{t("暂无市场新闻")}</div>
                <div className="summary-item__body">{t("当前没有可展示的重点新闻。")}</div>
              </div>
            ) : (
              marketNews.map((item, index) => (
                <div className="summary-item" key={`${index}-${item.title}`}>
                  <div className="summary-item__title">{item.title}</div>
                  <div className="summary-item__body">{item.body}</div>
                  <div className="chip-row" style={{ marginTop: 8 }}>
                    <span className="badge badge--neutral">{item.source || "market"}</span>
                    <span className="badge badge--neutral">{item.time || "--"}</span>
                    {item.url ? (
                      <a className="badge badge--neutral" href={item.url} target="_blank" rel="noreferrer">
                        {t("原文")}</a>
                    ) : null}
                  </div>
                </div>
              ))
            )}
          </div>
        </WorkbenchCard>
      </div>
    </div>
  );
}
