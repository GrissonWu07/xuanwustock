import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { ReplayCapitalPoolPanel } from "../features/quant/replay-capital-pool-panel";
import type { ReplayCapitalPool } from "../lib/page-models";

function buildCapitalPool(slotCount: number): ReplayCapitalPool {
  return {
    task: {
      runId: "26",
      status: "completed",
      checkpoint: "2026-04-10 15:00:00",
    },
    pool: {
      initialCash: "100000.00",
      cashValue: "12000.00",
      marketValue: "88000.00",
      totalEquity: "100000.00",
      realizedPnl: "0.00",
      unrealizedPnl: "0.00",
      slotCount,
      slotBudget: "20000.00",
      availableCash: "12000.00",
      occupiedCash: "88000.00",
      settlingCash: "0.00",
      poolReady: true,
    },
    selectedSlotIndex: 1,
    slots: Array.from({ length: slotCount }, (_, index) => {
      const slotIndex = index + 1;
      return {
        id: `slot-${slotIndex}`,
        index: slotIndex,
        title: `Slot ${String(slotIndex).padStart(2, "0")}`,
        status: slotIndex <= 6 ? "occupied" : "free",
        budgetCash: "20000.00",
        availableCash: slotIndex <= 6 ? "0.00" : "20000.00",
        occupiedCash: slotIndex <= 6 ? "20000.00" : "0.00",
        settlingCash: "0.00",
        usagePct: slotIndex <= 6 ? 100 : 0,
        hiddenLotGroups: 0,
        lots: [],
      };
    }),
  };
}

describe("ReplayCapitalPoolPanel", () => {
  it("shows six slots by default and pages through additional slots", () => {
    render(
      <MemoryRouter>
        <ReplayCapitalPoolPanel capitalPool={buildCapitalPool(8)} />
      </MemoryRouter>,
    );

    expect(screen.getAllByText("Slot 01").length).toBeGreaterThan(0);
    expect(screen.getByText("Slot 06")).toBeInTheDocument();
    expect(screen.queryAllByText("Slot 07")).toHaveLength(0);
    expect(screen.getByText("Slot 1-6 / 8")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "下一组 Slot" }));

    expect(screen.getAllByText("Slot 07").length).toBeGreaterThan(0);
    expect(screen.getByText("Slot 08")).toBeInTheDocument();
    expect(screen.queryAllByText("Slot 01")).toHaveLength(0);
    expect(screen.getByText("Slot 7-8 / 8")).toBeInTheDocument();
  });
});
