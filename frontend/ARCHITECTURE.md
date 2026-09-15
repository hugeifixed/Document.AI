# DocAI frontend architecture rulebook

`DESIGN.md` governs what the UI **looks like**. This document governs where code **lives** and which
module may talk to which. Both are mandatory.

Most people changing this codebase are backend developers or AI agents, not React specialists. So
the rules here are mechanical, not tasteful: there is a decision table for "where does this file
go", and the linter rejects the wrong answer. When this document and your instinct disagree,
this document wins. When this document is silent, add a rule to it in the same change.

## 1. Non-negotiables

1. **Three roots.** Every file under `src/` belongs to `app/`, `features/`, or `common/`.
2. **One-way dependencies.** `common/` → `features/` → `app/`. Never the other way.
3. **A feature never imports another feature.** Features are composed in `app/`.
4. **`common/` must be earned.** See the admission test in §5.
5. **No HTTP outside an `api/` folder.** No `axios`, no `fetch`, no `http` in a component.
6. **Server data lives in React Query and nowhere else.** Never copied into `useState`.
7. **Every new file is kebab-case** (§4.1). Existing files are renamed when they move.
8. **A component ships with its test** in the same folder (§4.3).
9. **No barrel files, no default exports.** Import the file you mean.
10. `npm run lint && npm run typecheck && npm test` passes before you call the work done.

## 2. The three roots

```
src/
  app/        composition root: providers, router, routes, the app shell
  features/   one folder per business capability; self-contained
  common/     genuinely shared, feature-agnostic building blocks
```

```
 common/  ──────►  features/  ──────►  app/
   ▲                   ▲                  │
   └───────────────────┴──────────────────┘
        app/ may import both. features/ may import common/.
        common/ imports neither. features never import each other.
```

Why this shape: it makes the blast radius of a change visible from the path alone. Touching
`features/runs/**` cannot break review. Touching `common/**` can break everything, so it is the
folder with the highest bar for entry.

### 2.1 `app/`

The composition root. It is the only place that knows the full set of features exists.

```
src/app/
  provider.tsx        QueryClientProvider, session, toaster — every global provider
  router.tsx          route table
  routes/             thin route modules; each renders one feature component
  layouts/app-shell/  the chrome: sidebar, header, working-context pickers
  navigation.ts       the nav model the shell renders
```

Route modules stay thin. A route file wires params to a feature component and nothing else:

```tsx
// src/app/routes/run-detail-route.tsx
export function RunDetailRoute() {
  const { id } = useParams();
  return <RunDetail runId={id!} />;
}
```

If a route file contains a form, a table, or a query, that code belongs in a feature.

### 2.2 `features/`

One folder per business capability, named after the capability, lowercase:

```
features/
  auth  dashboard  datasets  evaluation  exports
  projects  results  review  runs  settings  workflows
```

A feature owns its screens, its API calls, its state, its types, and its tests. If two features
want the same code, read §5 before moving anything.

### 2.3 `common/`

Feature-agnostic building blocks only:

```
src/common/
  api/         the HTTP client, request helpers, error types
  types/       the backend contract (see §6.1)
  components/  primitives with no domain knowledge: ui/, DataTable/, ConfirmDialog/
  hooks/       useTableState and friends
  lib/         preconfigured third-party wiring: react-query, announce, auth session
  stores/      global client state (prefs)
  utils/       pure functions with no domain vocabulary
  config/      route paths, polling intervals, env
```

`common/` is a library the app happens to ship with. It must be readable without knowing what
DocAI does.

## 3. Where does this file go?

| You are writing… | It goes in |
| --- | --- |
| A screen a route renders | `features/<feature>/components/` |
| A widget used by one feature | `features/<feature>/components/` |
| A widget used by two or more features | `common/components/` — but read §5 first |
| An API request | `features/<feature>/api/` |
| The HTTP client or an error helper | `common/api/` |
| A TypeScript type mirroring a DRF serializer | `common/types/api.ts` |
| A type used only inside one feature | `features/<feature>/types/` |
| A hook that calls an endpoint | `features/<feature>/api/` (next to the request) |
| A hook with no domain knowledge (`useDebounce`) | `common/hooks/` |
| Business logic about Runs, Documents, Labels | `features/<feature>/utils/` |
| A pure helper with no domain vocabulary | `common/utils/` |
| Zustand state one feature owns | `features/<feature>/stores/` |
| Zustand state the whole app reads | `common/stores/` |
| The route table, a provider, the shell | `app/` |
| A test | next to the file it tests (§4.3) |
| A browser test | `e2e/` — see `TESTING.md` |

Nothing goes at the root of `src/`. The only files allowed directly in `src/` are `main.tsx` and
`app.css`.

## 4. Anatomy of a feature

```
features/runs/
  api/          one file per endpoint, plus query-keys.ts
  components/   screens and widgets, each with its test
  hooks/        stateful logic that is not a request
  stores/       zustand state this feature owns
  types/        types not in the backend contract
  utils/        pure feature logic
```

Create only the folders you need. A feature with one screen and two endpoints has `api/` and
`components/` and nothing else.

### 4.1 Naming

**Every file and folder is kebab-case.** No exceptions, no matter what the file exports.

| File | Exports |
| --- | --- |
| `run-progress.tsx` | `RunProgress` |
| `run-progress.test.tsx` | the test for it |
| `use-table-state.ts` | `useTableState` |
| `query-keys.ts` | `runKeys` |
| `get-runs.ts` | `getRuns`, `useRuns` |

Symbols keep the casing their language expects — components PascalCase, hooks and functions
camelCase, types PascalCase. Only the *filename* is kebab. The rule to apply is: **the filename is
the kebab-case of what the file exports.** Strip the `use` prefix nowhere; `useTableState` becomes
`use-table-state.ts`, not `table-state.ts`.

- **One exported component per file.** Small private helpers in the same file are fine as long as
  they are not exported.
- Existing files keep their current names until they move. A migration move is already a rename,
  so rename and relocate in the same step rather than churning the tree twice.
- Renaming only the case of a file (`DataTable.tsx` → `data-table.tsx`) is invisible to macOS's
  case-insensitive filesystem and Git will not record it. Go through a temporary name:
  `git mv DataTable.tsx tmp.tsx && git mv tmp.tsx data-table.tsx`.

### 4.2 Imports

- Import across roots with the `@/` alias: `@/common/components/ui/card`.
- Import **inside** your own feature with relative paths: `./run-progress`, `../api/get-run`.
- Never import another feature. Never write `../../` inside a feature — if you need to, you are
  reaching out of your feature and the linter will stop you.

### 4.3 Tests live with their subject

Every component sits next to its test. While a folder holds exactly one component, both files may
sit flat:

```
features/runs/components/
  run-progress.tsx
  run-progress.test.tsx
```

As soon as a second component joins that folder, **each component moves into its own subfolder**:

```
features/runs/components/
  run-progress/
    run-progress.tsx
    run-progress.test.tsx
  run-items-table/
    run-items-table.tsx
    run-items-table.test.tsx
```

Never let `one.tsx`, `one.test.tsx`, `two.tsx`, `two.test.tsx` pile up flat in one folder.
Shared test setup and render helpers stay in `src/testing/`.

## 5. The admission test for `common/`

A file belongs in `common/` only when **all three** hold. This is the rule agents get wrong most
often, so it is checkable rather than a matter of judgment.

1. **Rule of two.** Two or more features import it *today*. Not "will probably", not "seems
   generic". Count the importers.
2. **No domain vocabulary.** It encodes no business rule about Runs, Documents, Labels, workflows,
   or field-naming conventions. Referencing a type from the backend contract is fine; encoding a
   rule about that type is not.
3. **Promote, never predict.** Code is born inside the feature that needs it. It moves to `common/`
   on the day a second feature imports it, as its own commit that does nothing else.

Worked examples from this repository:

| Module | Verdict | Why |
| --- | --- | --- |
| `listValues.ts` — parse a JSON list, summarize it | `common/utils/` | Two features use it; pure; no domain vocabulary. |
| `fieldPresentation.ts` — decode `checkbox p1:sm0` names | `features/review/utils/` | Encodes a DocAI naming rule. Generic-looking, domain-bound. |
| `navigation.ts` — the sidebar nav model | `app/` | Only the shell renders it; it names every feature. |
| `runs/lifecycle.ts` — poll intervals, run status logic | `features/runs/` | Pure Runs domain. |
| `DataTable.tsx` | `common/components/` | No DocAI concepts; drives any paginated endpoint. |
| `workspace/context.ts` — active project/dataset | `common/lib/` | Ambient context every feature reads, like the session. Documented exception to rule 2 (§14). |

When a third feature wants something that fails the test, **duplicate it**. Two honest copies are
cheaper than a shared abstraction that drags domain knowledge into `common/`.

## 6. Data access

### 6.1 The backend contract

`common/types/api.ts` is the single mirror of the DRF serializers. It is the one place where
backend and frontend agree, and it is deliberately shared rather than split per feature — the
backend owns this shape, and `Run`, `Document` and `Span` are genuinely used by six features.
Change it in the same pull request that changes the serializer.

`common/api/client.ts` owns the transport: the axios instance, the envelope unwrapping, `ApiError`
with `error_code` and `trace_id`, and the `get` / `post` / `del` / `list` / `tableParams` helpers.
Nothing else in the codebase may import `axios` or call `fetch`.

### 6.2 Every request is a named function

No inline `queryFn` in a component. A request is a typed function in the feature's `api/` folder,
paired with the hook that calls it:

```ts
// features/runs/api/query-keys.ts
export const runKeys = {
  all: ["runs"] as const,
  list: (filters: RunListFilters) => [...runKeys.all, "list", filters] as const,
  detail: (id: string) => [...runKeys.all, "detail", id] as const,
};

// features/runs/api/get-runs.ts
export function getRuns(filters: RunListFilters) {
  return list<Run>("/runs/", { ...tableParams(filters.table), project: filters.projectId });
}

export function useRuns(filters: RunListFilters) {
  return useQuery({ queryKey: runKeys.list(filters), queryFn: () => getRuns(filters) });
}
```

The component then reads one line:

```tsx
const runs = useRuns({ table: state, projectId });
```

Why the key factory: invalidation becomes reliable. `qc.invalidateQueries({ queryKey: runKeys.all })`
clears every runs query, including ones written after yours. Hand-written key arrays scattered
across call sites cannot give that guarantee, and stale tables after a mutation are the most common
bug in this codebase.

Rules:

- One file per endpoint, named after what it does: `get-runs.ts`, `cancel-run.ts`.
- The query hook lives beside its request function, not in `hooks/`.
- Every feature that queries has exactly one `query-keys.ts`.
- Mutations invalidate through the key factory. Never reach into the cache by string.

## 7. The four kinds of state

Choosing the wrong one is the second most common mistake here. There is exactly one right answer
per kind.

| Kind | Example | Where it lives |
| --- | --- | --- |
| **Server state** | the list of runs, a document | React Query. Only React Query. |
| **URL state** | page, sort, search, filters | `useSearchParams` via `common/hooks/useTableState` |
| **Global client state** | theme, page size, active project | zustand in `common/stores/` |
| **Local state** | is this dialog open, a draft input | `useState` in the component |

Hard rules:

- **Never copy server data into `useState` or zustand.** If you find yourself writing
  `useEffect(() => setRows(query.data), [query.data])`, delete it and read `query.data` directly.
  The copy goes stale, and no one can tell which version is on screen.
- Anything a user should be able to bookmark, refresh, or share belongs in the URL, not in state.
- Reach for zustand only when state outlives the component tree that shows it. Two components
  needing the same value is a reason to lift it up, not to make it global.

## 8. React rules for people who do not write React

This section exists because these five mistakes account for most of the review comments on this
codebase.

**A component is a function that returns UI from its props.** Same props in, same UI out. It may
not mutate its arguments, write to module-level variables, or call an API during render.

**`useEffect` is not `__init__` and not a lifecycle hook.** It is an escape hatch for
synchronizing with something outside React — a timer, the document title, an event listener. If
your effect only reads props and state and calls `setState`, delete it and compute the value
during render instead:

```tsx
// wrong: an extra render, and one frame where the screen shows the old value
const [total, setTotal] = useState(0);
useEffect(() => setTotal(items.length * price), [items, price]);

// right: derived values are just values
const total = items.length * price;
```

**Never fetch in `useEffect`.** React Query does caching, deduplication, retries, cancellation and
refetching. A hand-rolled effect does none of it and will race.

**Hooks run in order, every render.** Never call one inside a condition, a loop, or after an early
`return`. Put the early return after all the hooks.

**`key` is an identity, not a counter.** Use the row's `id`. Using the array index makes React
reuse the wrong DOM node when the list reorders, which shows up as an edit landing on the wrong
row.

**Use the primitives.** `common/components/ui/` exists so that spacing, focus rings, status
semantics and accessible names are decided once. A hand-rolled `<button className="...">` will
fail the accessibility gate and will not match `DESIGN.md`.

## 9. Component rules

- One exported component per file; file name equals the exported symbol.
- Named exports only. No `export default`.
- **300 lines is the ceiling.** At 300 the linter warns; treat it as a defect, not a suggestion.
  A component over 300 lines is doing three jobs — split the table, the form, and the dialog apart.
- Props are typed inline or as a local `interface Props`. No `any`; use `unknown` and narrow.
- A component renders; it does not transform. Non-trivial data shaping goes to `utils/` where it
  can be unit tested without rendering.
- No barrel files. `index.ts` re-export hubs break Vite tree-shaking and hide where code lives.

## 10. Styling and accessibility

`DESIGN.md` is the authority. In short: design tokens only, never a raw hex value in a component;
new UI patterns are added to `DESIGN.md` in the same change; check both themes and the tablet
sizes in `DESIGN.md` §12.

`jsx-a11y` runs on every lint. **An accessibility lint error blocks the change** — do not silence
it with a disable comment unless you explain in the comment why the rule is wrong here, as
`ScrollRegion` does.

## 11. Testing

- Unit and component tests are Vitest + React Testing Library, colocated per §4.3.
- Test what the user observes: query by role and accessible name, not by class name or test id.
- The coverage gate is in `vite.config.ts` and applies to the whole suite.
- Browser-only behavior — native dialogs, focus restoration, drag and drop, responsive overflow —
  belongs in `e2e/`. See `TESTING.md` for both lanes.

## 12. What the linter enforces

These are not suggestions; `npm run lint` fails on them. Each rule prints the reason.

| Rule | Enforced by |
| --- | --- |
| A feature never imports another feature | `no-restricted-imports` on `src/features/**` |
| No relative escape out of a feature | `no-restricted-imports`, pattern `../../*` |
| `common/` never imports `features/` or `app/` | `no-restricted-imports` on `src/common/**` |
| `features/` never imports `app/` | `no-restricted-imports` on `src/features/**` |
| No `axios` outside `common/api/` | `no-restricted-imports` |
| Code in the target layout never imports a pre-migration path | `no-restricted-imports`, patterns `@/pages/*`, `@/api/*`, `@/store/*`, … |
| No barrel files | `oxc/no-barrel-file` |
| Named exports only | `import/no-default-export` |
| No import cycles | `import/no-cycle` |
| Kebab-case filenames | `unicorn/filename-case` on `src/app/**`, `src/features/**`, `src/common/**` |
| 300-line ceiling | `max-lines` (warning) |
| Accessibility | `jsx-a11y` plugin |

Test files are exempt from the transport and boundary rules — they stub the transport and
reach across boundaries deliberately. §11 governs them instead.

One rule the linter cannot express and reviewers must hold: the raw `http` axios instance may
only be used inside an `api/` folder, and only where `get`/`post` cannot do the job — today that
is upload progress. It must never appear in a component.

Before you finish:

```bash
cd frontend && npm run lint && npm run typecheck && npm test && npm run build
```

## 13. Migration status

The target structure above is **not yet the shape on disk.** Root [`ARCHITECTURE.md`](../ARCHITECTURE.md)
maps the current implementation for juniors and agents. The rules are already armed: the
moment a `src/features/` or `src/common/` folder appears, the boundary rules apply to it, and the
legacy paths are already banned from new code.

Migration is a strangler, not a big-bang rewrite:

- **New work lands in the target layout.** A new screen creates its feature folder; it does not go
  in `src/pages/`.
- **A feature moves whole, in its own commit,** with no behavior change in that commit. Files are
  renamed to kebab-case as part of that move (§4.1), never as a separate pass.
- Suggested order, easiest first: `runs` (already half-extracted into `src/runs/`), `projects`,
  `datasets`, `workflows`, `evaluation`, `exports`, `dashboard`, `review`, then the `app/` split
  of `main.tsx` and `layouts/AppShell.tsx` into `app/`, and finally `common/`.
- `review` and `labeling` merge into a single `features/review`. They already share
  `ReviewWorkspace` through a `mode` prop, and keeping them apart would require exactly the
  cross-feature import this document bans. `app/routes` mounts the one component at both paths.
- When the last file leaves `src/pages/`, promote `max-lines` from warning to error.

Current homes and where they are going:

| Today | Destination |
| --- | --- |
| `src/pages/*` | `src/features/<feature>/components/`, renamed kebab (`RunDetail.tsx` → `run-detail.tsx`) |
| `src/runs/`, `src/groundTruth/`, `src/journey/`, `src/components/review/` | their feature |
| `src/fieldPresentation.ts` | `features/review/utils/` |
| `src/listValues.ts` | `common/utils/` |
| `src/navigation.ts` | `app/` |
| `src/workspace/` | `common/lib/workspace/` |
| `src/api/`, `src/a11y/`, `src/hooks/`, `src/store/`, `src/components/DataTable.tsx` | `common/` |
| `src/components/ui.tsx` | `common/components/ui/` — one kebab-named file per primitive (§9) |
| `src/auth/Session.tsx` | `common/lib/auth/`; `pages/Login.tsx` → `features/auth/` |
| `src/main.tsx`, `src/layouts/AppShell.tsx` | `src/app/` |
| `src/test/*` | colocated per §4.3; helpers to `src/testing/` |

## 14. Deviations from the standard feature-sliced layout, and why

This structure follows the widely used "bulletproof React" layout, with two deliberate changes.
Naming is *not* one of them: files are kebab-case here exactly as they are there.

1. **One shared root called `common/`** instead of top-level `components/`, `hooks/`, `lib/`,
   `utils/`, `types/`, `stores/`. Three roots are easier to hold in your head and make the
   boundary rule a single sentence. The same subfolders exist, one level down.
2. **One shared API contract** in `common/types/api.ts` rather than per-feature types. The Django
   serializers own this shape; splitting it would force either duplication or a shared "core
   types" escape hatch, which is the same thing with a worse name.

One documented exception to the `common/` admission test: `workspace/context.ts` names projects and
datasets, so it fails rule 2 on a strict reading. It is ambient application context that nearly
every feature reads, exactly like the session, and there is no feature that could own it. Treat it
as infrastructure, not as a precedent — a second exception needs a change to this document.

## 15. Checklists

### Add a screen

1. `src/features/<feature>/` — create it if this is a new capability.
2. `api/query-keys.ts` and `api/<verb>-<thing>.ts` for each endpoint, with its query hook.
3. `components/<screen>.tsx` — the screen, built from `common/components/ui/` primitives.
4. `components/<screen>.test.tsx` — beside it; move both into a subfolder if the folder now holds
   two components.
5. `app/routes/` — add the route module; register it in `app/router.tsx`.
6. `app/navigation.ts` — add the nav entry if it belongs in the sidebar.
7. `npm run lint && npm run typecheck && npm test`.

### Add an endpoint

1. Add or update the type in `common/types/api.ts` to match the serializer.
2. Add `api/<verb>-<thing>.ts` in the owning feature, using `get` / `post` / `list` / `tableParams`.
3. Add its key to that feature's `query-keys.ts`.
4. For a mutation, invalidate through the key factory in `onSuccess`.
5. Handle `ApiError`: show `message`, and surface `error_code` where support needs it.

### Promote a module to `common/`

1. Prove the rule of two — name both importing features.
2. Confirm there is no domain vocabulary in it; if there is, duplicate instead.
3. Move it in a commit that does nothing else, and update the importers in that commit.
4. If it is a component, move its test with it.

### Review a change (human or agent)

1. Does every new file have a home justified by the table in §3?
2. Any cross-feature import, or any `../../` inside a feature?
3. Any inline `queryFn`, hand-written query key, or `axios` outside `common/api/`?
4. Any server data copied into `useState`, or any `useEffect` computing a derived value?
5. Is each new file kebab-case, each new component under 300 lines, with its test beside it?
6. `DESIGN.md` checks: tokens, both themes, tablet sizes.

## 16. Browser page titles

`app/page-routes.ts` inventories every existing page with a static `handle.pageTitle` in Title Case.
`main.tsx` composes these records with their lazy modules while the legacy routes await migration (§13).
When adding a route, add its fixed label to that inventory and its lazy module to `pageModules`; extend
`app/page-routes.test.ts` with its expected path and label. Keep metadata outside the lazy module so
it is available before imports, session checks, and data requests complete.

`app/page-title-config.ts` is the single source for the application name, separator, environment
rules, and fallback. Production titles are `<Page Title> | <Application Name>`; nonproduction titles
are `[<ENV>] <Page Title> | <Application Name>`. `PageTitleOwner`, mounted outside `RouterProvider`,
is the only `document.title` writer. It follows current and pending router locations, browser history,
and error boundaries. Never write or restore titles in a page effect.

Use only approved page-level labels: no filenames, customer names, IDs, query parameters, record
content, counts, timestamps, or progress. Table loading/empty/retrieval failures retain the route label.
A whole-page failure or denied view declares its fixed label with `usePageTitleState`; the owner
formats it and removes the override when the view or location changes. This generic context hook
lives in `common/hooks/`, already consumed by workflows, labeling, review, and session infrastructure;
HTTP error classification lives in `common/utils/error-page-title.ts`. Neither knows application
branding, routes, or domain data. New features may use them without importing `app/`.

Current labels: `/` Workspace; `/datasets` Document Upload; `/review` Review Queue;
`/review/:documentId` Document Review; `/results` and `/documents/:documentId` Extraction Results;
`/runs` Processing History; `/runs/:id` Processing Run; `/projects` Projects;
`/configurations` Workflows; `/workflows/new` New Workflow; `/labeling` Ground Truth;
`/labeling/:documentId` Document Labeling; `/evaluation` Evaluation; `/exports` Exports;
`/settings` Settings; `/login` Sign In; unknown routes Page Not Found. Denied views use Access Denied;
other whole-page errors use Page Error. There are no standalone schema-library or access-management
pages to title. See `DEPLOYMENT.md` for environment configuration and the institutional Teams check.
