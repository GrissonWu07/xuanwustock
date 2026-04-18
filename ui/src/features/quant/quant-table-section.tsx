import type { CSSProperties, ReactNode } from "react";
import { WorkbenchCard } from "../../components/ui/workbench-card";
import type { TableAction, TableRow, TableSection } from "../../lib/page-models";

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
};

const emptyShellStyle: CSSProperties = {
  margin: 0,
};

const emptyBodyStyle: CSSProperties = {
  marginTop: "6px",
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
}: QuantTableSectionProps) {
  const showActions = Boolean(actionsHead) || table.rows.some((row) => (row.actions?.length ?? 0) > 0);
  const tableClassName = tableLayout === "auto" ? "table table--auto" : "table";

  const renderCell = (cell: string, column: string, index: number) => {
    const normalizedColumn = String(column).toLowerCase();
    const isActionColumn = normalizedColumn.includes("动作") || normalizedColumn === "action";
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
      <div className="table-shell">
        <table className={tableClassName}>
          <thead>
            <tr>
              {table.columns.map((column) => (
                <th key={column}>{column}</th>
              ))}
              {showActions ? <th className="table__actions-head">{actionsHead ?? "操作"}</th> : null}
            </tr>
          </thead>
          <tbody>
            {table.rows.length === 0 ? (
              <tr>
                <td className="table__empty" colSpan={table.columns.length + (showActions ? 1 : 0)}>
                  <div className="summary-item summary-item--accent" style={emptyShellStyle}>
                    <div className="summary-item__title">{emptyTitle}</div>
                    <div className="summary-item__body" style={emptyBodyStyle}>
                      {emptyDescription}
                    </div>
                  </div>
                </td>
              </tr>
            ) : (
              table.rows.map((row) => (
                <tr key={row.id}>
                  {row.cells.map((cell, index) => (
                    <td key={`${row.id}-${index}`} className={index === 0 ? "table__cell-strong" : undefined}>
                      {renderCell(String(cell), String(table.columns[index] ?? ""), index)}
                    </td>
                  ))}
                  {showActions ? (
                    <td>
                      <div className="table__actions">
                        {row.actions?.map((action) => {
                          const tone = action.tone ?? "neutral";
                          if (action.action && onRowAction) {
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
