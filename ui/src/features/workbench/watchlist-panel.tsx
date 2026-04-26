import { useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { IconButton } from "../../components/ui/icon-button";
import { WorkbenchCard } from "../../components/ui/workbench-card";
import type { TableRow, TableSection } from "../../lib/page-models";
import { useCompactLayout } from "../../lib/use-compact-layout";
import { useSelection } from "../../lib/use-selection";
import { t } from "../../lib/i18n";

type WatchlistPanelProps = {
  watchlist: TableSection;
  onAddWatchlist: (code: string) => Promise<void> | void;
  onRefresh: (codes: string[]) => void;
  onBatchQuant: (codes: string[]) => void;
  onBatchRemoveWatchlist: (codes: string[]) => void;
  onBatchPortfolio: (codes: string[], options?: { costPrice?: string; quantity?: string }) => Promise<void> | void;
  onClearSelection: () => void;
  onTableQueryChange?: (query: { search: string; page: number; pageSize: number }) => void;
};

const panelStyle: React.CSSProperties = {
  display: "grid",
  gap: "16px",
};

const PAGE_SIZE = 20;
const MAX_VISIBLE_PAGE_BUTTONS = 10;

const buildVisiblePageItems = (currentPage: number, pageCount: number): Array<number | "ellipsis-start" | "ellipsis-end"> => {
  if (pageCount <= MAX_VISIBLE_PAGE_BUTTONS) {
    return Array.from({ length: pageCount }, (_, index) => index + 1);
  }

  const halfWindow = Math.floor(MAX_VISIBLE_PAGE_BUTTONS / 2);
  let start = Math.max(1, currentPage - halfWindow);
  let end = start + MAX_VISIBLE_PAGE_BUTTONS - 1;
  if (end > pageCount) {
    end = pageCount;
    start = Math.max(1, end - MAX_VISIBLE_PAGE_BUTTONS + 1);
  }

  const pages: Array<number | "ellipsis-start" | "ellipsis-end"> = [];
  if (start > 1) {
    pages.push("ellipsis-start");
  }
  for (let pageNumber = start; pageNumber <= end; pageNumber += 1) {
    pages.push(pageNumber);
  }
  if (end < pageCount) {
    pages.push("ellipsis-end");
  }
  return pages;
};

const workflowBadgeTone = (label: string) => {
  if (/缺失|待补|待刷新|过期|待分析|失败|refresh|missing|pending/i.test(label)) return "warning";
  if (/持仓|量化|正常|BUY|买入|success|ok|pool/i.test(label)) return "success";
  return "neutral";
};

const signalBadgeTone = (label: string) => {
  const normalized = label.trim().toUpperCase();
  if (normalized === "BUY" || normalized.includes("买入")) return "success";
  if (normalized === "SELL" || normalized.includes("卖出")) return "danger";
  if (normalized === "HOLD" || normalized.includes("持有")) return "neutral";
  return "warning";
};

const isLegacySourceColumn = (column: unknown) => {
  const normalized = String(column ?? "").trim().toLowerCase();
  return normalized === "source" || normalized === "来源";
};

export function WatchlistPanel({
  watchlist,
  onAddWatchlist,
  onRefresh,
  onBatchQuant,
  onBatchRemoveWatchlist,
  onBatchPortfolio,
  onClearSelection,
  onTableQueryChange,
}: WatchlistPanelProps) {
  const isCompactLayout = useCompactLayout();
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  const [inlineAddOpen, setInlineAddOpen] = useState(false);
  const [inlineCode, setInlineCode] = useState("");
  const [inlineSaving, setInlineSaving] = useState(false);
  const [inlineError, setInlineError] = useState("");
  const [portfolioDialogOpen, setPortfolioDialogOpen] = useState(false);
  const [portfolioCostPrice, setPortfolioCostPrice] = useState("");
  const [portfolioQuantity, setPortfolioQuantity] = useState("");
  const [portfolioSaving, setPortfolioSaving] = useState(false);
  const [expandedRows, setExpandedRows] = useState<string[]>([]);
  const normalizedSearch = search.trim();
  const pageCount = Math.max(1, Number(watchlist.pagination?.totalPages ?? 1));
  const currentPage = Math.min(Number(watchlist.pagination?.page ?? page), pageCount);
  const totalRows = Number(watchlist.pagination?.totalRows ?? watchlist.rows.length);
  const visiblePageItems = useMemo(() => buildVisiblePageItems(currentPage, pageCount), [currentPage, pageCount]);
  const sourceColumnIndex = useMemo(() => watchlist.columns.findIndex(isLegacySourceColumn), [watchlist.columns]);
  const displayColumns = useMemo(
    () => (sourceColumnIndex >= 0 ? watchlist.columns.filter((_, index) => index !== sourceColumnIndex) : watchlist.columns),
    [sourceColumnIndex, watchlist.columns],
  );
  const pageRows = useMemo(
    () =>
      sourceColumnIndex >= 0
        ? watchlist.rows.map((row) => ({
            ...row,
            cells: row.cells.filter((_, index) => index !== sourceColumnIndex),
          }))
        : watchlist.rows,
    [sourceColumnIndex, watchlist.rows],
  );
  const rowIds = useMemo(() => pageRows.map((row) => row.id), [pageRows]);
  const selection = useSelection(rowIds);
  const selectAllRef = useRef<HTMLInputElement | null>(null);
  const renderStockCodeLink = (row: TableRow) => {
    const code = String(row.code ?? row.id ?? row.cells[0] ?? "").trim();
    const label = typeof row.cells[0] === "string" ? row.cells[0] : code;
    if (!code) {
      return typeof label === "string" ? t(label) : label;
    }
    return (
      <Link
        className="table-link"
        to={`/portfolio/position/${encodeURIComponent(code)}`}
        onClick={(event) => event.stopPropagation()}
      >
        {typeof label === "string" ? t(label) : label}
      </Link>
    );
  };

  const renderWorkflowCell = (row: TableRow, fallback: string | undefined) => {
    const badges = Array.isArray(row.workflowBadges) && row.workflowBadges.length > 0 ? row.workflowBadges : [];
    if (badges.length === 0) {
      return fallback ? t(fallback) : "-";
    }
    return (
      <div className="watchlist-workflow-badges">
        {badges.map((badge) => (
          <span className={`badge badge--${workflowBadgeTone(badge)} watchlist-workflow-badge`} key={`${row.id}-${badge}`}>
            {t(badge)}
          </span>
        ))}
      </div>
    );
  };

  const renderCell = (row: TableRow, cell: string, index: number) => {
    if (index === 0) {
      return renderStockCodeLink(row);
    }
    if (index === 4) {
      return <span className={`badge badge--${row.analysisTone || "neutral"} watchlist-analysis-badge`}>{t(cell)}</span>;
    }
    if (index === 5) {
      return <span className={`badge badge--${signalBadgeTone(row.signalStatus || cell)} watchlist-signal-badge`}>{t(row.signalStatus || cell)}</span>;
    }
    if (index === 6) {
      return renderWorkflowCell(row, cell);
    }
    return typeof cell === "string" ? t(cell) : cell;
  };

  useEffect(() => {
    if (selectAllRef.current) {
      selectAllRef.current.indeterminate = selection.someSelected;
    }
  }, [selection.someSelected]);

  useEffect(() => {
    setPage(1);
  }, [normalizedSearch]);

  useEffect(() => {
    setPage((current) => Math.min(current, pageCount));
  }, [pageCount]);

  useEffect(() => {
    onTableQueryChange?.({ search: normalizedSearch, page, pageSize: PAGE_SIZE });
  }, [normalizedSearch, onTableQueryChange, page]);

  const selectedCodes = selection.selectedIds;
  const selectedRows = pageRows.filter((row) => selectedCodes.includes(row.id));

  const resolveRowPrice = (row: (typeof selectedRows)[number] | undefined): string => {
    if (!row) return "";
    const fromField = String(row.latestPrice ?? "").trim();
    const fromCell = String(row.cells?.[2] ?? "").trim();
    const raw = fromField || fromCell;
    const normalized = raw.replace(/[^\d.-]/g, "");
    if (!normalized) return "";
    const value = Number(normalized);
    if (!Number.isFinite(value)) return "";
    return value.toFixed(2);
  };

  const handleBatchQuant = () => {
    if (selectedCodes.length > 0) {
      onBatchQuant(selectedCodes);
    }
  };

  const handleBatchDelete = () => {
    if (selectedCodes.length > 0) {
      onBatchRemoveWatchlist(selectedCodes);
      selection.clear();
    }
  };

  const handleRefresh = () => {
    const targetCodes = (selectedCodes.length > 0 ? selectedCodes : pageRows.map((row) => row.id)).filter(Boolean);
    if (targetCodes.length === 0) return;
    onRefresh(targetCodes);
  };

  const toggleExpandedRow = (rowId: string) => {
    setExpandedRows((current) => {
      const exists = current.includes(rowId);
      return exists ? current.filter((item) => item !== rowId) : [...current, rowId];
    });
  };

  const submitInlineAdd = async () => {
    if (inlineSaving) return;
    const value = inlineCode.trim();
    if (!value) return;
    setInlineSaving(true);
    setInlineError("");
    try {
      await Promise.resolve(onAddWatchlist(value));
      setInlineAddOpen(false);
      setInlineCode("");
    } catch (error) {
      const message = error instanceof Error ? error.message : t("Invalid stock code");
      setInlineError(message || t("Invalid stock code"));
    } finally {
      setInlineSaving(false);
    }
  };

  return (
    <WorkbenchCard>
      <div style={panelStyle}>
        <div>
          <h2 className="section-card__title">{t("My watchlist")}</h2>
        </div>

        <div className="watchlist-toolbar" data-testid="watchlist-toolbar">
          <div className="watchlist-toolbar__cluster" data-testid="watchlist-toolbar-cluster">
            <div className="watchlist-toolbar__actions" data-testid="watchlist-toolbar-actions">
              <input
                className="input"
                aria-label={t("Search")}
                placeholder={t("Search")}
                value={search}
                onChange={(event) => setSearch(event.target.value)}
                style={{ width: "220px", minWidth: "180px", height: "40px" }}
                data-size="compact-input"
              />
              <IconButton
                icon="+"
                label={t("Inline add")}
                tone="neutral"
                onClick={() => {
                  setInlineAddOpen(true);
                  setInlineError("");
                }}
              />
              <IconButton icon="↻" label={t("Refresh stock info")} tone="neutral" onClick={handleRefresh} />
              <IconButton
                icon="🧪"
                label={t("Add to quant candidates")}
                tone="accent"
                onClick={handleBatchQuant}
                disabled={selectedCodes.length === 0}
              />
              <IconButton
                icon="🗑"
                label={t("Delete selected")}
                tone="danger"
                onClick={handleBatchDelete}
                disabled={selectedCodes.length === 0}
              />
              <button
                className="button button--secondary"
                type="button"
                onClick={() => {
                  setPortfolioDialogOpen(true);
                  setPortfolioCostPrice(selectedRows.length === 1 ? resolveRowPrice(selectedRows[0]) : "");
                  setPortfolioQuantity("100");
                }}
                disabled={selectedCodes.length === 0}
                style={{ minHeight: "38px", padding: "0 12px" }}
              >
                {t("Register holdings")}
              </button>
              <IconButton
                icon="✕"
                label={t("Clear selection")}
                tone="neutral"
                onClick={() => {
                  selection.clear();
                  onClearSelection();
                }}
              />
            </div>
            <div className="watchlist-toolbar__status" data-testid="watchlist-toolbar-status">
              <span className="watchlist-toolbar__count">{t("Selected {count} stocks", { count: selectedCodes.length })}</span>
            </div>
          </div>
        </div>
        {portfolioDialogOpen ? (
          <div className="summary-item">
            <div className="summary-item__title">{t("Register holdings")}</div>
            <div className="summary-item__body">{t("Fill cost price and quantity for selected stocks.")}</div>
            <div className="section-grid" style={{ marginTop: 10 }}>
              <label className="field">
                <span className="field__label">{t("Cost price")}</span>
                <input
                  className="input"
                  type="number"
                  min={0}
                  step="0.01"
                  value={portfolioCostPrice}
                  onChange={(event) => setPortfolioCostPrice(event.target.value)}
                  placeholder={t("Current price")}
                />
              </label>
              <label className="field">
                <span className="field__label">{t("Quantity")}</span>
                <input
                  className="input"
                  type="number"
                  min={100}
                  step={100}
                  value={portfolioQuantity}
                  onChange={(event) => setPortfolioQuantity(event.target.value)}
                  placeholder="100"
                />
              </label>
            </div>
            <div className="toolbar toolbar--compact" style={{ marginTop: 10 }}>
              <button
                className="button button--secondary"
                type="button"
                disabled={portfolioSaving || selectedCodes.length === 0}
                onClick={async () => {
                  setPortfolioSaving(true);
                  try {
                    const normalizedQuantity = Math.max(100, Number(portfolioQuantity || 100) || 100);
                    await Promise.resolve(
                      onBatchPortfolio(selectedCodes, {
                        costPrice: portfolioCostPrice.trim(),
                        quantity: String(normalizedQuantity),
                      }),
                    );
                    setPortfolioDialogOpen(false);
                    setPortfolioCostPrice("");
                    setPortfolioQuantity("100");
                  } finally {
                    setPortfolioSaving(false);
                  }
                }}
              >
                {portfolioSaving ? t("Submitting...") : t("Confirm registration")}
              </button>
              <button
                className="button button--secondary"
                type="button"
                disabled={portfolioSaving}
                onClick={() => {
                  setPortfolioDialogOpen(false);
                  setPortfolioCostPrice("");
                  setPortfolioQuantity("100");
                }}
              >
                {t("Cancel")}
              </button>
            </div>
          </div>
        ) : null}

        <div className="table-shell watchlist-table-shell">
          <div className="watchlist-table__viewport">
            <table className="table watchlist-table" data-testid="watchlist-table">
            {!isCompactLayout ? (
              <colgroup>
                <col className="watchlist-table__col watchlist-table__col--checkbox" />
                <col className="watchlist-table__col watchlist-table__col--code" />
                <col className="watchlist-table__col watchlist-table__col--name" />
                <col className="watchlist-table__col watchlist-table__col--quote" />
                <col className="watchlist-table__col watchlist-table__col--sector" />
                <col className="watchlist-table__col watchlist-table__col--analysis" />
                <col className="watchlist-table__col watchlist-table__col--signal" />
                <col className="watchlist-table__col watchlist-table__col--workflow" />
                <col className="watchlist-table__col watchlist-table__col--updated" />
              </colgroup>
            ) : null}
            <thead>
              <tr>
                <th className="table__checkbox-cell">
                  <input
                    ref={selectAllRef}
                    type="checkbox"
                    aria-label={t("Select all current watchlist stocks")}
                    checked={selection.allSelected}
                    onChange={selection.toggleAll}
                  />
                </th>
                {isCompactLayout ? (
                  <>
                    <th>{t(String(watchlist.columns[0] ?? "Code"))}</th>
                    <th>{t(String(watchlist.columns[1] ?? "Name"))}</th>
                    <th>{t(String(watchlist.columns[4] ?? "Analysis"))}</th>
                    <th className="table__compact-actions-head">{t("Detail")}</th>
                  </>
                ) : (
                  displayColumns.map((column) => <th key={column}>{t(column)}</th>)
                )}
              </tr>
            </thead>
            <tbody>
                {inlineAddOpen ? (
                  <tr className="table__row--selected">
                    <td className="table__checkbox-cell" />
                    <td colSpan={isCompactLayout ? 4 : displayColumns.length}>
                      <div className="watchlist-inline-add">
                        <input
                          className="input"
                          autoFocus
                          value={inlineCode}
                          placeholder={t("Stock code")}
                          onChange={(event) => setInlineCode(event.target.value)}
                          onKeyDown={(event) => {
                            if (event.key === "Enter") {
                              event.preventDefault();
                              void submitInlineAdd();
                            }
                            if (event.key === "Escape") {
                              event.preventDefault();
                              setInlineAddOpen(false);
                              setInlineCode("");
                              setInlineError("");
                            }
                          }}
                        />
                        <IconButton
                          icon="✓"
                          label={t("Add")}
                          tone="accent"
                          disabled={inlineSaving || !inlineCode.trim()}
                          onClick={(event) => {
                            event.stopPropagation();
                            void submitInlineAdd();
                          }}
                        />
                        <IconButton
                          icon="✕"
                          label={t("Cancel")}
                          tone="neutral"
                          disabled={inlineSaving}
                          onClick={(event) => {
                            event.stopPropagation();
                            setInlineAddOpen(false);
                            setInlineCode("");
                            setInlineError("");
                          }}
                        />
                      </div>
                    </td>
                  </tr>
                ) : null}
                {pageRows.length === 0 ? (
                <tr>
                  <td className="table__empty" colSpan={(isCompactLayout ? 5 : displayColumns.length + 1)}>
                    {pageRows.length === 0
                      ? (watchlist.emptyLabel ? t(watchlist.emptyLabel) : t("My watchlist is empty"))
                      : t("Current page has no stocks. Switch page or adjust search.")}
                  </td>
                </tr>
              ) : (
                isCompactLayout
                  ? pageRows.flatMap((row) => {
                      const isSelected = selection.isSelected(row.id);
                      const isExpanded = expandedRows.includes(row.id);
                      const compactMainRow = (
                        <tr
                          key={`${row.id}-main`}
                          className={isSelected ? "table__row--selected table__compact-main-row" : "table__compact-main-row"}
                          onClick={() => selection.toggle(row.id)}
                          style={{ cursor: "pointer" }}
                        >
                          <td className="table__checkbox-cell">
                            <input
                              type="checkbox"
                              aria-label={t("Select {name}", { name: String(row.cells[1] ?? row.id) })}
                              checked={isSelected}
                              onClick={(event) => event.stopPropagation()}
                              onChange={() => selection.toggle(row.id)}
                            />
                          </td>
                          <td className="table__cell-strong">{renderStockCodeLink(row)}</td>
                          <td>{typeof row.cells[1] === "string" ? t(String(row.cells[1])) : row.cells[1]}</td>
                          <td>{renderCell(row, String(row.cells[4] ?? "-"), 4)}</td>
                          <td className="table__compact-control-cell">
                            <button
                              className="button button--secondary button--small table__expand-button"
                              type="button"
                              aria-expanded={isExpanded}
                              onClick={(event) => {
                                event.stopPropagation();
                                toggleExpandedRow(row.id);
                              }}
                            >
                              {isExpanded ? t("Collapse") : t("Expand")}
                            </button>
                          </td>
                        </tr>
                      );
                      if (!isExpanded) {
                        return [compactMainRow];
                      }
                      const compactDetailRow = (
                        <tr key={`${row.id}-detail`} className="table__compact-detail-row">
                          <td colSpan={5} className="table__compact-detail-cell">
                            <div className="compact-detail-grid">
                              {[2, 3, 5, 6, 7].map((index) => (
                                <div className="compact-detail-item" key={`${row.id}-detail-${index}`}>
                                  <div className="compact-detail-item__label">{t(String(displayColumns[index] ?? `col-${index}`))}</div>
                                  <div className="compact-detail-item__value">{renderCell(row, String(row.cells[index] ?? "-"), index)}</div>
                                </div>
                              ))}
                            </div>
                          </td>
                        </tr>
                      );
                      return [compactMainRow, compactDetailRow];
                    })
                  : pageRows.map((row) => {
                      const isSelected = selection.isSelected(row.id);
                      return (
                        <tr
                          key={row.id}
                          className={isSelected ? "table__row--selected" : undefined}
                          onClick={() => selection.toggle(row.id)}
                          style={{ cursor: "pointer" }}
                        >
                          <td className="table__checkbox-cell">
                            <input
                              type="checkbox"
                              aria-label={t("Select {name}", { name: String(row.cells[1] ?? row.id) })}
                              checked={isSelected}
                              onClick={(event) => event.stopPropagation()}
                              onChange={() => selection.toggle(row.id)}
                            />
                          </td>
                          {row.cells.map((cell, index) => (
                            <td key={`${row.id}-${index}`} className={index === 0 ? "table__cell-strong" : undefined}>
                              {renderCell(row, cell, index)}
                            </td>
                          ))}
                        </tr>
                      );
                    })
              )}
          </tbody>
            </table>
          </div>
        </div>
        {inlineError ? (
          <div className="summary-item">
            <div className="summary-item__body">{inlineError}</div>
          </div>
        ) : null}
        <div className="watchlist-pagination" data-testid="watchlist-pagination">
          <div className="watchlist-pagination__summary">
            <span className="watchlist-pagination__count">
              {t("Total {count}, page {current}/{total}", { count: totalRows, current: currentPage, total: pageCount })}
            </span>
          </div>
          <div className="watchlist-pagination__controls">
            <button
              className="button"
              type="button"
              onClick={() => setPage((current) => Math.max(1, current - 1))}
              disabled={currentPage === 1}
            >
              {t("Previous")}
            </button>
            {visiblePageItems.map((item) =>
              typeof item === "number" ? (
                <button
                  key={item}
                  className={`button watchlist-pagination__page${item === currentPage ? " watchlist-pagination__page--active" : ""}`}
                  type="button"
                  onClick={() => setPage(item)}
                  aria-current={item === currentPage ? "page" : undefined}
                  aria-label={`第 ${item} 页`}
                >
                  {item}
                </button>
              ) : (
                <span className="watchlist-pagination__ellipsis" key={item} aria-hidden="true">
                  ...
                </span>
              ),
            )}
            <button
              className="button"
              type="button"
              onClick={() => setPage((current) => Math.min(pageCount, current + 1))}
              disabled={currentPage === pageCount}
            >
              {t("Next")}
            </button>
          </div>
        </div>
        {selectedRows.length > 0 ? (
          <div className="summary-item summary-item--accent">
            <div className="summary-item__title">{t("Current selection")}</div>
            <div className="summary-item__body">
              {selectedRows.map((row) => `${row.cells[0]} ${row.cells[1]} · ${row.cells[3]}`).join(", ")}
            </div>
          </div>
        ) : null}
      </div>
    </WorkbenchCard>
  );
}
