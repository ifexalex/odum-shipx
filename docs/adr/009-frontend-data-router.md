# ADR-009: The frontend runs on a data router

**Status:** Accepted (2026-11-21, audit FD-54: "nothing warns before unsaved work is lost").
**Related:** `frontend/src/App.tsx`, `frontend/src/shell/UnsavedChangesGuard.tsx`, `frontend/src/hooks/useTabDraft.ts`,
`frontend/06_routing_rbac_and_navigation.md`.

## Context

A form or wizard with unsaved input must ask before the user leaves it: by a link, the sidebar, the browser's Back
button, or closing the tab. React Router can hold an in-app navigation only through `useBlocker`, and `useBlocker`
works only under a data router (`createBrowserRouter` + `RouterProvider`). The app used the declarative
`<BrowserRouter>`, under which nothing can stop a navigation: by the time a page learns the URL changed, the router has
already rendered the next page and unmounted the form. Intercepting link clicks by hand would miss `navigate()` calls
(the sidebar uses them) and the Back button.

## Decision

* **`App.tsx` creates a browser data router with one catch-all route** (`path: '*'`) whose element is the same tree as
  before: the providers and `AppRoutes`, which still declares every path with `<Routes>`. No route moves, no loader or
  action is introduced, and `routeTable.ts` / `RoleGuard` / the layouts are unchanged.
* **The app-level error boundary sits inside the route as well as around the router**, so a render error reaches the
  app's own fallback rather than the router's default error screen. Each layout keeps its own boundary.
* **The router is created on mount (`MainApp`), not at import**, so the dev-only preview pages that return before it
  (`/design-preview`, `/component-catalog`, `/auth-preview`) do not start a second router.
* **`UnsavedChangesGuard`** uses `useBlocker` for in-app navigation and `beforeunload` for tab close and reload. It
  reads `UNSAFE_DataRouterContext` and, outside a data router (a page rendered under `<MemoryRouter>` in a unit test),
  keeps only the tab-close prompt, so the ~80 page tests that use `MemoryRouter` are unaffected.

## Consequences

* Moving routes into the data router's own route objects (loaders, lazy routes, `errorElement`) becomes possible later
  without another root change; it is not done here.
* A navigation a form starts after a successful save must happen with the guard off: forms pass
  `when={dirty && !submitting}`, and `submitting` is set before the save and the navigation.
* The browser decides the wording of the tab-close prompt; only the in-app prompt is ours.
