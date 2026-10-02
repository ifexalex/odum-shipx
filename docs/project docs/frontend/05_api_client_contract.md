# Task FE-05 — API Client Contract

## Objective

Build the one HTTP client every page/hook calls through. Centralize auth headers, error parsing, pagination, and idempotency here once — no page should hand-roll a `fetch()` call.

## Depends On

Task 04 (needs `Session` to attach auth headers).

## Backend Contract (ground truth — `shared/responses.py`, `shared/pagination.py`, `shared/idempotency.py`)

### Success responses

```ts
// Single resource — GET/POST/PUT/PATCH
interface SuccessResponse<T> { data: T; meta?: Record<string, unknown> }

// 201 Created also sets a `Location` header
// 204 No Content has an empty body (DELETE)
```

### List responses (cursor pagination)

```ts
interface ListResponse<T> {
  data: T[];
  meta: {
    pagination: {
      has_more: boolean;
      next_cursor: string | null;   // opaque base64url string — never parse this client-side, just pass it back
      total_count: number;
    };
  };
}
```

Request params: `?cursor=<opaque>&limit=<1-100, default 20>`. Build a generic `useCursorPagination<T>()` hook (Task 09) once on top of this shape — every list page in Task 07 uses it identically.

### Error responses — RFC 7807 (`application/problem+json` shape, exact field names)

```ts
interface ApiError {
  type: string;           // "https://errors.logistics-api.com/{error-code-kebab}"
  title: string;
  status: number;
  detail: string;
  error_code: string;     // machine-readable, e.g. "RESOURCE_NOT_FOUND"
  instance?: string;      // request path
  errors?: { field: string; message: string }[];  // present only on 422 validation errors
}
```

### Status code → handling table

| Status | error_code examples | Frontend behavior |
|---|---|---|
| 401 | `AUTHENTICATION_REQUIRED` | Attempt silent token refresh once; if that also fails, force logout → redirect to `/login` |
| 403 | `INSUFFICIENT_PERMISSIONS`, `TENANT_SUSPENDED` | Show a blocking banner/page, do not retry. `TENANT_SUSPENDED` gets its own full-page state (see Task 07 — Platform-admin-only "tenant suspended" view also exists for staff logging into a suspended tenant) |
| 404 | `RESOURCE_NOT_FOUND` | Render the page's empty/not-found state — same for "doesn't exist" and "exists but you can't see it" (backend deliberately returns 404 not 403 for cross-tenant access, to avoid resource enumeration — don't try to distinguish these client-side) |
| 409 | `DUPLICATE_RESOURCE`, `ILLEGAL_TRANSITION`, `IDEMPOTENCY_CONFLICT` | Surface `detail` as an inline form/action error, not a toast — these are almost always actionable ("packing list already submitted") |
| 410 | `TENANT_OFFBOARDED` | Full-page terminal state, no retry, no nav — port `OffboardedScreen` from `Shipx_frontend_design/screens/gapfix/gapfix-screens-a.jsx` |
| 422 | `VALIDATION_ERROR`, `BUSINESS_RULE_VIOLATION`, `SELF_APPROVAL_FORBIDDEN` | Map `errors[].field` directly onto react-hook-form field errors when present; otherwise show `detail` as a form-level banner |
| 429 | `USAGE_LIMIT_EXCEEDED` | Show the quota-limit-reached modal (see Task 07 — Quota Enforcement screens already designed in `screens/quota/quota-screens.jsx`), not a generic error toast |
| 502 | `EXTERNAL_SERVICE_ERROR` | Retry-able toast ("a third-party service is unavailable, try again shortly") |
| 503 | `SERVICE_UNAVAILABLE` | Backend's fail-closed response when a security/infra check can't complete. Treat identically to 502 — retry-able, not the user's fault. |

### Idempotency

For every `POST` that creates a resource, generate a UUID v4 client-side **once per logical submission** (not per retry) and send it as `Idempotency-Key`. On a network-level retry of the *same* logical submission (timeout, double-click), reuse the same key — the backend returns the original cached response instead of creating a duplicate. Regenerate the key only when the user actually starts a new logical action (e.g. re-opening the "create container" form after a successful submit).

```ts
const idempotencyKey = useRef(crypto.randomUUID()); // stable for the lifetime of one form mount
```

## Client Shape

```ts
// src/api/client.ts
interface RequestOptions {
  method: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
  path: string;                       // e.g. "/v1/containers"
  body?: unknown;
  query?: Record<string, string | number | undefined>;
  idempotencyKey?: string;
}

async function apiRequest<T>(opts: RequestOptions): Promise<T> {
  // 1. attach Authorization: Bearer <token>, and X-Token-Type: impersonation if active
  // 2. attach Idempotency-Key if provided
  // 3. on 401: try silent refresh once, replay request once, else throw AuthExpiredError
  // 4. on non-2xx: throw a typed ApiError (parsed RFC7807 body)
  // 5. on 2xx with body: return parsed `data` (unwrap the SuccessResponse envelope here, once)
}

// Paginated list endpoints (shared/responses.py's paginated()) return
// {data: T[], meta: {pagination}} at the *top level* — there is no
// SuccessResponse envelope wrapping that shape, so there is nothing for
// apiRequest<T> to unwrap a level deeper. Use this for every paginated GET
// instead of apiRequest<ListResponse<T>> — the latter compiles but silently
// double-unwraps at runtime (result.data ends up undefined).
async function apiRequestList<T>(opts: RequestOptions): Promise<ListResponse<T>> {
  // steps 1-4 identical to apiRequest, then: return the parsed body as-is
}
```

One function per backend service under `src/api/` (`tenantManagement.ts`, `packingList.ts`, etc.), each a thin typed wrapper calling `apiRequest`/`apiRequestList`. Example:

```ts
// src/api/packingList.ts
export const packingListApi = {
  list: (params: { cursor?: string; limit?: number; containerId?: string }) =>
    apiRequestList<PackingList>({ method: "GET", path: "/v1/packing-lists", query: params }),
  create: (body: CreatePackingListRequest, idempotencyKey: string) =>
    apiRequest<PackingList>({ method: "POST", path: "/v1/packing-lists", body, idempotencyKey }),
  approve: (id: string) =>
    apiRequest<PackingList>({ method: "PATCH", path: `/v1/packing-lists/${id}/approve` }),
  // ...
};
```

**Implementation note:** the per-service wrapper files (`tenantManagement.ts`, `packingList.ts`, `manifest.ts`, `billing.ts`, `claims.ts`, `refunds.ts`, `paymentRelease.ts`, `tracking.ts`, `notifications.ts`, `excel.ts`) are left as their FE-01 `TODO(FE-05/FE-07)` stubs for now. Fleshing them out requires the real request/response types for each domain, which come from reading Tasks 07–15 screen-by-screen — that work happens in Task 07 as each module is built, not speculatively here. FE-05's deliverable is the generic `apiRequest`/`ApiError`/pagination-types/idempotency/error-behavior layer every one of those wrappers will call into.

## Request ID Propagation

Every backend response includes `X-Request-Id`. Capture it in the API client and attach it to any error-reporting/Sentry event for that failed call — this is the fastest way to correlate a frontend bug report with a CloudWatch log line.

## Acceptance Criteria

- [x] Single `apiRequest<T>` function handles auth headers, error parsing, and response unwrapping — verified by grepping `src/` for raw `fetch(` outside `client.ts` (zero matches; `sessionBridge.ts` has only a comment mentioning the word). A second function, `apiRequestList<T>`, shares the same auth/error-handling core (`fetchWithAuth`) but returns the parsed `ListResponse<T>` envelope unwrapped — added after FE-07 7.3 found that every list-endpoint call site had been written as `apiRequest<ListResponse<T>>`, which double-unwraps and silently returns `undefined` for `.data` (never caught earlier because no list page had been browser-tested against a real backend until 7.3 — see `07_domain_modules.md`'s 7.3 notes).
- [x] `ApiError` type matches the RFC 7807 shape exactly, including optional `errors[]` — `client.ts#ApiErrorShape`/`ApiError`, covered in `client.test.ts`.
- [x] 401 triggers exactly one silent-refresh-and-replay attempt before forcing logout — `client.ts#recoverFrom401`. Also handles a nuance the original wording didn't spell out: a 401 while **impersonating** exits impersonation instead of attempting a refresh (impersonation tokens never refresh, per Task 04) — covered in `client.test.ts`.
- [x] A generic cursor pagination helper exists and is used by every list page (no page reimplements cursor encoding/decoding) — FE-05 owns the contract (`ListResponse<T>`, `PaginationMeta`, the `cursor`/`limit` query convention in `RequestOptions`); the actual `useCursorPagination` hook built on top of it is Task 09's deliverable per `09_state_management_and_data_fetching.md`, used once list pages exist in Task 07.
- [x] Idempotency keys are generated once per logical form submission and verified (via a test) to stay stable across a simulated retry — `useIdempotencyKey.ts`, covered in `useIdempotencyKey.test.ts`.
- [x] Status-code → UI-behavior table above is implemented as a single error-handling layer (e.g. a React Query `onError` default), not duplicated per page — implemented now as a pure, directly-testable `interpretApiError()` in `errorBehavior.ts` (covers 403/404/409/410/422/429/502/503, plus a `0`/`NETWORK_ERROR` case for offline/DNS/CORS failures normalized in `client.ts#doFetch`); Task 09 wires this into React Query's global `onError` once that layer exists.
- [x] `X-Request-Id` from every failed response is captured and attached to error reports — captured on every thrown `ApiError` as `.requestId`. "Attached to error reports" is N/A for now: no Sentry/error-reporting service is integrated anywhere in this codebase yet — wire it in whenever that infra is added.
