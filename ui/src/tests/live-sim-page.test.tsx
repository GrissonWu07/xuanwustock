import { render, screen } from "@testing-library/react";
import { RouterProvider, createMemoryRouter } from "react-router-dom";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import type { ApiClient } from "../lib/api-client";
import { LiveSimPage } from "../features/quant/live-sim-page";

const emptyTable = {
  columns: ["代码", "名称", "价格"],
  rows: [],
  emptyLabel: "暂无数据",
  emptyMessage: "暂无数据",
};

const snapshot = {
  updatedAt: "2026-04-23 23:30:00",
  config: {
    interval: "15 分钟",
    timeframe: "30m",
    strategyMode: "auto",
    strategyProfileId: "aggressive_v23",
    aiDynamicStrategy: "hybrid",
    aiDynamicStrength: "0.5",
    aiDynamicLookback: "48",
    strategyProfiles: [{ id: "aggressive_v23", name: "积极", enabled: true, isDefault: true }],
    autoExecute: "true",
    market: "CN",
    initialCapital: "100000",
    commissionRatePct: "0.03",
    sellTaxRatePct: "0.10",
  },
  status: {
    running: "运行中",
    lastRun: "2026-04-23 23:15:00",
    nextRun: "2026-04-23 23:30:00",
    candidateCount: "3",
  },
  metrics: [],
  candidatePool: emptyTable,
  pendingSignals: [],
  executionCenter: {
    title: "执行中心",
    body: "暂无待执行信号",
    chips: [],
  },
  holdings: emptyTable,
  trades: emptyTable,
  curve: [],
};

beforeAll(() => {
  Object.defineProperty(window, "matchMedia", {
    writable: true,
    value: vi.fn().mockImplementation(() => ({
      matches: false,
      media: "(max-width: 1200px)",
      onchange: null,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      addListener: vi.fn(),
      removeListener: vi.fn(),
      dispatchEvent: vi.fn(),
    })),
  });
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

function renderLiveSimPage(client: ApiClient) {
  const router = createMemoryRouter(
    [{ path: "/live-sim", element: <LiveSimPage client={client} /> }],
    { initialEntries: ["/live-sim"] },
  );

  render(<RouterProvider router={router} />);
}

describe("LiveSimPage", () => {
  it("hides strategy from the live summary metric and signal list", async () => {
    const client = {
      getPageSnapshot: vi.fn().mockResolvedValue(snapshot),
      runPageAction: vi.fn().mockResolvedValue(snapshot),
    } as unknown as ApiClient;

    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({
          table: {
            columns: ["信号ID", "时间", "代码", "动作", "策略", "状态"],
            rows: [
              {
                id: "9001",
                cells: ["#9001", "2026-04-23 23:20:00", "600000 浦发银行", "BUY", "aggressive_v23", "已落库"],
                code: "600000",
                name: "浦发银行",
                actions: [{ label: "详情", action: "show-signal-detail", icon: "→", tone: "accent" }],
              },
            ],
          },
        }),
      }),
    );

    renderLiveSimPage(client);

    await screen.findByText("信号记录");
    expect(screen.getAllByText("策略配置")).toHaveLength(1);
    expect(screen.queryByRole("columnheader", { name: "策略" })).not.toBeInTheDocument();
    expect(await screen.findByRole("columnheader", { name: "状态" })).toBeInTheDocument();
  });
});
