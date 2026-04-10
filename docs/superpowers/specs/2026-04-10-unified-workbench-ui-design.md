# Unified Workbench UI Design

**Date:** 2026-04-10

## Goal

Rebuild the app UI into a coherent **modern product workbench** instead of a page-by-page collection of gradients, oversized buttons, and inconsistent card patterns.

The new direction should feel:

- calm
- contemporary
- operational
- visually restrained
- consistent across `股票分析`、`量化模拟`、`历史回放`、sidebar navigation

The approved visual direction is:

- **modern product workbench**
- **light gray-blue surfaces**
- **soft cards**
- **clean spacing**
- **clear hierarchy**

## Product Outcome

After the redesign:

- the app no longer feels like different pages belong to different products
- the sidebar, home page, realtime quant simulation, and historical replay all share one visual system
- gradients become restrained accents instead of full-page mood layers
- the top hero/banner treatment is removed in favor of a lighter page header
- spacing and alignment become systematic instead of ad hoc
- actions, metrics, tables, and detail views follow consistent visual rules

This is not a small polish pass. It is a **system-level UI unification**.

## Current Problems

The current interface feels inconsistent for four reasons:

1. **Competing visual languages**
   - purple gradients, white pill buttons, heavy banners, and soft glass-like cards all appear at once

2. **Weak layout hierarchy**
   - pages often stack big blocks top-to-bottom without a stable skeleton
   - titles, descriptions, controls, and tables do not align to a shared rhythm

3. **Spacing inconsistency**
   - title-to-description spacing changes from section to section
   - cards have inconsistent internal padding
   - labels, buttons, and table headers do not share baselines

4. **Operational pages look like marketing layouts**
   - the app is a working tool, but parts of the UI still behave like decorative landing-page sections

## Approved Direction

Use a **unified modern workbench** layout system.

This means:

- light neutral background
- soft, restrained cards
- one accent color family
- no oversized decorative hero blocks
- strong typography and spacing
- one primary workspace per page
- details shown by tabs, dialogs, or selected-row views instead of long stacked expansions

## Visual Thesis

The product should feel like a **professional investment workbench** rather than a themed Streamlit demo:

- light gray-blue shell
- white content surfaces
- soft blue accent
- very limited use of gradients
- dark neutral typography
- compact but readable controls
- dense information handled through hierarchy, not decorative chrome

## Content Plan

The UI system should organize every major page into the same broad order:

1. **Page header**
   - page title
   - short operating description
   - top-right actions only if needed

2. **Summary band**
   - KPI cards or compact metrics relevant to that page

3. **Primary workspace**
   - the most important table, form, or operating surface

4. **Secondary detail area**
   - tabs, detail panes, selected-row view, dialog, or result view

This avoids long undifferentiated pages.

## Interaction Thesis

Motion should stay minimal, but the interface should still feel alive through:

- light hover elevation on cards and buttons
- stable selected states in navigation and tabs
- dialogs and detail panels for deep inspection

No ornamental animation is required.

## Global Design System

### Color System

#### Page Background

- base: very light gray-blue
- content shell: near-white

Recommended feel:

- app shell: `#F5F8FD`
- content container: `#FBFCFF`
- sidebar surface: `#EEF3FC`

#### Accent

One blue family only:

- primary action blue
- pale blue selected states
- subtle blue chart/metric accents

Purple should no longer dominate the interface.

#### Semantic Colors

- positive / buy emphasis: warm red
- negative / sell emphasis: green
- warning: amber
- neutral / hold: gray-blue

These semantic colors should appear consistently in:

- signals
- actions
- badges
- trade outcome labels

### Typography

Use one clear hierarchy:

- page title: large, dark, strong
- section title: medium, bold
- description: smaller, quiet, gray-blue
- table body: compact, readable
- metric values: bold, strong, high contrast

Do not mix decorative heading styles between pages.

### Spacing Rules

This redesign must use explicit spacing rules instead of eyeballed spacing.

Recommended rhythm:

- title to description: `8-12px`
- section header to first control: `20-24px`
- card internal top padding: consistent per card class
- form label to field: `10-12px`
- table header to first row: `12-16px`
- stacked cards: `16-24px`

The core requirement is: **titles and descriptions must never appear visually glued together**.

### Cards

Use three card types only:

1. **Page summary card**
   - KPI value and short label

2. **Workspace card**
   - primary table, form, or working content

3. **Detail card**
   - selected-row details, signal explanations, charts

All cards should use:

- soft radius
- thin border
- low shadow
- consistent internal padding

### Buttons

Buttons must be visually calmer than the current implementation.

Rules:

- primary action: filled blue
- secondary action: pale fill or outlined
- destructive action: pale red
- row actions: compact small buttons

Do not use large CTA-sized buttons inside dense operational tables.

### Tables

Tables should be the main information surface, not a secondary afterthought.

Rules:

- tighter row height
- consistent header alignment
- compact action buttons
- no nested scroll containers inside the table area by default
- selected-row details appear elsewhere instead of expanding every row inline

## Layout System

## Sidebar

The sidebar should stay compact, quiet, and grouped.

Keep:

- `首页`
- `选股`
- `策略`
- `投资管理`
- `系统`

But render them as:

- soft grouped cards
- compact nav rows
- one selected state

The lower sidebar informational blocks should also adopt the same system:

- no heavy section dividers
- no large marketing-like blocks
- no `当前模型` panel

## Page Header

Replace the current oversized gradient banner with a **light page header**:

- left: page title + short operating description
- right: one or two top-level actions only when necessary

This header must feel like product UI, not a campaign hero.

## Page Skeleton

All major pages should use a common outer skeleton:

- left navigation rail
- main content container
- top header
- metric strip
- primary workspace row

This skeleton can adapt, but the visual logic must stay consistent.

## Page-Level Designs

## 1. 股票分析

### Role

This remains the main entry surface of the product.

### Structure

1. light header
2. compact metric strip if useful
3. left-side analysis workspace
4. right-side unified result workbench

### Analysis Workspace

Contains:

- stock input
- analysis mode
- analyst selection
- start action

This area should feel like a clean operating panel, not a long page section.

### Result Workbench

This becomes the shared visual language for downstream result display.

Examples:

- summary
- analyst opinions
- final decision
- exported artifacts
- references to quant sim / replay

This workbench should visually preview the same system used later in `量化模拟` and `历史回放`.

## 2. 量化模拟

### Role

Realtime operational workspace for:

- configuration
- candidate pool
- execution center
- account result view

### Layout

- left: configuration rail
- right top: account summary
- right middle: candidate pool table
- right bottom: switchable area for `执行中心 / 账户结果`

### Candidate Pool

Must remain the primary table.

Rules:

- compact rows
- small `立即分析 / 删除`
- no extra inline details under every row
- single-stock analysis opens in dialog

### Execution Center

Should combine:

- pending actions
- signal list
- selected signal detail

### Account Result

Should combine:

- positions
- equity
- trade summary

This avoids multiple giant tables appearing at once.

## 3. 历史回放

### Role

Replay configuration, run selection, and result audit workspace.

### Layout

- left:
  - replay configuration
  - run overview
  - current replay task
  - all replay tasks list
- right:
  - selected replay task
  - run metadata
  - replay result
  - holdings
  - equity curve
  - trades
  - signal records

### Visual Relationship to Quant Sim

This page should feel like a sibling of `量化模拟`, not a separate product.

Differences are structural, not stylistic.

## 4. Other Strategy Pages

The same system should extend to:

- 主力选股
- 低价擒牛
- 小市值策略
- 净利增长
- 低估值策略
- 智策板块
- 智瞰龙虎
- 新闻流量
- 宏观分析
- 宏观周期

These pages should generally follow:

- compact filter/config area at top
- results table as the main surface
- details shown in dialog or secondary panel

## Detailed Alignment Rules

These are mandatory visual rules for implementation:

1. Card titles and card descriptions must always have clear vertical separation.
2. Left and right columns must share top alignment baselines.
3. Table headers and row content must align to a shared grid.
4. Primary buttons must not exceed the visual weight of the data they operate on.
5. No nested section should introduce a new visual language unless it represents a new semantic level.
6. Dialogs should be used for deep details when inline expansion would break page rhythm.

## Implementation Strategy

The redesign should happen in this order:

1. define global design tokens and CSS helpers
2. rebuild sidebar and global page shell
3. rebuild `股票分析`
4. unify `量化模拟`
5. unify `历史回放`
6. normalize remaining strategy pages onto the same system

This order reduces visual drift while the redesign is underway.

## Out of Scope

This spec does not require:

- changing backend trading logic
- changing replay semantics
- redesigning the business workflow itself
- changing data fields or strategy outputs

It is a **UI system redesign**, not a business-logic rewrite.

## Acceptance Criteria

The redesign is complete when:

- the app no longer relies on oversized purple-heavy presentation blocks
- sidebar, stock analysis, realtime quant sim, and replay look like one product
- titles, descriptions, controls, and tables follow a stable spacing rhythm
- the candidate pool and replay result tables remain compact and readable
- dialogs and selected-detail views replace sprawling inline detail sections where appropriate
- the whole product feels cleaner, calmer, and more professional than the current implementation

