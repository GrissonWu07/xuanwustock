import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { RouterProvider, createMemoryRouter } from "react-router-dom";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import type { ApiClient } from "../lib/api-client";
import { DiscoverPage } from "../features/discover/discover-page";

const discoverSnapshot = {
  updatedAt: "2026-04-24 00:10:00",
  metrics: [],
  strategies: [
    { key: "main_force", name: "Main force selection", note: "test", status: "Latest picks: 1" },
  ],
  summary: {
    title: "Discover summary",
    body: "Discover body",
  },
  candidateTable: {
    columns: ["Code", "Name", "Industry", "Source", "Price", "Market cap", "PE", "PB"],
    rows: [
      {
        id: "600519",
        cells: ["600519", "贵州茅台", "白酒", "main_force", "1453.96", "100", "20", "8"],
        actions: [{ label: "Add to watchlist", icon: "⭐", tone: "accent", action: "item-watchlist" }],
        code: "600519",
        name: "贵州茅台",
        industry: "白酒",
        source: "main_force",
        latestPrice: "1453.96",
        reason: "reason",
        selectedAt: "2026-04-24 00:00:00",
      },
    ],
    emptyLabel: "No candidate stocks",
    emptyMessage: "No candidate stocks",
  },
  recommendation: {
    title: "Top recommendations",
    body: "Recommendation body",
    chips: [],
  },
  taskJob: null,
};

const lifecycleDiscoverSnapshot = {
  ...discoverSnapshot,
  candidateTable: {
    ...discoverSnapshot.candidateTable,
    rows: [
      {
        id: "600001",
        cells: ["600001", "eligible 股", "行业A", "main_force", "10.00", "100", "20", "2"],
        code: "600001",
        name: "eligible 股",
        eligible_status: "eligible",
        blocking_reason: "",
        candidate_score: 0.82,
        already_in_quant: false,
        actions: [{ label: "Add to watchlist", icon: "⭐", tone: "accent", action: "item-watchlist" }],
      },
      {
        id: "600002",
        cells: ["600002", "已入池股", "行业B", "main_force", "11.00", "100", "20", "2"],
        code: "600002",
        name: "已入池股",
        eligible_status: "already_in_quant",
        blocking_reason: "",
        candidate_score: 0.72,
        already_in_quant: true,
        actions: [{ label: "Add to watchlist", icon: "⭐", tone: "accent", action: "item-watchlist" }],
      },
      {
        id: "600003",
        cells: ["600003", "跳过股", "行业C", "main_force", "12.00", "100", "20", "2"],
        code: "600003",
        name: "跳过股",
        eligible_status: "skipped",
        blocking_reason: "基础信息缺失",
        candidate_score: 0.62,
        already_in_quant: false,
        actions: [{ label: "Add to watchlist", icon: "⭐", tone: "accent", action: "item-watchlist" }],
      },
      {
        id: "600004",
        cells: ["600004", "冷却股", "行业D", "main_force", "13.00", "100", "20", "2"],
        code: "600004",
        name: "冷却股",
        eligible_status: "cooling_blocked",
        blocking_reason: "冷却期未结束",
        candidate_score: 0.70,
        already_in_quant: false,
        actions: [{ label: "Add to watchlist", icon: "⭐", tone: "accent", action: "item-watchlist" }],
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

function renderDiscoverPage(client: ApiClient) {
  const router = createMemoryRouter(
    [
      { path: "/discover", element: <DiscoverPage client={client} /> },
      { path: "/portfolio/position/:symbol", element: <div data-testid="stock-detail-page" /> },
    ],
    {
      initialEntries: ["/discover"],
    },
  );
  render(<RouterProvider router={router} />);
}

describe("DiscoverPage", () => {
  it("shows lifecycle eligibility badges and promotes selected candidates with row-level partial results", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        success: [{ stock_code: "600001", new_status: "trial" }],
        skipped: [{ stock_code: "600003", reason_text: "基础信息缺失" }],
        failed: [],
      }),
    });
    vi.stubGlobal("fetch", fetchMock);
    const client = {
      getPageSnapshot: vi.fn().mockResolvedValue(lifecycleDiscoverSnapshot),
      runPageAction: vi.fn().mockResolvedValue(lifecycleDiscoverSnapshot),
      getTaskStatus: vi.fn(),
    } as unknown as ApiClient;

    renderDiscoverPage(client);

    expect(await screen.findByText("eligible")).toBeInTheDocument();
    expect(screen.getByText("already_in_quant")).toBeInTheDocument();
    expect(screen.getByText("skipped")).toBeInTheDocument();
    expect(screen.getByText("cooling_blocked")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "仅看 eligible" })).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: "纳入量化观察" }).length).toBeGreaterThan(0);
    expect(screen.getAllByRole("button", { name: "忽略自动纳入" }).length).toBeGreaterThan(0);

    fireEvent.click(screen.getByRole("button", { name: "仅看 eligible" }));
    expect(screen.getByText("eligible 股")).toBeInTheDocument();
    expect(screen.queryByText("已入池股")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "仅看 eligible" }));

    fireEvent.click(screen.getByRole("checkbox", { name: "Select eligible 股" }));
    fireEvent.click(screen.getByRole("checkbox", { name: "Select 跳过股" }));
    fireEvent.click(screen.getAllByRole("button", { name: "纳入量化观察" })[0]);
    expect(screen.getByRole("dialog", { name: "确认纳入量化观察" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "确认纳入" }));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        "/api/v1/quant/universe/actions/promote-to-trial",
        expect.objectContaining({
          method: "POST",
          body: JSON.stringify({ stock_codes: ["600001", "600003"], source_type: "discover" }),
        }),
      );
    });
    expect(screen.getByText("600001")).toBeInTheDocument();
    expect(screen.getAllByText("already_in_quant").length).toBeGreaterThan(0);
    expect(screen.getByText("基础信息缺失")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "仅看 eligible" }));
    expect(screen.getByText("600001")).toBeInTheDocument();
    expect(screen.getByText("600003")).toBeInTheDocument();
  });

  it("supports row click selection and isolates single watchlist action", async () => {
    const runPageAction = vi.fn().mockResolvedValue(discoverSnapshot);
    const client = {
      getPageSnapshot: vi.fn().mockResolvedValue(discoverSnapshot),
      runPageAction,
    } as unknown as ApiClient;

    renderDiscoverPage(client);

    const checkbox = await screen.findByRole("checkbox", { name: "Select 贵州茅台" });
    expect(checkbox).not.toBeChecked();
    expect(screen.getByRole("link", { name: "600519" })).toHaveAttribute("href", "/portfolio/position/600519");
    expect(screen.getByRole("link", { name: "贵州茅台" })).toHaveAttribute("href", "/portfolio/position/600519");

    fireEvent.click(screen.getByText("白酒"));
    expect(checkbox).toBeChecked();

    fireEvent.click(screen.getByRole("button", { name: "Add to watchlist" }));
    await waitFor(() => {
      expect(runPageAction).toHaveBeenCalledWith("discover", "item-watchlist", { code: "600519" });
    });
    expect(checkbox).toBeChecked();

    const toolbar = screen.getByTestId("discover-candidate-toolbar");
    fireEvent.click(within(toolbar).getByRole("button", { name: "Add selected to watchlist" }));
    await waitFor(() => {
      expect(runPageAction).toHaveBeenCalledWith("discover", "batch-watchlist", { codes: ["600519"] });
    });
  });
});
