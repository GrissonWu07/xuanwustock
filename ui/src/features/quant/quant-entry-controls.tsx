import type { TableRow } from "../../lib/page-models";

export type EntryStatusOverride = {
  status: string;
  reason?: string;
};

export type QuantEntryActionResult = {
  success?: ({ stock_code?: string; code?: string } | string)[];
  skipped?: { stock_code?: string; code?: string; reason_text?: string; reason_code?: string }[];
  failed?: { stock_code?: string; code?: string; reason_text?: string; error?: string }[];
};

type EntryRow = TableRow & Record<string, unknown>;

const fieldText = (row: TableRow, key: string) => {
  const value = (row as EntryRow)[key];
  return typeof value === "string" ? value.trim() : "";
};

const fieldBool = (row: TableRow, key: string) => Boolean((row as EntryRow)[key]);

export const entryStatusOf = (row: TableRow, override?: EntryStatusOverride) => {
  if (override?.status) return override.status;
  if (fieldBool(row, "already_in_quant")) return "already_in_quant";
  const status = fieldText(row, "eligible_status") || fieldText(row, "eligibleStatus");
  if (status) return status;
  const blocking = fieldText(row, "blocking_reason") || fieldText(row, "blockingReason");
  return blocking ? "skipped" : "not_evaluated";
};

export const entryReasonOf = (row: TableRow, override?: EntryStatusOverride) =>
  override?.reason || fieldText(row, "blocking_reason") || fieldText(row, "blockingReason");

export const isEligibleEntry = (row: TableRow, override?: EntryStatusOverride) => entryStatusOf(row, override) === "eligible";

export function EligibleBadge({ row, override }: { row: TableRow; override?: EntryStatusOverride }) {
  const status = entryStatusOf(row, override);
  const reason = entryReasonOf(row, override);
  const tone = status === "eligible" ? "badge--success" : status === "already_in_quant" ? "badge--accent" : "badge--neutral";
  return (
    <span className="chip-row" style={{ gap: "6px" }}>
      <span className={`badge ${tone}`}>{status}</span>
      {reason ? <span className="badge badge--neutral">{reason}</span> : null}
    </span>
  );
}

export function BatchPromoteDialog({
  open,
  count,
  pending,
  onCancel,
  onConfirm,
}: {
  open: boolean;
  count: number;
  pending?: boolean;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  if (!open) return null;
  return (
    <div
      className="modal-backdrop"
      style={{
        position: "fixed",
        inset: 0,
        zIndex: 40,
        display: "grid",
        placeItems: "center",
        background: "rgba(15, 23, 42, 0.28)",
        padding: "24px",
      }}
    >
      <section className="card section-card" role="dialog" aria-modal="true" aria-label="确认纳入量化试运行">
        <h2 className="section-card__title">确认纳入量化试运行</h2>
        <p className="section-card__description">将选中的 {count} 只股票纳入 trial，成功和跳过结果会保留在当前列表中。</p>
        <div className="toolbar toolbar--compact">
          <button className="button button--secondary" type="button" onClick={onCancel} disabled={pending}>
            取消
          </button>
          <button className="button button--primary" type="button" onClick={onConfirm} disabled={pending || count <= 0}>
            {pending ? "纳入中..." : "确认纳入"}
          </button>
        </div>
      </section>
    </div>
  );
}

export async function postQuantEntryAction<T>(path: string, payload: unknown): Promise<T> {
  const response = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload ?? {}),
  });
  if (!response.ok) {
    throw new Error(`Request failed: ${response.status}`);
  }
  return (await response.json()) as T;
}

const resultCodeOf = (item: { stock_code?: string; code?: string } | string) =>
  String(typeof item === "string" ? item : item.stock_code || item.code || "").trim();

export function promoteResultOverrides(result: QuantEntryActionResult) {
  const updates: Record<string, EntryStatusOverride> = {};
  (result.success ?? []).forEach((item) => {
    const code = resultCodeOf(item);
    if (code) updates[code] = { status: "already_in_quant" };
  });
  (result.skipped ?? []).forEach((item) => {
    const code = String(item.stock_code || item.code || "").trim();
    if (code) updates[code] = { status: "skipped", reason: item.reason_text || item.reason_code || "skipped" };
  });
  (result.failed ?? []).forEach((item) => {
    const code = String(item.stock_code || item.code || "").trim();
    if (code) updates[code] = { status: "skipped", reason: item.reason_text || item.error || "failed" };
  });
  return updates;
}

export function ignoreResultOverrides(codes: string[], result?: QuantEntryActionResult) {
  const updates: Record<string, EntryStatusOverride> = {};
  codes.forEach((code) => {
    updates[code] = { status: "skipped", reason: "已忽略" };
  });
  (result?.success ?? []).forEach((item) => {
    const code = resultCodeOf(item);
    if (code) updates[code] = { status: "skipped", reason: "已忽略" };
  });
  (result?.failed ?? []).forEach((item) => {
    const code = resultCodeOf(item);
    if (code) updates[code] = { status: "skipped", reason: item.reason_text || item.error || "failed" };
  });
  return updates;
}
