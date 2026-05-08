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
});
