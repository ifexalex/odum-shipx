# ADR-007: Rate limiting — Redis-backed, fail-open, and only where Redis is reachable

**Status:** Accepted (2026-11-15, owner decision on audit finding SEC-03).
**Related:** `shared/rate_limit.py`, `shared/client_ip.py`, `shared/distributed_cache.py`,
`04c_terraform_api_gateway.md`, `docs/runbook.md`.

## Context

The only limit was one stage-wide API Gateway throttle (50 requests per second) shared by every tenant. One
script could flood sign-ups and onboarding leads, guess tracking-code and phone pairs, try passwords through
the login proxy, or use up the shared budget for everyone. `22_gaps_and_improvements.md` and
`04c_terraform_api_gateway.md` claimed per-tenant throttling through API Gateway usage plans and API keys. An HTTP
API has neither, and the Terraform never implemented it.

## Decision

* **Redis fixed-window counters** (`DistributedCache.incr_window`, one Lua script so the count and the expiry are
  set together and a counter can never be left without one). Keys hold a hash of the identifier, never an
  email, tracking code or address.
* **Two shapes.** Flood limits count every request (`hit`: per address, per tenant). Guessing limits count
  only failures (`peek` / `record_failure` / `clear`: per username, per tracking code), so a user's own typos
  or a correct answer are not punished.
* **Limits** (all overridable with `RATE_LIMIT_<NAME>=limit/window` or `off`): login 10/min per address and
  5 failed/15 min per username; register and onboarding-requests 5/hour per address; tracking lookup 30/min
  per address and 10 wrong-phone guesses/hour per code; cookie routes 60/min per address; authenticated 600/min
  per tenant.
* **Fail open.** If Redis cannot be reached the request goes through and `rate_limiter_unavailable` is logged at
  ERROR (the alarm hook for OPS-04). Failing closed would make Redis an availability dependency of sign-in.
* **Only where Redis is reachable.** The `auth` Lambda runs outside the VPC (it only talks to Cognito) and
  cannot reach ElastiCache, so Terraform sets `RATE_LIMIT_ENABLED=false` there rather than pay a connection
  timeout on every request. Those routes are throttled per route at API Gateway instead
  (`public_route_throttles`): per route, not per client, but a flood of one route can no longer take the
  stage-wide budget from everyone else.

## Consequences

* **`DistributedCache` had a latent outage amplifier, found by testing against a real Redis.** redis-py 8
  retries a failed command with exponential backoff, so every operation against an unreachable Redis took about
  four seconds. The tenant-status and identity caches already made several such calls per authenticated request.
  The client now does not retry, and a per-process circuit breaker leaves Redis alone for five seconds after a
  failure: an outage costs one fast failure instead of one per call.
* Per-client limits need the real client address, which `requestContext.identity.sourceIp` does not provide on
  an HTTP API (it is `requestContext.http.sourceIp`; handlers had been recording no IP at all in production
  audit logs). `shared/client_ip.py` reads both. Behind the container deployment's proxies the socket peer is
  a proxy, so `TRUSTED_PROXY_HOPS` says how many append to `X-Forwarded-For`; unset and behind a proxy, the
  address is treated as **unknown** and per-address limits are skipped rather than lumping every user into
  one bucket.
* The wrong-guess limit on a tracking code can be used to lock the code's legitimate owner out for an hour.
  Phone numbers are not guessable at 10 an hour, so the exposure is denial of that one code, not disclosure.
* 600/min per tenant is a guess at a ceiling; tune it with `RATE_LIMIT_TENANT` once real traffic is known.
