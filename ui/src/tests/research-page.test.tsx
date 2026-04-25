import { fireEvent, render, screen, waitFor } from "@testing-library/react";
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
  const router = createMemoryRouter([{ path: "/research", element: <ResearchPage client={client} /> }], {
    initialEntries: ["/research"],
  });
  render(<RouterProvider router={router} />);
}

describe("ResearchPage", () => {
  it("supports row click selection and isolates single watchlist action", async () => {
    const runPageAction = vi.fn().mockResolvedValue(researchSnapshot);
    const client = {
      getPageSnapshot: vi.fn().mockResolvedValue(researchSnapshot),
      runPageAction,
      getTaskStatus: vi.fn(),
    } as unknown as ApiClient;

    renderResearchPage(client);

    const checkbox = await screen.findByRole("checkbox", { name: "Select 平安银行" });
    expect(checkbox).not.toBeChecked();

    fireEvent.click(screen.getByText("平安银行"));
    expect(checkbox).toBeChecked();

    fireEvent.click(screen.getByRole("button", { name: "Add to watchlist" }));
    await waitFor(() => {
      expect(runPageAction).toHaveBeenCalledWith("research", "item-watchlist", { code: "000001" });
    });
    expect(checkbox).toBeChecked();

    fireEvent.click(screen.getAllByRole("button", { name: "Add selected to watchlist" })[0]);
    await waitFor(() => {
      expect(runPageAction).toHaveBeenCalledWith("research", "batch-watchlist", { codes: ["000001"] });
    });
  });
});
