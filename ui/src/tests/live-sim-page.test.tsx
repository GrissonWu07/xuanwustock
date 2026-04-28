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
    strategyProfileId: "aggressive",
    aiDynamicStrategy: "hybrid",
    aiDynamicStrength: "0.5",
    aiDynamicLookback: "48",
    strategyProfiles: [{ id: "aggressive", name: "积极", enabled: true, isDefault: true }],
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
  candidatePool: {
    columns: ["代码", "名称", "价格"],
    rows: [
      {
        id: "600519",
        cells: ["600519", "贵州茅台", "1453.96"],
        code: "600519",
        name: "贵州茅台",
      },
    ],
    emptyLabel: "暂无数据",
    emptyMessage: "暂无数据",
  },
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
    [
      { path: "/live-sim", element: <LiveSimPage client={client} /> },
      { path: "/portfolio/position/:symbol", element: <div data-testid="stock-detail-page" /> },
    ],
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
      vi.fn().mockImplementation((url: string) =>
        Promise.resolve({
          ok: true,
          json: async () => ({
            table: String(url).includes("/trades")
              ? {
                  columns: ["时间", "代码", "动作", "数量", "价格", "备注"],
                  rows: [],
                }
              : {
                  columns: ["信号ID", "时间", "代码", "动作", "策略", "状态"],
                  rows: [
                    {
                      id: "9001",
                      cells: ["#9001", "2026-04-23 23:20:00", "600000 浦发银行", "BUY", "aggressive", "已落库"],
                      code: "600000",
                      name: "浦发银行",
                      actions: [{ label: "详情", action: "show-signal-detail", icon: "→", tone: "accent" }],
                    },
                  ],
                },
          }),
        }),
      ),
    );

    renderLiveSimPage(client);

    await screen.findByText("信号记录");
    expect(screen.getByRole("link", { name: "600519" })).toHaveAttribute("href", "/portfolio/position/600519");
    expect(await screen.findByRole("link", { name: "600000 浦发银行" })).toHaveAttribute("href", "/portfolio/position/600000");
    expect(screen.getAllByText("策略配置")).toHaveLength(1);
    expect(screen.queryByText("资金池最低(元)")).not.toBeInTheDocument();
    expect(screen.queryByText("资金池最高(元)")).not.toBeInTheDocument();
    expect(screen.queryByText("单Slot最低(元)")).not.toBeInTheDocument();
    expect(screen.queryByText("卖出资金复用")).not.toBeInTheDocument();
    expect(screen.queryByText("启用Slot资金管理")).not.toBeInTheDocument();
    expect(screen.queryByText("自动执行模拟交易")).not.toBeInTheDocument();
    expect(screen.queryByText("弱BUY最小Slot比例")).not.toBeInTheDocument();
    expect(screen.queryByText("Slot下限")).not.toBeInTheDocument();
    expect(screen.queryByRole("columnheader", { name: "策略" })).not.toBeInTheDocument();
    expect(await screen.findByRole("columnheader", { name: "状态" })).toBeInTheDocument();
  });
});
