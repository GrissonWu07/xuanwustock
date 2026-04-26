import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { RouterProvider, createMemoryRouter, useParams } from "react-router-dom";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import type { ApiClient } from "../lib/api-client";
import { WorkbenchPage } from "../features/workbench/workbench-page";

const workbenchSnapshot = {
  updatedAt: "2026-04-25 10:00:00",
  metrics: [],
  watchlist: {
    columns: ["代码", "名称", "行情", "板块", "分析", "信号", "工作流", "更新"],
    rows: [
      {
        id: "600519",
        cells: ["600519", "贵州茅台", "1453.96 +1.23%", "白酒", "今日已分析 · 买入", "BUY", "量化池 · 数据正常", "04-25 10:00"],
        actions: [],
        workflowBadges: ["量化池", "数据正常"],
        analysisStatus: "今日已分析 · 买入",
        signalStatus: "BUY",
      },
    ],
    emptyLabel: "关注池为空",
    pagination: { page: 1, pageSize: 20, totalRows: 1, totalPages: 1 },
  },
  watchlistMeta: {
    selectedCount: 0,
    quantCount: 0,
    refreshHint: "刷新关注池",
  },
  analysis: {
    symbol: "600519",
    stockName: "贵州茅台",
    analysts: [
      { label: "技术分析师", value: "technical", selected: true },
      { label: "基本面分析师", value: "fundamental", selected: true },
    ],
    mode: "单个分析",
    cycle: "1y",
    inputHint: "600519",
    summaryTitle: "最近分析",
    summaryBody: "暂无新分析。",
    indicators: [],
    decision: "观察",
    insights: [],
    analystViews: [],
    curve: [],
    results: [],
  },
  analysisJob: null,
  nextSteps: [],
  activity: [],
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

function PositionDetailStub() {
  const { symbol = "" } = useParams<{ symbol: string }>();
  return <div data-testid="position-detail">{symbol}</div>;
}

function renderWorkbenchPage(client: ApiClient) {
  const router = createMemoryRouter([
    { path: "/workbench", element: <WorkbenchPage client={client} /> },
    { path: "/portfolio/position/:symbol", element: <PositionDetailStub /> },
  ], {
    initialEntries: ["/workbench"],
  });
  render(<RouterProvider router={router} />);
}

describe("WorkbenchPage", () => {
  it("requests watchlist table data with a maximum page size of 20", async () => {
    const getPageSnapshot = vi.fn().mockResolvedValue(workbenchSnapshot);
    const client = {
      getPageSnapshot,
      runPageAction: vi.fn().mockResolvedValue(workbenchSnapshot),
    } as unknown as ApiClient;

    renderWorkbenchPage(client);

    await waitFor(() => {
      expect(getPageSnapshot).toHaveBeenCalledWith("workbench", { search: "", page: 1, pageSize: 20 });
    });
    expect(getPageSnapshot).toHaveBeenCalledTimes(1);
  });

  it("does not render stock analysis controls on the workbench", async () => {
    const getPageSnapshot = vi.fn().mockResolvedValue(workbenchSnapshot);
    const client = {
      getPageSnapshot,
      runPageAction: vi.fn().mockResolvedValue(workbenchSnapshot),
    } as unknown as ApiClient;

    renderWorkbenchPage(client);

    await screen.findByRole("link", { name: "600519" });
    expect(screen.queryByRole("heading", { name: /股票分析|Stock analysis/i })).toBeNull();
    expect(screen.queryByRole("button", { name: /开始分析|Start analysis/i })).toBeNull();
  });

  it("limits watchlist pagination to 10 page buttons and uses ellipsis for the rest", async () => {
    const pagedSnapshot = {
      ...workbenchSnapshot,
      watchlist: {
        ...workbenchSnapshot.watchlist,
        pagination: { page: 1, pageSize: 20, totalRows: 240, totalPages: 12 },
      },
    };
    const getPageSnapshot = vi.fn().mockResolvedValue(pagedSnapshot);
    const client = {
      getPageSnapshot,
      runPageAction: vi.fn().mockResolvedValue(pagedSnapshot),
    } as unknown as ApiClient;

    renderWorkbenchPage(client);

    await waitFor(() => {
      expect(getPageSnapshot).toHaveBeenCalledWith("workbench", { search: "", page: 1, pageSize: 20 });
    });
    expect(document.querySelectorAll(".watchlist-pagination__page")).toHaveLength(10);
    expect(document.querySelectorAll(".watchlist-pagination__ellipsis")).toHaveLength(1);

    for (let page = 1; page <= 10; page += 1) {
      expect(document.querySelector(`button.watchlist-pagination__page[aria-label="第 ${page} 页"]`)).not.toBeNull();
    }
    expect(document.querySelector(`button.watchlist-pagination__page[aria-label="第 11 页"]`)).toBeNull();
    expect(document.querySelector(`button.watchlist-pagination__page[aria-label="第 12 页"]`)).toBeNull();
  });

  it("opens the portfolio stock detail when clicking a watchlist code", async () => {
    const getPageSnapshot = vi.fn().mockResolvedValue(workbenchSnapshot);
    const client = {
      getPageSnapshot,
      runPageAction: vi.fn().mockResolvedValue(workbenchSnapshot),
    } as unknown as ApiClient;

    renderWorkbenchPage(client);

    const codeLink = await screen.findByRole("link", { name: "600519" });
    fireEvent.click(codeLink);

    await waitFor(() => {
      expect(screen.getByTestId("position-detail")).toHaveTextContent("600519");
    });
  });

  it("renders decision-oriented watchlist fields as structured badges", async () => {
    const getPageSnapshot = vi.fn().mockResolvedValue(workbenchSnapshot);
    const client = {
      getPageSnapshot,
      runPageAction: vi.fn().mockResolvedValue(workbenchSnapshot),
    } as unknown as ApiClient;

    renderWorkbenchPage(client);

    await screen.findByRole("link", { name: "600519" });

    expect(screen.getByText("行情")).toBeInTheDocument();
    expect(screen.getByText("分析")).toBeInTheDocument();
    expect(screen.getByText("信号")).toBeInTheDocument();
    expect(screen.getByText("工作流")).toBeInTheDocument();
    expect(screen.queryByText("来源")).toBeNull();
    expect(screen.queryByText("量化状态")).toBeNull();
    expect(screen.queryByText("AI选股 · 主力资金流入")).toBeNull();
    expect(document.querySelectorAll(".watchlist-workflow-badge")).toHaveLength(2);
  });

  it("moves watchlist row actions to the toolbar and supports batch delete", async () => {
    const getPageSnapshot = vi.fn().mockResolvedValue(workbenchSnapshot);
    const runPageAction = vi.fn().mockResolvedValue(workbenchSnapshot);
    const client = {
      getPageSnapshot,
      runPageAction,
    } as unknown as ApiClient;

    renderWorkbenchPage(client);

    await screen.findByRole("link", { name: "600519" });

    expect(screen.queryByRole("columnheader", { name: "操作" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Delete 600519" })).toBeNull();

    fireEvent.click(screen.getByRole("checkbox", { name: "Select 贵州茅台" }));
    fireEvent.click(screen.getByRole("button", { name: "Delete selected" }));

    await waitFor(() => {
      expect(runPageAction).toHaveBeenCalledWith("workbench", "delete-watchlist", { codes: ["600519"] });
    });
  });

  it("filters legacy source columns from watchlist snapshots", async () => {
    const legacySnapshot = {
      ...workbenchSnapshot,
      watchlist: {
        ...workbenchSnapshot.watchlist,
        columns: ["代码", "名称", "行情", "板块", "来源", "分析", "信号", "工作流", "更新"],
        rows: [
          {
            ...workbenchSnapshot.watchlist.rows[0],
            cells: ["600519", "贵州茅台", "1453.96 +1.23%", "白酒", "AI选股 · 主力资金流入", "今日已分析 · 买入", "BUY", "量化池 · 数据正常", "04-25 10:00"],
          },
        ],
      },
    };
    const getPageSnapshot = vi.fn().mockResolvedValue(legacySnapshot);
    const client = {
      getPageSnapshot,
      runPageAction: vi.fn().mockResolvedValue(legacySnapshot),
    } as unknown as ApiClient;

    renderWorkbenchPage(client);

    await screen.findByRole("link", { name: "600519" });

    expect(screen.queryByText("来源")).toBeNull();
    expect(screen.queryByText("AI选股 · 主力资金流入")).toBeNull();
    expect(screen.getByText("今日已分析 · 买入")).toBeInTheDocument();
    expect(screen.getByText("BUY")).toBeInTheDocument();
  });
});
