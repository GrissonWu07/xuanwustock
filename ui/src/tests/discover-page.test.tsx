import { fireEvent, render, screen, waitFor } from "@testing-library/react";
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
  const router = createMemoryRouter([{ path: "/discover", element: <DiscoverPage client={client} /> }], {
    initialEntries: ["/discover"],
  });
  render(<RouterProvider router={router} />);
}

describe("DiscoverPage", () => {
  it("supports row click selection and isolates single watchlist action", async () => {
    const runPageAction = vi.fn().mockResolvedValue(discoverSnapshot);
    const client = {
      getPageSnapshot: vi.fn().mockResolvedValue(discoverSnapshot),
      runPageAction,
    } as unknown as ApiClient;

    renderDiscoverPage(client);

    const checkbox = await screen.findByRole("checkbox", { name: "Select 贵州茅台" });
    expect(checkbox).not.toBeChecked();

    fireEvent.click(screen.getByText("贵州茅台"));
    expect(checkbox).toBeChecked();

    fireEvent.click(screen.getByRole("button", { name: "Add to watchlist" }));
    await waitFor(() => {
      expect(runPageAction).toHaveBeenCalledWith("discover", "item-watchlist", { code: "600519" });
    });
    expect(checkbox).toBeChecked();

    fireEvent.click(screen.getByRole("button", { name: "Add selected to watchlist" }));
    await waitFor(() => {
      expect(runPageAction).toHaveBeenCalledWith("discover", "batch-watchlist", { codes: ["600519"] });
    });
  });
});
