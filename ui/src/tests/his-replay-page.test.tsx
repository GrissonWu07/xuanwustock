import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { RouterProvider, createMemoryRouter } from "react-router-dom";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import type { ApiClient } from "../lib/api-client";
import { HisReplayPage } from "../features/quant/his-replay-page";

const emptyTable = {
  columns: ["时间", "代码", "动作"],
  rows: [],
  emptyLabel: "暂无数据",
  emptyMessage: "暂无数据",
};

const initialSnapshot = {
  updatedAt: "2026-04-23 22:00:00",
  config: {
    mode: "historical_range",
    range: "2026-04-01 -> 2026-04-10",
    timeframe: "30m",
    market: "CN",
    strategyMode: "auto",
    strategyProfileId: "aggressive",
    strategyProfiles: [
      { id: "aggressive", name: "积极", enabled: true, isDefault: true },
    ],
    aiDynamicStrategy: "hybrid",
    aiDynamicStrength: "0.5",
    aiDynamicLookback: "48",
    initialCapital: "50000",
    commissionRatePct: "0.03",
    sellTaxRatePct: "0.10",
  },
  metrics: [],
  candidatePool: emptyTable,
  tasks: [
    {
      id: "#101",
      runId: "101",
      status: "completed",
      stage: "已完成",
      progress: 100,
      progressCurrent: 12,
      progressTotal: 12,
      checkpointCount: 12,
      latestCheckpointAt: "2026-04-10 15:00:00",
      startAt: "2026-04-01 09:30:00",
      endAt: "2026-04-10 15:00:00",
      range: "2026-04-01 09:30:00 -> 2026-04-10 15:00:00",
      mode: "historical_range",
      timeframe: "30m",
      market: "CN",
      strategyMode: "auto",
      returnPct: "8.2%",
      finalEquity: "108200.00",
      cashValue: "68200",
      marketValue: "40000",
      realizedPnl: "7600",
      unrealizedPnl: "600",
      tradeCount: "14",
      winRate: "57.1%",
      sellWinRate: "57.1%",
      buyTradeCount: 7,
      sellTradeCount: 7,
      winningSellCount: 4,
      losingSellCount: 3,
      avgWin: "1800",
      avgLoss: "-950",
      payoffRatio: "1.89",
      strategyProfileId: "aggressive",
      strategyProfileName: "积极",
      strategyProfileVersionId: "3",
      holdings: [],
      terminalLiquidation: {
        fee_total: 25.44,
        liquidation_cash: 50453.56,
        liquidation_total_pnl: 453.56,
        liquidation_return_pct: 0.91,
      },
      capitalPool: {
        task: {
          runId: "101",
          status: "completed",
          progress: 100,
          checkpoint: "2026-04-10 15:00:00",
          timeframe: "30m",
          range: "2026-04-01 09:30:00 -> 2026-04-10 15:00:00",
          strategy: "积极",
        },
        pool: {
          initialCash: "50000.00",
          cashValue: "25039.00",
          marketValue: "25440.00",
          totalEquity: "50479.00",
          realizedPnl: "0.00",
          unrealizedPnl: "480.00",
          slotCount: 2,
          slotBudget: "25000.00",
          availableCash: "25039.00",
          occupiedCash: "24961.00",
          settlingCash: "0.00",
          poolReady: true,
        },
        slots: [
          {
            id: "slot-1",
            index: 1,
            title: "Slot 01",
            status: "occupied",
            budgetCash: "25000.00",
            availableCash: "39.00",
            occupiedCash: "24961.00",
            settlingCash: "0.00",
            usagePct: 99.8,
            hiddenLotGroups: 0,
            lots: [
              {
                id: "301381-1",
                stockCode: "301381",
                stockName: "宏工科技",
                lotCount: 12,
                quantity: 1200,
                sellableQuantity: 0,
                lockedQuantity: 1200,
                allocatedCash: "24961.00",
                marketValue: "25440.00",
                costBand: "20.80",
                priceBasis: "market",
                status: "locked",
                isAdd: false,
                isStack: true,
                lotIds: ["301381-20260410-1"],
                hiddenLotCount: 0,
              },
            ],
          },
          {
            id: "slot-2",
            index: 2,
            title: "Slot 02",
            status: "free",
            budgetCash: "25000.00",
            availableCash: "25000.00",
            occupiedCash: "0.00",
            settlingCash: "0.00",
            usagePct: 0,
            hiddenLotGroups: 0,
            lots: [],
          },
        ],
        selectedSlotIndex: 1,
        taskMetrics: [
          { label: "任务", value: "#101" },
          { label: "状态", value: "completed" },
          { label: "检查点", value: "2026-04-10 15:00:00" },
          { label: "成交", value: "14" },
        ],
        notes: ["资金池按本次回放结束时的现金、持仓和成交lot重建。"],
      },
    },
  ],
  tradingAnalysis: {
    title: "回放摘要",
    body: "summary",
    chips: [],
  },
  holdings: emptyTable,
  trades: emptyTable,
  signals: { ...emptyTable, rows: [] },
  tradeCostSummary: [
    { label: "初始资金", value: "50000.00" },
    { label: "最终权益", value: "50479.00" },
    { label: "最终现金", value: "25039.00" },
    { label: "持仓市值", value: "25440.00" },
    { label: "总盈亏", value: "479.00" },
    { label: "总收益率", value: "0.96%" },
    { label: "交易笔数", value: "14" },
    { label: "胜率", value: "57.1%" },
    { label: "买入笔数", value: "7" },
    { label: "卖出笔数", value: "7" },
    { label: "加仓次数", value: "2" },
    { label: "买入毛额", value: "23800.00" },
    { label: "卖出毛额", value: "24400.00" },
    { label: "买入总成本", value: "23807.14" },
    { label: "卖出到账", value: "24375.66" },
    { label: "总费用", value: "18.20" },
    { label: "手续费", value: "8.20" },
    { label: "印花税", value: "10.00" },
    { label: "实现盈亏", value: "568.52" },
    { label: "买入lot", value: "12" },
    { label: "卖出lot", value: "6" },
    { label: "剩余lot", value: "6" },
    { label: "占用slot", value: "4" },
    { label: "释放slot", value: "2" },
    { label: "最大占用slot", value: "3" },
    { label: "平均占用slot", value: "1.50" },
    { label: "Slot数量", value: "2" },
    { label: "单Slot预算", value: "25000.00" },
    { label: "最终空闲", value: "25039.00" },
    { label: "最终占用", value: "24961.00" },
    { label: "最终待结算", value: "0.00" },
    { label: "期末清算费用", value: "25.44" },
    { label: "期末清算盈亏", value: "454.56" },
    { label: "清算后现金", value: "50453.56" },
    { label: "清算后总盈亏", value: "453.56" },
    { label: "清算后收益率", value: "0.91%" },
  ],
  curve: [],
};

const startedSnapshot = {
  ...initialSnapshot,
  updatedAt: "2026-04-23 22:05:00",
  tasks: [
    {
      id: "#102",
      runId: "102",
      status: "running",
      stage: "正在执行第 2/24 个检查点",
      progress: 4,
      progressCurrent: 1,
      progressTotal: 24,
      checkpointCount: 1,
      latestCheckpointAt: "2026-04-02 10:00:00",
      startAt: "2026-04-02 09:30:00",
      endAt: "2026-04-23 15:00:00",
      range: "2026-04-02 09:30:00 -> 2026-04-23 15:00:00",
      mode: "historical_range",
      timeframe: "1d+30m",
      market: "CN",
      strategyMode: "auto",
      returnPct: "--",
      finalEquity: "--",
      tradeCount: "0",
      winRate: "--",
      strategyProfileId: "aggressive",
      strategyProfileName: "积极",
      strategyProfileVersionId: "4",
      holdings: [],
    },
    ...initialSnapshot.tasks,
  ],
};

const progressedReplayProgress = {
  updatedAt: "2026-04-23 22:10:00",
  tasks: [
    {
      ...startedSnapshot.tasks[0],
      stage: "检查点 2026-01-06 10:30:00：分析候选股 1/9 002463",
      progress: 75,
      progressCurrent: 1497,
      progressTotal: 1992,
      checkpointCount: 1497,
      latestCheckpointAt: "2026-01-06 10:30:00",
    },
    ...initialSnapshot.tasks,
  ],
  holdings: emptyTable,
  trades: emptyTable,
  signals: {
    columns: ["信号ID", "时间", "代码", "动作", "策略", "执行结果"],
    rows: [
      {
        id: "99",
        cells: ["#99", "2026-01-06 10:30:00", "002463", "BUY", "自动", "待处理"],
        code: "002463",
        name: "沪电股份",
      },
    ],
    emptyLabel: "暂无信号",
    emptyMessage: "暂无信号",
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
  vi.restoreAllMocks();
});

function renderHisReplayPage(client: ApiClient) {
  const router = createMemoryRouter(
    [
      { path: "/his-replay", element: <HisReplayPage client={client} /> },
      { path: "/portfolio/position/:symbol", element: <div data-testid="stock-detail-page" /> },
    ],
    { initialEntries: ["/his-replay"] },
  );

  render(<RouterProvider router={router} />);
}

describe("HisReplayPage", () => {
  it("loads the initial signal table as BUY/SELL with a ten-row page size", async () => {
    const client = {
      getPageSnapshot: vi.fn().mockResolvedValue(initialSnapshot),
      runPageAction: vi.fn(),
    } as unknown as ApiClient;

    renderHisReplayPage(client);

    await screen.findByLabelText("已选回放任务详情");
    expect(client.getPageSnapshot).toHaveBeenCalledWith(
      "his-replay",
      expect.objectContaining({
        signalAction: "TRADE",
        signalPage: 1,
        signalPageSize: 10,
      }),
    );
  });

  it("shows immediate feedback while a replay start request is being submitted", async () => {
    let resolveStart!: (value: typeof startedSnapshot) => void;
    const startPromise = new Promise<typeof startedSnapshot>((resolve) => {
      resolveStart = resolve;
    });
    const client = {
      getPageSnapshot: vi.fn().mockResolvedValue(initialSnapshot),
      runPageAction: vi.fn().mockReturnValue(startPromise),
    } as unknown as ApiClient;

    renderHisReplayPage(client);

    await screen.findByLabelText("已选回放任务详情");
    expect(screen.queryByText("资金池最低(元)")).not.toBeInTheDocument();
    expect(screen.queryByText("资金池最高(元)")).not.toBeInTheDocument();
    expect(screen.queryByText("单Slot最低(元)")).not.toBeInTheDocument();
    expect(screen.queryByText("卖出资金复用")).not.toBeInTheDocument();
    expect(screen.queryByText("启用Slot资金管理")).not.toBeInTheDocument();
    expect(screen.queryByText("自动执行模拟交易")).not.toBeInTheDocument();
    expect(screen.queryByText("弱BUY最小Slot比例")).not.toBeInTheDocument();
    const initialCashInput = screen.getByLabelText("回放资金池(元)");
    fireEvent.change(initialCashInput, { target: { value: "300000" } });
    fireEvent.click(screen.getByRole("button", { name: "开始回溯" }));

    expect(screen.getByRole("button", { name: "提交中..." })).toBeDisabled();
    expect(client.runPageAction).toHaveBeenCalledWith("his-replay", "start", expect.objectContaining({ initialCash: 300000 }));
    expect(screen.getByText("回放任务正在提交")).toBeInTheDocument();
    expect(screen.getByText("后台已接收请求前，前端会保持提交状态；任务创建后会自动切到最新任务进度。")).toBeInTheDocument();

    await act(async () => {
      resolveStart(startedSnapshot);
      await startPromise;
    });

    expect(await screen.findByText("回放任务已提交")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "开始回溯" })).toBeDisabled();
  });

  it("shows the backend action error instead of the generic missing snapshot message", async () => {
    const client = {
      getPageSnapshot: vi.fn().mockResolvedValue(initialSnapshot),
      runPageAction: vi.fn().mockRejectedValue(new Error("候选池为空，无法执行历史区间模拟")),
    } as unknown as ApiClient;

    renderHisReplayPage(client);

    await screen.findByLabelText("已选回放任务详情");
    fireEvent.click(screen.getByRole("button", { name: "开始回溯" }));

    expect(await screen.findByText("操作失败")).toBeInTheDocument();
    expect(screen.getByText("候选池为空，无法执行历史区间模拟")).toBeInTheDocument();
    expect(screen.queryByText("后台没有返回新的任务快照，请查看操作失败信息或稍后重试。")).not.toBeInTheDocument();
  });

  it("switches the right-side summary to the newly started replay task and shows checkpoint progress", async () => {
    const client = {
      getPageSnapshot: vi.fn().mockResolvedValue(initialSnapshot),
      runPageAction: vi.fn().mockResolvedValue(startedSnapshot),
    } as unknown as ApiClient;

    renderHisReplayPage(client);

    const initialTaskDetails = await screen.findByLabelText("已选回放任务详情");
    expect(within(initialTaskDetails).getByText("#101 · 已完成")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "开始回溯" }));

    const updatedTaskDetails = await screen.findByLabelText("已选回放任务详情");
    expect(await within(updatedTaskDetails).findByText("#102 · 进行中")).toBeInTheDocument();
    expect(within(updatedTaskDetails).getByText("检查点进度：1/24 · 4%")).toBeInTheDocument();
    expect(within(updatedTaskDetails).getByText("已写入检查点：1")).toBeInTheDocument();
    expect(within(updatedTaskDetails).getByText("最近检查点：2026-04-02 10:00:00")).toBeInTheDocument();
    expect(within(updatedTaskDetails).getByText("回放节点：24")).toBeInTheDocument();
    expect(within(updatedTaskDetails).getByText("总权益")).toBeInTheDocument();
    expect(within(updatedTaskDetails).getByText("清算后现金")).toBeInTheDocument();
  });

  it("renders the selected replay task capital pool slots and lot cards", async () => {
    const client = {
      getPageSnapshot: vi.fn().mockResolvedValue(initialSnapshot),
      runPageAction: vi.fn(),
    } as unknown as ApiClient;

    renderHisReplayPage(client);

    expect(await screen.findByText("资金池总览")).toBeInTheDocument();
    expect(screen.queryByText("资金池槽位")).not.toBeInTheDocument();
    expect(screen.queryByText("任务快照")).not.toBeInTheDocument();
    expect(screen.queryByText("每个回放任务的最终资金池快照：现金、持仓市值、slot占用和lot批次集中展示。")).not.toBeInTheDocument();
    expect(screen.getAllByText("Slot 01").length).toBeGreaterThan(0);
    expect(screen.getAllByText("12 lot · 1200 股").length).toBeGreaterThan(0);
    expect(screen.getAllByText("成本 20.80 · 现价 21.20").length).toBeGreaterThan(0);
    expect(screen.getAllByText("涨 +1.92%").length).toBeGreaterThan(0);
    const stockLinks = screen.getAllByRole("link", { name: "301381 宏工科技" });
    expect(stockLinks.length).toBeGreaterThan(0);
    expect(stockLinks[0]).toHaveAttribute("href", "/portfolio/position/301381");
  });

  it("renders liquidation summary in the selected replay task metrics", async () => {
    const client = {
      getPageSnapshot: vi.fn().mockResolvedValue(initialSnapshot),
      runPageAction: vi.fn(),
    } as unknown as ApiClient;

    renderHisReplayPage(client);

    const taskDetails = await screen.findByLabelText("已选回放任务详情");
    expect(within(taskDetails).getByText("清算后现金")).toBeInTheDocument();
    expect(within(taskDetails).getByText("50453.56")).toBeInTheDocument();
    expect(within(taskDetails).getByText("期末清算费用")).toBeInTheDocument();
    expect(within(taskDetails).getByText("25.44")).toBeInTheDocument();
    expect(within(taskDetails).queryByText("成交")).not.toBeInTheDocument();
    expect(within(taskDetails).queryByText("SELL胜率")).not.toBeInTheDocument();
    expect(within(taskDetails).queryByText("均盈/均亏")).not.toBeInTheDocument();
    expect(within(taskDetails).queryByText("盈亏比")).not.toBeInTheDocument();
    expect(screen.getByText("费用与执行统计")).toBeInTheDocument();
    expect(screen.getAllByText("清算后现金")).toHaveLength(1);
  });

  it("renders execution statistics as grouped summaries", async () => {
    const client = {
      getPageSnapshot: vi.fn().mockResolvedValue(initialSnapshot),
      runPageAction: vi.fn(),
    } as unknown as ApiClient;

    renderHisReplayPage(client);

    const section = await screen.findByLabelText("费用与执行统计");
    expect(within(section).getByText("关键成交")).toBeInTheDocument();
    expect(within(section).getByText("14")).toBeInTheDocument();
    expect(within(section).getByText("交易笔数 · 胜率 57.1%")).toBeInTheDocument();
    expect(within(section).getByText("交易结构")).toBeInTheDocument();
    expect(within(section).getByText("资金与费用")).toBeInTheDocument();
    expect(within(section).getByText("Lot / Slot")).toBeInTheDocument();
    expect(within(section).getByText("期末资金")).toBeInTheDocument();
    expect(within(section).getAllByText("总费用")).toHaveLength(1);
    expect(within(section).getByText("买入毛额")).toBeInTheDocument();
    expect(within(section).getByText("手续费")).toBeInTheDocument();
    expect(within(section).queryByText("其他")).not.toBeInTheDocument();
    expect(within(section).queryByText("清算后现金")).not.toBeInTheDocument();
  });

  it("opens all lot details from the capital pool slot summary", async () => {
    const client = {
      getPageSnapshot: vi.fn().mockResolvedValue(initialSnapshot),
      runPageAction: vi.fn(),
    } as unknown as ApiClient;

    renderHisReplayPage(client);

    await screen.findByText("资金池总览");
    fireEvent.click(screen.getByRole("button", { name: "2 slots · 12 lots" }));

    const allLotsPanel = await screen.findByLabelText("全部 Lot 明细");
    expect(within(allLotsPanel).getByText("全部 Lot 明细")).toBeInTheDocument();
    expect(within(allLotsPanel).getByText("Slot 01")).toBeInTheDocument();
    expect(within(allLotsPanel).getByText("占用 24961.00")).toBeInTheDocument();
    expect(within(allLotsPanel).getByText("可卖 0 · 锁定 1200")).toBeInTheDocument();
    expect(within(allLotsPanel).getByRole("link", { name: "301381 宏工科技" })).toHaveAttribute("href", "/portfolio/position/301381");
  });

  it("loads capital pool lots for a selected replay checkpoint page", async () => {
    const checkpointCapitalPool = {
      ...initialSnapshot.tasks[0].capitalPool,
      task: {
        ...initialSnapshot.tasks[0].capitalPool.task,
        checkpoint: "2026-04-09 10:00:00",
      },
      pool: {
        ...initialSnapshot.tasks[0].capitalPool.pool,
        cashValue: "26000.00",
      },
      slots: initialSnapshot.tasks[0].capitalPool.slots.map((slot) => ({
        ...slot,
        lots: slot.lots.map((lot) => ({
          ...lot,
          marketValue: "24960.00",
          priceBasis: "entry",
        })),
      })),
    };
    const client = {
      getPageSnapshot: vi.fn().mockResolvedValue(initialSnapshot),
      getReplayCapitalPool: vi.fn().mockResolvedValue({
        updatedAt: "2026-04-23 22:10:00",
        runId: "101",
        selectedCheckpointAt: "2026-04-09 10:00:00",
        checkpoints: {
          items: [
            { id: "c2", checkpointAt: "2026-04-10 15:00:00", label: "2026-04-10 15:00:00", totalEquity: "50479.00", cashValue: "25039.00", marketValue: "25440.00" },
            { id: "c1", checkpointAt: "2026-04-09 10:00:00", label: "2026-04-09 10:00:00", totalEquity: "50200.00", cashValue: "26000.00", marketValue: "24200.00" },
          ],
          pagination: { page: 1, pageSize: 2, totalRows: 1992, totalPages: 996 },
        },
        capitalPool: checkpointCapitalPool,
      }),
      runPageAction: vi.fn(),
    } as unknown as ApiClient;

    renderHisReplayPage(client);

    const taskDetails = await screen.findByLabelText("已选回放任务详情");
    expect(within(taskDetails).getByLabelText("检查点")).toBeInTheDocument();
    expect(screen.getAllByLabelText("检查点")).toHaveLength(1);
    await waitFor(() => {
      expect(client.getReplayCapitalPool).toHaveBeenCalledWith(expect.objectContaining({ runId: "101", checkpointPage: 1, checkpointPageSize: 50 }));
    });

    fireEvent.change(within(taskDetails).getByLabelText("检查点"), { target: { value: "2026-04-09 10:00:00" } });

    await waitFor(() => {
      expect(client.getReplayCapitalPool).toHaveBeenCalledWith(expect.objectContaining({ runId: "101", checkpointAt: "2026-04-09 10:00:00" }));
    });
    expect(await screen.findByText("26000.00")).toBeInTheDocument();
    expect(screen.getAllByText("成本价 20.80").length).toBeGreaterThan(0);
    expect(screen.getByText("第 1 / 996 页")).toBeInTheDocument();
  });

  it("polls lightweight replay progress and updates the selected task without reloading the full snapshot", async () => {
    const intervalCallbacks: Array<() => Promise<void>> = [];
    const nativeSetInterval = window.setInterval.bind(window);
    const nativeClearInterval = window.clearInterval.bind(window);
    vi.spyOn(window, "setInterval").mockImplementation((callback: TimerHandler, timeout?: number, ...args: unknown[]) => {
      if (timeout === 60 * 1000) {
        intervalCallbacks.push(callback as () => Promise<void>);
        return 1;
      }
      return nativeSetInterval(callback, timeout, ...args);
    });
    vi.spyOn(window, "clearInterval").mockImplementation((handle?: number) => {
      if (handle === 1) return;
      nativeClearInterval(handle);
    });
    const client = {
      getPageSnapshot: vi.fn().mockResolvedValue(startedSnapshot),
      getReplayProgress: vi.fn().mockResolvedValue(progressedReplayProgress),
      runPageAction: vi.fn(),
    } as unknown as ApiClient;

    renderHisReplayPage(client);

    const taskDetails = await screen.findByLabelText("已选回放任务详情");
    expect(intervalCallbacks).toHaveLength(1);
    expect(await within(taskDetails).findByText("检查点进度：1497/1992 · 75%")).toBeInTheDocument();
    expect(client.getReplayProgress).toHaveBeenCalledWith({
      pageSize: 20,
      tradePageSize: 20,
      tradePage: 1,
      tradeAction: "ALL",
      tradeStock: "",
      signalPageSize: 10,
      signalPage: 1,
      signalAction: "TRADE",
      signalStock: "",
    });

    await act(async () => {
      await intervalCallbacks[0]();
    });

    const updatedTaskDetails = await screen.findByLabelText("已选回放任务详情");
    expect(within(updatedTaskDetails).getByText("检查点进度：1497/1992 · 75%")).toBeInTheDocument();
    expect(within(updatedTaskDetails).getByText("检查点 2026-01-06 10:30:00")).toBeInTheDocument();
    expect(within(updatedTaskDetails).getByText("分析候选股 1/9 002463")).toBeInTheDocument();
    expect(screen.getByText("分析候选股 1/9 002463").closest(".replay-task-stage")).toBeTruthy();
    expect(screen.getByText("002463 沪电股份")).toBeInTheDocument();
    expect(client.getReplayProgress).toHaveBeenCalledTimes(2);
    expect(client.getPageSnapshot).toHaveBeenCalledTimes(1);
    expect(await screen.findByRole("link", { name: /002463/ })).toHaveAttribute("href", "/portfolio/position/002463");
  });
});
