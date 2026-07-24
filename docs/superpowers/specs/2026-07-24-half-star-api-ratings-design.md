# Half-Star API Ratings

## Goal

Allow Hunt members to submit ratings from 1 through 5 in half-star steps, including 4.5, through the existing Unit Group rating endpoint. This completes the contract required by the frontend's `fractions={2}` rating control.

## Contract

`PUT /v1/listings/{listing_id}/unit-groups/{unit_group_key}/rating` accepts exactly:

`1, 1.5, 2, 2.5, 3, 3.5, 4, 4.5, 5`

Values outside 1–5 or not aligned to a 0.5 step receive FastAPI's standard `422` validation response. Successful responses expose `rating` as a JSON number. The route, authorization, Unit Group validation, upsert identity, deletion behavior, and direct Supabase read shape remain unchanged.

## Persistence

Change `ratings.rating` from `smallint` to `numeric(2,1)`. Replace the existing range-only constraint with one that enforces both the inclusive 1–5 range and half-step alignment. Existing integer ratings convert without data loss.

`numeric` is preferred over floating-point storage because it enforces decimal values exactly. Storing doubled integers is rejected because frontend reads go directly through RLS-backed Supabase queries and would otherwise expose encoded 2–10 values.

## API Models

Change the rating request and response fields from `int` to a decimal-capable type. Request validation enforces the range and half-step multiple before the service writes to Postgres. The service continues passing the validated value through without transformation.

## Documentation

Update `DESIGN.md` §8.2 and its Decision Log because the persisted ratings contract is authoritative there. Update the Phase 2 mechanics in `IMPLEMENTATION.md` from integer 1–5 ratings to half-step 1–5 ratings.

## Testing and Generated Contract

Extend the existing API integration test to prove:

- `4.5` is accepted, returned, and persisted exactly.
- An off-step value such as `4.2` receives `422`.
- Existing lower/upper bound rejection remains intact.

Regenerate the frontend OpenAPI declarations so `RatingUpsert` and `RatingResponse` reflect numeric rather than integer fields. Run the focused API collaboration test, the API suite, migration/RLS coverage relevant to ratings, frontend tests, and frontend build.
