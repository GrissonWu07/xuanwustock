import { useEffect, useMemo, useRef, useState } from "react";
import { apiClient, type ApiClient } from "../../lib/api-client";
import { IconButton } from "../../components/ui/icon-button";
import { PageHeader } from "../../components/ui/page-header";
import { WorkbenchCard } from "../../components/ui/workbench-card";
import { PageEmptyState, PageErrorState, PageLoadingState } from "../../components/ui/page-state";
import { usePageData } from "../../lib/use-page-data";
import { useSelection } from "../../lib/use-selection";
import type { DiscoverSnapshot, WorkbenchSnapshot } from "../../lib/page-models";
import { t } from "../../lib/i18n";

type DiscoverPageProps = {
  client?: ApiClient;
};

const DECISION_FIELD_LABELS = [
  "Investment rating",
  "Target price",
  "Entry range",
  "Take-profit",
  "Stop-loss",
  "Holding period",
  "Position sizing",
  "Confidence",
] as const;

const escapeRegExp = (value: string) => value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

const DISCOVER_TEXT_ALIASES: Record<string, string> = {
  "净利增长": "Profit growth",
  "AI选股": "AI stock selection",
};

const localizeDiscoverText = (value: string | undefined) => {
  const source = (value ?? "").trim();
  if (!source) return "";
  const aggregateMatch = source.match(
    /^Aggregated latest results from\s+(\d+)\s+discovery strategies,\s+(\d+)\s+candidates in total,\s+latest update at\s+(.+)\.$/i,
  );
  if (aggregateMatch) {
    return t(
      "Aggregated latest results from {strategy_count} discovery strategies, {candidate_count} candidates in total, latest update at {updated_at}.",
      {
        strategy_count: Number.parseInt(aggregateMatch[1], 10) || aggregateMatch[1],
        candidate_count: Number.parseInt(aggregateMatch[2], 10) || aggregateMatch[2],
        updated_at: aggregateMatch[3],
      },
    );
  }
  const latestCandidatesMatch = source.match(/^⭐\s*Latest\s+(\d+)\s+candidates$/i);
  if (latestCandidatesMatch) {
    return t("⭐ Latest {count} candidates", {
      count: Number.parseInt(latestCandidatesMatch[1], 10) || latestCandidatesMatch[1],
    });
  }
  const strategyCountMatch = source.match(/^📌\s*(\d+)\s+strategies$/i);
  if (strategyCountMatch) {
    return t("📌 {count} strategies", {
      count: Number.parseInt(strategyCountMatch[1], 10) || strategyCountMatch[1],
    });
  }
  const normalizedKey = DISCOVER_TEXT_ALIASES[source] ?? source;
  const direct = t(normalizedKey);
  if (direct !== normalizedKey || normalizedKey !== source) {
    return direct;
  }
  let output = source;
  const tokenKeys = [
    "Main force selection",
    "Low price momentum",
    "Small cap",
    "Profit growth",
    "Value",
    "AI stock selection",
    "Main fund flow + financial filter + AI pick",
    "Low-price high-elasticity candidates",
    "Small but active growth candidates",
    "Earnings growth trend screening",
    "Valuation re-rating direction",
    "AI scanner sector-theme selection",
    "Top recommendations",
    "This section keeps priority targets after model aggregation, with single/batch add to watchlist.",
    "⭐ Add selected to watchlist",
    "⭐ Add single to watchlist",
  ];
  for (const token of tokenKeys) {
    output = output.replace(new RegExp(escapeRegExp(token), "g"), t(token));
  }
  output = output.replace(/Latest picks:\s*(\d+)/gi, (_, count) =>
    t("Latest picks: {count}", { count: Number.parseInt(count, 10) || count }),
  );
  return output;
};

const localizeDecisionText = (value: string) => {
  let output = value ?? "";
  for (const label of DECISION_FIELD_LABELS) {
    const pattern = new RegExp(`${escapeRegExp(label)}\\s*[:：]`, "gi");
    output = output.replace(pattern, `${t(label)}：`);
  }
  return output;
};

export function DiscoverPage({ client }: DiscoverPageProps) {
  const taskClient = client ?? apiClient;
  const resource = usePageData("discover", client);
  const [search, setSearch] = useState("");
  const [batching, setBatching] = useState(false);
  const [runningStrategy, setRunningStrategy] = useState(false);
  const [resettingList, setResettingList] = useState(false);
  const [runStrategySelection, setRunStrategySelection] = useState<string>("all");
  const [runFeedback, setRunFeedback] = useState<string>("");
  const [analysisFeedback, setAnalysisFeedback] = useState<string>("");
  const [analysisSnapshot, setAnalysisSnapshot] = useState<WorkbenchSnapshot["analysis"] | null>(null);
  const [analyzingCode, setAnalyzingCode] = useState<string>("");
  const [taskJob, setTaskJob] = useState<DiscoverSnapshot["taskJob"]>(null);
  const [currentPage, setCurrentPage] = useState(0);
  const selectAllRef = useRef<HTMLInputElement | null>(null);
  const analysisPanelRef = useRef<HTMLElement | null>(null);
  const pageSize = 6;

  const snapshot = resource.data;
  const runStrategyOptions = [
    { value: "all", label: t("All strategies") },
    { value: "main_force", label: t("Main force selection") },
    { value: "low_price_bull", label: t("Low price momentum") },
    { value: "small_cap", label: t("Small cap") },
    { value: "profit_growth", label: t("Profit growth") },
    { value: "value_stock", label: t("Value") },
    { value: "ai_scanner", label: t("AI stock selection") },
  ];
  const searchTerm = search.trim();
  const normalizedSearch = searchTerm.toLowerCase();
  const sourceRows = snapshot?.candidateTable.rows ?? [];
  const strategyBusy = Boolean(taskJob && ["queued", "running"].includes(taskJob.status));
  const candidateColumnsFromBackend = snapshot?.candidateTable.columns ?? [];
  const discoveredAtColumnKeys = new Set([t("Discovered at"), "Discovered at", "发现时间"]);
  const hasBackendSelectedAtColumn = candidateColumnsFromBackend.some((column) => discoveredAtColumnKeys.has(column));
  const getRowSelectedAt = (row: (typeof sourceRows)[number]) => {
    const rawSelectedAt = row.selectedAt;
    const rawLegacySelectedAt = (row as Record<string, unknown>).selected_at;
    if (typeof rawSelectedAt === "string" && rawSelectedAt.trim()) {
      return rawSelectedAt.trim();
    }
    if (typeof rawLegacySelectedAt === "string" && rawLegacySelectedAt.trim()) {
      return rawLegacySelectedAt.trim();
    }
    if (row.cells.length >= 9 && typeof row.cells[8] === "string" && row.cells[8].trim()) {
      return row.cells[8].trim();
    }
    return "";
  };
  const showSelectedAtColumn = sourceRows.length > 0 && !hasBackendSelectedAtColumn;
  const candidateColumns = useMemo(
    () => (showSelectedAtColumn ? [...candidateColumnsFromBackend, t("Discovered at")] : candidateColumnsFromBackend),
    [candidateColumnsFromBackend, showSelectedAtColumn],
  );
  const filteredRows = useMemo(
    () =>
      sourceRows.filter((row) => {
        const text = [
          row.id,
          row.reason ?? "",
          ...row.cells,
          getRowSelectedAt(row),
          ...(row.badges ?? []),
        ].join(" ").toLowerCase();
        return text.includes(normalizedSearch);
      }),
    [normalizedSearch, sourceRows],
  );
  const totalPages = Math.max(1, Math.ceil(filteredRows.length / pageSize));
  const visibleRows = useMemo(
    () => filteredRows.slice(currentPage * pageSize, currentPage * pageSize + pageSize),
    [currentPage, filteredRows],
  );
  const rowIds = useMemo(() => visibleRows.map((row) => row.id), [visibleRows]);
  const selection = useSelection(rowIds);
  const selectedRows = visibleRows.filter((row) => selection.isSelected(row.id));
  const selectedCodes = selectedRows.map((row) => row.id);
  const canBatchWatchlist = selectedCodes.length > 0;
  const discoverAnalystViews = analysisSnapshot?.analystViews ?? [];
  const discoverDecisionInsights = (analysisSnapshot?.insights ?? []).filter(
    (item) => !discoverAnalystViews.some((view) => view.title === item.title),
  );
  const selectionPreview = selectedRows.slice(0, 3);
  const selectedPreviewLabel =
    selection.selectedCount > 0
      ? t("{count} stocks selected. You can batch add them below.", { count: selection.selectedCount })
      : t("No candidate selected. Choose from {count} candidates and batch add.", { count: filteredRows.length });
  const candidateEmptyLabel = normalizedSearch
    ? t('No candidate matches "{keyword}"', { keyword: searchTerm })
    : snapshot?.candidateTable.emptyLabel
      ? t(snapshot.candidateTable.emptyLabel)
      : t("No candidate stocks");
  const candidateEmptyMessage =
    normalizedSearch && snapshot
      ? t("Try searching by code, name, industry, source, or reason.")
      : snapshot?.candidateTable.emptyMessage
        ? t(snapshot.candidateTable.emptyMessage)
        : undefined;
  const currentPageLabel = t("Page {current}/{total}", { current: Math.min(currentPage + 1, totalPages), total: totalPages });

  const handleBatchWatchlist = async () => {
    if (!canBatchWatchlist || batching) return;
    setBatching(true);
    try {
      await resource.runAction("batch-watchlist", { codes: selectedCodes });
      selection.clear();
      setRunFeedback(t("Added to watchlist"));
    } catch (error) {
      setRunFeedback(`${t("Failed")}: ${error instanceof Error ? error.message : String(error)}`);
    } finally {
      setBatching(false);
    }
  };

  const handleSingleWatchlist = async (code: string) => {
    try {
      await resource.runAction("item-watchlist", { code });
      setRunFeedback(t("Added to watchlist"));
    } catch (error) {
      setRunFeedback(`${t("Failed")}: ${error instanceof Error ? error.message : String(error)}`);
    }
  };

  const handleAnalyzeCandidate = async (code: string) => {
    if (analyzingCode) return;
    setAnalyzingCode(code);
    setAnalysisFeedback(t("Analyzing {code}...", { code }));
    try {
      const result = (await taskClient.runPageAction("workbench", "analysis", { stockCode: code })) as {
        analysis?: WorkbenchSnapshot["analysis"];
      };
      if (result.analysis) {
        setAnalysisSnapshot(result.analysis);
        setAnalysisFeedback(t("Analysis for {code} completed. Summary/indicators/decision are shown below.", { code }));
        window.requestAnimationFrame(() => {
          if (typeof analysisPanelRef.current?.scrollIntoView === "function") {
            analysisPanelRef.current.scrollIntoView({ behavior: "smooth", block: "start" });
          }
        });
      } else {
        setAnalysisFeedback(t("Analysis for {code} submitted but result is not returned yet.", { code }));
      }
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      setAnalysisFeedback(t("Stock analysis failed: {message}", { message }));
    } finally {
      setAnalyzingCode("");
    }
  };

  const handleRunStrategy = async () => {
    if (runningStrategy || strategyBusy || resettingList) return;
    setRunningStrategy(true);
    setRunFeedback(t("Submitting discover task..."));
    const runPayload: Record<string, unknown> = {};
    if (runStrategySelection !== "all") {
      runPayload.strategy = runStrategySelection;
    }
    const pollTask = async (taskId: string) => {
      for (let index = 0; index < 180; index += 1) {
        const latest = (await taskClient.getTaskStatus(taskId)) as DiscoverSnapshot["taskJob"];
        setTaskJob(latest);
        if (latest && ["completed", "failed"].includes(latest.status)) {
          await resource.refresh();
          return latest;
        }
        await new Promise((resolve) => {
          setTimeout(resolve, 1000);
        });
      }
      await resource.refresh();
      return null;
    };
    try {
      const result = await resource.runAction("run-strategy", runPayload);
      if (!result) {
        setRunFeedback(t("Discover task submission failed. Please retry."));
        return;
      }
      const taskId = result?.taskId;
      if (taskId) {
        const finished = await pollTask(taskId);
        if (finished?.status === "completed") {
          setRunFeedback((finished.message ? t(finished.message) : "") || t("Discover result updated. Candidates and summary refreshed."));
        } else if (finished?.status === "failed") {
          setRunFeedback(t("Discover task failed: {message}", { message: finished.message ? t(finished.message) : t("Please check task logs") }));
        } else {
          setRunFeedback(t("Discover task submitted and running in background."));
        }
      } else {
        setRunFeedback(t("Discover result updated. Candidates and summary refreshed."));
      }
    } finally {
      setRunningStrategy(false);
    }
  };

  const handleResetList = async () => {
    if (resettingList || runningStrategy || strategyBusy) return;
    setResettingList(true);
    try {
      await resource.runAction("reset-list");
      selection.clear();
      setSearch("");
      setCurrentPage(0);
      setRunFeedback(t("Discover list reset completed."));
    } finally {
      setResettingList(false);
    }
  };

  const currentSelectionSummary = selectionPreview.length
    ? selectionPreview.map((row) => `${row.cells[1] ?? row.id} · ${row.cells[0]} · ${row.cells[3] ?? row.source ?? t("Unknown source")}`)
    : [];

  useEffect(() => {
    if (selectAllRef.current) {
      selectAllRef.current.indeterminate = selection.someSelected;
    }
  }, [selection.someSelected]);

  useEffect(() => {
    setCurrentPage(0);
  }, [normalizedSearch]);

  useEffect(() => {
    setCurrentPage((current) => Math.min(current, totalPages - 1));
  }, [totalPages]);

  useEffect(() => {
    setTaskJob(snapshot?.taskJob ?? null);
  }, [snapshot?.taskJob]);

  useEffect(() => {
    const timer = window.setInterval(() => {
      void resource.refresh();
    }, 5 * 60 * 1000);
    return () => window.clearInterval(timer);
  }, [resource.refresh]);

  if (resource.status === "loading" && !snapshot) {
    return <PageLoadingState title={t("Discover loading...")} description={t("Loading strategies, candidate stocks, and recent recommendations.")} />;
  }

  if (resource.status === "error" && !snapshot) {
    return (
      <PageErrorState
        title={t("Discover failed to load")}
        description={resource.error ?? t("Unable to load discovery data. Please retry later.")}
        actionLabel={t("Refresh")}
        onAction={resource.refresh}
      />
    );
  }

  if (!snapshot) {
    return <PageEmptyState title={t("Discover has no data")} description={t("Backend has not returned a discovery snapshot yet.")} actionLabel={t("Refresh")} onAction={resource.refresh} />;
  }

  return (
    <div>
      <PageHeader
        eyebrow={t("Discover")}
        title={t("Discover")}
        description={localizeDiscoverText("Aggregate multiple selection strategies in one page and add outputs into watchlist.")}
        actions={
          <div className="table-toolbar-compact">
            <select
              className="input discover-strategy-select"
              style={{ minWidth: "180px" }}
              data-size="compact-select"
              value={runStrategySelection}
              onChange={(event) => setRunStrategySelection(event.target.value)}
              disabled={runningStrategy || strategyBusy || resettingList}
            >
              {runStrategyOptions.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
            <button className="button button--primary discover-run-button" type="button" onClick={() => void handleRunStrategy()} disabled={runningStrategy || strategyBusy || resettingList}>
              {runningStrategy || strategyBusy ? t("Running...") : t("Run strategy")}
            </button>
            <button className="button button--secondary discover-run-button" type="button" onClick={() => void handleResetList()} disabled={runningStrategy || strategyBusy || resettingList}>
              {resettingList ? t("Resetting...") : t("Reset list")}
            </button>
          </div>
        }
      />
      <div className="stack">
        <div className="metric-grid">
          {snapshot.metrics.map((metric) => (
            <WorkbenchCard className="metric-card" key={metric.label}>
              <div className="metric-card__label">{t(metric.label)}</div>
              <div className="metric-card__value">{metric.value}</div>
            </WorkbenchCard>
          ))}
        </div>

        <WorkbenchCard>
          <div className="toolbar">
            <div>
              <h2 className="section-card__title">{t("Discover strategy")}</h2>
              <p className="section-card__description" style={{ marginBottom: 0 }}>
                {localizeDiscoverText(snapshot.summary.title)}
              </p>
            </div>
            <span className="toolbar__spacer" />
            <div className="chip-row">
              {snapshot.strategies.map((strategy) => (
                <span className="badge badge--neutral" key={strategy.key || strategy.name}>
                  {localizeDiscoverText(strategy.name)} · {localizeDiscoverText(strategy.status)}
                </span>
              ))}
            </div>
          </div>
          <div className="section-grid section-grid--three" style={{ marginTop: "8px" }}>
            {snapshot.strategies.map((strategy) => (
              <div className="summary-item" key={strategy.key || strategy.name} style={{ padding: "12px 14px" }}>
                <div className="summary-item__title">{localizeDiscoverText(strategy.name)}</div>
                <div className="summary-item__body">{localizeDiscoverText(strategy.note)}</div>
                <div className="card-divider" />
                <div className="chip-row" style={{ gap: "4px", marginTop: "0" }}>
                  <span className="badge badge--neutral">{localizeDiscoverText(strategy.status)}</span>
                  {strategy.highlight ? <span className="badge badge--success">{localizeDiscoverText(strategy.highlight)}</span> : null}
                </div>
              </div>
            ))}
          </div>
        </WorkbenchCard>

        <WorkbenchCard>
          <div className="toolbar">
            <div>
              <h2 className="section-card__title" style={{ margin: 0 }}>
                {t("Candidate stocks")}
              </h2>
              <p className="table__caption" style={{ marginBottom: 0 }}>
                {localizeDiscoverText("Supports row-level analysis, batch add to watchlist, and preserving source strategy for follow-up quant flow.")}
              </p>
            </div>
          </div>
          <div className="discover-candidate-toolbar" data-testid="discover-candidate-toolbar">
            <div className="discover-candidate-toolbar__search-row">
              <span className="discover-candidate-toolbar__label">{t("Search candidate")}</span>
              <input
                className="input discover-candidate-toolbar__input"
                placeholder={t("Input code, name, industry, source, reason, or discovered time")}
                value={search}
                onChange={(event) => setSearch(event.target.value)}
              />
            </div>
            <span className="badge badge--neutral discover-candidate-toolbar__summary">
              {t("Selected / candidate {selected} / {total}", { selected: selection.selectedCount, total: filteredRows.length })}
            </span>
            <div className="discover-candidate-toolbar__actions">
              <IconButton icon="↻" label={t("Refresh discover result")} tone="neutral" onClick={() => void handleRunStrategy()} disabled={runningStrategy || strategyBusy || resettingList} />
              <IconButton icon="🗑" label={resettingList ? t("Resetting...") : t("Reset list")} tone="danger" onClick={() => void handleResetList()} disabled={runningStrategy || strategyBusy || resettingList} />
              <IconButton icon="✕" label={t("Clear selection")} tone="neutral" onClick={selection.clear} />
            </div>
          </div>
          {runFeedback ? <div className="discover-candidate-toolbar__feedback">{runFeedback}</div> : null}
          <div className="table-shell">
            <table className="table">
              <thead>
                <tr>
                  <th className="table__checkbox-cell">
                    <input
                      ref={selectAllRef}
                      type="checkbox"
                      aria-label={t("Select all current candidate stocks")}
                      checked={selection.allSelected}
                      onChange={selection.toggleAll}
                    />
                  </th>
                  {candidateColumns.map((column) => (
                    <th key={column}>{t(column)}</th>
                  ))}
                  <th className="table__actions-head">{t("Actions")}</th>
                </tr>
              </thead>
              <tbody>
                {filteredRows.length === 0 ? (
                  <tr>
                    <td className="table__empty" colSpan={candidateColumns.length + 2}>
                      <div className="summary-item">
                        <div className="summary-item__title">{candidateEmptyLabel}</div>
                        {candidateEmptyMessage ? <div className="summary-item__body">{candidateEmptyMessage}</div> : null}
                      </div>
                    </td>
                  </tr>
                ) : visibleRows.length === 0 ? (
                  <tr>
                    <td className="table__empty" colSpan={candidateColumns.length + 2}>
                      <div className="summary-item">
                        <div className="summary-item__title">{t("Current page has no candidate stocks")}</div>
                        <div className="summary-item__body">{t("You can switch page to view other candidates.")}</div>
                      </div>
                    </td>
                  </tr>
                ) : (
                  visibleRows.map((row) => (
                    <tr
                      key={row.id}
                      className={selection.isSelected(row.id) ? "table__row--selected" : undefined}
                      onClick={() => selection.toggle(row.id)}
                    >
                      <td className="table__checkbox-cell" onClick={(event) => event.stopPropagation()}>
                        <input
                          type="checkbox"
                          aria-label={t("Select {name}", { name: String(row.cells[1] ?? row.id) })}
                          checked={selection.isSelected(row.id)}
                          onChange={() => selection.toggle(row.id)}
                        />
                      </td>
                      {row.cells.map((cell, index) => (
                        <td key={`${row.id}-${index}`} className={index === 0 ? "table__cell-strong" : undefined}>
                          {typeof cell === "string" ? t(cell) : cell}
                        </td>
                      ))}
                          {showSelectedAtColumn ? (
                        <td key={`${row.id}-selected-at`}>
                          {getRowSelectedAt(row) || "-"}
                        </td>
                      ) : null}
                      <td>
                        <div className="table__actions">
                          <button
                            className="button button--secondary"
                            type="button"
                            onClick={(event) => {
                              event.stopPropagation();
                              void handleAnalyzeCandidate(row.id);
                            }}
                            disabled={analyzingCode === row.id}
                          >
                            <span aria-hidden="true">🔎</span>
                            <span>{analyzingCode === row.id ? t("Analyze in progress") : t("Analyze")}</span>
                          </button>
                          <button
                            className="button button--secondary"
                            type="button"
                            onClick={(event) => {
                              event.stopPropagation();
                              void handleSingleWatchlist(row.id);
                            }}
                          >
                            <span aria-hidden="true">{row.actions?.[0]?.icon ?? "⭐"}</span>
                            <span>{row.actions?.[0]?.label ? t(row.actions[0].label) : t("Add to watchlist")}</span>
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
          <div className="discover-candidate-footer" data-testid="discover-candidate-footer">
            <div className="discover-candidate-footer__left">
              {filteredRows.length > 0 ? (
                <>
                  <span className="toolbar__status">
                    {t("Current showing {start}-{end} / {total}", {
                      start: currentPage * pageSize + 1,
                      end: Math.min(filteredRows.length, currentPage * pageSize + visibleRows.length),
                      total: filteredRows.length,
                    })}
                  </span>
                </>
              ) : (
                <span className="toolbar__status">{t("No candidate stocks")}</span>
              )}
            </div>
            <span className="toolbar__status discover-candidate-footer__page">{currentPageLabel}</span>
            <div className="discover-candidate-footer__actions">
              <button className="button button--primary" type="button" onClick={() => void handleBatchWatchlist()} disabled={!canBatchWatchlist || batching}>
                {t("Add selected to watchlist")}
              </button>
              <button className="button button--secondary" type="button" onClick={() => setCurrentPage((current) => Math.max(0, current - 1))} disabled={currentPage === 0}>
                {t("Previous")}
              </button>
              <button
                className="button button--secondary"
                type="button"
                onClick={() => setCurrentPage((current) => Math.min(totalPages - 1, current + 1))}
                disabled={currentPage >= totalPages - 1}
              >
                {t("Next")}
              </button>
            </div>
          </div>
        </WorkbenchCard>

        <WorkbenchCard className="discover-analysis-panel discover-summary-panel" ref={analysisPanelRef}>
          <div className="toolbar toolbar--compact">
            <div>
              <h2 className="section-card__title" style={{ margin: 0 }}>
                {t("Stock analysis")}
              </h2>
              <p className="section-card__description" style={{ marginBottom: 0 }}>
                {t("After clicking analyze in candidate table, summary/indicators/decision/analyst views are shown here.")}
              </p>
            </div>
            <span className="toolbar__spacer" />
            {analysisSnapshot ? <span className="badge badge--neutral">{t("Analyze target {symbol}", { symbol: analysisSnapshot.symbol || t("Unknown") })}</span> : null}
          </div>
          {analysisFeedback ? <div className="discover-candidate-toolbar__feedback">{analysisFeedback}</div> : null}
          {analysisSnapshot ? (
            <>
              <div className="summary-list">
                <div className="summary-item summary-item--accent" style={{ padding: "12px 14px" }}>
                  <div className="summary-item__title">{t(analysisSnapshot.summaryTitle)}</div>
                  <div className="summary-item__body content-scroll">{analysisSnapshot.summaryBody}</div>
                  {analysisSnapshot.generatedAt ? <div className="summary-item__meta">{t("Generate time: {time}", { time: analysisSnapshot.generatedAt })}</div> : null}
                </div>
              </div>
              <div className="mini-metric-grid" style={{ marginTop: "12px" }}>
                {analysisSnapshot.indicators.map((indicator) => (
                  <div className="mini-metric" key={indicator.label}>
                    <div className="mini-metric__label">{t(indicator.label)}</div>
                    <div className="mini-metric__value">{indicator.value}</div>
                  </div>
                ))}
              </div>
              <div className="summary-list" style={{ marginTop: "12px" }}>
                <div className="summary-item" style={{ padding: "12px 14px" }}>
                  <div className="summary-item__title">{t("Final decision")}</div>
                  <div className="summary-item__body content-scroll">{localizeDecisionText(analysisSnapshot.finalDecisionText ?? analysisSnapshot.decision)}</div>
                </div>
              </div>
              {discoverDecisionInsights.length > 0 ? (
                <div className="summary-list" style={{ marginTop: "12px" }}>
                  {discoverDecisionInsights.map((insight) => (
                    <div className="summary-item" key={insight.title} style={{ padding: "12px 14px" }}>
                      <div className="summary-item__title">{t(insight.title)}</div>
                      <div className="summary-item__body content-scroll">{insight.body}</div>
                    </div>
                  ))}
                </div>
              ) : null}
              {discoverAnalystViews.length > 0 ? (
                <div className="summary-list" style={{ marginTop: "12px" }}>
                  {discoverAnalystViews.map((insight) => (
                    <div className="summary-item" key={insight.title} style={{ padding: "12px 14px" }}>
                      <div className="summary-item__title">{t(insight.title)}</div>
                      <div className="summary-item__body content-scroll">{insight.body}</div>
                    </div>
                  ))}
                </div>
              ) : null}
            </>
          ) : (
            <div className="summary-list">
              <div className="summary-item" style={{ padding: "12px 14px" }}>
                <div className="summary-item__title">{t("Waiting for analysis result")}</div>
                <div className="summary-item__body">
                  {t("After clicking analyze in candidate table, summary/indicators/decision/analyst views are shown here.")}
                </div>
              </div>
            </div>
          )}
        </WorkbenchCard>

        <div className="section-grid">
          <WorkbenchCard className="discover-summary-panel">
            <h2 className="section-card__title">{t("Latest result summary")}</h2>
            <p className="section-card__description">{localizeDiscoverText(snapshot.summary.body)}</p>
            <div className="summary-list">
              <div className="summary-item" style={{ padding: "12px 14px" }}>
                <div className="summary-item__title">{localizeDiscoverText(snapshot.recommendation.title)}</div>
                <div className="summary-item__body">{localizeDiscoverText(snapshot.recommendation.body)}</div>
              </div>
            </div>
            <div className="chip-row" style={{ gap: "4px" }}>
              {snapshot.recommendation.chips.map((chip) => (
                <span className="chip chip--active" key={chip}>
                  {localizeDiscoverText(chip)}
                </span>
              ))}
            </div>
            <div className="card-divider" />
            <div className="summary-item__body">{t("Snapshot updated at: {time}", { time: snapshot.updatedAt })}</div>
          </WorkbenchCard>
          <WorkbenchCard className="discover-summary-panel">
            <h2 className="section-card__title">{t("Current selection")}</h2>
            <p className="section-card__description">{t("Select rows to batch add to watchlist; single-row actions still work in table.")}</p>
            <div className="summary-list">
              <div className="summary-item" style={{ padding: "12px 14px" }}>
                <div className="summary-item__title">{t("Current selection summary")}</div>
                <div className="summary-item__body">{selectedPreviewLabel}</div>
                <div className="summary-item__body" style={{ marginTop: "4px" }}>
                  {t("To inspect a single stock first, use the row-level analyze action on the right.")}
                </div>
                {currentSelectionSummary.length > 0 ? (
                  <div className="chip-row" style={{ marginTop: "8px", gap: "4px" }}>
                    {currentSelectionSummary.map((item) => (
                      <span className="badge badge--neutral" key={item}>
                        {item}
                      </span>
                    ))}
                  </div>
                ) : null}
              </div>
            </div>
          </WorkbenchCard>
        </div>
      </div>
    </div>
  );
}
