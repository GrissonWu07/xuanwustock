import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { WorkbenchCard } from "../../components/ui/workbench-card";
import type { ReplayCapitalLot, ReplayCapitalPool, ReplayCapitalPoolSnapshot } from "../../lib/page-models";

const CHECKPOINT_PAGE_SIZE = 50;
type CheckpointQuery = Record<string, string | number>;

function localizeSlotStatus(status: string) {
  const normalized = String(status || "").trim().toLowerCase();
  if (normalized === "occupied") return "占用";
  if (normalized === "settling") return "待结算";
  if (normalized === "free") return "空闲";
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
  if (normalized === "locked") return "T+1锁定";
  if (normalized === "mixed") return "部分可卖";
  if (normalized === "settling") return "结算中";
  if (normalized === "available") return "可卖";
  return status || "--";
}

type LotWithSlot = ReplayCapitalLot & {
  slotTitle: string;
  slotIndex: number;
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

function lotPriceInfo(lot: ReplayCapitalLot) {
  const cost = parseDisplayNumber(lot.costBand);
  const marketValue = parseDisplayNumber(lot.marketValue);
  const quantity = Number(lot.quantity || 0);
  const hasMarketPrice = String(lot.priceBasis || "").trim().toLowerCase() === "market";
  const current = marketValue !== null && quantity > 0 ? marketValue / quantity : null;
  if (!hasMarketPrice) {
    return {
      priceText: `成本价 ${formatPrice(cost)}`,
      trendText: "",
      trendClass: "is-flat",
    };
  }
  if (cost === null || current === null || cost <= 0) {
    return {
      priceText: `成本 ${formatPrice(cost)} · 现价 ${formatPrice(current)}`,
      trendText: "",
      trendClass: "is-flat",
    };
  }
  const pct = ((current - cost) / cost) * 100;
  if (Math.abs(pct) < 0.005) {
    return {
      priceText: `成本 ${formatPrice(cost)} · 现价 ${formatPrice(current)}`,
      trendText: "平 0.00%",
      trendClass: "is-flat",
    };
  }
  return {
    priceText: `成本 ${formatPrice(cost)} · 现价 ${formatPrice(current)}`,
    trendText: pct > 0 ? `涨 +${pct.toFixed(2)}%` : `跌 ${pct.toFixed(2)}%`,
    trendClass: pct > 0 ? "is-up" : "is-down",
  };
}

function lotValueLabel(lot: ReplayCapitalLot) {
  return String(lot.priceBasis || "").trim().toLowerCase() === "market" ? "市值" : "成本市值";
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

export function ReplayCapitalPoolPanel({
  capitalPool,
  loadCheckpoint,
}: {
  capitalPool: ReplayCapitalPool;
  loadCheckpoint?: (query: CheckpointQuery) => Promise<ReplayCapitalPoolSnapshot>;
}) {
  const [checkpointSnapshot, setCheckpointSnapshot] = useState<ReplayCapitalPoolSnapshot | null>(null);
  const viewCapitalPool = checkpointSnapshot?.capitalPool ?? capitalPool;
  const defaultSlotIndex = viewCapitalPool.selectedSlotIndex ?? viewCapitalPool.slots[0]?.index ?? 0;
  const [selectedSlotIndex, setSelectedSlotIndex] = useState(defaultSlotIndex);
  const [checkpointPage, setCheckpointPage] = useState(1);
  const [checkpointLoading, setCheckpointLoading] = useState(false);
  const [checkpointError, setCheckpointError] = useState("");
  const [showAllLots, setShowAllLots] = useState(false);

  useEffect(() => {
    setSelectedSlotIndex(defaultSlotIndex);
  }, [viewCapitalPool.task.runId, defaultSlotIndex]);

  useEffect(() => {
    setCheckpointSnapshot(null);
    setCheckpointPage(1);
    setCheckpointError("");
    setShowAllLots(false);
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
      setCheckpointError(error instanceof Error ? error.message : "检查点资金池加载失败");
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

  return (
    <WorkbenchCard>
      <div className="replay-capital-header">
        <div>
          <h2 className="section-card__title">资金池总览</h2>
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
            <span className="field__label">检查点</span>
            <select
              className="input"
              value={selectedCheckpointAt}
              aria-label="检查点"
              disabled={checkpointLoading || !checkpointItems.length}
              onChange={(event) => void loadCheckpointPage(checkpointPage, event.target.value)}
            >
              {checkpointItems.length ? (
                checkpointItems.map((item) => (
                  <option key={item.id} value={item.checkpointAt}>
                    {`${item.label} · 权益 ${item.totalEquity ?? "--"}`}
                  </option>
                ))
              ) : (
                <option value={selectedCheckpointAt}>{selectedCheckpointAt || "暂无检查点"}</option>
              )}
            </select>
          </label>
          <div className="replay-capital-checkpoint-toolbar__pager">
            <button
              type="button"
              className="icon-button icon-button--neutral"
              aria-label="上一组检查点"
              disabled={checkpointLoading || !checkpointPagination || checkpointPagination.page <= 1}
              onClick={() => void loadCheckpointPage(Math.max(1, checkpointPage - 1))}
            >
              ←
            </button>
            <span>{checkpointPagination ? `第 ${checkpointPagination.page} / ${checkpointPagination.totalPages} 页` : "第 -- / -- 页"}</span>
            <button
              type="button"
              className="icon-button icon-button--neutral"
              aria-label="下一组检查点"
              disabled={checkpointLoading || !checkpointPagination || checkpointPagination.page >= checkpointPagination.totalPages}
              onClick={() => void loadCheckpointPage(checkpointPage + 1)}
            >
              →
            </button>
          </div>
          {checkpointLoading ? <span className="badge badge--neutral">加载中</span> : null}
          {checkpointError ? <span className="badge badge--danger">{checkpointError}</span> : null}
        </div>
      ) : null}

      <div className="mini-metric-grid replay-capital-metrics">
        <div className="mini-metric">
          <div className="mini-metric__label">现金</div>
          <div className="mini-metric__value">{viewCapitalPool.pool.cashValue}</div>
        </div>
        <div className="mini-metric">
          <div className="mini-metric__label">持仓市值</div>
          <div className="mini-metric__value">{viewCapitalPool.pool.marketValue}</div>
        </div>
        <div className="mini-metric">
          <div className="mini-metric__label">总权益</div>
          <div className="mini-metric__value">{viewCapitalPool.pool.totalEquity}</div>
        </div>
        <div className="mini-metric">
          <div className="mini-metric__label">Slot预算</div>
          <div className="mini-metric__value">{viewCapitalPool.pool.slotBudget}</div>
        </div>
      </div>

      {showAllLots ? (
        <div className="replay-capital-all-lots" aria-label="全部 Lot 明细">
          <div className="replay-capital-all-lots__head">
            <strong>全部 Lot 明细</strong>
            <span>{`${allLots.length} 个lot组 · ${totalLots} lots`}</span>
          </div>
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
                  <span>{`${lot.lotCount} lot · ${lot.quantity}股 · ${localizeLotStatus(lot.status)}`}</span>
                  <span>{`占用 ${lot.allocatedCash}`}</span>
                  <span>{`可卖 ${lot.sellableQuantity ?? 0} · 锁定 ${lot.lockedQuantity ?? 0}`}</span>
                </div>
              </div>
            ))}
            {!allLots.length ? <div className="summary-item__body">当前检查点没有lot。</div> : null}
          </div>
        </div>
      ) : null}

      {!viewCapitalPool.pool.poolReady || !viewCapitalPool.slots.length ? (
        <div className="summary-item summary-item--accent" style={{ marginTop: "12px" }}>
          <div className="summary-item__title">资金池未形成slot</div>
          <div className="summary-item__body">当前回放资金低于量化资金池下限，或任务尚未写入slot/lot快照。</div>
        </div>
      ) : (
        <div className="replay-capital-layout">
          <div className="replay-capital-pool-board">
            <div className="replay-capital-slot-grid">
              {viewCapitalPool.slots.map((slot) => (
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
                    <span>{`占用 ${slot.occupiedCash}`}</span>
                    <span>{`可用 ${slot.availableCash}`}</span>
                  </div>
                  <div className="replay-capital-slot__bar" aria-label={`${slot.title} 使用率 ${slot.usagePct}%`}>
                    <span style={{ width: `${Math.max(0, Math.min(slot.usagePct || 0, 100))}%` }} />
                  </div>
                  <div className="replay-capital-slot__lots">
                    {slot.lots.slice(0, 3).map((lot) => (
                      <div className={`replay-capital-lot-card ${lot.isStack ? "replay-capital-lot-card--stack" : ""}`} key={lot.id}>
                        <div className="replay-capital-lot-card__top">
                          <Link className="replay-capital-stock-link" to={`/portfolio/position/${lot.stockCode}`}>
                            {`${lot.stockCode} ${lot.stockName || ""}`.trim()}
                          </Link>
                          <em>{localizeLotStatus(lot.status)}</em>
                        </div>
                        <strong>{`${lot.lotCount} lot · ${lot.quantity} 股`}</strong>
                        {renderLotPriceLine(lot)}
                        <small>{`${lotValueLabel(lot)} ${lot.marketValue} · 占用 ${lot.allocatedCash}`}</small>
                      </div>
                    ))}
                    {slot.hiddenLotGroups ? <div className="replay-capital-lot-more">{`+${slot.hiddenLotGroups} 个lot组`}</div> : null}
                    {!slot.lots.length ? <div className="replay-capital-slot__empty">空槽，等待强信号占用</div> : null}
                  </div>
                </button>
              ))}
            </div>
          </div>

          <aside className="replay-capital-inspector">
            <div className="summary-item__title">{selectedSlot?.title ?? "Slot"}</div>
            <div className="replay-capital-inspector__metrics">
              <span>{`预算 ${selectedSlot?.budgetCash ?? "--"}`}</span>
              <span>{`占用 ${selectedSlot?.occupiedCash ?? "--"}`}</span>
              <span>{`可用 ${selectedSlot?.availableCash ?? "--"}`}</span>
            </div>
            <div className="replay-capital-inspector__title">Lot 明细</div>
            <div className="replay-capital-inspector__lots">
              {(selectedSlot?.lots ?? []).map((lot) => (
                <div className="replay-capital-inspector__lot" key={lot.id}>
                  <div>
                    <Link className="replay-capital-stock-link" to={`/portfolio/position/${lot.stockCode}`}>
                      {`${lot.stockCode} ${lot.stockName || ""}`.trim()}
                    </Link>
                    <span>{`${lot.lotCount} lot · ${lot.quantity}股 · ${localizeLotStatus(lot.status)}`}</span>
                  </div>
                  {renderLotPriceLine(lot)}
                  <div>
                    <span>{`占用 ${lot.allocatedCash}`}</span>
                    <span>{`可卖 ${lot.sellableQuantity ?? 0} · 锁定 ${lot.lockedQuantity ?? 0}`}</span>
                  </div>
                </div>
              ))}
              {!selectedSlot?.lots?.length ? <div className="summary-item__body">当前slot没有lot。</div> : null}
            </div>
          </aside>
        </div>
      )}
    </WorkbenchCard>
  );
}
