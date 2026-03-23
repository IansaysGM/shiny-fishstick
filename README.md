# OrbitalOps Mock API

This repository contains a mock FastAPI backend for a job assignment. It simulates a satellite company that validates SAR imagery collection requests against simple customer-specific policies.

The API is designed for candidates building agents or tools that must:

- inspect API documentation
- reason about object relationships
- validate policy constraints before creation
- create and mutate session data

## Domain Model

The API centers on one main workflow object plus reference data:

- `customer_name`: a fixed enum-like list of 5 allowed customer strings
- `Sensor`: one of 3 SAR sensors with a name, resolution, and max taskable area
- `CustomerProfile`: per-customer policy rules describing allowed sensors, priorities, and delivery formats
- `CollectionRequest`: the only mutable business object, created only if it complies with policy

Relationship flow:

`customer_name` -> `CustomerProfile` -> validates `CollectionRequest`

## Seeded Data

The service starts with two kinds of data:

- immutable reference data:
  - customer names
  - customer profiles
  - sensors
- mutable session data:
  - seeded collection requests

Reference data is hardcoded and read-only. Session data is in memory and may be deleted, replaced, or extended during a demo session.

## Persistence Model

This service uses in-memory dictionaries, not a real database.

- data is intentionally short-lived
- records are suitable for a few minutes of realistic demo interactions
- session records expire automatically after a TTL window
- a restart or redeploy resets the session state

This makes it a good fit for assignment demos on Render, but not for durable production storage.

## Main Endpoints

- `GET /`
  Returns a service summary and links to the docs endpoints.

- `GET /customer-names`
- `GET /customer-profiles`
- `GET /sensors`
  Inspect the read-only business objects and allowed business rules.

- `POST /collection-requests/validate`
  Validate a proposed collection request without persisting it.

- `POST /collection-requests/conflict-validation`
  Return stored collection requests whose `acquisition_time` conflicts within 1 hour.

- `GET /collection-requests`
- `POST /collection-requests`
- `GET /collection-requests/{collection_request_id}`
- `DELETE /collection-requests/{collection_request_id}`
- `POST /collection-requests/reset`
  Manage session-scoped collection requests.

- `GET /docs/assignment`
  Assignment-specific documentation describing the API suite, object relationships, and recommended workflow.

- `GET /docs`
- `GET /openapi.json`
  FastAPI-generated interactive docs and OpenAPI schema.

## Policy Validation

Collection requests are checked against policy before they can be persisted.

Example validation rules include:

- customer name must exist
- requested sensor must be allowed by the policy
- AOI size must be within the selected sensor limit
- priority may be restricted
- delivery format may be restricted
- acquisition windows must be valid and near-term
- acquisition windows cannot be larger than 24 hours
- each AOI deterministically maps to an `acquisition_time`
- a collection request is only feasible if that `acquisition_time` falls inside the requested acquisition window
- the normal validate endpoint does not check database conflicts
- creation is rejected if another stored collection request has an `acquisition_time` within 10 minutes

Validation responses return structured violations with machine-readable codes so candidates can build agents that react intelligently to errors.

Created collection requests also include an `acquisition_time` field. It is derived from the AOI coordinates modulo 24 hours, so the same AOI always produces the same acquisition time-of-day.

## Known Enum Values

These values are also exposed in `GET /docs/assignment`.

- `Priority`: `low`, `mid`, `high`
- `DeliveryFormat`: `geotiff`, `png_tiles`, `analytic_bundle`

## Local Development

This repo uses `requirements.txt` for deployment, but for local Python workflows you can use `uv`.

Install and run locally:

```bash
uv run --with "fastapi[all]" uvicorn main:app --reload
```

The app will then be available at:

- `http://127.0.0.1:8000/docs`
- `http://127.0.0.1:8000/docs/assignment`

## Example Workflow

1. Call `GET /customer-names`, `GET /customer-profiles`, and `GET /sensors` to inspect the catalog.
2. Call `POST /collection-requests/validate` with a proposed request.
3. Optionally call `POST /collection-requests/conflict-validation` to inspect acquisition-time conflicts with existing requests.
4. Create a valid non-conflicting request with `POST /collection-requests`.
5. Fetch or delete it with `GET /collection-requests/{collection_request_id}` or `DELETE /collection-requests/{collection_request_id}`.
6. Restore the seeded dataset with `POST /collection-requests/reset`.

## Render Deployment

This project is already configured for Render in `render.yaml`.

Start command:

```bash
uvicorn main:app --host 0.0.0.0 --port $PORT
```

Because persistence is in memory:

- data resets on deploy or restart
- data should be treated as session/demo state only
- this is expected for the assignment use case
