# Signal Detail IA Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rework the signal detail page into a decision-first 5-layer layout so users can understand "why no buy/sell" without reading the full audit trail.

**Architecture:** Keep the existing `/signal-detail/:signalId` route and payload fetch, but reorganize the page into small derived view-model sections inside `signal-detail-page.tsx`. Use the already-returned `strategyProfile.explainability` payload to build gate checks, contribution summaries, and default-collapsed detail areas without expanding backend scope.

**Tech Stack:** React 19, React Router 7, TypeScript, Vitest, Testing Library, existing global CSS utilities.

---

### Task 1: Lock Scope And Add Regression Coverage

**Files:**
- Modify: `ui/src/features/quant/signal-detail-page.tsx`
- Create: `ui/src/tests/signal-detail-page.test.tsx`

- [ ] **Step 1: Write the failing test for the new information hierarchy**

```tsx
it("renders the decision-first sections for signal detail", async () => {
  renderSignalDetailPage(mockPayload);

  expect(await screen.findByText("门控检查")).toBeInTheDocument();
  expect(screen.getByText("贡献拆解")).toBeInTheDocument();
  expect(screen.getByText("投票明细")).toBeInTheDocument();
  expect(screen.getByText("审计模式")).toBeInTheDocument();
  expect(screen.getByText(/未买入：融合分/)).toBeInTheDocument();
});
```

- [ ] **Step 2: Run the targeted test to confirm RED**

Run: `npm test -- src/tests/signal-detail-page.test.tsx`
Expected: FAIL because the current page does not render the new section titles or the concise decision-first sentence.

- [ ] **Step 3: Write the failing test for collapsed detail behavior**

```tsx
it("keeps vote details and audit text collapsed until expanded", async () => {
  renderSignalDetailPage(mockPayload);

  await screen.findByText("投票明细");
  expect(screen.queryByText("ONLY_IN_VOTE_TABLE")).not.toBeInTheDocument();
  expect(screen.queryByText("ONLY_IN_AUDIT")).not.toBeInTheDocument();

  await user.click(screen.getByRole("button", { name: /展开投票明细/i }));
  await user.click(screen.getByRole("button", { name: /展开审计模式/i }));

  expect(screen.getByText("ONLY_IN_VOTE_TABLE")).toBeInTheDocument();
  expect(screen.getByText("ONLY_IN_AUDIT")).toBeInTheDocument();
});
```

- [ ] **Step 4: Run the targeted test to confirm RED**

Run: `npm test -- src/tests/signal-detail-page.test.tsx`
Expected: FAIL because the current page shows the old long-form layout and does not have the new collapse controls.

### Task 2: Implement The 5-Layer Page Layout

**Files:**
- Modify: `ui/src/features/quant/signal-detail-page.tsx`
- Modify: `ui/src/styles/globals.css`

- [ ] **Step 1: Extend the page payload typing with the explainability fields already returned by the API**

```ts
type SignalExplainability = {
  technical_breakdown?: { groups?: ExplainGroup[]; dimensions?: ExplainDimension[]; track?: ExplainTrack };
  context_breakdown?: { groups?: ExplainGroup[]; dimensions?: ExplainDimension[]; track?: ExplainTrack };
  fusion_breakdown?: { fusion_score?: number | string; buy_threshold_eff?: number | string; sell_threshold_eff?: number | string; weighted_action_raw?: string; weighted_gate_fail_reasons?: string[]; tech_enabled?: boolean; context_enabled?: boolean };
  decision_path?: Array<{ step?: string; matched?: string; detail?: string }>;
  vetoes?: Array<{ id?: string; action?: string; reason?: string; priority?: number | string }>;
};
```

- [ ] **Step 2: Build derived view-model helpers for the new sections**

```ts
const gateCards = buildGateCards({ decision, fusionBreakdown, vetoes, buyThreshold, sellThreshold });
const contributionSummary = buildContributionSummary({ technicalBreakdown, contextBreakdown, voteRows });
const filteredVoteRows = filterVoteRows(voteRows, voteFilter);
const auditRows = { basisList, parameterDetails, originalAnalysis, originalReasoning };
```

- [ ] **Step 3: Replace the current long "依据与推导总览" block with the 5-layer layout**

```tsx
<WorkbenchCard>
  <DecisionHero ... />
  <GateChecklist ... />
  <ContributionSection ... />
  <CollapsibleSection title="投票明细" defaultCollapsed>
    <VoteFilters ... />
    <CompactDataTable ... />
  </CollapsibleSection>
  <CollapsibleSection title="审计模式" defaultCollapsed>
    ...
  </CollapsibleSection>
</WorkbenchCard>
```

- [ ] **Step 4: Add minimal CSS for the new section rhythm and collapse controls**

```css
.signal-detail-section-stack { display: grid; gap: 14px; }
.signal-detail-checklist { display: grid; gap: 10px; }
.signal-detail-collapsible__trigger { width: 100%; justify-content: space-between; }
.signal-detail-driver-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }
```

- [ ] **Step 5: Run the targeted UI test to confirm GREEN**

Run: `npm test -- src/tests/signal-detail-page.test.tsx`
Expected: PASS with both tests green.

### Task 3: Verify Build Safety

**Files:**
- Modify: `ui/src/features/quant/signal-detail-page.tsx`
- Modify: `ui/src/styles/globals.css`
- Create: `ui/src/tests/signal-detail-page.test.tsx`

- [ ] **Step 1: Run the focused frontend test suite**

Run: `npm test -- src/tests/signal-detail-page.test.tsx`
Expected: PASS.

- [ ] **Step 2: Run a UI build verification**

Run: `npm run build`
Expected: exit code 0 with the redesigned page compiling cleanly.

- [ ] **Step 3: Inspect diff before summarizing**

Run: `git diff -- ui/src/features/quant/signal-detail-page.tsx ui/src/styles/globals.css ui/src/tests/signal-detail-page.test.tsx`
Expected: Only the intended page redesign, CSS support, and new regression test.
