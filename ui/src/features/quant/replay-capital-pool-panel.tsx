import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { WorkbenchCard } from "../../components/ui/workbench-card";
import type { ReplayCapitalLot, ReplayCapitalPool, ReplayCapitalPoolSnapshot } from "../../lib/page-models";
import { t } from "../../lib/i18n";

const CHECKPOINT_PAGE_SIZE = 50;
const SLOT_PAGE_SIZE = 6;
type CheckpointQuery = Record<string, string | number>;

function localizeSlotStatus(status: string) {
  const normalized = String(status || "").trim().toLowerCase();
  if (normalized === "occupied") return t("占用");
  if (normalized === "settling") return t("待结算");
  if (normalized === "free") return t("空闲");
  return status || "--";
}

function slotStatusClass(status: string) {
  const normalized = String(status || "").trim().toLowerCase();
  if (normalized === "occupied") return "is-occupied";
  if (normalized === "settling") return "is-settling";
  return "is-free";
}

function slotUsageClass(status: string, usagePct: number) {
  const normalized = String(status || "").trim().toLowerCase();
  if (normalized === "occupied" && Number(usagePct) >= 99.5) {
    return "is-full";
  }
  return "";
}

function localizeLotStatus(status: string) {
  const normalized = String(status || "").trim().toLowerCase();
  if (normalized === "locked") return t("T+1锁定");
  if (normalized === "mixed") return t("部分可卖");
  if (normalized === "settling") return t("结算中");
  if (normalized === "available") return t("可卖");
  return status || "--";
}

function lotStatusClass(status: string) {
  const normalized = String(status || "").trim().toLowerCase();
  if (normalized === "available") return "is-sellable";
  if (normalized === "mixed") return "is-partial";
  return "is-unavailable";
}

type LotWithSlot = ReplayCapitalLot & {
  slotTitle: string;
  slotIndex: number;
};

type StockLotGroup = {
  stockCode: string;
  stockName: string;
  lotCount: number;
  quantity: number;
  sellableQuantity: number;
  lockedQuantity: number;
  allocatedCash: number;
  marketValue: number;
  costBasis: number;
  slots: string[];
  status: string;
};

function flattenLots(capitalPool: ReplayCapitalPool): LotWithSlot[] {
  return capitalPool.slots.flatMap((slot) =>
    slot.lots.map((lot) => ({
      ...lot,
      slotTitle: slot.title,
      slotIndex: slot.index,
    })),
  );
}

function parseDisplayNumber(value: unknown) {
  const match = String(value ?? "").replace(/,/g, "").match(/-?\d+(\.\d+)?/);
  if (!match) return null;
  const parsed = Number(match[0]);
  return Number.isFinite(parsed) ? parsed : null;
}

function formatPrice(value: number | null) {
  return value === null ? "--" : value.toFixed(2);
}

function formatMoney(value: number) {
  return Number.isFinite(value) ? value.toFixed(2) : "--";
}

function lotPriceInfo(lot: ReplayCapitalLot) {
  const cost = parseDisplayNumber(lot.costBand);
  const marketValue = parseDisplayNumber(lot.marketValue);
  const quantity = Number(lot.quantity || 0);
  const hasMarketPrice = String(lot.priceBasis || "").trim().toLowerCase() === "market";
  const current = marketValue !== null && quantity > 0 ? marketValue / quantity : null;
  if (!hasMarketPrice) {
    return {
      priceText: t("成本价 {v0}", { v0: formatPrice(cost) }),
      trendText: "",
      trendClass: "is-flat",
    };
  }
  if (cost === null || current === null || cost <= 0) {
    return {
      priceText: t("成本 {v0} · 现价 {v1}", { v0: formatPrice(cost), v1: formatPrice(current) }),
      trendText: "",
      trendClass: "is-flat",
    };
  }
  const pct = ((current - cost) / cost) * 100;
  if (Math.abs(pct) < 0.005) {
    return {
      priceText: t("成本 {v0} · 现价 {v1}", { v0: formatPrice(cost), v1: formatPrice(current) }),
      trendText: t("平 0.00%"),
      trendClass: "is-flat",
    };
  }
  return {
    priceText: t("成本 {v0} · 现价 {v1}", { v0: formatPrice(cost), v1: formatPrice(current) }),
    trendText: pct > 0 ? t("涨 +{v0}%", { v0: pct.toFixed(2) }) : t("跌 {v0}%", { v0: pct.toFixed(2) }),
    trendClass: pct > 0 ? "is-up" : "is-down",
  };
}

function lotValueLabel(lot: ReplayCapitalLot) {
  return String(lot.priceBasis || "").trim().toLowerCase() === "market" ? t("市值") : t("成本市值");
}

function renderLotPriceLine(lot: ReplayCapitalLot) {
  const info = lotPriceInfo(lot);
  return (
    <div className="replay-capital-lot-price">
      <span>{info.priceText}</span>
      {info.trendText ? <em className={info.trendClass}>{info.trendText}</em> : null}
    </div>
  );
}

function groupLotsByStock(lots: LotWithSlot[]): StockLotGroup[] {
  const groups = new Map<string, StockLotGroup>();
  for (const lot of lots) {
    const key = lot.stockCode;
    const current = groups.get(key) ?? {
      stockCode: lot.stockCode,
      stockName: lot.stockName ?? "",
      lotCount: 0,
      quantity: 0,
      sellableQuantity: 0,
      lockedQuantity: 0,
      allocatedCash: 0,
      marketValue: 0,
      costBasis: 0,
      slots: [],
      status: "available",
    };
    const quantity = Number(lot.quantity || 0);
    const allocatedCash = parseDisplayNumber(lot.allocatedCash) ?? 0;
    const marketValue = parseDisplayNumber(lot.marketValue) ?? 0;
    const cost = parseDisplayNumber(lot.costBand);
    current.lotCount += Number(lot.lotCount || 0);
    current.quantity += quantity;
    current.sellableQuantity += Number(lot.sellableQuantity || 0);
    current.lockedQuantity += Number(lot.lockedQuantity || 0);
    current.allocatedCash += allocatedCash;
    current.marketValue += marketValue;
    current.costBasis += cost !== null ? cost * quantity : allocatedCash;
    if (!current.slots.includes(lot.slotTitle)) {
      current.slots.push(lot.slotTitle);
    }
    if (lot.status === "locked") {
      current.status = current.status === "available" ? "locked" : "mixed";
    } else if (lot.status === "mixed" || current.status === "locked") {
      current.status = "mixed";
    }
    groups.set(key, current);
  }
  return Array.from(groups.values()).sort((left, right) => right.marketValue - left.marketValue);
}

function stockGroupPriceLine(group: StockLotGroup) {
  const cost = group.quantity > 0 ? group.costBasis / group.quantity : null;
  const current = group.quantity > 0 ? group.marketValue / group.quantity : null;
  if (cost === null || current === null || cost <= 0) {
    return {
      priceText: t("成本 {v0} · 现价 {v1}", { v0: formatPrice(cost), v1: formatPrice(current) }),
      trendText: "",
      trendClass: "is-flat",
    };
  }
  const pct = ((current - cost) / cost) * 100;
  if (Math.abs(pct) < 0.005) {
    return {
      priceText: t("成本 {v0} · 现价 {v1}", { v0: formatPrice(cost), v1: formatPrice(current) }),
      trendText: t("平 0.00%"),
      trendClass: "is-flat",
    };
  }
  return {
    priceText: t("成本 {v0} · 现价 {v1}", { v0: formatPrice(cost), v1: formatPrice(current) }),
    trendText: pct > 0 ? t("涨 +{v0}%", { v0: pct.toFixed(2) }) : t("跌 {v0}%", { v0: pct.toFixed(2) }),
    trendClass: pct > 0 ? "is-up" : "is-down",
  };
}

export function ReplayCapitalPoolPanel({
  capitalPool,
  loadCheckpoint,
}: {
  capitalPool: ReplayCapitalPool;
  loadCheckpoint?: (query: CheckpointQuery) => Promise<ReplayCapitalPoolSnapshot>;
  showPositionSummary?: boolean;
}) {
  const [checkpointSnapshot, setCheckpointSnapshot] = useState<ReplayCapitalPoolSnapshot | null>(null);
  const viewCapitalPool = checkpointSnapshot?.capitalPool ?? capitalPool;
  const defaultSlotIndex = viewCapitalPool.selectedSlotIndex ?? viewCapitalPool.slots[0]?.index ?? 0;
  const [selectedSlotIndex, setSelectedSlotIndex] = useState(defaultSlotIndex);
  const [checkpointPage, setCheckpointPage] = useState(1);
  const [checkpointLoading, setCheckpointLoading] = useState(false);
  const [checkpointError, setCheckpointError] = useState("");
  const [showAllLots, setShowAllLots] = useState(false);
  const [slotPage, setSlotPage] = useState(1);
  const [selectedStockCode, setSelectedStockCode] = useState("");

  useEffect(() => {
    setSelectedSlotIndex(defaultSlotIndex);
  }, [viewCapitalPool.task.runId, defaultSlotIndex]);

  useEffect(() => {
    setCheckpointSnapshot(null);
    setCheckpointPage(1);
    setCheckpointError("");
    setShowAllLots(false);
    setSlotPage(1);
    setSelectedStockCode("");
  }, [capitalPool.task.runId]);

  const loadCheckpointPage = async (page: number, checkpointAt?: string) => {
    if (!loadCheckpoint || !capitalPool.task.runId) {
      return;
    }
    setCheckpointLoading(true);
    setCheckpointError("");
    try {
      const next = await loadCheckpoint({
        runId: capitalPool.task.runId,
        checkpointPage: page,
        checkpointPageSize: CHECKPOINT_PAGE_SIZE,
        ...(checkpointAt ? { checkpointAt } : {}),
      });
      setCheckpointSnapshot(next);
      setCheckpointPage(next.checkpoints.pagination.page);
    } catch (error) {
      setCheckpointError(error instanceof Error ? error.message : t("检查点资金池加载失败"));
    } finally {
      setCheckpointLoading(false);
    }
  };

  useEffect(() => {
    if (!loadCheckpoint || !capitalPool.task.runId) {
      return;
    }
    void loadCheckpointPage(1);
  }, [capitalPool.task.runId, loadCheckpoint]);

  const selectedSlot = viewCapitalPool.slots.find((slot) => slot.index === selectedSlotIndex) ?? viewCapitalPool.slots[0];
  const allLots = flattenLots(viewCapitalPool);
  const totalLots = allLots.reduce((sum, lot) => sum + (lot.lotCount || 0), 0);
  const checkpointItems = checkpointSnapshot?.checkpoints.items ?? [];
  const checkpointPagination = checkpointSnapshot?.checkpoints.pagination;
  const selectedCheckpointAt = checkpointSnapshot?.selectedCheckpointAt ?? viewCapitalPool.task.checkpoint ?? "";
  const slotTotal = viewCapitalPool.slots.length;
  const slotTotalPages = Math.max(1, Math.ceil(slotTotal / SLOT_PAGE_SIZE));
  const currentSlotPage = Math.min(slotPage, slotTotalPages);
  const slotPageStart = (currentSlotPage - 1) * SLOT_PAGE_SIZE;
  const visibleSlots = viewCapitalPool.slots.slice(slotPageStart, slotPageStart + SLOT_PAGE_SIZE);
  const slotRangeStart = slotTotal ? slotPageStart + 1 : 0;
  const slotRangeEnd = Math.min(slotPageStart + visibleSlots.length, slotTotal);
  const visibleSlotIndexes = visibleSlots.map((slot) => slot.index).join(",");
  const stockLotGroups = groupLotsByStock(allLots);
  const selectedStockGroup =
    stockLotGroups.find((group) => group.stockCode === selectedStockCode) ?? stockLotGroups[0];
  const selectedStockLots = selectedStockGroup
    ? allLots.filter((lot) => lot.stockCode === selectedStockGroup.stockCode).sort((left, right) => left.slotIndex - right.slotIndex)
    : [];

  useEffect(() => {
    if (slotPage > slotTotalPages) {
      setSlotPage(slotTotalPages);
    }
  }, [slotPage, slotTotalPages]);

  useEffect(() => {
    setSlotPage(1);
  }, [selectedCheckpointAt]);

  useEffect(() => {
    if (!visibleSlots.length) {
      return;
    }
    if (!visibleSlots.some((slot) => slot.index === selectedSlotIndex)) {
      setSelectedSlotIndex(visibleSlots[0].index);
    }
  }, [selectedSlotIndex, visibleSlotIndexes, visibleSlots]);

  return (
    <WorkbenchCard>
      <div className="replay-capital-header">
        <div>
          <h2 className="section-card__title">{t("资金池总览")}</h2>
        </div>
        <button
          type="button"
          className="badge badge--accent replay-capital-lot-summary"
          aria-expanded={showAllLots}
          onClick={() => setShowAllLots((value) => !value)}
        >
          {`${viewCapitalPool.pool.slotCount} slots · ${totalLots} lots`}
        </button>
      </div>

      {loadCheckpoint ? (
        <div className="replay-capital-checkpoint-toolbar">
          <label className="field replay-capital-checkpoint-toolbar__select">
            <span className="field__label">{t("检查点")}</span>
            <select
              className="input"
              value={selectedCheckpointAt}
              aria-label={t("检查点")}
              disabled={checkpointLoading || !checkpointItems.length}
              onChange={(event) => void loadCheckpointPage(checkpointPage, event.target.value)}
            >
              {checkpointItems.length ? (
                checkpointItems.map((item) => (
                  <option key={item.id} value={item.checkpointAt}>
                    {t("{v0} · 权益 {v1}", { v0: item.label, v1: item.totalEquity ?? "--" })}
                  </option>
                ))
              ) : (
                <option value={selectedCheckpointAt}>{selectedCheckpointAt || t("暂无检查点")}</option>
              )}
            </select>
          </label>
          <div className="replay-capital-checkpoint-toolbar__pager">
            <button
              type="button"
              className="icon-button icon-button--neutral"
              aria-label={t("上一组检查点")}
              disabled={checkpointLoading || !checkpointPagination || checkpointPagination.page <= 1}
              onClick={() => void loadCheckpointPage(Math.max(1, checkpointPage - 1))}
            >
              ←
            </button>
            <span>{checkpointPagination ? `第 ${checkpointPagination.page} / ${checkpointPagination.totalPages} 页` : t("第 -- / -- 页")}</span>
            <button
              type="button"
              className="icon-button icon-button--neutral"
              aria-label={t("下一组检查点")}
              disabled={checkpointLoading || !checkpointPagination || checkpointPagination.page >= checkpointPagination.totalPages}
              onClick={() => void loadCheckpointPage(checkpointPage + 1)}
            >
              →
            </button>
          </div>
          {checkpointLoading ? <span className="badge badge--neutral">{t("加载中")}</span> : null}
          {checkpointError ? <span className="badge badge--danger">{checkpointError}</span> : null}
        </div>
      ) : null}

      <div className="mini-metric-grid replay-capital-metrics">
        <div className="mini-metric">
          <div className="mini-metric__label">{t("现金")}</div>
          <div className="mini-metric__value">{viewCapitalPool.pool.cashValue}</div>
        </div>
        <div className="mini-metric">
          <div className="mini-metric__label">{t("持仓市值")}</div>
          <div className="mini-metric__value">{viewCapitalPool.pool.marketValue}</div>
        </div>
        <div className="mini-metric">
          <div className="mini-metric__label">{t("总权益")}</div>
          <div className="mini-metric__value">{viewCapitalPool.pool.totalEquity}</div>
        </div>
        <div className="mini-metric">
          <div className="mini-metric__label">{t("Slot预算")}</div>
          <div className="mini-metric__value">{viewCapitalPool.pool.slotBudget}</div>
        </div>
      </div>

      {showAllLots ? (
        <div className="replay-capital-all-lots" aria-label={t("全部 Lot 明细")}>
          <div className="replay-capital-all-lots__head">
            <strong>{t("全部 Lot 明细")}</strong>
            <span>{t("{v0} 只股票 · {v1} 个lot组 · {v2} lots", { v0: stockLotGroups.length, v1: allLots.length, v2: totalLots })}</span>
          </div>
          <div className="live-position-lot-summary live-position-lot-summary--embedded" aria-label={t("按股票持仓")}>
            <div className="live-position-lot-summary__head">
              <strong>{t("按股票汇总")}</strong>
              <span>{t("{v0} 只股票 · {v1} lots", { v0: stockLotGroups.length, v1: totalLots })}</span>
            </div>
            <div className="live-position-lot-summary__grid">
              {stockLotGroups.map((group) => {
                const price = stockGroupPriceLine(group);
                return (
                  <div
                    className={`live-position-lot-card live-position-lot-card--selectable ${
                      selectedStockGroup?.stockCode === group.stockCode ? "is-selected" : ""
                    }`}
                    key={group.stockCode}
                    role="button"
                    tabIndex={0}
                    onClick={() => setSelectedStockCode(group.stockCode)}
                    onKeyDown={(event) => {
                      if (event.key === "Enter" || event.key === " ") {
                        event.preventDefault();
                        setSelectedStockCode(group.stockCode);
                      }
                    }}
                  >
                    <div className="live-position-lot-card__top">
                      <Link
                        className="replay-capital-stock-link"
                        to={`/portfolio/position/${group.stockCode}`}
                        onClick={(event) => event.stopPropagation()}
                      >
                        {`${group.stockCode} ${group.stockName || ""}`.trim()}
                      </Link>
                      <em className={lotStatusClass(group.status)}>{localizeLotStatus(group.status)}</em>
                    </div>
                    <div className="replay-capital-lot-price">
                      <span>{price.priceText}</span>
                      {price.trendText ? <em className={price.trendClass}>{price.trendText}</em> : null}
                    </div>
                    <div className="live-position-lot-card__facts">
                      <span>{`${group.lotCount} lots`}</span>
                      <span>{t("{v0}股", { v0: group.quantity })}</span>
                      <span>{t("可卖 {v0} · 锁定 {v1}", { v0: group.sellableQuantity, v1: group.lockedQuantity })}</span>
                    </div>
                    <div className="live-position-lot-card__money">
                      <span>{t("市值 {v0}", { v0: formatMoney(group.marketValue) })}</span>
                      <span>{t("占用 {v0}", { v0: formatMoney(group.allocatedCash) })}</span>
                    </div>
                    <div className="live-position-lot-card__slots">{group.slots.join(" / ")}</div>
                  </div>
                );
              })}
              {!stockLotGroups.length ? <div className="summary-item__body">{t("当前没有持仓lot。")}</div> : null}
            </div>
          </div>
          {selectedStockGroup ? (
            <div className="live-position-stock-detail" aria-label={t("选中股票 Slot 和 Lot 明细")}>
              <div className="live-position-lot-summary__head">
                <strong>{t("按股票汇总 · {v0} {v1}", { v0: selectedStockGroup.stockCode, v1: selectedStockGroup.stockName || "" }).trim()}</strong>
                <span>{t("{v0} 个slot · {v1} 个lot组 · {v2} lots", { v0: selectedStockGroup.slots.length, v1: selectedStockLots.length, v2: selectedStockGroup.lotCount })}</span>
              </div>
              <div className="replay-capital-all-lots__grid replay-capital-all-lots__grid--stock-detail">
                {selectedStockLots.map((lot) => (
                  <div className="replay-capital-inspector__lot" key={`${lot.slotIndex}-${lot.id}`}>
                    <div>
                      <Link className="replay-capital-stock-link" to={`/portfolio/position/${lot.stockCode}`}>
                        {`${lot.stockCode} ${lot.stockName || ""}`.trim()}
                      </Link>
                      <strong>{lot.slotTitle}</strong>
                    </div>
                    {renderLotPriceLine(lot)}
                    <div>
                      <span>{t("{v0} lot · {v1}股 · {v2}", { v0: lot.lotCount, v1: lot.quantity, v2: localizeLotStatus(lot.status) })}</span>
                      <span>{t("占用 {v0}", { v0: lot.allocatedCash })}</span>
                      <span>{t("可卖 {v0} · 锁定 {v1}", { v0: lot.sellableQuantity ?? 0, v1: lot.lockedQuantity ?? 0 })}</span>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          ) : null}
          <div className="replay-capital-all-lots__section-title">{t("Slot / Lot 分布")}</div>
          <div className="replay-capital-all-lots__grid">
            {allLots.map((lot) => (
              <div className="replay-capital-inspector__lot" key={`${lot.slotIndex}-${lot.id}`}>
                <div>
                  <Link className="replay-capital-stock-link" to={`/portfolio/position/${lot.stockCode}`}>
                    {`${lot.stockCode} ${lot.stockName || ""}`.trim()}
                  </Link>
                  <strong>{lot.slotTitle}</strong>
                </div>
                {renderLotPriceLine(lot)}
                <div>
                  <span>{t("{v0} lot · {v1}股 · {v2}", { v0: lot.lotCount, v1: lot.quantity, v2: localizeLotStatus(lot.status) })}</span>
                  <span>{t("占用 {v0}", { v0: lot.allocatedCash })}</span>
                  <span>{t("可卖 {v0} · 锁定 {v1}", { v0: lot.sellableQuantity ?? 0, v1: lot.lockedQuantity ?? 0 })}</span>
                </div>
              </div>
            ))}
            {!allLots.length ? <div className="summary-item__body">{t("当前检查点没有lot。")}</div> : null}
          </div>
        </div>
      ) : null}

      {!viewCapitalPool.pool.poolReady || !viewCapitalPool.slots.length ? (
        <div className="summary-item summary-item--accent" style={{ marginTop: "12px" }}>
          <div className="summary-item__title">{t("资金池未形成slot")}</div>
          <div className="summary-item__body">{t("当前回放资金低于量化资金池下限，或任务尚未写入slot/lot快照。")}</div>
        </div>
      ) : (
        <div className="replay-capital-layout">
          <div className="replay-capital-pool-board">
            {slotTotal > SLOT_PAGE_SIZE ? (
              <div className="replay-capital-slot-toolbar">
                <span>{`Slot ${slotRangeStart}-${slotRangeEnd} / ${slotTotal}`}</span>
                <div>
                  <button
                    type="button"
                    className="icon-button icon-button--neutral"
                    aria-label={t("上一组 Slot")}
                    disabled={currentSlotPage <= 1}
                    onClick={() => setSlotPage((page) => Math.max(1, page - 1))}
                  >
                    ←
                  </button>
                  <button
                    type="button"
                    className="icon-button icon-button--neutral"
                    aria-label={t("下一组 Slot")}
                    disabled={currentSlotPage >= slotTotalPages}
                    onClick={() => setSlotPage((page) => Math.min(slotTotalPages, page + 1))}
                  >
                    →
                  </button>
                </div>
              </div>
            ) : null}
            <div className="replay-capital-slot-grid">
              {visibleSlots.map((slot) => (
                <button
                  type="button"
                  key={slot.id}
                  className={`replay-capital-slot ${slotStatusClass(slot.status)} ${slotUsageClass(slot.status, slot.usagePct)} ${selectedSlot?.index === slot.index ? "is-selected" : ""}`}
                  onClick={() => setSelectedSlotIndex(slot.index)}
                >
                  <div className="replay-capital-slot__head">
                    <strong>{slot.title}</strong>
                    <span>{localizeSlotStatus(slot.status)}</span>
                  </div>
                  <div className="replay-capital-slot__money">
                    <span>{t("占用 {v0}", { v0: slot.occupiedCash })}</span>
                    <span>{t("可用 {v0}", { v0: slot.availableCash })}</span>
                  </div>
                  <div className="replay-capital-slot__bar" aria-label={t("{v0} 使用率 {v1}%", { v0: slot.title, v1: slot.usagePct })}>
                    <span style={{ width: `${Math.max(0, Math.min(slot.usagePct || 0, 100))}%` }} />
                  </div>
                  <div className="replay-capital-slot__lots">
                    {slot.lots.slice(0, 3).map((lot) => (
                      <div className={`replay-capital-lot-card ${lot.isStack ? "replay-capital-lot-card--stack" : ""}`} key={lot.id}>
                        <div className="replay-capital-lot-card__top">
                          <Link className="replay-capital-stock-link" to={`/portfolio/position/${lot.stockCode}`}>
                            {`${lot.stockCode} ${lot.stockName || ""}`.trim()}
                          </Link>
                          <em className={lotStatusClass(lot.status)}>{localizeLotStatus(lot.status)}</em>
                        </div>
                        <strong>{t("{v0} lot · {v1} 股", { v0: lot.lotCount, v1: lot.quantity })}</strong>
                        {renderLotPriceLine(lot)}
                        <small>{t("{v0} {v1} · 占用 {v2}", { v0: lotValueLabel(lot), v1: lot.marketValue, v2: lot.allocatedCash })}</small>
                      </div>
                    ))}
                    {slot.hiddenLotGroups ? <div className="replay-capital-lot-more">{t("+{v0} 个lot组", { v0: slot.hiddenLotGroups })}</div> : null}
                    {!slot.lots.length ? <div className="replay-capital-slot__empty">{t("空槽，等待强信号占用")}</div> : null}
                  </div>
                </button>
              ))}
            </div>
          </div>

          <aside className="replay-capital-inspector">
            <div className="summary-item__title">{selectedSlot?.title ?? "Slot"}</div>
            <div className="replay-capital-inspector__metrics">
              <span>{t("预算 {v0}", { v0: selectedSlot?.budgetCash ?? "--" })}</span>
              <span>{t("占用 {v0}", { v0: selectedSlot?.occupiedCash ?? "--" })}</span>
              <span>{t("可用 {v0}", { v0: selectedSlot?.availableCash ?? "--" })}</span>
            </div>
            <div className="replay-capital-inspector__title">{t("Lot 明细")}</div>
            <div className="replay-capital-inspector__lots">
              {(selectedSlot?.lots ?? []).map((lot) => (
                <div className="replay-capital-inspector__lot" key={lot.id}>
                  <div>
                    <Link className="replay-capital-stock-link" to={`/portfolio/position/${lot.stockCode}`}>
                      {`${lot.stockCode} ${lot.stockName || ""}`.trim()}
                    </Link>
                    <span>{t("{v0} lot · {v1}股 · {v2}", { v0: lot.lotCount, v1: lot.quantity, v2: localizeLotStatus(lot.status) })}</span>
                  </div>
                  {renderLotPriceLine(lot)}
                  <div>
                    <span>{t("占用 {v0}", { v0: lot.allocatedCash })}</span>
                    <span>{t("可卖 {v0} · 锁定 {v1}", { v0: lot.sellableQuantity ?? 0, v1: lot.lockedQuantity ?? 0 })}</span>
                  </div>
                </div>
              ))}
              {!selectedSlot?.lots?.length ? <div className="summary-item__body">{t("当前slot没有lot。")}</div> : null}
            </div>
          </aside>
        </div>
      )}
    </WorkbenchCard>
  );
}
