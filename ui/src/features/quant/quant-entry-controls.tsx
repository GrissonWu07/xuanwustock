import type { TableRow } from "../../lib/page-models";
import { t } from "../../lib/i18n";

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
type ResultReasonItem = { stock_code?: string; code?: string; reason_text?: string; reason_code?: string; error?: string };

const fieldText = (row: TableRow, key: string) => {
  const value = (row as EntryRow)[key];
  return typeof value === "string" ? value.trim() : "";
};

const fieldNumber = (row: TableRow, key: string) => {
  const value = (row as EntryRow)[key];
  if (value === null || value === undefined || value === "") return null;
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
};

const fieldBool = (row: TableRow, key: string) => Boolean((row as EntryRow)[key]);

const formatDiagnosticNumber = (value: number) => value.toFixed(2);

const fieldList = (row: TableRow, key: string) => {
  const value = (row as EntryRow)[key];
  if (Array.isArray(value)) return value.map((item) => String(item).trim()).filter(Boolean);
  if (typeof value === "string" && value.trim()) {
    return value.split(",").map((item) => item.trim()).filter(Boolean);
  }
  return [];
};

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
  const score = fieldNumber(row, "candidate_score");
  const confidence = fieldNumber(row, "candidate_confidence");
  const snapshotStatus = fieldText(row, "technical_snapshot_status") || fieldText(row, "technicalSnapshotStatus");
  const missingFields = fieldList(row, "technical_snapshot_missing_fields");
  const tone = status === "eligible" ? "badge--success" : status === "already_in_quant" ? "badge--accent" : "badge--neutral";
  return (
    <span className="chip-row" style={{ gap: "6px" }}>
      <span className={`badge ${tone}`}>{status}</span>
      {score !== null ? <span className="badge badge--neutral">{t("量化技术入池分")} {formatDiagnosticNumber(score)}</span> : null}
      {confidence !== null ? <span className="badge badge--neutral">{t("技术置信度")} {formatDiagnosticNumber(confidence)}</span> : null}
      {reason ? <span className="badge badge--neutral">{reason}</span> : null}
      {snapshotStatus ? <span className="badge badge--neutral">{t("Technical snapshot")} {snapshotStatus}</span> : null}
      {missingFields.length > 0 ? <span className="badge badge--neutral">{missingFields.join(", ")}</span> : null}
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
      <section className="card section-card" role="dialog" aria-modal="true" aria-label={t("确认纳入量化")}>
        <h2 className="section-card__title">{t("确认纳入量化")}</h2>
        <p className="section-card__description">{t("将选中的")}{count} {t("只股票纳入量化名单，执行结果会在确认后弹出显示。")}</p>
        <div className="toolbar toolbar--compact">
          <button className="button button--secondary" type="button" onClick={onCancel} disabled={pending}>
            {t("取消")}</button>
          <button className="button button--primary" type="button" onClick={onConfirm} disabled={pending || count <= 0}>
            {pending ? t("纳入中...") : t("确认纳入")}
          </button>
        </div>
      </section>
    </div>
  );
}

export function QuantEntryResultDialog({
  result,
  onClose,
}: {
  result: QuantEntryActionResult | null;
  onClose: () => void;
}) {
  if (!result) return null;
  const successCount = result.success?.length ?? 0;
  const skipped = result.skipped ?? [];
  const failed = result.failed ?? [];
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
      <section className="card section-card" role="dialog" aria-modal="true" aria-label={t("纳入量化结果")}>
        <h2 className="section-card__title">{t("纳入量化结果")}</h2>
        <div className="chip-row" style={{ gap: "8px", marginBottom: "14px" }}>
          <span className="badge badge--success">{t("成功")} {successCount} {t("只")}</span>
          <span className="badge badge--neutral">{t("跳过")} {skipped.length} {t("只")}</span>
          <span className="badge badge--neutral">{t("失败")} {failed.length} {t("只")}</span>
        </div>
        {skipped.length > 0 ? (
          <ResultReasonList title={t("跳过原因")} items={skipped} />
        ) : null}
        {failed.length > 0 ? (
          <ResultReasonList title={t("失败原因")} items={failed} />
        ) : null}
        <div className="toolbar toolbar--compact" style={{ marginTop: "16px" }}>
          <button className="button button--primary" type="button" onClick={onClose}>
            {t("关闭")}
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

const resultReasonOf = (item: ResultReasonItem) => item.reason_text || item.reason_code || item.error || "unknown";

function ResultReasonList({ title, items }: { title: string; items: ResultReasonItem[] }) {
  return (
    <div className="summary-item" style={{ marginTop: "10px" }}>
      <div className="summary-item__title">{title}</div>
      <ul className="summary-item__body" style={{ margin: "8px 0 0", paddingLeft: "18px" }}>
        {items.map((item, index) => {
          const code = resultCodeOf(item);
          const reason = resultReasonOf(item);
          return <li key={`${code || "unknown"}-${index}`}>{code ? `${code} - ${reason}` : reason}</li>;
        })}
      </ul>
    </div>
  );
}

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
    updates[code] = { status: "skipped", reason: t("已忽略") };
  });
  (result?.success ?? []).forEach((item) => {
    const code = resultCodeOf(item);
    if (code) updates[code] = { status: "skipped", reason: t("已忽略") };
  });
  (result?.failed ?? []).forEach((item) => {
    const code = resultCodeOf(item);
    if (code) updates[code] = { status: "skipped", reason: item.reason_text || item.error || "failed" };
  });
  return updates;
}

