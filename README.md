# OrbitalOps Mock API

This repository contains a mock FastAPI backend for a job assignment. It simulates a satellite constellation company that validates imagery collection requests and tracks their progress for dashboards or agent-driven workflows.

The API is designed for candidates building agents or tools that must:

- inspect API documentation
- reason about object relationships
- validate policy constraints before creation
- create and mutate session data
- track order status over time

## Domain Model

The API centers on one main workflow object plus reference data:

- `PolicyProfile`: read-only business rules that determine what a customer may request
- `CustomerAccount`: read-only customer metadata with an assigned default policy
- `Sensor`: read-only imaging asset metadata
- `CollectionRequest`: the main workflow object, combining imagery tasking details with status, progress, and event history

Relationship flow:

`PolicyProfile` -> validates `CollectionRequest`

## Seeded Data

The service starts with two kinds of data:

- immutable reference data:
  - policy profiles
  - customer accounts
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

- `GET /policy-profiles`
- `GET /customer-accounts`
- `GET /sensors`
  Inspect the read-only business objects and allowed business rules.

- `POST /collection-requests/validate`
  Validate a proposed collection request without persisting it.

- `GET /collection-requests`
- `POST /collection-requests`
- `GET /collection-requests/{collection_request_id}`
- `DELETE /collection-requests/{collection_request_id}`
  Manage session-scoped collection requests.

- `POST /collection-requests/{collection_request_id}/simulate-tick`
  Advance a collection request through its demo lifecycle.

- `GET /docs/assignment`
  Assignment-specific documentation describing the API suite, object relationships, and recommended workflow.

- `GET /docs`
- `GET /openapi.json`
  FastAPI-generated interactive docs and OpenAPI schema.

## Collection Request Lifecycle

Collection requests move through a dashboard-friendly status flow:

- `validated`
- `scheduled`
- `tasking`
- `capturing`
- `processing`
- `ready`
- `delivered`
- `failed`

Each collection request includes:

- current status
- progress percentage
- timestamps
- an event timeline
- an order-style tracking number

## Policy Validation

Collection requests are checked against policy before they can be persisted.

Example validation rules include:

- customer must use the correct assigned policy profile
- requested sensor must be allowed by the policy
- AOI size must be within policy and sensor limits
- rush priority may be restricted
- delivery format may be restricted
- acquisition windows must be valid and near-term

Validation responses return structured violations with machine-readable codes so candidates can build agents that react intelligently to errors.

## Known Enum Values

These values are also exposed in `GET /docs/assignment`.

- `Priority`: `standard`, `rush`
- `DeliveryFormat`: `geotiff`, `png_tiles`, `analytic_bundle`
- `CollectionRequestStatus`: `validated`, `scheduled`, `tasking`, `capturing`, `processing`, `ready`, `delivered`, `failed`

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

1. Call `GET /policy-profiles`, `GET /customer-accounts`, and `GET /sensors` to inspect the catalog.
2. Call `POST /collection-requests/validate` with a proposed request.
3. Create a valid request with `POST /collection-requests`.
4. Poll `GET /collection-requests/{collection_request_id}`.
5. Advance it with `POST /collection-requests/{collection_request_id}/simulate-tick`.

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
