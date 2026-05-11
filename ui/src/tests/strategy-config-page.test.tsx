import { render, screen, within } from "@testing-library/react";
import { RouterProvider, createMemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import type { ApiClient } from "../lib/api-client";
import { StrategyConfigPage, buildUnifiedEditableConfig } from "../features/settings/strategy-config-page";

const getPolicy = (config: Record<string, unknown>, path: string[]) => {
  let value: unknown = config;
  for (const key of path) {
    value = (value as Record<string, unknown>)[key];
  }
  return value as Record<string, unknown>;
};

describe("StrategyConfigPage config normalization", () => {
  it("keeps built-in profile stock feedback policy ahead of candidate defaults", () => {
    const config = buildUnifiedEditableConfig({
      base: {
        context: {
          stock_execution_feedback_policy: {
            loss_reentry_size_multiplier: 0.5,
            repeated_stop_size_multiplier: 0.35,
          },
        },
      },
      profiles: {
        candidate: {
          context: {},
        },
        position: {
          context: {},
        },
      },
    });

    expect(getPolicy(config, ["base", "context", "stock_execution_feedback_policy"])).toMatchObject({
      loss_reentry_size_multiplier: 0.5,
      repeated_stop_size_multiplier: 0.35,
    });
    expect(getPolicy(config, ["profiles", "candidate", "context", "stock_execution_feedback_policy"])).toMatchObject({
      loss_reentry_size_multiplier: 0.5,
      repeated_stop_size_multiplier: 0.35,
    });
    expect(getPolicy(config, ["profiles", "position", "context", "stock_execution_feedback_policy"])).toMatchObject({
      loss_reentry_size_multiplier: 0.5,
      repeated_stop_size_multiplier: 0.35,
    });
  });

  it("keeps built-in profile portfolio guard policy ahead of candidate defaults", () => {
    const config = buildUnifiedEditableConfig({
      base: {
        context: {
          portfolio_execution_guard_policy: {
            weak_edge_abs: 0.03,
            cooldown_size_multiplier: 0.5,
            max_new_buys_per_checkpoint: 2,
          },
        },
      },
      profiles: {
        candidate: {
          context: {},
        },
        position: {
          context: {},
        },
      },
    });

    expect(getPolicy(config, ["base", "context", "portfolio_execution_guard_policy"])).toMatchObject({
      weak_edge_abs: 0.03,
      cooldown_size_multiplier: 0.5,
      max_new_buys_per_checkpoint: 2,
    });
    expect(getPolicy(config, ["profiles", "candidate", "context", "portfolio_execution_guard_policy"])).toMatchObject({
      weak_edge_abs: 0.03,
      cooldown_size_multiplier: 0.5,
      max_new_buys_per_checkpoint: 2,
    });
    expect(getPolicy(config, ["profiles", "position", "context", "portfolio_execution_guard_policy"])).toMatchObject({
      weak_edge_abs: 0.03,
      cooldown_size_multiplier: 0.5,
      max_new_buys_per_checkpoint: 2,
    });
  });

  it("keeps lifecycle policy profile-scoped and excludes system switches", () => {
    const config = buildUnifiedEditableConfig({
      base: {
        context: {
          quant_universe_lifecycle_policy: {
            trial_threshold: 0.55,
            strong_candidate_threshold: 0.75,
            health_score_lookback_checkpoints: 10,
            trial_position_multiplier: 0.35,
          },
        },
      },
      profiles: {
        candidate: {
          context: {},
        },
        position: {
          context: {},
        },
      },
    });

    const policy = getPolicy(config, ["base", "context", "quant_universe_lifecycle_policy"]);
    expect(policy).toMatchObject({
      trial_threshold: 0.55,
      strong_candidate_threshold: 0.75,
      health_score_lookback_checkpoints: 10,
      trial_position_multiplier: 0.35,
    });
    expect(policy).not.toHaveProperty("auto_exit_enabled");
    expect(policy).not.toHaveProperty("auto_entry_mode");
  });

  it("fills hard trailing position tiers into every profile scope", () => {
    const config = buildUnifiedEditableConfig({
      base: {
        veto: {
          profit_protection: {
            hard_trailing_enabled: true,
          },
        },
      },
      profiles: {
        candidate: {
          veto: {},
        },
        position: {
          veto: {},
        },
      },
    });

    const basePolicy = getPolicy(config, ["base", "veto", "profit_protection"]);
    const candidatePolicy = getPolicy(config, ["profiles", "candidate", "veto", "profit_protection"]);
    const positionPolicy = getPolicy(config, ["profiles", "position", "veto", "profit_protection"]);
    const tiers = basePolicy.hard_trailing_position_tiers as Record<string, unknown>[];

    expect(tiers).toHaveLength(4);
    expect(tiers[0]).toMatchObject({ name: "small", max_position_cost: 10000, peak_pct: 12, drawdown_pct: 6 });
    expect(tiers[1]).toMatchObject({ name: "regular", min_position_cost: 10000, max_position_cost: 30000, peak_pct: 8, drawdown_pct: 4 });
    expect(tiers[3]).toMatchObject({ name: "large", min_position_cost: 80000, peak_pct: 5, drawdown_pct: 2.5 });
    expect(candidatePolicy.hard_trailing_position_tiers).toEqual(basePolicy.hard_trailing_position_tiers);
    expect(positionPolicy.hard_trailing_position_tiers).toEqual(basePolicy.hard_trailing_position_tiers);
  });

  it("fills missing lifecycle policy with stable spec defaults", () => {
    const config = buildUnifiedEditableConfig({
      base: {
        context: {
          quant_universe_lifecycle_policy: {},
        },
      },
      profiles: {
        candidate: {
          context: {},
        },
        position: {
          context: {},
        },
      },
    });

    expect(getPolicy(config, ["base", "context", "quant_universe_lifecycle_policy"])).toMatchObject({
      active_upgrade_threshold: 68,
      exit_only_threshold: 45,
      cooling_threshold: 36,
      retire_threshold: 28,
      exit_only_downtrend_streak: 3,
      reentry_watch_hours: 96,
      candidate_support_lookback_days: 7,
      max_auto_entries_per_batch: 4,
      max_auto_entries_per_day: 12,
      max_auto_entries_per_strategy_batch: 2,
    });
  });

  it("renders a dedicated lifecycle policy section without system-level auto exit", async () => {
    const client = {
      getPageSnapshot: vi.fn().mockImplementation((page: string) => {
        if (page === "settings") {
          return Promise.resolve({
            selectedStrategyProfileId: "stable",
            strategyProfiles: [
              {
                id: "stable",
                name: "中性",
                enabled: true,
                isDefault: true,
                config: {
                  base: {
                    context: {
                      quant_universe_lifecycle_policy: {
                        trial_threshold: 0.55,
                        strong_candidate_threshold: 0.75,
                        health_score_lookback_checkpoints: 10,
                        trial_position_multiplier: 0.35,
                      },
                    },
                  },
                  profiles: {
                    candidate: { context: {} },
                    position: { context: {} },
                  },
                },
              },
            ],
          });
        }
        return Promise.resolve({ config: { aiDynamicStrategy: "off" } });
      }),
      runPageAction: vi.fn(),
    } as unknown as ApiClient;
    const router = createMemoryRouter([{ path: "/settings/strategy", element: <StrategyConfigPage client={client} /> }], {
      initialEntries: ["/settings/strategy"],
    });

    render(<RouterProvider router={router} />);

    const sectionTitle = await screen.findByText(/Quant lifecycle|量化生命周期/);
    const section = sectionTitle.closest(".strategy-config-card");
    expect(section).not.toBeNull();
    const scoped = within(section as HTMLElement);
    expect(scoped.getByText(/trial_threshold/)).toBeInTheDocument();
    expect(scoped.getByText(/strong_candidate_threshold/)).toBeInTheDocument();
    expect(scoped.getByText(/health_score_lookback_checkpoints/)).toBeInTheDocument();
    expect(scoped.getByText(/trial_position_multiplier/)).toBeInTheDocument();
    expect(scoped.queryByText(/auto_exit_enabled/)).not.toBeInTheDocument();
  });

  it("renders hard trailing tier controls in profit protection section", async () => {
    const client = {
      getPageSnapshot: vi.fn().mockImplementation((page: string) => {
        if (page === "settings") {
          return Promise.resolve({
            selectedStrategyProfileId: "stable",
            strategyProfiles: [
              {
                id: "stable",
                name: "中性",
                enabled: true,
                isDefault: true,
                config: {
                  base: {
                    veto: {
                      profit_protection: {
                        hard_trailing_enabled: true,
                      },
                    },
                  },
                  profiles: {
                    candidate: { veto: {} },
                    position: { veto: {} },
                  },
                },
              },
            ],
          });
        }
        return Promise.resolve({ config: { aiDynamicStrategy: "off" } });
      }),
      runPageAction: vi.fn(),
    } as unknown as ApiClient;
    const router = createMemoryRouter([{ path: "/settings/strategy", element: <StrategyConfigPage client={client} /> }], {
      initialEntries: ["/settings/strategy"],
    });

    render(<RouterProvider router={router} />);

    const title = await screen.findByText(/持仓移动止盈分层|Position-size trailing tiers/);
    const section = title.closest(".strategy-config-card");
    expect(section).not.toBeNull();
    const scoped = within(section as HTMLElement);
    expect(scoped.getAllByText(/小仓位|Small/).length).toBeGreaterThan(0);
    expect(scoped.getByText(/常规仓位|Regular/)).toBeInTheDocument();
    expect(scoped.getByText(/大仓位|Large/)).toBeInTheDocument();
    expect(scoped.getAllByDisplayValue("12").length).toBeGreaterThan(0);
    expect(scoped.getAllByDisplayValue("2.5").length).toBeGreaterThan(0);
  });
});
