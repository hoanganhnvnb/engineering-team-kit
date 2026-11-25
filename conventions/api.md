# API

How to design HTTP/JSON APIs, responses and errors. Match what the project already does first.

## Resources and methods

- URLs are plural kebab-case nouns, no verbs: `/orders/{id}/items`, not `/getOrderItems`.
  Nest at most 2 levels; beyond that, use a top-level resource with a filter.
- Method semantics per RFC 9110 (GET/HEAD safe; PUT/DELETE idempotent) and RFC 5789
  (PATCH, partial update). Use POST to create. Never change state on GET.

## Status codes

| Code | Use |
|---|---|
| 200 | Success with a body |
| 201 | Created; set `Location` to the new resource |
| 204 | Success, no body (DELETE, some PUT/PATCH) |
| 400 | Malformed request (bad JSON, wrong types) |
| 401 | Not authenticated (missing or invalid credentials) |
| 403 | Authenticated but not allowed |
| 404 | Not found, or hidden from this caller |
| 409 | Conflict with current state (duplicate, version mismatch) |
| 422 | Well-formed but fails validation |
| 429 | Rate limited; send `Retry-After` |
| 500 / 503 | Server fault / temporarily unavailable |

## Errors

- RFC 9457 Problem Details, `Content-Type: application/problem+json`, with `type`,
  `title`, `status`, `detail`, `instance`. No stack traces, SQL or hostnames in `detail`.
- Field errors as an extension, matching RFC 9457 §3 unless the project differs:
  `"errors": [{ "detail": "must be a positive integer", "pointer": "#/age" }]`.

## Payloads

- Success shape: the plain resource, or `{ "data": ..., "meta": ... }` only if the project uses an envelope.
- JSON key case: one style across the API (see `naming.md`).
- Dates: RFC 3339 / ISO 8601 in UTC, e.g. `2026-11-25T04:00:00Z`.
- Money: integer minor units (`1999`) or a decimal string (`"19.99"`) plus an ISO 4217
  `currency`. Never a float.
- New APIs: IDs as strings in JSON. Never retype existing IDs.

## Lists

- Paginate lists that can grow without bound: cursor for large or changing sets, else `page` and capped `limit`.
  Return the next cursor or a `next` link.
- Filter with plain query params (`?status=paid`); sort with `?sort=-created_at`.

## Change and safety

- Payment/order POSTs that clients retry take an `Idempotency-Key`; replay the stored response.
- Never break existing clients: add optional fields; do not rename, remove or retype
  without a deprecation period. Version per `versioning.md`.
- GraphQL: follow the existing schema's naming, nullability and pagination.

Sources: RFC 9110 https://www.rfc-editor.org/rfc/rfc9110 ; RFC 5789 https://www.rfc-editor.org/rfc/rfc5789 ;
RFC 9457 https://www.rfc-editor.org/rfc/rfc9457 ; RFC 3339 https://www.rfc-editor.org/rfc/rfc3339 ;
RFC 6585 (429) https://www.rfc-editor.org/rfc/rfc6585 ; ISO 4217 https://www.iso.org/iso-4217-currency-codes.html ;
Idempotency-Key draft https://datatracker.ietf.org/doc/draft-ietf-httpapi-idempotency-key-header/
