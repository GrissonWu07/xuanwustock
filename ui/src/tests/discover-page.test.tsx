// @ts-nocheck
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";
import process from "node:process";
import { RouterProvider, createMemoryRouter } from "react-router-dom";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import type { ApiClient } from "../lib/api-client";
import { DiscoverPage } from "../features/discover/discover-page";

const loadDiagnosticsParams = () => {
  const root = process.cwd().endsWith("ui") ? join(process.cwd(), "..") : process.cwd();
  const candidates = [
    join(root, "openspec", "changes", "fix-discover-lifecycle-scoring", "test-params", "discover-api-ui-diagnostics.md"),
    join(root, "openspec", "changes", "archive", "2026-05-15-fix-discover-lifecycle-scoring", "test-params", "discover-api-ui-diagnostics.md"),
  ];
  const paramsPath = candidates.find((path) => existsSync(path));
  if (!paramsPath) throw new Error("missing diagnostics test parameters");
  const text = readFileSync(paramsPath, "utf8");
  const match = text.match(/```json\s*([\s\S]*?)\s*```/);
  if (!match) throw new Error("missing diagnostics test parameters");
  return JSON.parse(match[1]);
};

const diagnosticsParams = loadDiagnosticsParams();

const loadSnapshotReadinessParams = () => {
  const root = process.cwd().endsWith("ui") ? join(process.cwd(), "..") : process.cwd();
  const candidates = [
    join(root, "openspec", "changes", "discover-market-data-snapshot-gate", "test-params", "discover-ui-snapshot-readiness.md"),
    join(
      root,
      "openspec",
      "changes",
      "archive",
      "2026-05-16-discover-market-data-snapshot-gate",
      "test-params",
      "discover-ui-snapshot-readiness.md",
    ),
  ];
  const paramsPath = candidates.find((path) => existsSync(path));
  if (!paramsPath) throw new Error("missing snapshot readiness test parameters");
  const text = readFileSync(paramsPath, "utf8");
  const cases: Record<string, unknown> = {};
  const pattern = /##\s+([a-zA-Z0-9_-]+)\s+```json\s*([\s\S]*?)\s*```/g;
  for (const match of text.matchAll(pattern)) {
    cases[match[1]] = JSON.parse(match[2]);
  }
  return cases as {
    discover_ui_rows: {
      rows: typeof discoverSnapshot.candidateTable.rows;
      task_result: {
        technicalSnapshotPreparation: {
          uniqueStocks: number;
          prepared: number;
          complete: number;
          incomplete: number;
          failed: number;
          blocked: number;
        };
      };
      expected: {
        ready_text: string;
        incomplete_text: string;
        missing_field_text: string;
        task_summary: string;
      };
    };
  };
};

const snapshotReadinessParams = loadSnapshotReadinessParams();

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
        ...diagnosticsParams.ui_candidate_diagnostics.row,
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

const technicalSnapshotDiscoverSnapshot = {
  ...discoverSnapshot,
  candidateTable: {
    ...discoverSnapshot.candidateTable,
    rows: snapshotReadinessParams.discover_ui_rows.rows,
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
  it("loads ten candidates by default and filters by discovery method", async () => {
    const getPageSnapshot = vi.fn().mockResolvedValue(discoverSnapshot);
    const client = {
      getPageSnapshot,
      runPageAction: vi.fn().mockResolvedValue(discoverSnapshot),
      getTaskStatus: vi.fn(),
    } as unknown as ApiClient;

    renderDiscoverPage(client);

    await screen.findByRole("link", { name: "600519" });
    await waitFor(() => {
      expect(getPageSnapshot).toHaveBeenCalledWith("discover", { search: "", page: 1, pageSize: 10 });
    });

    fireEvent.change(screen.getByLabelText("Discovery method"), { target: { value: "low_price_bull" } });

    await waitFor(() => {
      expect(getPageSnapshot).toHaveBeenCalledWith("discover", {
        search: "",
        page: 1,
        pageSize: 10,
        strategyKey: "low_price_bull",
      });
    });
  });

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
    expect(screen.getByText(diagnosticsParams.ui_candidate_diagnostics.expected.score_text)).toBeInTheDocument();
    expect(screen.getByText(diagnosticsParams.ui_candidate_diagnostics.expected.confidence_text)).toBeInTheDocument();
    expect(screen.getByText("already_in_quant")).toBeInTheDocument();
    expect(screen.getByText("skipped")).toBeInTheDocument();
    expect(screen.getByText("cooling_blocked")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "仅看 eligible" })).toBeNull();
    expect(screen.queryByRole("columnheader", { name: "Actions" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Analyze" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Add to watchlist" })).toBeNull();
    expect(screen.getAllByRole("button", { name: "纳入量化" })).toHaveLength(1);
    expect(screen.getAllByRole("button", { name: "忽略自动纳入" })).toHaveLength(1);

    fireEvent.click(screen.getByRole("checkbox", { name: "Select eligible 股" }));
    fireEvent.click(screen.getByRole("checkbox", { name: "Select 跳过股" }));
    fireEvent.click(screen.getAllByRole("button", { name: "纳入量化" })[0]);
    expect(screen.getByRole("dialog", { name: "确认纳入量化" })).toBeInTheDocument();
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
    expect(screen.getByText("600001")).toBeInTheDocument();
    expect(screen.getByText("600003")).toBeInTheDocument();
  });

  it("shows discovery task auto-entry diagnostics after strategy completion", async () => {
    const expected = diagnosticsParams.task_quant_auto_entry.expected;
    const client = {
      getPageSnapshot: vi.fn().mockResolvedValue(discoverSnapshot),
      runPageAction: vi.fn().mockResolvedValue({ ...discoverSnapshot, taskId: "discover-test" }),
      getTaskStatus: vi.fn().mockResolvedValue({
        id: "discover-test",
        status: "completed",
        title: "Stock discovery task",
        message: "Discovery task completed.",
        stage: "completed",
        progress: 100,
        result: {
          quantAutoEntry: {
            attempted: expected.attempted,
            events: expected.events,
            promoted: expected.promoted,
            eligible: expected.eligible,
            skipped: [],
          },
        },
      }),
    } as unknown as ApiClient;

    renderDiscoverPage(client);

    fireEvent.click(await screen.findByRole("button", { name: "Run" }));

    await waitFor(() => {
      expect(client.getTaskStatus).toHaveBeenCalledWith("discover-test");
    });
    expect(await screen.findByText(expected.ui_summary)).toBeInTheDocument();
  });

  it("shows technical snapshot readiness and missing fields", async () => {
    const expected = snapshotReadinessParams.discover_ui_rows.expected;
    const client = {
      getPageSnapshot: vi.fn().mockResolvedValue(technicalSnapshotDiscoverSnapshot),
      runPageAction: vi.fn().mockResolvedValue(technicalSnapshotDiscoverSnapshot),
      getTaskStatus: vi.fn(),
    } as unknown as ApiClient;

    renderDiscoverPage(client);

    expect(await screen.findByText(expected.ready_text)).toBeInTheDocument();
    expect(screen.getByText(expected.incomplete_text)).toBeInTheDocument();
    expect(screen.getByText(expected.missing_field_text)).toBeInTheDocument();
  });

  it("shows technical snapshot preparation counts after strategy completion", async () => {
    const expected = snapshotReadinessParams.discover_ui_rows.expected;
    const client = {
      getPageSnapshot: vi.fn().mockResolvedValue(discoverSnapshot),
      runPageAction: vi.fn().mockResolvedValue({ ...discoverSnapshot, taskId: "discover-snapshot-test" }),
      getTaskStatus: vi.fn().mockResolvedValue({
        id: "discover-snapshot-test",
        status: "completed",
        title: "Stock discovery task",
        message: "Discovery task completed.",
        stage: "completed",
        progress: 100,
        result: snapshotReadinessParams.discover_ui_rows.task_result,
      }),
    } as unknown as ApiClient;

    renderDiscoverPage(client);

    fireEvent.click(await screen.findByRole("button", { name: "Run" }));

    await waitFor(() => {
      expect(client.getTaskStatus).toHaveBeenCalledWith("discover-snapshot-test");
    });
    expect(await screen.findByText(expected.task_summary)).toBeInTheDocument();
  });

  it("supports row click selection and keeps candidate operations batch-only", async () => {
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
    expect(screen.queryByRole("button", { name: "Add to watchlist" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Analyze" })).toBeNull();

    const toolbar = screen.getByTestId("discover-candidate-toolbar");
    fireEvent.click(within(toolbar).getByRole("button", { name: "Analyze selected" }));
    await waitFor(() => {
      expect(runPageAction).toHaveBeenCalledWith("workbench", "analysis-batch", { stockCodes: ["600519"] });
    });

    fireEvent.click(within(toolbar).getByRole("button", { name: "Add selected to watchlist" }));
    await waitFor(() => {
      expect(runPageAction).toHaveBeenCalledWith("discover", "batch-watchlist", { codes: ["600519"] });
    });
  });
});
