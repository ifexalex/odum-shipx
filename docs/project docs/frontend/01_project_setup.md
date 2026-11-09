# Task FE-01 — Project Setup & Tooling

## Objective

Scaffold the React + TypeScript + Vite SPA. No business logic yet — this task produces a buildable, deployable, empty shell.

## Depends On

None — first task.

## Stack

| Concern | Choice | Why |
|---|---|---|
| Framework | React 18 | Matches mockup component model (functional components + hooks); largest ecosystem for the libraries below |
| Language | TypeScript (strict mode) | Backend is fully typed (Pydantic + type hints) — frontend should match. Generate types from the API contracts in [05_api_client_contract.md](05_api_client_contract.md) rather than hand-rolling. |
| Build tool | Vite | Fast dev server, native ESM, simplest static-export-to-S3 story |
| Routing | react-router v6 | Matches the flat route tree documented in [06_routing_rbac_and_navigation.md](06_routing_rbac_and_navigation.md) |
| Data fetching/cache | TanStack Query v5 | See [09_state_management_and_data_fetching.md](09_state_management_and_data_fetching.md) |
| Forms | react-hook-form + zod | zod schemas can mirror the backend Pydantic models field-for-field (same validation rules, e.g. `endpoint_url` must start with `https://`) |
| Styling | CSS variables + CSS Modules (no Tailwind) | The design system (`Shipx_frontend_design/`) is built on CSS custom properties and inline styles, not Tailwind utility classes — follow that, don't introduce a second styling paradigm. See [02_design_tokens_and_theming.md](02_design_tokens_and_theming.md). |
| Icons | Custom line-icon set (port from `screens/shared/components.jsx` `Icon` component) | The mockups already define ~60 icons as inline SVG paths keyed by name — port this component directly rather than pulling in a third-party icon library, to keep visual parity. |
| Auth | `amazon-cognito-identity-js` or AWS Amplify Auth (pick one — see [04_auth_and_session.md](04_auth_and_session.md)) | Direct Cognito User Pool integration, no Amplify Hosting/backend lock-in required |
| Testing | Vitest + React Testing Library (unit/component), Playwright (e2e) | See [12_testing_strategy.md](12_testing_strategy.md) |
| Linting | ESLint (typescript-eslint) + Prettier | Mirror the backend's PEP8-equivalent rigor |

## Repo Structure

Create a new top-level `frontend/` directory (sibling to `services/`, `shared/`):

```
frontend/
├── index.html
├── vite.config.ts
├── tsconfig.json
├── package.json
├── .env.example
├── .env.local.sample                # tracked; CI copies it to .env.local
├── .nvmrc                           # pins Node 22.x for local + CI
├── eslint.config.js                 # ESLint 9 flat config (replaced .eslintrc.cjs)
├── public/
│   └── favicon.svg                 # Odum mark, see 02_design_tokens_and_theming.md
└── src/
    ├── main.tsx
    ├── App.tsx                     # router + providers root
    ├── api/                        # one file per backend service, see 05
    │   ├── client.ts                 # base fetch wrapper, error/pagination handling
    │   ├── tenantManagement.ts
    │   ├── packingList.ts
    │   ├── manifest.ts
    │   ├── tracking.ts
    │   ├── billing.ts
    │   ├── claims.ts
    │   ├── releaseNotes.ts           # payment/release — see note below
    │   ├── refunds.ts
    │   ├── notifications.ts
    │   └── excel.ts
    ├── auth/                       # see 04
    │   ├── CognitoClient.ts
    │   ├── SessionProvider.tsx
    │   ├── useSession.ts
    │   └── RoleGuard.tsx
    ├── design/                     # see 02, 03
    │   ├── tokens.css                # CSS custom properties
    │   ├── theme.ts                  # TypeScript token mirror (for JS-driven styles)
    │   └── components/
    │       ├── Button.tsx
    │       ├── Badge.tsx
    │       ├── Card.tsx
    │       ├── Field.tsx
    │       ├── Table.tsx
    │       ├── Modal.tsx
    │       ├── Banner.tsx
    │       ├── Avatar.tsx
    │       ├── Chip.tsx
    │       ├── Icon.tsx
    │       └── index.ts
    ├── shell/                      # see 06
    │   ├── Sidebar.tsx
    │   ├── TopBar.tsx
    │   ├── PageShell.tsx
    │   ├── ImpersonationBanner.tsx   # see 08
    │   └── routes.tsx
    ├── pages/                      # see 07, one subfolder per domain
    │   ├── auth/
    │   ├── platform/
    │   ├── tenant-admin/
    │   ├── china/
    │   ├── nigeria/
    │   ├── warehouse/
    │   ├── customer/
    │   └── reports/
    ├── hooks/                      # see 09; useCursorPagination.ts is the
    │                               #   cursor layer (no lib/pagination.ts)
    └── lib/
        ├── format.ts                  # currency/number display helpers
        ├── localDevSession.ts         # dev auth shim identity
        └── queryClient.ts             # TanStack Query client config
```

**No `src/types/` and no `lib/idempotency.ts` / `lib/rfc7807.ts` / `lib/pagination.ts`.**
FE-01 scaffolded those four as `TODO(FE-05)` placeholders; each was then built
somewhere better and the placeholder was never removed, so they sat as two-line
`export {}` files with zero importers until 2026-11-09:

| planned placeholder | what actually implements it |
|---|---|
| `lib/idempotency.ts` | `api/useIdempotencyKey.ts` — a hook, so the key is stable across re-renders of one mutation |
| `lib/rfc7807.ts` | `api/client.ts` (`ApiErrorShape` / `ApiError`, i.e. type/title/status/detail) + `api/errorBehavior.ts` for the status → UI mapping |
| `lib/pagination.ts` | `hooks/useCursorPagination.ts` |
| `types/api.ts` | response types co-located with the service that returns them (`api/billing.ts` exports `Billing`, and so on) rather than one central file |

The last one was a real design choice, not drift: a single shared types file has
to be kept in step with every service by hand, whereas a type beside its own
`apiRequest` call changes in the same edit as the call.

## Environment Variables

```
# .env.example
VITE_API_BASE_URL=https://api.shipx.co
VITE_COGNITO_USER_POOL_ID=eu-west-1_xxxxxxxxx
VITE_COGNITO_CLIENT_ID=xxxxxxxxxxxxxxxxxxxxxxxxxx
VITE_COGNITO_REGION=eu-west-1
VITE_ENVIRONMENT=local            # local | dev | staging | production
```

No secret values belong here — the Cognito client ID is a public identifier (no client secret is used for a SPA/public client flow). Per CLAUDE.md, never hardcode these; they're injected at build time per environment by the CI/CD pipeline (see [13_deployment_and_cicd.md](13_deployment_and_cicd.md)).

## NPM Scripts

```json
{
  "scripts": {
    "dev": "vite",
    "build": "tsc -b && vite build",
    "preview": "vite preview",
    "lint": "eslint src --ext ts,tsx",
    "test": "vitest run",
    "test:watch": "vitest",
    "test:e2e": "playwright test",
    "typecheck": "tsc --noEmit"
  }
}
```

## Local Dev Against the Backend

The backend already has a local dev story (`make stack`, `make up`, Flask dev server — see `LOCAL_TESTING.md`). Point `VITE_API_BASE_URL` at the local Flask server — default `http://localhost:3000` (the `LOCAL_PORT` env var in `scripts/local_server.py`, overridable). For local dev without real Cognito, the backend's local server accepts `X-Tenant-ID` / `X-Role` / `X-User-ID` headers directly (see [04_auth_and_session.md](04_auth_and_session.md) for how the frontend's dev-mode auth shim sets these instead of a real JWT). Copy `frontend/.env.local.example` to `frontend/.env.local` to get these defaults.

`scripts/local_server.py` runs `flask-cors` (origins `localhost:5173`/`127.0.0.1:5173`, allowing the `X-Tenant-ID`/`X-Role`/`X-User-ID`/`Idempotency-Key` headers) so the Vite dev server can call it directly — those custom headers trigger a browser CORS preflight that would otherwise block every request before it reaches Flask. Local-only; production's API Gateway + Cognito don't need this.

## Acceptance Criteria

- [x] `npm run dev` starts a Vite dev server with hot reload
- [x] `npm run build` produces a static `dist/` bundle deployable to S3
- [x] `npm run typecheck` and `npm run lint` pass with zero errors on the empty scaffold
- [x] `.env.example` documents every required `VITE_*` variable; `.env.local` (gitignored) overrides for local dev (see `.env.local.example` for the local-backend defaults)
- [x] Repo structure above exists with placeholder/empty files (no dead code, just the directories that later tasks will fill in)
- [x] CI runs `typecheck`, `lint`, and `test` on every PR touching `frontend/` (extend the existing pipeline — see `18_cicd_pipeline.md`; implemented as a separate path-filtered `.github/workflows/frontend-ci.yml`)
