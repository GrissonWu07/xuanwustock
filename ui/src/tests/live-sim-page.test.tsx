import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { RouterProvider, createMemoryRouter } from "react-router-dom";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import type { ApiClient } from "../lib/api-client";
import { LiveSimPage } from "../features/quant/live-sim-page";

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
    initialCapital: "120000",
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
  tradeCostSummary: [
    { label: "交易笔数", value: "2" },
    { label: "胜率", value: "50.0%" },
    { label: "买入笔数", value: "1" },
    { label: "卖出笔数", value: "1" },
    { label: "买入毛额", value: "145396.00" },
    { label: "卖出毛额", value: "148000.00" },
    { label: "买入总成本", value: "145439.62" },
    { label: "卖出到账", value: "147808.38" },
    { label: "手续费", value: "88.02" },
    { label: "印花税", value: "148.00" },
    { label: "总费用", value: "236.02" },
    { label: "实现盈亏", value: "2368.76" },
    { label: "买入lot", value: "2" },
    { label: "卖出lot", value: "1" },
    { label: "剩余lot", value: "1" },
  ],
};

const lifecycleSnapshot = {
  ...snapshot,
  candidatePool: {
    ...snapshot.candidatePool,
    rows: [
      {
        id: "600001",
        cells: ["600001", "观察股", "discover", "10.00"],
        code: "600001",
        name: "观察股",
        lifecycle: {
          quant_status: "trial",
          health_score: 82,
          latest_reason: "新发现已进入量化",
          quant_auto_managed: true,
          quant_manual_override: "",
        },
      },
      {
        id: "600002",
        cells: ["600002", "正常股", "discover", "11.00"],
        code: "600002",
        name: "正常股",
        lifecycle: {
          quant_status: "active",
          health_score: 68,
          latest_reason: "趋势确认后正常扫描",
          quant_auto_managed: true,
          quant_manual_override: "",
        },
      },
      {
        id: "600003",
        cells: ["600003", "只出场股", "discover", "12.00"],
        code: "600003",
        name: "只出场股",
        lifecycle: {
          quant_status: "exit_only",
          health_score: 31,
          latest_reason: "趋势转弱，仅允许出场",
          quant_auto_managed: true,
          quant_manual_override: "",
        },
      },
      {
        id: "600004",
        cells: ["600004", "冷却股", "discover", "13.00"],
        code: "600004",
        name: "冷却股",
        lifecycle: {
          quant_status: "cooling",
          health_score: 22,
          latest_reason: "连续下行进入冷却",
          quant_auto_managed: true,
          quant_manual_override: "",
        },
      },
      {
        id: "600005",
        cells: ["600005", "暂停股", "manual", "14.00"],
        code: "600005",
        name: "暂停股",
        lifecycle: {
          quant_status: "manual_paused",
          health_score: 55,
          latest_reason: "用户手工暂停",
          quant_auto_managed: false,
          quant_manual_override: "manual_pause",
        },
      },
      {
        id: "600006",
        cells: ["600006", "退出股", "discover", "15.00"],
        code: "600006",
        name: "退出股",
        lifecycle: {
          quant_status: "retired",
          health_score: 10,
          latest_reason: "长期无有效买点退出",
          quant_auto_managed: true,
          quant_manual_override: "",
        },
      },
    ],
  },
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

const emptySignalTable = () => ({
  columns: ["信号ID", "时间", "代码", "动作", "状态"],
  rows: [],
  emptyLabel: "暂无信号",
});

const emptyTradeTable = () => ({
  columns: ["时间", "代码", "动作", "数量", "价格", "备注"],
  rows: [],
  emptyLabel: "暂无交易记录",
});

describe("LiveSimPage", () => {
  it("renders lifecycle summary, status chips, health fields, and scoped restore actions", async () => {
    const fetchMock = vi.fn().mockImplementation((url: string, options?: RequestInit) => {
      if (String(url).includes("/api/v1/quant/universe/settings")) {
        return Promise.resolve({
          ok: true,
          headers: new Headers({ "content-type": "application/json" }),
          json: async () => ({
            quant_universe_lifecycle_enabled: true,
            auto_entry_mode: "auto_trial",
            auto_exit_enabled: true,
          }),
        });
      }
      if (String(url).includes("/api/v1/quant/universe/actions/restore-to-trial")) {
        return Promise.resolve({
          ok: true,
          headers: new Headers({ "content-type": "application/json" }),
          json: async () => ({ stock_code: "600004", new_status: "trial" }),
        });
      }
      if (String(url).includes("/api/v1/quant/universe/actions/set-override")) {
        return Promise.resolve({
          ok: true,
          headers: new Headers({ "content-type": "application/json" }),
          json: async () => ({ stock_code: "600001", quant_status: "manual_paused", quant_auto_managed: false }),
        });
      }
      return Promise.resolve({
        ok: true,
        headers: new Headers({ "content-type": "application/json" }),
        json: async () => ({ table: String(url).includes("/trades") ? emptyTradeTable() : emptySignalTable() }),
      });
    });
    vi.stubGlobal("fetch", fetchMock);
    vi.spyOn(window, "confirm").mockReturnValue(true);
    const client = {
      getPageSnapshot: vi.fn().mockResolvedValue(lifecycleSnapshot),
      runPageAction: vi.fn().mockResolvedValue(lifecycleSnapshot),
    } as unknown as ApiClient;

    renderLiveSimPage(client);

    expect(await screen.findByText("基于评分的股票量化自动化：开启")).toBeInTheDocument();
    expect(screen.queryByText("生命周期开启")).not.toBeInTheDocument();
    expect(screen.queryByText("自动纳入观察")).not.toBeInTheDocument();
    expect(screen.queryByText("自动出池开启")).not.toBeInTheDocument();
    expect(screen.queryByRole("checkbox", { name: "量化生命周期" })).not.toBeInTheDocument();
    expect(screen.queryByLabelText("自动入池模式")).not.toBeInTheDocument();
    expect(screen.queryByRole("checkbox", { name: "自动出池" })).not.toBeInTheDocument();

    const statusFilter = screen.getByLabelText("生命周期状态筛选");
    const statusNames = [/量化|Quant/, /正常扫描/, /只出场/, /冷却/, /已退出/, /手工暂停/];
    statusNames.forEach((status) => expect(within(statusFilter).getByRole("button", { name: status })).toBeInTheDocument());
    expect(within(statusFilter).getByRole("button", { name: /量化|Quant/ })).toHaveAttribute("aria-pressed", "true");
    expect(within(statusFilter).getByRole("button", { name: /正常扫描/ })).toHaveAttribute("aria-pressed", "true");
    expect(within(statusFilter).getByRole("button", { name: /只出场/ })).toHaveAttribute("aria-pressed", "true");
    expect(within(statusFilter).getByRole("button", { name: /手工暂停/ })).toHaveAttribute("aria-pressed", "false");

    expect(screen.getByLabelText("健康 82")).toBeInTheDocument();
    expect(screen.queryByText("新发现已进入量化")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "恢复到量化 600001" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "恢复到量化 600002" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "恢复到量化 600003" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "暂停自动管理 600001" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "删除候选股" })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /冷却/ }));
    fireEvent.click(screen.getByRole("button", { name: /手工暂停/ }));
    fireEvent.click(screen.getByRole("button", { name: /已退出/ }));
    expect(screen.queryByRole("button", { name: "恢复到量化 600004" })).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "600004" })).toBeInTheDocument();
  });

  it("clears local signal, trade, and capital pool views after reset", async () => {
    const resetSnapshot = {
      ...snapshot,
      updatedAt: snapshot.updatedAt,
      capitalPool: {
        ...snapshot.capitalPool,
        pool: {
          ...snapshot.capitalPool.pool,
          slotCount: 0,
          slotBudget: "0.00",
          occupiedCash: "0.00",
          availableCash: "0.00",
          poolReady: false,
        },
        slots: [],
        selectedSlotIndex: null,
      },
    };
    const client = {
      getPageSnapshot: vi.fn().mockResolvedValue(snapshot),
      runPageAction: vi.fn().mockResolvedValue(resetSnapshot),
    } as unknown as ApiClient;

    vi.stubGlobal(
      "fetch",
      vi.fn().mockImplementation((url: string) =>
        Promise.resolve({
          ok: true,
          json: async () => ({
            table: String(url).includes("/trades")
              ? {
                  columns: ["时间", "代码", "动作", "执行明细"],
                  rows: [{ id: "trade-1", cells: ["2026-04-23 23:25:00", "600519", "BUY", "占用 Slot 01"], code: "600519", name: "贵州茅台" }],
                  emptyLabel: "暂无交易记录",
                }
              : {
                  columns: ["信号ID", "时间", "代码", "动作", "状态"],
                  rows: [{ id: "9001", cells: ["#9001", "2026-04-23 23:20:00", "600000 浦发银行", "BUY", "已执行"], code: "600000", name: "浦发银行" }],
                  emptyLabel: "暂无信号",
                },
          }),
        }),
      ),
    );

    renderLiveSimPage(client);

    expect(await screen.findByRole("link", { name: "#9001" })).toBeInTheDocument();
    expect(await screen.findByText("占用 Slot 01")).toBeInTheDocument();
    expect(screen.getAllByText("Slot 01").length).toBeGreaterThan(0);

    fireEvent.click(screen.getByRole("button", { name: "重置" }));

    await waitFor(() => {
      expect(client.runPageAction).toHaveBeenCalledWith("live-sim", "reset", expect.objectContaining({ initialCash: 120000 }));
    });
    expect(screen.queryByRole("link", { name: "#9001" })).not.toBeInTheDocument();
    expect(screen.queryByText("占用 Slot 01")).not.toBeInTheDocument();
    expect(screen.queryByText("Slot 01")).not.toBeInTheDocument();
    expect(screen.getByText("资金池未形成slot")).toBeInTheDocument();
  });

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
    await waitFor(() => expect(screen.getByDisplayValue("120000")).toBeInTheDocument());
    fireEvent.change(screen.getByDisplayValue("120000"), { target: { value: "500000" } });
    fireEvent.click(screen.getByRole("button", { name: "保存" }));
    await waitFor(() => {
      expect(client.runPageAction).toHaveBeenCalledWith("live-sim", "save", expect.objectContaining({ initialCash: 500000 }));
    });
    expect(screen.getAllByRole("link", { name: "600519" })[0]).toHaveAttribute("href", "/portfolio/position/600519");
    expect(screen.queryByRole("columnheader", { name: "来源" })).not.toBeInTheDocument();
    expect(screen.queryByText("watchlist-source")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "分析候选股" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "删除候选股" })).not.toBeInTheDocument();
    expect(await screen.findByRole("link", { name: "600000 浦发银行" })).toHaveAttribute("href", "/portfolio/position/600000");
    expect(screen.getByRole("link", { name: "#9001" })).toHaveAttribute("href", "/signal-detail/9001?source=live");
    expect(screen.queryByText("执行中心")).not.toBeInTheDocument();
    expect(screen.queryByText("类别不应展示")).not.toBeInTheDocument();
    expect(screen.getAllByText("600519 贵州茅台").length).toBeGreaterThan(0);
    expect(screen.getAllByText(/2 lot/).length).toBeGreaterThan(0);
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
    expect((await screen.findAllByRole("columnheader", { name: "状态" })).length).toBeGreaterThan(0);
    const executionSection = screen.getByLabelText("费用与执行统计");
    expect(within(executionSection).getByText("收益结果")).toBeInTheDocument();
    expect(within(executionSection).getByText("2368.76")).toBeInTheDocument();
    expect(within(executionSection).getByText("买入总成本")).toBeInTheDocument();
    expect(within(executionSection).getByText("卖出到账")).toBeInTheDocument();
    expect(within(executionSection).getByText("已扣手续费与印花税 · 交易笔数 2 · 胜率 50.0%")).toBeInTheDocument();
    expect(within(executionSection).getByText("成本拆解")).toBeInTheDocument();
    expect(within(executionSection).getByText("收入拆解")).toBeInTheDocument();
    expect(within(executionSection).getByText("交易背景")).toBeInTheDocument();
  });
});

