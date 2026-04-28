import { useEffect, useMemo, useState, type CSSProperties, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { WorkbenchCard } from "../../components/ui/workbench-card";
import type { TableAction, TableRow, TableSection } from "../../lib/page-models";
import { useCompactLayout } from "../../lib/use-compact-layout";
import { t } from "../../lib/i18n";
import { localizeDecisionCode } from "./quant-decision-localizer";

type CompactConfig = {
  coreColumnIndexes?: number[];
  detailColumnIndexes?: number[];
};

type QuantTableSectionProps = {
  title: string;
  description?: ReactNode;
  table: TableSection;
  emptyTitle: string;
  emptyDescription: string;
  meta?: string[];
  actionsHead?: string;
  actionVariant?: "icon" | "chip";
  tableLayout?: "fixed" | "auto";
  toolbar?: ReactNode;
  onRowAction?: (row: TableRow, action: TableAction) => void;
  compactConfig?: CompactConfig;
  signalDetailSource?: "live" | "replay";
};

const emptyShellStyle: CSSProperties = {
  margin: 0,
};

const emptyBodyStyle: CSSProperties = {
  marginTop: "6px",
};

const STOCK_CODE_PATTERN = /\b\d{6}\b/;
const SIGNAL_ID_PATTERN = /\b\d+\b/;

const normalizeStockCode = (value?: string) => {
  const match = String(value ?? "").match(STOCK_CODE_PATTERN);
  return match?.[0] ?? "";
};

const normalizeSignalId = (value?: string) => {
  const match = String(value ?? "").match(SIGNAL_ID_PATTERN);
  return match?.[0] ?? "";
};

const stockDetailPath = (code: string) => `/portfolio/position/${encodeURIComponent(code)}`;
const signalDetailPath = (signalId: string, source: "live" | "replay") =>
  `/signal-detail/${encodeURIComponent(signalId)}?source=${encodeURIComponent(source)}`;

const rowStockCode = (row: TableRow) =>
  normalizeStockCode(row.code)
  || normalizeStockCode(row.id)
  || normalizeStockCode(row.cells.find((cell) => STOCK_CODE_PATTERN.test(String(cell))) ?? "");

const isStockReferenceColumn = (column: string, index: number) => {
  const normalized = String(column).trim().toLowerCase();
  if (normalized.includes("信号id") || normalized === "id") return false;
  return (
    normalized.includes("代码")
    || normalized.includes("股票")
    || normalized === "code"
    || normalized === "symbol"
    || normalized.includes("名称")
    || normalized === "name"
  );
};

const isSignalReferenceColumn = (column: string) => {
  const normalized = String(column).trim().toLowerCase();
  return normalized.includes("信号id") || normalized === "signalid" || normalized === "signal_id";
};

export function QuantTableSectionCard({
  title,
  description,
  table,
  emptyTitle,
  emptyDescription,
  meta = [],
  actionsHead,
  actionVariant = "icon",
  tableLayout = "fixed",
  toolbar,
  onRowAction,
  compactConfig,
  signalDetailSource,
}: QuantTableSectionProps) {
  const isCompactLayout = useCompactLayout();
  const showActions = Boolean(actionsHead) || table.rows.some((row) => (row.actions?.length ?? 0) > 0);
  const tableClassName = tableLayout === "auto" ? "table table--auto" : "table";
  const compactEnabled = isCompactLayout;
  const columnIndexes = useMemo(() => table.columns.map((_, index) => index), [table.columns]);
  const compactCoreIndexes = useMemo(() => {
    const source = compactConfig?.coreColumnIndexes?.length ? compactConfig.coreColumnIndexes : columnIndexes.slice(0, 4);
    const valid = source.filter((index, position, all) => Number.isInteger(index) && index >= 0 && index < table.columns.length && all.indexOf(index) === position);
    return valid.length > 0 ? valid : columnIndexes.slice(0, 1);
  }, [columnIndexes, compactConfig?.coreColumnIndexes, table.columns.length]);
  const compactDetailIndexes = useMemo(() => {
    if (compactConfig?.detailColumnIndexes?.length) {
      return compactConfig.detailColumnIndexes.filter(
        (index, position, all) =>
          Number.isInteger(index) &&
          index >= 0 &&
          index < table.columns.length &&
          all.indexOf(index) === position &&
          !compactCoreIndexes.includes(index),
      );
    }
    return columnIndexes.filter((index) => !compactCoreIndexes.includes(index));
  }, [columnIndexes, compactConfig?.detailColumnIndexes, compactCoreIndexes, table.columns.length]);
  const [expandedRows, setExpandedRows] = useState<string[]>([]);
  const [openMenuRowId, setOpenMenuRowId] = useState<string | null>(null);

  useEffect(() => {
    if (!compactEnabled || !openMenuRowId) return undefined;
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
  }, [compactEnabled, openMenuRowId]);

  const toggleExpanded = (rowId: string) => {
    setExpandedRows((current) => {
      const exists = current.includes(rowId);
      if (exists) {
        if (openMenuRowId === rowId) {
          setOpenMenuRowId(null);
        }
        return current.filter((item) => item !== rowId);
      }
      return [...current, rowId];
    });
  };

  const renderCell = (row: TableRow, cell: string, column: string, index: number) => {
    const normalizedColumn = String(column).toLowerCase();
    const isActionColumn = normalizedColumn.includes("动作") || normalizedColumn === "action";
    const isStrategyColumn = normalizedColumn.includes("策略") || normalizedColumn === "strategy";
    const code = rowStockCode(row);
    const signalId = signalDetailSource && isSignalReferenceColumn(column) ? normalizeSignalId(cell) : "";
    if (signalId && signalDetailSource) {
      return (
        <Link className="stock-link" to={signalDetailPath(signalId, signalDetailSource)}>
          {cell}
        </Link>
      );
    }
    if (code && isStockReferenceColumn(column, index)) {
      return (
        <Link className="stock-link" to={stockDetailPath(code)}>
          {cell}
        </Link>
      );
    }
    if (isActionColumn) {
      const signalAction = String(cell).trim().toUpperCase();
      if (signalAction === "BUY" || signalAction === "BUG") {
        return <span className="signal-pill signal-pill--buy">{cell}</span>;
      }
      if (signalAction === "SELL") {
        return <span className="signal-pill signal-pill--sell">{cell}</span>;
      }
      if (signalAction === "HOLD") {
        return <span className="signal-pill signal-pill--hold">{cell}</span>;
      }
    }
    if (isStrategyColumn) {
      return <>{localizeDecisionCode(String(cell))}</>;
    }
    return <>{cell}</>;
  };

  return (
    <WorkbenchCard>
      <div className="toolbar">
        <div>
          <h2 className="section-card__title" style={{ margin: 0 }}>
            {title}
          </h2>
          {description ? <p className="table__caption" style={{ marginBottom: 0 }}>{description}</p> : null}
          {meta.length > 0 ? (
            <div className="chip-row" style={{ marginTop: "10px" }}>
              {meta.map((item) => (
                <span className="badge badge--neutral" key={item}>
                  {item}
                </span>
              ))}
            </div>
          ) : null}
        </div>
        {toolbar ? <span className="toolbar__spacer" /> : null}
        {toolbar}
      </div>
      <div className={`table-shell${compactEnabled ? " table-shell--compact" : ""}`}>
        <table className={tableClassName}>
          <thead>
            <tr>
              {(compactEnabled ? compactCoreIndexes.map((index) => table.columns[index]) : table.columns).map((column) => (
                <th key={column}>{column}</th>
              ))}
              {compactEnabled && compactDetailIndexes.length > 0 ? <th className="table__compact-actions-head">详情</th> : null}
              {showActions ? <th className={compactEnabled ? "table__compact-actions-head" : "table__actions-head"}>{actionsHead ?? "操作"}</th> : null}
            </tr>
          </thead>
          <tbody>
            {table.rows.length === 0 ? (
              <tr>
                <td
                  className="table__empty"
                  colSpan={(compactEnabled ? compactCoreIndexes.length : table.columns.length) + (compactEnabled && compactDetailIndexes.length > 0 ? 1 : 0) + (showActions ? 1 : 0)}
                >
                  <div className="summary-item summary-item--accent" style={emptyShellStyle}>
                    <div className="summary-item__title">{emptyTitle}</div>
                    <div className="summary-item__body" style={emptyBodyStyle}>
                      {emptyDescription}
                    </div>
                  </div>
                </td>
              </tr>
            ) : (
              compactEnabled
                ? table.rows.flatMap((row) => {
                    const isExpanded = expandedRows.includes(row.id);
                    const compactColumnsCount = compactCoreIndexes.length + (compactDetailIndexes.length > 0 ? 1 : 0) + (showActions ? 1 : 0);
                    const mainRow = (
                      <tr key={`${row.id}-main`} className="table__compact-main-row">
                        {compactCoreIndexes.map((index) => {
                          const cell = row.cells[index];
                          return (
                            <td key={`${row.id}-core-${index}`} className={index === compactCoreIndexes[0] ? "table__cell-strong" : undefined}>
                              {renderCell(row, String(cell ?? ""), String(table.columns[index] ?? ""), index)}
                            </td>
                          );
                        })}
                        {compactDetailIndexes.length > 0 ? (
                          <td className="table__compact-control-cell">
                            <button
                              className="button button--secondary button--small table__expand-button"
                              type="button"
                              aria-expanded={isExpanded}
                              onClick={() => toggleExpanded(row.id)}
                            >
                              {isExpanded ? t("Collapse") : t("Expand")}
                            </button>
                          </td>
                        ) : null}
                        {showActions ? (
                          <td className="table__compact-control-cell">
                            {(row.actions?.length ?? 0) > 0 ? (
                              <div className="row-more">
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
                                    {row.actions?.map((action) => {
                                      const tone = action.tone ?? "neutral";
                                      return (
                                        <button
                                          key={`${row.id}-${action.label}`}
                                          className={`row-more__item row-more__item--${tone}`}
                                          type="button"
                                          role="menuitem"
                                          disabled={!onRowAction}
                                          onClick={() => {
                                            setOpenMenuRowId(null);
                                            if (onRowAction) {
                                              onRowAction(row, action);
                                            }
                                          }}
                                        >
                                          <span aria-hidden="true">{action.icon ?? "•"}</span>
                                          <span>{action.label}</span>
                                        </button>
                                      );
                                    })}
                                  </div>
                                ) : null}
                              </div>
                            ) : (
                              <span>--</span>
                            )}
                          </td>
                        ) : null}
                      </tr>
                    );
                    if (!isExpanded || compactDetailIndexes.length === 0) {
                      return [mainRow];
                    }
                    const detailRow = (
                      <tr key={`${row.id}-detail`} className="table__compact-detail-row">
                        <td className="table__compact-detail-cell" colSpan={compactColumnsCount}>
                          <div className="compact-detail-grid">
                            {compactDetailIndexes.map((index) => (
                              <div className="compact-detail-item" key={`${row.id}-detail-${index}`}>
                                <div className="compact-detail-item__label">{table.columns[index]}</div>
                                <div className="compact-detail-item__value">
                                  {renderCell(row, String(row.cells[index] ?? ""), String(table.columns[index] ?? ""), index)}
                                </div>
                              </div>
                            ))}
                          </div>
                        </td>
                      </tr>
                    );
                    return [mainRow, detailRow];
                  })
                : table.rows.map((row) => (
                    <tr key={row.id}>
                      {row.cells.map((cell, index) => (
                        <td key={`${row.id}-${index}`} className={index === 0 ? "table__cell-strong" : undefined}>
                          {renderCell(row, String(cell), String(table.columns[index] ?? ""), index)}
                        </td>
                      ))}
                      {showActions ? (
                        <td>
                          <div className="table__actions">
                            {row.actions?.map((action) => {
                              const tone = action.tone ?? "neutral";
                              if (onRowAction) {
                                if (actionVariant === "chip") {
                                  return (
                                    <button
                                      key={`${row.id}-${action.label}`}
                                      className="chip chip--active"
                                      type="button"
                                      aria-label={action.label}
                                      onClick={() => onRowAction(row, action)}
                                    >
                                      {action.icon ?? action.label}
                                      <span>{action.label}</span>
                                    </button>
                                  );
                                }

                                return (
                                  <button
                                    key={`${row.id}-${action.label}`}
                                    className={`icon-button icon-button--${tone}`}
                                    type="button"
                                    aria-label={action.label}
                                    onClick={() => onRowAction(row, action)}
                                  >
                                    {action.icon ?? action.label}
                                  </button>
                                );
                              }

                              if (actionVariant === "chip") {
                                return (
                                  <span className="chip chip--active" key={`${row.id}-${action.label}`}>
                                    {action.icon ?? action.label}
                                    <span>{action.label}</span>
                                  </span>
                                );
                              }

                              return (
                                <span className={`icon-button icon-button--${tone}`} key={`${row.id}-${action.label}`} aria-hidden="true">
                                  {action.icon ?? action.label}
                                </span>
                              );
                            })}
                          </div>
                        </td>
                      ) : null}
                    </tr>
                  ))
            )}
          </tbody>
        </table>
      </div>
    </WorkbenchCard>
  );
}
