import { useEffect, useMemo, useRef, useState } from "react";
import { IconButton } from "../../components/ui/icon-button";
import { WorkbenchCard } from "../../components/ui/workbench-card";
import type { TableSection } from "../../lib/page-models";
import { useCompactLayout } from "../../lib/use-compact-layout";
import { useSelection } from "../../lib/use-selection";
import { t } from "../../lib/i18n";

type WatchlistPanelProps = {
  watchlist: TableSection;
  onAddWatchlist: (code: string) => Promise<void> | void;
  onRefresh: (codes: string[]) => void;
  onBatchQuant: (codes: string[]) => void;
  onBatchPortfolio: (codes: string[], options?: { costPrice?: string; quantity?: string }) => Promise<void> | void;
  onBatchAnalyze: (codes: string[]) => void;
  analysisBusy?: boolean;
  analysisBusyMessage?: string;
  onClearSelection: () => void;
  onRemoveWatchlist: (code: string) => void;
  onTableQueryChange?: (query: { search: string; page: number; pageSize: number }) => void;
};

const panelStyle: React.CSSProperties = {
  display: "grid",
  gap: "16px",
};

const PAGE_SIZE = 50;

export function WatchlistPanel({
  watchlist,
  onAddWatchlist,
  onRefresh,
  onBatchQuant,
  onBatchPortfolio,
  onBatchAnalyze,
  analysisBusy = false,
  analysisBusyMessage = "",
  onClearSelection,
  onRemoveWatchlist,
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
  const [openMenuRowId, setOpenMenuRowId] = useState<string | null>(null);
  const normalizedSearch = search.trim();
  const pageCount = Math.max(1, Number(watchlist.pagination?.totalPages ?? 1));
  const currentPage = Math.min(Number(watchlist.pagination?.page ?? page), pageCount);
  const totalRows = Number(watchlist.pagination?.totalRows ?? watchlist.rows.length);
  const pageRows = watchlist.rows;
  const rowIds = useMemo(() => pageRows.map((row) => row.id), [pageRows]);
  const selection = useSelection(rowIds);
  const selectAllRef = useRef<HTMLInputElement | null>(null);

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

  useEffect(() => {
    if (!isCompactLayout || !openMenuRowId) return undefined;
    const onMouseDown = (event: MouseEvent) => {
      const target = event.target as HTMLElement | null;
      if (target?.closest(".row-more")) return;
      setOpenMenuRowId(null);
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setOpenMenuRowId(null);
      }
    };
    document.addEventListener("mousedown", onMouseDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("mousedown", onMouseDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [isCompactLayout, openMenuRowId]);

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

  const handleBatchAnalyze = () => {
    if (!analysisBusy && selectedCodes.length > 0) {
      onBatchAnalyze(selectedCodes);
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
      if (exists && openMenuRowId === rowId) {
        setOpenMenuRowId(null);
      }
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
                icon="🔎"
                label={analysisBusy ? t("Analysis in progress") : t("Start analysis")}
                tone="accent"
                onClick={handleBatchAnalyze}
                disabled={selectedCodes.length === 0 || analysisBusy}
              />
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
              {analysisBusy ? (
                <span className="badge badge--accent" style={{ marginLeft: "8px" }}>
                  {analysisBusyMessage || t("Analysis in progress")}
                </span>
              ) : null}
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
                <col className="watchlist-table__col watchlist-table__col--price" />
                <col className="watchlist-table__col watchlist-table__col--source" />
                <col className="watchlist-table__col watchlist-table__col--status" />
                <col className="watchlist-table__col watchlist-table__col--quant" />
                <col className="watchlist-table__col watchlist-table__col--actions" />
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
                    <th>{t(String(watchlist.columns[4] ?? "Status"))}</th>
                    <th className="table__compact-actions-head">{t("Detail")}</th>
                  </>
                ) : (
                  watchlist.columns.map((column) => <th key={column}>{t(column)}</th>)
                )}
                <th className={isCompactLayout ? "table__compact-actions-head" : "table__actions-head"}>{t("Actions")}</th>
              </tr>
            </thead>
            <tbody>
                {inlineAddOpen ? (
                  <tr className="table__row--selected">
                    <td className="table__checkbox-cell" />
                    <td>
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
                    </td>
                    <td>{isCompactLayout ? "-" : "-"}</td>
                    <td>{isCompactLayout ? "-" : "-"}</td>
                    {isCompactLayout ? <td>-</td> : <><td>-</td><td>-</td><td>-</td></>}
                    <td className="table__actions-cell">
                      <div className="table__actions">
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
                  <td className="table__empty" colSpan={(isCompactLayout ? 6 : watchlist.columns.length + 2)}>
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
                          <td className="table__cell-strong">{typeof row.cells[0] === "string" ? t(String(row.cells[0])) : row.cells[0]}</td>
                          <td>{typeof row.cells[1] === "string" ? t(String(row.cells[1])) : row.cells[1]}</td>
                          <td>{typeof row.cells[4] === "string" ? t(String(row.cells[4])) : row.cells[4] ?? "-"}</td>
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
                          <td className="table__compact-control-cell">
                            <div className="row-more" onClick={(event) => event.stopPropagation()}>
                              <button
                                className="icon-button icon-button--neutral row-more__trigger"
                                type="button"
                                aria-haspopup="menu"
                                aria-expanded={openMenuRowId === row.id}
                                onClick={() => setOpenMenuRowId((current) => (current === row.id ? null : row.id))}
                              >
                                ⋯
                              </button>
                              {openMenuRowId === row.id ? (
                                <div className="row-more__menu" role="menu">
                                  <button
                                    className="row-more__item row-more__item--neutral"
                                    type="button"
                                    role="menuitem"
                                    onClick={() => {
                                      setOpenMenuRowId(null);
                                      onBatchQuant([row.id]);
                                    }}
                                  >
                                    <span aria-hidden="true">🧪</span>
                                    <span>{t("Add to quant candidates")}</span>
                                  </button>
                                  <button
                                    className="row-more__item row-more__item--danger"
                                    type="button"
                                    role="menuitem"
                                    onClick={() => {
                                      setOpenMenuRowId(null);
                                      onRemoveWatchlist(row.id);
                                    }}
                                  >
                                    <span aria-hidden="true">🗑</span>
                                    <span>{t("Delete")}</span>
                                  </button>
                                </div>
                              ) : null}
                            </div>
                          </td>
                        </tr>
                      );
                      if (!isExpanded) {
                        return [compactMainRow];
                      }
                      const compactDetailRow = (
                        <tr key={`${row.id}-detail`} className="table__compact-detail-row">
                          <td colSpan={6} className="table__compact-detail-cell">
                            <div className="compact-detail-grid">
                              {[2, 3, 5].map((index) => (
                                <div className="compact-detail-item" key={`${row.id}-detail-${index}`}>
                                  <div className="compact-detail-item__label">{t(String(watchlist.columns[index] ?? `col-${index}`))}</div>
                                  <div className="compact-detail-item__value">{typeof row.cells[index] === "string" ? t(String(row.cells[index])) : row.cells[index] ?? "-"}</div>
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
                              {typeof cell === "string" ? t(cell) : cell}
                            </td>
                          ))}
                          <td className="table__actions-cell">
                            <div className="table__actions">
                              <IconButton
                                icon="🧪"
                                label={t("Add quant candidate {code}", { code: row.id })}
                                tone="neutral"
                                onClick={(event) => {
                                  event.stopPropagation();
                                  onBatchQuant([row.id]);
                                }}
                              />
                              <IconButton
                                icon="🗑"
                                label={t("Delete {code}", { code: row.id })}
                                tone="danger"
                                onClick={(event) => {
                                  event.stopPropagation();
                                  onRemoveWatchlist(row.id);
                                }}
                              />
                            </div>
                          </td>
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
            {Array.from({ length: pageCount }, (_, index) => index + 1).map((number) => (
              <button
                key={number}
                className={`button watchlist-pagination__page${number === currentPage ? " watchlist-pagination__page--active" : ""}`}
                type="button"
                onClick={() => setPage(number)}
                aria-current={number === currentPage ? "page" : undefined}
              >
                {number}
              </button>
            ))}
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
