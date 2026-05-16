import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { RouterProvider, createMemoryRouter } from "react-router-dom";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import type { ApiClient } from "../lib/api-client";
import { ResearchPage } from "../features/research/research-page";

const researchSnapshot = {
  updatedAt: "2026-04-24 00:12:00",
  modules: [{ name: "Sector strategy", note: "module note", output: "Bullish 1 / Bearish 0" }],
  marketView: [],
  outputTable: {
    columns: ["Code", "Name", "Industry", "Source module", "Latest price", "Next action"],
    rows: [
      {
        id: "000001",
        cells: ["000001", "平安银行", "银行", "Sector strategy", "12.30", "Add to watchlist"],
        actions: [{ label: "Add to watchlist", icon: "⭐", tone: "accent", action: "item-watchlist" }],
        code: "000001",
        name: "平安银行",
        industry: "银行",
        source: "Sector strategy",
        latestPrice: "12.30",
      },
    ],
    emptyLabel: "No stock output",
    emptyMessage: "No stock output",
  },
  summary: { title: "Research", body: "Research body" },
  taskJob: null,
};

const lifecycleResearchSnapshot = {
  ...researchSnapshot,
  outputTable: {
    ...researchSnapshot.outputTable,
    rows: [
      {
        id: "000001",
        cells: ["000001", "平安银行", "银行", "Sector strategy", "12.30", "Add to watchlist"],
        actions: [{ label: "Add to watchlist", icon: "⭐", tone: "accent", action: "item-watchlist" }],
        code: "000001",
        name: "平安银行",
        industry: "银行",
        source: "Sector strategy",
        latestPrice: "12.30",
        eligible_status: "eligible",
        blocking_reason: "",
        candidate_score: 0.81,
        already_in_quant: false,
      },
      {
        id: "000002",
        cells: ["000002", "万科A", "地产", "Sector strategy", "8.20", "Already in quant"],
        actions: [{ label: "Add to watchlist", icon: "⭐", tone: "accent", action: "item-watchlist" }],
        code: "000002",
        name: "万科A",
        industry: "地产",
        source: "Sector strategy",
        latestPrice: "8.20",
        eligible_status: "already_in_quant",
        blocking_reason: "",
        candidate_score: 0.73,
        already_in_quant: true,
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

function renderResearchPage(client: ApiClient) {
  const router = createMemoryRouter(
    [
      { path: "/research", element: <ResearchPage client={client} /> },
      { path: "/portfolio/position/:symbol", element: <div data-testid="stock-detail-page" /> },
    ],
    {
      initialEntries: ["/research"],
    },
  );
  render(<RouterProvider router={router} />);
}

describe("ResearchPage", () => {
  it("renders research summary markdown instead of raw markdown text", async () => {
    const markdownSnapshot = {
      ...researchSnapshot,
      summary: {
        title: "Research",
        body: "### 宏观判断\n\n- **政策底** 明确\n- 关注 `AI` 主线",
      },
    };
    const client = {
      getPageSnapshot: vi.fn().mockResolvedValue(markdownSnapshot),
      runPageAction: vi.fn().mockResolvedValue(markdownSnapshot),
      getTaskStatus: vi.fn(),
    } as unknown as ApiClient;

    renderResearchPage(client);

    expect(await screen.findAllByRole("heading", { name: "宏观判断" })).toHaveLength(2);
    expect(screen.getAllByText("政策底")[0].tagName).toBe("STRONG");
    expect(screen.queryByText("### 宏观判断")).toBeNull();
    expect(screen.queryByText("**政策底** 明确")).toBeNull();
    expect(screen.getAllByText("AI")[0].tagName).toBe("CODE");
  });

  it("shows lifecycle badges and batch promotes selected research outputs", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        success: [{ stock_code: "000001", new_status: "trial" }],
        skipped: [],
        failed: [],
      }),
    });
    vi.stubGlobal("fetch", fetchMock);
    const client = {
      getPageSnapshot: vi.fn().mockResolvedValue(lifecycleResearchSnapshot),
      runPageAction: vi.fn().mockResolvedValue(lifecycleResearchSnapshot),
      getTaskStatus: vi.fn(),
    } as unknown as ApiClient;

    renderResearchPage(client);

    expect(await screen.findByText("eligible")).toBeInTheDocument();
    expect(screen.getByText("already_in_quant")).toBeInTheDocument();
    expect(screen.queryByRole("columnheader", { name: "Actions" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Add to watchlist" })).toBeNull();
    expect(screen.getAllByRole("button", { name: "纳入量化" })).toHaveLength(1);
    expect(screen.getAllByRole("button", { name: "忽略自动纳入" })).toHaveLength(1);
    fireEvent.click(screen.getByRole("checkbox", { name: "Select 平安银行" }));
    const alreadyInQuantCountBefore = screen.getAllByText("already_in_quant").length;
    fireEvent.click(screen.getAllByRole("button", { name: "纳入量化" })[0]);
    expect(screen.getByRole("dialog", { name: "确认纳入量化" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "确认纳入" }));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        "/api/v1/quant/universe/actions/promote-to-trial",
        expect.objectContaining({
          method: "POST",
          body: JSON.stringify({ stock_codes: ["000001"], source_type: "research" }),
        }),
      );
    });
    const resultDialog = await screen.findByRole("dialog", { name: "纳入量化结果" });
    expect(within(resultDialog).getByText("成功 1 只")).toBeInTheDocument();
    expect(within(resultDialog).getByText("跳过 0 只")).toBeInTheDocument();
    expect(within(resultDialog).getByText("失败 0 只")).toBeInTheDocument();
    expect(screen.getAllByText("already_in_quant")).toHaveLength(alreadyInQuantCountBefore);
    expect(screen.getByText("eligible")).toBeInTheDocument();
  });

  it("supports row click selection and keeps stock output operations batch-only", async () => {
    const runPageAction = vi.fn().mockResolvedValue(researchSnapshot);
    const client = {
      getPageSnapshot: vi.fn().mockResolvedValue(researchSnapshot),
      runPageAction,
      getTaskStatus: vi.fn(),
    } as unknown as ApiClient;

    renderResearchPage(client);

    const checkbox = await screen.findByRole("checkbox", { name: "Select 平安银行" });
    expect(checkbox).not.toBeChecked();
    expect(screen.getByRole("link", { name: "000001" })).toHaveAttribute("href", "/portfolio/position/000001");
    expect(screen.getByRole("link", { name: "平安银行" })).toHaveAttribute("href", "/portfolio/position/000001");

    fireEvent.click(screen.getByText("银行"));
    expect(checkbox).toBeChecked();
    expect(screen.queryByRole("button", { name: "Add to watchlist" })).toBeNull();

    fireEvent.click(screen.getAllByRole("button", { name: "Add selected to watchlist" })[0]);
    await waitFor(() => {
      expect(runPageAction).toHaveBeenCalledWith("research", "batch-watchlist", { codes: ["000001"] });
    });
  });
});

