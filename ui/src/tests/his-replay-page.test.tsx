import { fireEvent, render, screen, within } from "@testing-library/react";
import { RouterProvider, createMemoryRouter } from "react-router-dom";
import { beforeAll, describe, expect, it, vi } from "vitest";
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
    strategyProfileId: "aggressive_v23",
    strategyProfiles: [
      { id: "aggressive_v23", name: "积极", enabled: true, isDefault: true },
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
      tradeCount: "14",
      winRate: "57.1%",
      strategyProfileId: "aggressive_v23",
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
      strategyProfileId: "aggressive_v23",
      strategyProfileName: "积极",
      strategyProfileVersionId: "4",
      holdings: [],
    },
    ...initialSnapshot.tasks,
  ],
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

function renderHisReplayPage(client: ApiClient) {
  const router = createMemoryRouter(
    [{ path: "/his-replay", element: <HisReplayPage client={client} /> }],
    { initialEntries: ["/his-replay"] },
  );

  render(<RouterProvider router={router} />);
}

describe("HisReplayPage", () => {
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
    expect(within(updatedTaskDetails).getByText("回放节点数")).toBeInTheDocument();
    expect(within(updatedTaskDetails).getByText("1/24")).toBeInTheDocument();
  });
});
