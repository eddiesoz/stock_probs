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

The endpoint accepts integer limits 1 through 10 and defaults to 5. The dashboard uses exactly 5 for
the initial disclosure and 10 only after “Show up to 10 headlines”; assert `[5, 10]` for that UI
journey rather than describing the endpoint as accepting only those two values. Also prove news stays
optional, outside immutable saved evidence, and absent from the history ledger.

## Deterministic race pattern

For response-order races, install the route before the action, capture request identity, hold the
older response on a promise, trigger the newer action, await its result, release the older response,
and assert the current state did not regress. Use that pattern for lookup, history filtering/paging,
and fresh reconstruction.

News supersession is an abort race: install a controllable fetch before opening the disclosure,
attach its abort listener, change the instrument while `data-state=loading`, then require the abort
event, `data-state=superseded`, and zero retained headline items. Do not wait to release an old news
response that the product contract aborts. Count requests and expected aborts where Playwright emits
them so duplicate work cannot pass.

For disabled duplicate-submit or paging controls, assert both the disabled state during the held
request and the request count. For timeout behavior, shorten only the known product deadline in the
test harness, require one terminal state, and prove retry remains manual rather than hidden.
