# ShipX Frontend

React + TypeScript + Vite SPA for the ShipX logistics platform. See
[`docs/project docs/frontend/`](../docs/project%20docs/frontend) for the build plan,
starting with [`00_frontend_master_plan.md`](../docs/project%20docs/frontend/00_frontend_master_plan.md).

## Local dev

```bash
cp .env.local.example .env.local   # points at the local Flask dev server (LOCAL_TESTING.md)
npm install
npm run dev
```

## Scripts

| Script | Purpose |
|---|---|
| `npm run dev` | Vite dev server with HMR |
| `npm run build` | Type-check + production build to `dist/` |
| `npm run preview` | Preview the production build locally |
| `npm run lint` | ESLint |
| `npm run typecheck` | `tsc --noEmit` |
| `npm test` | Vitest (unit/component) |
| `npm run test:watch` | Vitest in watch mode |
| `npm run test:e2e` | Playwright e2e (run `npm run build && npm run preview` target) |
