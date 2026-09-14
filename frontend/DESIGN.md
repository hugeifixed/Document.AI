# DocAI frontend design rulebook

This is the single source of truth for how the DocAI frontend looks and behaves. It binds
humans and AI coding agents alike (Claude, OpenAI Codex/GPT, or any other). `src/app.css`
implements it; components reference its sections by number (for example `§6.2`), so keep the
numbering stable when you edit this file.

The direction in one sentence: **Mercury's structure on the brand palette.** Calm, spacious,
data-first screens; Brand Blue does the work, Brand Orange gives it a voice, and navy (not gray)
carries dark mode.

---

## 1. Non-negotiables

1. **Tokens only.** Components never use raw hex values. Use the daisyUI semantic classes
   (`bg-base-100`, `text-secondary`, `border-base-300`, `btn-primary`, …) or the extended tokens
   in §3.3 via `var(--color-…)`. If a color you need does not exist, add a token to both themes
   in `src/app.css` first.
2. **Both themes, every time.** Any visual change is checked in `extract-light` and
   `extract-dark`. Light is the complete base; dark overrides. Never ship a color that is only
   defined for one theme.
3. **Accessibility is part of "done".** WCAG 2.2 AA: 4.5:1 for text, 3:1 for UI boundaries
   and focus rings, visible focus, real semantics, keyboard reachable, reduced-motion respected.
   `oxlint` runs `jsx-a11y`; a lint error is a blocker, not a warning.
4. **No new visual vocabulary.** Extend what exists (§5–§10). Do not introduce new fonts,
   radii, shadows, gradients or icon sets. When a genuinely new pattern is needed, add it to this
   rulebook in the same change.
5. **Real data or nothing.** No decorative numbers, sparklines or stats the API cannot back.
   Empty states say what will appear and how to make it appear.

## 2. Voice and content

* Sentence case everywhere: headings, buttons, labels, chips ("Review queue", not "Review Queue").
* Buttons are verbs ("Start run", "Create project"). Links name their destination ("View all").
* Numbers are formatted with `toLocaleString()` and rendered `tabular-nums`.
* Descriptions are one plain sentence; the second sentence, if any, says what refreshes or what
  happens next ("Counts refresh every 15 seconds.").
* No emoji. No exclamation marks. No marketing adjectives inside the product.

## 3. Color

### 3.1 The palette

| Role | Light | Dark | Rule |
| --- | --- | --- | --- |
| Brand Blue `primary` | `#0069AA` | `#4FA8E4` | Every interactive element: links, primary buttons, focus ring, selection, chart marks. `#0069AA` is never text on a dark surface. |
| Brand Orange `accent` | `#F58025` | `#F58025` | Brand voice only: the brand mark, notification dots, and the thin marker on a next-step cue. Never body text in light (use `--color-orange-ink`). Never a status color. |
| Navy `neutral` | `#0B2E52` | `#172338` | Hero/brand panels. Dark mode's canvas is derived from this hue. |
| Ink `base-content` | `#0F1B2D` | `#E7EDF5` | Primary text. |
| `secondary` | `#4B5A6E` | `#A3B1C4` | Descriptions, table cells, labels. |
| `--color-ink-3` | `#65758A` | `#8393A8` | Column headers, hints, placeholders, section eyebrows. |
| Canvas `base-200` | `#F3F5F9` | `#0A1220` | Sidebar and page ground. Blue-tinted, never neutral gray. |
| `--color-main` | `#FBFCFD` | `#0D1626` | Main content ground; one step lighter than the canvas. |
| Surface `base-100` | `#FFFFFF` | `#111B2C` | Cards, tables, inputs, menus. |
| Border `base-300` | `#E1E7EF` | `#223049` | Dividers and card borders (decorative, may be < 3:1). |
| `--border-interactive` | `#8893A3` | `#5A6880` | Input and select boundaries: the quietest value that still meets 3:1 (WCAG 1.4.11). Never louder than this; the focus ring carries emphasis. |

### 3.2 Status colors (§6)

| Status | Light | Dark | Soft ground |
| --- | --- | --- | --- |
| `success` | `#0F7A4A` | `#4ADE80` | `--color-success-soft` |
| `warning` | `#7A4E00` (amber) | `#E0A93A` | `--color-warning-soft` |
| `error` | `#B3261E` | `#FF7B85` | `--color-error-soft` |
| `info` | = primary | = primary | `--color-blue-soft` |

Warning is amber, **never orange** (§6.4): orange is the brand, and a warning must not look
like a brand highlight. Do not revert this.

### 3.3 Extended tokens

`--color-main`, `--color-ink-3`, `--color-blue-soft`, `--color-orange-soft`,
`--color-orange-ink`, `--color-success-soft`, `--color-warning-soft`, `--color-error-soft`,
`--border-interactive`, `--shadow-raised`, `--shadow-overlay`, `--shadow-modal`, and the splash set
(§9.5): `--splash-ground`, `--splash-content`, `--splash-muted`, `--splash-track`, `--splash-sweep`,
`--splash-ring-opacity`; and the brand mark pair (§3.4): `--brand-mark-tile`, `--brand-mark-ring`. In Tailwind
classes write them as `bg-(--color-blue-soft)`, `text-(--color-ink-3)`, `border-(--border-interactive)`.

### 3.4 Where orange may appear

The brand mark is "Rings": three concentric white rings cropped at the top-right of a navy tile
(`--brand-mark-tile`, 28% radius) with the sign-in cover's short orange bar bottom-left. The tile is the
same navy in both themes; in dark a base-300 hairline (`--brand-mark-ring`) keeps its edge on the canvas.
Source of truth is `<BrandMark />`; the same drawing ships as `public/favicon.svg` and
`public/brand/mark-rings.svg` (the other shortlisted marks sit beside it for reference). Change all
three together. The mark carries no letter: the app's name is not settled.

The brand mark (`<BrandMark />`), the notification dot, the login panel's short bar, and the thin
leading marker on at most one next-step cue per page. Not in navigation or status. Anywhere else, ask.

## 4. Typography and focus

* **Faces.** `Geist Variable` for UI, `Geist Mono Variable` for hashes, adapters, timestamps
  and code. Both are bundled from `@fontsource-variable/*`; never load fonts from a CDN.
* **Ramp.** Page title 26px/600/−0.02em (`h1`, `text-page-title`); section title 17px/600
  (`h2`, `text-section-title`); body 14px/400; caption 13px (`text-caption`); column headers 12px/500
  in `--color-ink-3`; big metrics 26–36px/600 with `tracking-tight tabular-nums`.
* **Line length.** Descriptions use `reading-copy` (65ch, `text-wrap: pretty`).
* **4.5 Focus.** One global treatment: 2px `primary` outline with 2px offset on every
  focusable element, ≥ 3:1 in both themes. Never remove it; never restyle it per component.
  Native daisyUI disclosures place this single ring on the `details` container while its summary
  has keyboard focus, in both open and closed states.
  Sticky chrome must not obscure a focused element (`scroll-margin-block: 6rem` on `main`).

## 5. Shape, depth, motion

* **5.1 Buttons are pills** (`border-radius: 999px`, set globally on `.btn`). Square buttons
  become circles. Heights: `btn-sm` 32px, default 40px. Primary is filled blue; secondary is
  `btn-outline`; quiet actions are `btn-ghost`. One primary action per view.
* **Radii.** Inputs, selects and nav items 8px (`--radius-field`), cards and menus 12px
  (`--radius-box`), chips and checkboxes 6px (`--radius-selector`). Smaller than you think: Linear,
  Stripe and Mercury all sit at 6–12px.
* **Depth.** Three levels only: `elevation-raised` (cards, stats, tables: 1px border plus a
  whisper of shadow), `elevation-overlay` (menus, popovers), `elevation-modal`. No other shadows;
  no gradients except the login brand panel and the splash ground (§9.5).
* **Motion.** 120ms for color/shadow, 180ms for panels, both `cubic-bezier(0,0,0.2,1)`. Everything
  is wrapped in `prefers-reduced-motion: no-preference`; reduced motion disables it all.

## 6. Status and confidence semantics

* **6.1 Confidence** (`<ConfidenceCue />`): three cues minimum, color + glyph + text, and the
  numeric value is always shown ("97% High", "40% Needs review").
  Identify this as model confidence, independently of source verification, in its accessible label
  and hover help; the fields panel explains the distinction quietly below its header.
* **6.2 Status chips** (`<StatusChip />`): `badge badge-sm badge-soft badge-{info|success|warning|error}`
  or `badge-ghost`; tinted ground, colored text, a glyph and a text label. Never color alone.
  New statuses are added to the `CHIP` map in `src/components/ui.tsx`, not inlined.
* **6.3 Progress** is numeric text (`842/1,240`) beside any bar; failed counts are named.
  Run details use one progress card below the header. Its bar counts terminal documents only,
  including failed and skipped documents; it never estimates provider work. Count buttons filter
  the following server-paginated items table and reset its page. All clears the status filter.
  Show up to five current documents in the server's stable activity order. Each has its operation,
  elapsed time, applicable measured page/chunk counts and group context, plus a native daisyUI
  "Processing details" disclosure for Prepare scans (when enabled), Read document, Analyze and
  Save results. Preserve expansion and focus on refresh. No event timeline or animation loop.
  Elapsed time advances from the server timestamp with a monotonic client clock. Unknown provider
  work shows waiting copy without page completion or a percentage. Estimate only when supplied
  by the server and eligible; expired estimates say "Taking longer than the estimate". After
  15 seconds without a successful progress refresh, retain data and show "Updates interrupted"
  with Retry refresh, hiding estimates. After 120 seconds without an item milestone, say
  "No new milestone for [duration]" beside its operation without diagnosing worker health.
  Announce operation, interruption and run-state changes, never elapsed-second ticks. Completion
  replaces activity with a compact summary. The items table stays before versions, metrics and
  usage, defaults to 50 rows in stable creation order, and preserves filename/status alignment,
  scan details, errors and operator-only token data. Lifecycle actions always use aggregate counts.
* **6.4 Warning is amber, never orange.**

## 7. Icons

Heroicons only (`@heroicons/react`): 24px outline in navigation and empty states, 20px solid
inside buttons, chips and table cells. Every icon carries `aria-hidden="true"` unless it is the
sole content of a control, in which case the control has an `aria-label`. No emoji, ever.

## 8. App shell

* **8.1 Layout.** 260px sidebar on the canvas ground, fixed from `lg` (1024px) up, and hideable
  there (the preference persists in `usePrefs`); when it is hidden the header shows a menu button
  that brings it back. Below `lg`, including tablets in portrait, the sidebar is a native
  `<dialog>` drawer with a real focus trap, opened by the header button. The product tour uses the
  same breakpoint. Main content is centered at max 1200px with `p-4 sm:p-6 xl:p-8` on the
  `--color-main` ground.
* **8.2 Navigation.** Grouped by lifecycle (Workspace, Configure, Process, Review, Measure &
  share); group labels are 11–13px uppercase in `secondary` for AA contrast. Items are 40px tall, 14px/500,
  8px radius, 12px horizontal padding, content vertically centered (`content-center`; daisyUI's
  menu grid otherwise top-aligns), icon in `--color-ink-3`; idle hover is a `base-100` fill. The active item is themed through
  the `--nav-active-*` tokens: in light it is a brand-blue fill with white text, icon and count
  chip, and hovering it flips to a white surface with blue text and icon; in dark the lightened
  blue reads badly as a fill, so the active item is a quiet `#172338` surface with light text and
  a blue icon, and hover lifts it one step. Text, icon and chip always switch together. No rail,
  no border. `aria-current="page"` drives all of it, and the colors live in the `menu` utility in
  `app.css` (utility classes on the link would otherwise outrank daisyUI's active color — this has
  bitten once). Live counts are quiet chips, never red.
* **8.3 Sidebar anatomy, top to bottom:** the brand row, the "Working context" card (project and
  dataset selects), the nav groups, and the adapter status card pinned to the bottom.
  The **brand row** is brand mark + wordmark on the left and exactly one 32px square ghost icon
  button at the far end, on the same axis as the mark: a double-left chevron to hide the sidebar
  on desktop, an X to close the drawer below `lg`. Never a text button — a labelled "Close"
  button in a 260px column reads as broken (Linear, Grok, Fibery and Lightfield all use the icon).
  The brand row is the only place these controls live; nothing else is added to it.
  Working-context changes refresh lists and reset pagination. From document or run details, open
  the corresponding list; from the workflow builder, open workflow versions. On document routes,
  place "Changing workspace opens its documents." quietly beneath the selectors and associate
  it with both through `aria-describedby`. Confirm unsaved drafts before changing context and
  page together; Cancel preserves the selectors and draft. Disable the selectors while saving.
* **8.4 Header.** 64px, `--color-main` ground, bottom border. Left: drawer trigger (below `lg`) and
  the working-context breadcrumb. Right: theme toggle and account menu as round ghost buttons.
  Keep the `#tour-*` ids; the product tour anchors to them.

## 9. Page anatomy

* **9.1 Dashboard.** `PageHeader` greets the user by name with a one-sentence live summary;
  one contextual `JourneyCue`; a hero grid (`xl:grid-cols-[1.6fr_1fr]`) with the run summary card
  and the review-queue card; three distinct `Stat` cards for datasets, workflow versions, and
  evaluations; then recent runs and recent errors. Do not duplicate the cue with shortcut pills
  or repeat review counts in a second stat.
  Recent runs reserve space for status, progress and date; run names truncate within the remaining
  width with the full link text retained and available on hover. On phones, show the creation date
  beneath the name instead of in a separate column so the table fits without horizontal scrolling.
* **9.2 List pages** (`Projects`, `Runs`, `Datasets`, …). `PageHeader` with a one-sentence
  description; an optional create form or `Card`; a toolbar row (search left, filters right);
  the `DataTable`. Nothing else above the table.
* **9.3 Sign in.** Centered split card (`md:max-w-3xl`): form on the left, the navy brand panel
  with the one-sentence product statement on the right (hidden below `md`). Its header carries the
  brand row and the same `<ThemeToggle />` as the app header — one control, one shape, everywhere;
  the three-way System setting lives in Settings, never in a header. The panel gradient
  `#0B2E52 → #0069AA` is the single permitted gradient and is the same in both themes.
* **9.4 Callouts.** Next-step callouts use a neutral surface, a thin orange leading marker, and a
  real labelled action. Reserve warm fills for exceptional blockers or immediate post-action
  feedback, and use at most one prominent callout per page.
* **9.5 Splash** (`<Splash />`): the boot screen while the session is checked, and its connection-error
  state. Ground `--splash-ground`: the sign-in cover gradient in light, the dark canvas with a minimal
  drift toward navy in dark; the cover's three rings top-right at `--splash-ring-opacity`. Desktop: brand
  mark and wordmark top-left, statement bottom-left with the status line and a 200×3 progress sweep
  in `--splash-sweep`. Below `lg`: everything centered. The statement cycles through three lines of
  existing sign-in copy, 3.5s each with a 400ms crossfade; the rings breathe 3% over 9s. On error the
  `<ErrorNotice />` sits top-right inset by the page padding (20 / 32 / 40px), the status reads
  "Not connected" and the sweep stops. Reduced motion shows the first line only and stops everything.
* **9.6 Recommended next step** (`<JourneyCue />`). Use at most one compact cue per page. It combines
  authoritative lifecycle facts with the user's role and links to the next useful screen with Project,
  Dataset, Workflow, Run, and origin query context preserved. Prioritize missing prerequisites, failures,
  review work, a new run, inspection, evaluation, and export in that order. Upload and creation handoffs may
  prefill a form, but they never start processing or approve governed configuration without explicit
  confirmation. Keep passive status in metrics and alternate actions in the page's normal controls.
* **9.7 Product tour.** First login starts a five-step lifecycle primer: working context, preparation,
  processing, review, and measure/share. “Take a tour” in the account menu starts the detailed role-aware
  menu tour. Both variants use the same accessible card, transition timing, and reduced-motion behavior.

## 10. Data display

* **10.1 Cards** (`<Card />`): `card card-border elevation-raised`, 16–20px padding, 16px/600
  title on the left and an optional link action on the right.
  The operator-only LLM token usage card uses a native daisyUI disclosure, collapsed on entry to
  each run. Its summary shows the title and reported total; expanding reveals the existing
  breakdown. Retain keyboard toggling and focus, and preserve expansion during background refresh.
  Loading or missing measurements must never appear as a measured zero.
* **10.2 Stats** (`<Stat />`): label 14px/500 secondary, value 26px/600 tabular, hint caption in
  `--color-ink-3`; the whole stat is a link when a page exists for it.
* **10.3 Document overlays** are measured against the rendered page in `primary` (12–15% tint).
  Evidence boxes expand visually by 4 CSS pixels on each side, clipped to the page edges,
  so their borders do not crowd the text. Saved coordinates and word-selection targets stay exact.
  Selected evidence retains its primary border with a neutral outer outline, which stays visible
  on white document pages in both themes. Activating a field locates its saved page
  and scrolls its box into view on both axes after rendering, with one 700ms emphasis that settles
  into the selected outline. Reduced motion uses the static outline and instant scrolling.
  Focus stays on the field; the location is announced. Repeat activation locates it again, while
  background refreshes preserve manual navigation. Evidence uses the processing source, with a
  quiet explanation when switching from an incompatible original. Missing locations or boxes
  are stated in the viewer; never invent geometry.
  Field names use underlined primary text and a padded hover target around the name and value,
  without a separate action label. "Clear selection" in the Fields header removes the selected
  outline and location cue, preserves the current document page, and returns keyboard focus to the field. Review mode
  chooses the first pending field on entry; it does not undo an explicit clear on refresh.
  Document inspection has compact Previous/Next controls above the viewer, with explicit run or
  dataset scope and newest-upload-first ordering. Disable controls at either end; no wraparound.
  Preserve the selected run and origin while clearing field selection on a document change.
  Review and labeling retain their task-specific navigation and draft safeguards.
  The document viewer header gives the filename its own wrapping row. Beneath it, group the
  result version separately from Page/Sheet and Zoom, with labels above controls of equal height.
  For a single result, show "Processed in" above one truncated run link and its status; use the
  workflow name/version only for an unnamed run. Do not repeat workflow metadata already carried
  by suggested run names. The full label is available on hover and the link opens run details.
  In the two-column workspace (`xl` and at least 48rem tall), the document pane sizes to its
  content and sticks 16px below the app header while the fields scroll with the page. Cap the
  pane to the available viewport height; large documents scroll inside the keyboard-focusable
  preview while controls stay visible. Narrow or short windows use normal document flow.
  Wrap the groups based on available pane width; keep page and zoom together. Version-switch help
  remains accessible without a repeated visible sentence. Source information and its switch form a
  quiet row, separated from the preview by a single divider. Controls are 44px on phones, 40px above.
  Overflowing PDF/image previews support primary mouse dragging on blank page areas, with a quiet
  hint and grab/grabbing cursor. Text and word-box targets keep their existing selection behavior.
  Trackpad, touch and keyboard scrolling stay native. Panning moves only the scroll position;
  release, cancellation or source/page changes end the gesture without changing saved evidence.
  Canonical generated checkbox names use shared display aliases: `checkbox p1:sm2` becomes
  "Checkbox 3 · Page 1". Identified checkbox states display as Checked/Unchecked; preserve business
  names, masked values, and stored values in edits, labels, and exports. Correction inputs explain
  the stored selected/unselected states. Custom extraction schemas can supply governed business
  field names; never infer names from nearby text or change a workflow to add them automatically.
  Generated checkbox markers are not document quotes. Show "Verified checkbox location" only for
  a grounded selection-mark span with a saved page, mark ID and box; otherwise say "Checkbox location
  not verified". Use the same display names in tables, document evidence, labels and review actions.
* **10.4 Tables** (`<DataTable />`): TanStack Table as a headless controller over server
  pagination. Semantic `<table>` with a `<caption>`, real `<button>`s in sortable headers with
  `aria-sort`, an opaque sticky header on `base-100`, 12px/500 headers in `--color-ink-3`, 48px
  rows, hover `base-200`, selected rows on `--color-blue-soft`, numeric columns right-aligned
  and `tabular-nums`, monospace for hashes and adapters. Search inputs are debounced 250–400ms.
  Long document names use `<FileNameLink />`: the stem truncates to keep the table compact, the
  extension remains visible, and the complete name remains the accessible label and hover title.
  Workflow names likewise truncate within a bounded column; preserve the full accessible name
  and hover title, and open the existing detail dialog to read it in full with keyboard or touch.
  Results use compact document links and bounded, single-line field names and values. Preserve
  full text for assistive technology and hover; the field name links to its document, run and
  selected field so keyboard and touch users can inspect the complete result.
  Loading, empty and error states are explicit rows, never a blank table.

* **10.5 Scan enhancement outcomes.** Keep page adjustments and skipped counts below the run-item
  status in a bounded cell. A "Scan details" button opens a native daisyUI dialog outside the table,
  keeping rows compact. Name the document and show page counts, preparation time, profile, and page
  warnings in aligned rows. Distinguish preparation outcomes from subsequent layout or extraction
  failures. Warnings use amber plus an icon and text. Escape and Close dismiss the dialog and return
  focus to its trigger. Off-mode runs add no status clutter. In the
  document pane, a quiet source switch names the analyzed representation; viewing an incompatible
  original suppresses geometry and label capture until the processing source is selected again.

## 11. Forms

Labels are visible and 14px/500 (`label` above the control, never placeholder-only). Inputs are
`input border-(--border-interactive) w-full`; errors set `input-error`, `aria-invalid` and
`aria-describedby` to a message in `text-error`. Required fields show `*` with `aria-hidden` and the
`required` attribute. Pending submits use `<AsyncButton />`, which reserves space for both labels
and announces the pending state.

Run scope offers all eligible documents, an optional oldest-first document limit, or an explicit
selection in one full-width "Documents to process" fieldset below the run's setup fields. Keep
the optional limit and "or Choose documents" on the same row when space allows, stacking on phones.
An applied selection replaces the limit with its count, "Change selection", and "Use all eligible
documents"; do not add a separate mode control. "Choose documents" opens a native dialog with
server-paginated search and labelled checkbox rows. Selections persist across pages and searches;
"Select this page" affects only
visible rows. Applying a selection clears the numeric limit, Cancel/Escape discard draft changes,
and changing dataset clears the selection. Long filenames wrap inside the chooser. Eligibility
is filtered by the server and rechecked when creating the run.

Workflow names are optional in the new-version builder: the placeholder combines document/schema
context with the workflow type, and is used when left blank. Preserve entered names and let the
server number versions; avoid timestamps in reusable workflow names. Initialize the deployment
from the backend environment default, with `gpt-5.2` as fallback, without replacing operator edits
or making a pristine form dirty.

Workflow validation uses a short toast and a persistent disclosure below the JSON editor,
open on failure with focus on its summary. Show the issue count, complete property paths,
and wrapping messages; never truncate errors or put the full report in a toast. The summary
is keyboard-toggleable. Editing configuration expires the report, and successful validation
clears it. Server reports belong to the submitted configuration, including when responses arrive late.

Workflow and chunking help uses a quiet information icon beside the field label or card heading.
Keep the help button outside the label and give it an accessible name and a 44px touch target
(40px above phone sizes). Clicking opens a native daisyUI dialog with concise use cases, a
keyboard-scrollable body and a visible Close action. Escape closes it and returns focus to the
trigger. Reading help never submits the form, changes selections or expires validation.
Chunking options use plain-language labels while retaining their API values.

## 12. Responsive rules

Design mobile-first with Tailwind's `sm` 640 / `md` 768 / `lg` 1024 / `xl` 1280 breakpoints.
Checked sizes for every screen change: 390×844 (phone), **768×1024 and 1024×768 (tablet)**,
1440×900 (desktop). Grids collapse in this order: 4 → 2 → 1 columns for stats, hero grid 2 → 1
below `xl`. Tables never squeeze: they scroll inside `ScrollRegion`, and the page body never
scrolls horizontally. Touch targets are at least 40×40 CSS px (44 on phone layouts).

## 13. Theme mechanics

Theme preference (`system | light | dark`) lives in `usePrefs` (`docai-prefs` in localStorage),
is stamped on `<html data-theme="extract-…">` before first paint by the inline script in
`index.html`, and toggled by `<ThemeToggle />`. `prefersdark` handles the system setting. New
components never read the theme in JS; they rely on tokens.

## 13.1 Small-detail checklist

Zoom to 200% on every changed region and look for: text or icons not vertically centered in
their row; a legend, label or value that wraps mid-phrase (`whitespace-nowrap` the unit);
numbers that are not `tabular-nums`; a border louder than `base-300` on anything non-interactive;
inconsistent gaps inside one row (use `gap-*`, not per-item margins); orphaned right-aligned
values with no row structure (give them a `dl` with divided rows).

## 15. Spacing system

Four steps, and every `p-*`, `gap-*`, `mb-*` in a page maps to one of them:

| Step | Value | Used for |
| --- | --- | --- |
| Inside a group | 8px (`gap-2`) | label → control, chip rows, icon → label, help text (6px via `field`) |
| Between groups | 16px (`gap-4`, `mb-4`) | form fields side by side (`gap-x-4`), toolbar → table, card grids, pagination padding |
| Between sections | 24px (`mb-6`, `gap-y-5` inside forms = 20px) | page header → content, form card → table, stacked cards |
| Page gutter | 32px (`p-8` at `xl`; 16/24 below) | `main` padding, empty states |

Rules that follow from it:

* **One container padding.** Every surface (`Card`, banners, workspace panes, dialogs) pads
  20px (`p-5`; 16px on phones). The sidebar context card pads 16px because the column is narrow.
  Nothing pads 12px except table cells and chips.
* **Tables bleed to the card edge.** A table inside a `Card` uses `flush`, which pulls it to the
  border and pads the first and last cells to the card padding, so cell text aligns with the
  card title. Never nest a padded table inside a padded card.
* **Forms use `Field`.** `<Field id label required>` owns label, help and error rhythm. Form grids
  are `gap-x-4 gap-y-5`; stacked fields sit in a `grid gap-5`. No `mt-*` between fields, ever.
  A button beside fields reserves the label row with `field-spacer` instead of a magic margin.
* **Controls in one row share a height:** 40px default, 32px `*-sm`. Mixed heights in one row are a
  bug.
* **Toolbar → table is 16px**, page header → content 24px, and cards in a grid sit 16px apart.

## 14. Definition of done for a UI change

- [ ] Uses tokens and the existing components; no raw hex, no new font/shadow/radius.
- [ ] Looks right in light and dark.
- [ ] Keyboard path works; focus visible; roles/labels correct; `npm run lint` clean.
- [ ] Checked at 768×1024, 1024×768 and 1440×900; no horizontal page scroll.
- [ ] Zoomed pass for the small details in §13.1 and the spacing steps in §15.
- [ ] `npm test` and `npm run build` pass.
- [ ] If a new pattern was introduced, this file was updated in the same change.
