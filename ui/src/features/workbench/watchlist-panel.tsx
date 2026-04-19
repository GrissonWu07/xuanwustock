import { useEffect, useMemo, useRef, useState } from "react";
import { IconButton } from "../../components/ui/icon-button";
import { WorkbenchCard } from "../../components/ui/workbench-card";
import type { TableSection } from "../../lib/page-models";
import { useSelection } from "../../lib/use-selection";
import { t } from "../../lib/i18n";

type WatchlistPanelProps = {
  watchlist: TableSection;
  onAddWatchlist: (code: string) => Promise<void> | void;
  onRefresh: (codes: string[]) => void;
  onBatchQuant: (codes: string[]) => void;
  onBatchAnalyze: (codes: string[]) => void;
  onClearSelection: () => void;
  onRemoveWatchlist: (code: string) => void;
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
  onBatchAnalyze,
  onClearSelection,
  onRemoveWatchlist,
}: WatchlistPanelProps) {
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  const [inlineAddOpen, setInlineAddOpen] = useState(false);
  const [inlineCode, setInlineCode] = useState("");
  const [inlineSaving, setInlineSaving] = useState(false);
  const [inlineError, setInlineError] = useState("");
  const normalizedSearch = search.trim().toLowerCase();
  const filteredRows = useMemo(() => {
    if (!normalizedSearch) return watchlist.rows;
    return watchlist.rows.filter((row) =>
      row.cells.some((cell) => String(cell).toLowerCase().includes(normalizedSearch)) ||
      row.id.toLowerCase().includes(normalizedSearch) ||
      (row.code ?? "").toLowerCase().includes(normalizedSearch) ||
      (row.name ?? "").toLowerCase().includes(normalizedSearch) ||
      (row.source ?? "").toLowerCase().includes(normalizedSearch),
    );
  }, [normalizedSearch, watchlist.rows]);
  const pageCount = Math.max(1, Math.ceil(filteredRows.length / PAGE_SIZE));
  const currentPage = Math.min(page, pageCount);
  const pageRows = useMemo(
    () => filteredRows.slice((currentPage - 1) * PAGE_SIZE, currentPage * PAGE_SIZE),
    [currentPage, filteredRows],
  );
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

  const selectedCodes = selection.selectedIds;
  const selectedRows = pageRows.filter((row) => selectedCodes.includes(row.id));

  const handleBatchQuant = () => {
    if (selectedCodes.length > 0) {
      onBatchQuant(selectedCodes);
    }
  };

  const handleBatchAnalyze = () => {
    if (selectedCodes.length > 0) {
      onBatchAnalyze(selectedCodes);
    }
  };

  const handleRefresh = () => {
    const targetCodes = (selectedCodes.length > 0 ? selectedCodes : pageRows.map((row) => row.id)).filter(Boolean);
    if (targetCodes.length === 0) return;
    onRefresh(targetCodes);
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
                icon="🔎"
                label={t("Start analysis")}
                tone="accent"
                onClick={handleBatchAnalyze}
                disabled={selectedCodes.length === 0}
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
            </div>
          </div>
        </div>

        <div className="table-shell watchlist-table-shell">
          <div className="watchlist-table__viewport">
            <table className="table watchlist-table" data-testid="watchlist-table">
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
                {watchlist.columns.map((column) => (
                  <th key={column}>{t(column)}</th>
                ))}
              <th className="table__actions-head">{t("Actions")}</th>
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
                    <td>-</td>
                    <td>-</td>
                    <td>-</td>
                    <td>-</td>
                    <td>-</td>
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
                  <td className="table__empty" colSpan={watchlist.columns.length + 2}>
                    {filteredRows.length === 0
                      ? (watchlist.emptyLabel ? t(watchlist.emptyLabel) : t("My watchlist is empty"))
                      : t("Current page has no stocks. Switch page or adjust search.")}
                  </td>
                </tr>
              ) : (
                pageRows.map((row) => {
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
              {t("Total {count}, page {current}/{total}", { count: filteredRows.length, current: currentPage, total: pageCount })}
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
