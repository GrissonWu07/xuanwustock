import { act, fireEvent, render, screen, within } from "@testing-library/react";
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
    fireEvent.click(screen.getByRole("button", { name: "开始回溯" }));

    expect(screen.getByRole("button", { name: "提交中..." })).toBeDisabled();
    expect(screen.getByText("回放任务正在提交")).toBeInTheDocument();
    expect(screen.getByText("后台已接收请求前，前端会保持提交状态；任务创建后会自动切到最新任务进度。")).toBeInTheDocument();

    await act(async () => {
      resolveStart(startedSnapshot);
      await startPromise;
    });

    expect(await screen.findByText("回放任务已提交")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "开始回溯" })).toBeDisabled();
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
    expect(within(updatedTaskDetails).getByText("SELL胜率")).toBeInTheDocument();
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
      tradePage: 1,
      tradeAction: "ALL",
      tradeStock: "",
      signalPage: 1,
      signalAction: "ALL",
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
