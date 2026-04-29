import { fireEvent, render, screen, waitFor } from "@testing-library/react";
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
    columns: ["代码", "名称", "来源", "价格"],
    rows: [
      {
        id: "600519",
        cells: ["600519", "贵州茅台", "watchlist-source", "1453.96"],
        code: "600519",
        name: "贵州茅台",
        actions: [
          { label: "分析候选股", action: "analyze-candidate", icon: "🔎", tone: "accent" },
          { label: "删除候选股", action: "delete-candidate", icon: "🗑", tone: "danger" },
        ],
      },
    ],
    emptyLabel: "暂无数据",
    emptyMessage: "暂无数据",
  },
  pendingSignals: [],
  executionCenter: {
    title: "执行中心",
    body: "暂无待执行信号",
    chips: ["类别不应展示"],
  },
  capitalPool: {
    task: {
      runId: "live",
      status: "running",
    },
    pool: {
      initialCash: "100000.00",
      cashValue: "52000.00",
      marketValue: "48000.00",
      totalEquity: "100000.00",
      realizedPnl: "0.00",
      unrealizedPnl: "0.00",
      slotCount: 2,
      slotBudget: "50000.00",
      availableCash: "52000.00",
      occupiedCash: "48000.00",
      settlingCash: "0.00",
      poolReady: true,
    },
    selectedSlotIndex: 1,
    slots: [
      {
        id: "slot-1",
        index: 1,
        title: "Slot 01",
        status: "occupied",
        budgetCash: "50000.00",
        availableCash: "0.00",
        occupiedCash: "48000.00",
        settlingCash: "0.00",
        usagePct: 96,
        lots: [
          {
            id: "lot-1",
            stockCode: "600519",
            stockName: "贵州茅台",
            lotCount: 2,
            quantity: 200,
            sellableQuantity: 100,
            lockedQuantity: 100,
            allocatedCash: "48000.00",
            marketValue: "50000.00",
            costBand: "240.00",
            priceBasis: "market",
            status: "mixed",
          },
        ],
      },
      {
        id: "slot-2",
        index: 2,
        title: "Slot 02",
        status: "free",
        budgetCash: "50000.00",
        availableCash: "50000.00",
        occupiedCash: "0.00",
        settlingCash: "0.00",
        usagePct: 0,
        lots: [],
      },
    ],
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
                  columns: [
                    "时间",
                    "代码",
                    "动作",
                    "类型",
                    "数量",
                    "价格",
                    "成交毛额",
                    "手续费",
                    "印花税",
                    "总费用",
                    "现金影响",
                    "盈亏",
                    "盈亏率",
                    "Slot用量",
                    "执行明细",
                    "备注",
                  ],
                  rows: [
                    {
                      id: "trade-1",
                      cells: [
                        "2026-04-23 23:25:00",
                        "600519",
                        "BUY",
                        "开仓",
                        "100",
                        "1453.96",
                        "145396.00",
                        "43.62",
                        "0.00",
                        "43.62",
                        "-145439.62",
                        "--",
                        "--",
                        "1 slot",
                        "占用 Slot 01",
                        "自动执行备注",
                      ],
                      code: "600519",
                      name: "贵州茅台",
                    },
                  ],
                }
              : {
                  columns: ["信号ID", "时间", "代码", "动作", "策略", "状态"],
                  rows: [
                    {
                      id: "9001",
                      cells: ["#9001", "2026-04-23 23:20:00", "600000 浦发银行", "BUY", "aggressive", "已执行"],
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
    fireEvent.change(screen.getByLabelText("初始资金池(元)"), { target: { value: "500000" } });
    fireEvent.click(screen.getByRole("button", { name: "保存" }));
    await waitFor(() => {
      expect(client.runPageAction).toHaveBeenCalledWith("live-sim", "save", expect.objectContaining({ initialCash: 500000 }));
    });
    expect(screen.getAllByRole("link", { name: "600519" })[0]).toHaveAttribute("href", "/portfolio/position/600519");
    expect(screen.queryByRole("columnheader", { name: "来源" })).not.toBeInTheDocument();
    expect(screen.queryByText("watchlist-source")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "分析候选股" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "删除候选股" }));
    await waitFor(() => {
      expect(client.runPageAction).toHaveBeenCalledWith("live-sim", "delete-candidate", "600519");
    });
    expect(await screen.findByRole("link", { name: "600000 浦发银行" })).toHaveAttribute("href", "/portfolio/position/600000");
    expect(screen.getByRole("link", { name: "#9001" })).toHaveAttribute("href", "/signal-detail/9001?source=live");
    expect(screen.queryByText("执行中心")).not.toBeInTheDocument();
    expect(screen.queryByText("类别不应展示")).not.toBeInTheDocument();
    expect(screen.getAllByText("600519 贵州茅台").length).toBeGreaterThan(0);
    expect(screen.getByText("2 lots")).toBeInTheDocument();
    expect(screen.getAllByText("Slot 01").length).toBeGreaterThan(0);
    expect(screen.getAllByText("成本 240.00 · 现价 250.00").length).toBeGreaterThan(0);
    expect(screen.queryByRole("columnheader", { name: "备注" })).not.toBeInTheDocument();
    expect(await screen.findByText("占用 Slot 01 · 自动执行备注")).toBeInTheDocument();
    const signalSection = screen.getByText("信号记录").closest(".section-card");
    const capitalSection = screen.getByText("资金池总览").closest(".section-card");
    expect(signalSection?.compareDocumentPosition(capitalSection as Node)).toBe(Node.DOCUMENT_POSITION_FOLLOWING);
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
