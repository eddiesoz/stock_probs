# State and race coverage

## News states

Exercise all ten states through the local `/api/v1/news` boundary and actual disclosure/retry
controls:

1. not requested: disclosure closed and zero news requests;
2. loading: announced and `aria-busy=true`;
3. fresh: source/as-of, bounded items, metadata, and HTTPS-safe links;
4. empty: successful empty response, not a 404 or provider error;
5. partial metadata: missing optional fields do not discard the headline;
6. stale fallback: cached content plus explicit refresh-failure warning;
7. provider unavailable: 502, no cache, distinct message, manual retry;
8. local service unreachable: network failure distinct from provider failure;
9. capacity busy: 503 and manual retry; and
10. instrument changed/request superseded: abort the old request, clear stale items, and render no
   old-symbol result.

Also prove news stays optional, bounded to limits 5/10, outside immutable saved evidence, and absent
from the history ledger.

## Deterministic race pattern

Install the route before the action, capture the request identity, and hold the older response on a
promise. Trigger the newer action, await its observable result, release the older response, then
assert the current state did not regress. Use this pattern for lookup, history filtering/paging,
fresh reconstruction, and news. Count requests and expected aborts so duplicate work cannot pass.

For disabled duplicate-submit or paging controls, assert both the disabled state during the held
request and the request count. For timeout behavior, shorten only the known product deadline in the
test harness, require one terminal state, and prove retry remains manual rather than hidden.
