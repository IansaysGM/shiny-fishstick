from __future__ import annotations

from datetime import UTC, datetime, timedelta
from enum import Enum
from typing import Literal
from uuid import uuid4

from fastapi import FastAPI, HTTPException, status
from pydantic import BaseModel, Field

SESSION_TTL_MINUTES = 20
SESSION_STARTED_AT = datetime.now(UTC)
CUSTOMER_NAMES = [
    "atlas-mining",
    "civic-planning",
    "relief-watch",
    "northstar-energy",
    "ocean-grid",
]


def utc_now() -> datetime:
    return datetime.now(UTC)


def session_expiry() -> datetime:
    return utc_now() + timedelta(minutes=SESSION_TTL_MINUTES)


class Priority(str, Enum):
    low = "low"
    mid = "mid"
    high = "high"


class DeliveryFormat(str, Enum):
    geotiff = "geotiff"
    png_tiles = "png_tiles"
    analytic_bundle = "analytic_bundle"


class Sensor(BaseModel):
    id: str
    name: str
    resolution_m: float
    max_taskable_sq_km: float


class CustomerProfile(BaseModel):
    customer_name: str
    allowed_sensor_ids: list[str]
    allowed_priorities: list[Priority]
    allowed_delivery_formats: list[DeliveryFormat]
    max_aoi_sq_km: float


class AreaOfInterest(BaseModel):
    name: str = Field(..., min_length=3, max_length=80)
    center_lat: float = Field(..., ge=-90, le=90)
    center_lon: float = Field(..., ge=-180, le=180)
    area_sq_km: float = Field(..., gt=0, le=2500)


def compute_daily_acquisition_offset(area_of_interest: AreaOfInterest) -> timedelta:
    lat_ratio = (area_of_interest.center_lat + 90) / 180
    lon_ratio = (area_of_interest.center_lon + 180) / 360
    offset_seconds = int((((lat_ratio * 0.65) + (lon_ratio * 0.35)) % 1) * 86400)
    return timedelta(seconds=offset_seconds)


def compute_acquisition_time(
    area_of_interest: AreaOfInterest,
    acquisition_window_start: datetime,
) -> datetime:
    start_utc = acquisition_window_start.astimezone(UTC)
    base_day = start_utc.replace(hour=0, minute=0, second=0, microsecond=0)
    acquisition_time = base_day + compute_daily_acquisition_offset(area_of_interest)
    if acquisition_time < start_utc:
        acquisition_time += timedelta(days=1)
    return acquisition_time


class PolicyViolation(BaseModel):
    code: str
    message: str
    field: str | None = None


class CollectionRequestInput(BaseModel):
    customer_name: str
    sensor_id: str
    priority: Priority
    delivery_format: DeliveryFormat
    acquisition_window_start: datetime
    acquisition_window_end: datetime
    area_of_interest: AreaOfInterest


class ValidationResult(BaseModel):
    allowed: bool
    acquisition_time: datetime | None = None
    violations: list[PolicyViolation]


class CollectionRequest(CollectionRequestInput):
    id: str
    acquisition_time: datetime
    created_at: datetime
    updated_at: datetime
    expires_at: datetime
    source: Literal["seeded", "user"]


class DeleteResult(BaseModel):
    deleted: bool
    id: str
    resource: Literal["collection_request"]


class ResetResult(BaseModel):
    reset: bool
    collection_request_count: int
    collection_request_ids: list[str]


class ConflictValidationResult(BaseModel):
    acquisition_time: datetime
    conflicts: list[CollectionRequest]


SENSORS: dict[str, Sensor] = {}
CUSTOMER_PROFILES: dict[str, CustomerProfile] = {}
COLLECTION_REQUESTS: dict[str, CollectionRequest] = {}


app = FastAPI(
    title="OrbitalOps Mock API",
    summary="Simple mock API for satellite collection requests",
    description=(
        "A demo-friendly FastAPI service for validating short-lived collection "
        "requests against customer-specific policies."
    ),
    version="2.0.0",
)


def seed_reference_data() -> None:
    global SENSORS, CUSTOMER_PROFILES

    SENSORS = {
        "sar-horizon-1": Sensor(
            id="sar-horizon-1",
            name="SAR Horizon 1",
            resolution_m=0.5,
            max_taskable_sq_km=120,
        ),
        "sar-horizon-2": Sensor(
            id="sar-horizon-2",
            name="SAR Horizon 2",
            resolution_m=1.0,
            max_taskable_sq_km=300,
        ),
        "sar-surveyor-1": Sensor(
            id="sar-surveyor-1",
            name="SAR Surveyor 1",
            resolution_m=3.0,
            max_taskable_sq_km=800,
        ),
    }

    CUSTOMER_PROFILES = {
        "atlas-mining": CustomerProfile(
            customer_name="atlas-mining",
            allowed_sensor_ids=["sar-horizon-1", "sar-horizon-2"],
            allowed_priorities=[Priority.mid, Priority.high],
            allowed_delivery_formats=[
                DeliveryFormat.geotiff,
                DeliveryFormat.analytic_bundle,
            ],
            max_aoi_sq_km=120,
        ),
        "civic-planning": CustomerProfile(
            customer_name="civic-planning",
            allowed_sensor_ids=["sar-horizon-2", "sar-surveyor-1"],
            allowed_priorities=[Priority.low, Priority.mid],
            allowed_delivery_formats=[
                DeliveryFormat.geotiff,
                DeliveryFormat.png_tiles,
            ],
            max_aoi_sq_km=400,
        ),
        "relief-watch": CustomerProfile(
            customer_name="relief-watch",
            allowed_sensor_ids=["sar-horizon-2", "sar-surveyor-1"],
            allowed_priorities=[Priority.mid, Priority.high],
            allowed_delivery_formats=[
                DeliveryFormat.geotiff,
                DeliveryFormat.png_tiles,
            ],
            max_aoi_sq_km=600,
        ),
        "northstar-energy": CustomerProfile(
            customer_name="northstar-energy",
            allowed_sensor_ids=["sar-horizon-1", "sar-surveyor-1"],
            allowed_priorities=[Priority.low, Priority.mid, Priority.high],
            allowed_delivery_formats=[
                DeliveryFormat.geotiff,
                DeliveryFormat.png_tiles,
                DeliveryFormat.analytic_bundle,
            ],
            max_aoi_sq_km=250,
        ),
        "ocean-grid": CustomerProfile(
            customer_name="ocean-grid",
            allowed_sensor_ids=["sar-surveyor-1"],
            allowed_priorities=[Priority.low],
            allowed_delivery_formats=[DeliveryFormat.png_tiles],
            max_aoi_sq_km=700,
        ),
    }


def validate_collection_request(payload: CollectionRequestInput) -> ValidationResult:
    now = utc_now()
    violations: list[PolicyViolation] = []
    acquisition_time: datetime | None = None

    if payload.customer_name not in CUSTOMER_NAMES:
        violations.append(
            PolicyViolation(
                code="UNKNOWN_CUSTOMER_NAME",
                message="Customer name is not recognized.",
                field="customer_name",
            )
        )

    profile = CUSTOMER_PROFILES.get(payload.customer_name)
    sensor = SENSORS.get(payload.sensor_id)

    if sensor is None:
        violations.append(
            PolicyViolation(
                code="UNKNOWN_SENSOR",
                message="Sensor does not exist.",
                field="sensor_id",
            )
        )

    if profile is None:
        violations.append(
            PolicyViolation(
                code="MISSING_CUSTOMER_PROFILE",
                message="Customer profile is not configured.",
                field="customer_name",
            )
        )

    if profile and payload.sensor_id not in profile.allowed_sensor_ids:
        violations.append(
            PolicyViolation(
                code="SENSOR_NOT_ALLOWED",
                message="This sensor is not allowed for the selected customer.",
                field="sensor_id",
            )
        )

    if profile and payload.priority not in profile.allowed_priorities:
        violations.append(
            PolicyViolation(
                code="PRIORITY_NOT_ALLOWED",
                message="This priority is not allowed for the selected customer.",
                field="priority",
            )
        )

    if profile and payload.delivery_format not in profile.allowed_delivery_formats:
        violations.append(
            PolicyViolation(
                code="FORMAT_NOT_ALLOWED",
                message="This delivery format is not allowed for the selected customer.",
                field="delivery_format",
            )
        )

    if profile and payload.area_of_interest.area_sq_km > profile.max_aoi_sq_km:
        violations.append(
            PolicyViolation(
                code="AOI_TOO_LARGE",
                message=(
                    f"AOI exceeds the customer profile limit of {profile.max_aoi_sq_km} sq km."
                ),
                field="area_of_interest.area_sq_km",
            )
        )

    if sensor and payload.area_of_interest.area_sq_km > sensor.max_taskable_sq_km:
        violations.append(
            PolicyViolation(
                code="SENSOR_AOI_LIMIT_EXCEEDED",
                message=(
                    f"Sensor {payload.sensor_id} cannot task an AOI larger than "
                    f"{sensor.max_taskable_sq_km} sq km."
                ),
                field="area_of_interest.area_sq_km",
            )
        )

    if payload.acquisition_window_start >= payload.acquisition_window_end:
        violations.append(
            PolicyViolation(
                code="INVALID_WINDOW",
                message="Acquisition window start must be before the end.",
                field="acquisition_window_start",
            )
        )

    if payload.acquisition_window_end - payload.acquisition_window_start > timedelta(hours=24):
        violations.append(
            PolicyViolation(
                code="WINDOW_TOO_LARGE",
                message="Acquisition window cannot be larger than 24 hours.",
                field="acquisition_window_end",
            )
        )

    if payload.acquisition_window_start < now:
        violations.append(
            PolicyViolation(
                code="WINDOW_IN_PAST",
                message="Acquisition window must start in the future.",
                field="acquisition_window_start",
            )
        )

    if payload.acquisition_window_end > now + timedelta(days=14):
        violations.append(
            PolicyViolation(
                code="WINDOW_TOO_FAR_OUT",
                message="Acquisition window must end within 14 days.",
                field="acquisition_window_end",
            )
        )

    if payload.acquisition_window_start < payload.acquisition_window_end:
        acquisition_time = compute_acquisition_time(
            payload.area_of_interest,
            payload.acquisition_window_start,
        )
        if acquisition_time > payload.acquisition_window_end:
            violations.append(
                PolicyViolation(
                    code="COLLECTION_REQUEST_NOT_FEASIBLE",
                    message=(
                        "Computed acquisition_time falls outside the acquisition window."
                    ),
                    field="acquisition_window_end",
                )
            )

    return ValidationResult(
        allowed=not violations,
        acquisition_time=acquisition_time,
        violations=violations,
    )


def build_collection_request(
    payload: CollectionRequestInput,
    *,
    request_id: str | None = None,
    source: Literal["seeded", "user"],
    created_at: datetime | None = None,
    expires_at: datetime | None = None,
) -> CollectionRequest:
    created = created_at or utc_now()
    acquisition_time = compute_acquisition_time(
        payload.area_of_interest,
        payload.acquisition_window_start,
    )
    return CollectionRequest(
        id=request_id or f"cr_{uuid4().hex[:10]}",
        acquisition_time=acquisition_time,
        created_at=created,
        updated_at=created,
        expires_at=expires_at or session_expiry(),
        source=source,
        **payload.model_dump(),
    )


def cleanup_expired_records() -> None:
    now = utc_now()
    expired_request_ids = [
        request_id
        for request_id, collection_request in COLLECTION_REQUESTS.items()
        if collection_request.expires_at <= now
    ]
    for request_id in expired_request_ids:
        del COLLECTION_REQUESTS[request_id]


def get_collection_request_or_404(collection_request_id: str) -> CollectionRequest:
    cleanup_expired_records()
    collection_request = COLLECTION_REQUESTS.get(collection_request_id)
    if collection_request is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Collection request not found.",
        )
    return collection_request


def find_conflicting_collection_requests(
    payload: CollectionRequestInput,
) -> tuple[datetime, list[CollectionRequest]]:
    acquisition_time = compute_acquisition_time(
        payload.area_of_interest,
        payload.acquisition_window_start,
    )
    conflicts = [
        collection_request
        for collection_request in COLLECTION_REQUESTS.values()
        if abs(
            (collection_request.acquisition_time - acquisition_time).total_seconds()
        )
        <= 3600
    ]
    conflicts.sort(key=lambda collection_request: collection_request.acquisition_time)
    return acquisition_time, conflicts


def seed_session_data() -> None:
    global COLLECTION_REQUESTS

    COLLECTION_REQUESTS = {}
    now = utc_now()

    def make_seeded_input(
        *,
        customer_name: str,
        sensor_id: str,
        priority: Priority,
        delivery_format: DeliveryFormat,
        area_of_interest: AreaOfInterest,
    ) -> CollectionRequestInput:
        base_window_start = now + timedelta(hours=2)
        acquisition_time = compute_acquisition_time(area_of_interest, base_window_start)
        return CollectionRequestInput(
            customer_name=customer_name,
            sensor_id=sensor_id,
            priority=priority,
            delivery_format=delivery_format,
            acquisition_window_start=acquisition_time - timedelta(hours=1),
            acquisition_window_end=acquisition_time + timedelta(hours=8),
            area_of_interest=area_of_interest,
        )

    seeded_payloads = [
        make_seeded_input(
            customer_name="civic-planning",
            sensor_id="sar-surveyor-1",
            priority=Priority.low,
            delivery_format=DeliveryFormat.png_tiles,
            area_of_interest=AreaOfInterest(
                name="Seville ring road",
                center_lat=37.3891,
                center_lon=-5.9845,
                area_sq_km=140,
            ),
        ),
        make_seeded_input(
            customer_name="atlas-mining",
            sensor_id="sar-horizon-1",
            priority=Priority.high,
            delivery_format=DeliveryFormat.analytic_bundle,
            area_of_interest=AreaOfInterest(
                name="Atacama pit north wall",
                center_lat=-22.9108,
                center_lon=-68.1997,
                area_sq_km=65,
            ),
        ),
        make_seeded_input(
            customer_name="relief-watch",
            sensor_id="sar-horizon-2",
            priority=Priority.high,
            delivery_format=DeliveryFormat.geotiff,
            area_of_interest=AreaOfInterest(
                name="Floodplain north sector",
                center_lat=14.5995,
                center_lon=120.9842,
                area_sq_km=210,
            ),
        ),
    ]

    COLLECTION_REQUESTS = {
        f"cr_demo_{index:03d}": build_collection_request(
            payload,
            request_id=f"cr_demo_{index:03d}",
            source="seeded",
            created_at=now - timedelta(minutes=10 - index),
            expires_at=now + timedelta(minutes=SESSION_TTL_MINUTES),
        )
        for index, payload in enumerate(seeded_payloads, start=1)
    }


def initialize_state() -> None:
    seed_reference_data()
    seed_session_data()


initialize_state()


@app.get("/")
def root() -> dict[str, object]:
    cleanup_expired_records()
    return {
        "service": "OrbitalOps Mock API",
        "purpose": "Simple demo API for validating satellite collection requests.",
        "session_started_at": SESSION_STARTED_AT,
        "session_ttl_minutes": SESSION_TTL_MINUTES,
        "counts": {
            "customer_names": len(CUSTOMER_NAMES),
            "customer_profiles": len(CUSTOMER_PROFILES),
            "sensors": len(SENSORS),
            "collection_requests": len(COLLECTION_REQUESTS),
        },
        "links": {
            "interactive_docs": "/docs",
            "openapi": "/openapi.json",
            "assignment_docs": "/docs/assignment",
            "customer_names": "/customer-names",
            "customer_profiles": "/customer-profiles",
            "sensors": "/sensors",
            "reset_collection_requests": "/collection-requests/reset",
        },
    }


@app.get("/customer-names", response_model=list[str])
def list_customer_names() -> list[str]:
    return CUSTOMER_NAMES


@app.get("/customer-profiles", response_model=list[CustomerProfile])
def list_customer_profiles() -> list[CustomerProfile]:
    return list(CUSTOMER_PROFILES.values())


@app.get("/sensors", response_model=list[Sensor])
def list_sensors() -> list[Sensor]:
    return list(SENSORS.values())


@app.post("/collection-requests/validate", response_model=ValidationResult)
def validate_request(payload: CollectionRequestInput) -> ValidationResult:
    return validate_collection_request(payload)


@app.post(
    "/collection-requests/conflict-validation",
    response_model=ConflictValidationResult,
)
def conflict_validate_request(payload: CollectionRequestInput) -> ConflictValidationResult:
    cleanup_expired_records()
    acquisition_time, conflicts = find_conflicting_collection_requests(payload)
    return ConflictValidationResult(
        acquisition_time=acquisition_time,
        conflicts=conflicts,
    )


@app.get("/collection-requests", response_model=list[CollectionRequest])
def list_collection_requests() -> list[CollectionRequest]:
    cleanup_expired_records()
    return sorted(
        COLLECTION_REQUESTS.values(),
        key=lambda collection_request: collection_request.updated_at,
        reverse=True,
    )


@app.post(
    "/collection-requests",
    response_model=CollectionRequest,
    status_code=status.HTTP_201_CREATED,
)
def create_collection_request(payload: CollectionRequestInput) -> CollectionRequest:
    cleanup_expired_records()
    validation = validate_collection_request(payload)
    if not validation.allowed:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "message": "Collection request failed policy validation.",
                "violations": [violation.model_dump() for violation in validation.violations],
            },
        )

    acquisition_time, conflicts = find_conflicting_collection_requests(payload)
    if conflicts:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "message": (
                    "Collection request conflicts with an existing request whose "
                    "acquisition_time is within 1 hour."
                ),
                "acquisition_time": acquisition_time.isoformat(),
                "conflicting_collection_requests": [
                    conflict.model_dump(mode="json") for conflict in conflicts
                ],
            },
        )

    collection_request = build_collection_request(payload, source="user")
    COLLECTION_REQUESTS[collection_request.id] = collection_request
    return collection_request


@app.get("/collection-requests/{collection_request_id}", response_model=CollectionRequest)
def get_collection_request(collection_request_id: str) -> CollectionRequest:
    return get_collection_request_or_404(collection_request_id)


@app.delete(
    "/collection-requests/{collection_request_id}",
    response_model=DeleteResult,
)
def delete_collection_request(collection_request_id: str) -> DeleteResult:
    collection_request = get_collection_request_or_404(collection_request_id)
    del COLLECTION_REQUESTS[collection_request.id]
    return DeleteResult(
        deleted=True,
        id=collection_request.id,
        resource="collection_request",
    )


@app.post("/collection-requests/reset", response_model=ResetResult)
def reset_collection_requests() -> ResetResult:
    seed_session_data()
    return ResetResult(
        reset=True,
        collection_request_count=len(COLLECTION_REQUESTS),
        collection_request_ids=sorted(COLLECTION_REQUESTS.keys()),
    )


@app.get("/docs/assignment")
def assignment_docs() -> dict[str, object]:
    return {
        "title": "OrbitalOps assignment guide",
        "overview": (
            "This API simulates a satellite company with simple customer-specific "
            "policies. Collection requests are either accepted or rejected based on "
            "policy and acquisition feasibility."
        ),
        "objects": {
            "customer_names": {
                "mutable": False,
                "purpose": "The fixed set of allowed customer names.",
            },
            "sensors": {
                "mutable": False,
                "purpose": "The fixed set of SAR sensors candidates can choose from.",
            },
            "customer_profiles": {
                "mutable": False,
                "purpose": (
                    "Per-customer policies describing allowed sensors, priorities, "
                    "delivery formats, and AOI limits."
                ),
            },
            "collection_requests": {
                "mutable": True,
                "purpose": (
                    "Short-lived collection requests that are only created if policy "
                    "validation passes. Created records include a deterministic "
                    "acquisition_time derived from the AOI coordinates."
                ),
            },
        },
        "known_values": {
            "priority": [priority.value for priority in Priority],
            "delivery_format": [delivery_format.value for delivery_format in DeliveryFormat],
        },
        "relationships": [
            "Each customer name has exactly one customer profile.",
            "A collection request must use a known customer name.",
            "The chosen sensor, priority, and delivery format must all be allowed by that customer's profile.",
            "The AOI must fit both the customer profile limit and the sensor tasking limit.",
            "The AOI coordinates deterministically map to an acquisition_time modulo 24 hours.",
            "A collection request is only feasible when that acquisition_time falls within the requested acquisition window.",
            "A collection request cannot be created if another stored request has an acquisition_time within 10 minutes of it.",
        ],
        "collection_request_input": {
            "required_fields": [
                "customer_name",
                "sensor_id",
                "priority",
                "delivery_format",
                "acquisition_window_start",
                "acquisition_window_end",
                "area_of_interest",
            ],
            "rules": [
                "The acquisition window cannot be larger than 24 hours.",
                "Validation returns acquisition_time so clients can explain feasibility decisions.",
                "The standard validate endpoint does not check conflicts with existing collection requests.",
                "Conflict checks are exposed separately and are enforced during creation.",
            ],
        },
        "mutable_session_data": {
            "ttl_minutes": SESSION_TTL_MINUTES,
            "notes": [
                "Seeded collection requests are loaded when the app starts.",
                "Collection requests may be deleted or replaced during the exercise.",
                "Reference objects are immutable and should be treated as catalog data.",
            ],
        },
        "starter_validation_examples": [
            {
                "name": "priority_not_allowed",
                "description": "Fails because ocean-grid only allows low priority.",
                "payload": {
                    "customer_name": "ocean-grid",
                    "sensor_id": "sar-surveyor-1",
                    "priority": "high",
                    "delivery_format": "png_tiles",
                    "acquisition_window_start": (utc_now() + timedelta(hours=5)).isoformat(),
                    "acquisition_window_end": (utc_now() + timedelta(days=1)).isoformat(),
                    "area_of_interest": {
                        "name": "North Atlantic cable route",
                        "center_lat": 48.85,
                        "center_lon": -27.12,
                        "area_sq_km": 300,
                    },
                },
            },
            {
                "name": "collection_request_not_feasible",
                "description": "Fails because the computed acquisition_time falls outside the requested acquisition window.",
                "payload": {
                    "customer_name": "northstar-energy",
                    "sensor_id": "sar-horizon-1",
                    "priority": "mid",
                    "delivery_format": "geotiff",
                    "acquisition_window_start": (utc_now() + timedelta(hours=2)).isoformat(),
                    "acquisition_window_end": (utc_now() + timedelta(hours=3)).isoformat(),
                    "area_of_interest": {
                        "name": "Remote compressor station",
                        "center_lat": 29.76,
                        "center_lon": -95.36,
                        "area_sq_km": 80,
                    },
                },
            },
            {
                "name": "conflict_example",
                "description": "May conflict with an existing seeded collection request if the computed acquisition_time is within 10 minutes.",
                "payload": {
                    "customer_name": "civic-planning",
                    "sensor_id": "sar-surveyor-1",
                    "priority": "low",
                    "delivery_format": "png_tiles",
                    "acquisition_window_start": (utc_now() + timedelta(hours=1)).isoformat(),
                    "acquisition_window_end": (utc_now() + timedelta(hours=20)).isoformat(),
                    "area_of_interest": {
                        "name": "Seville ring road variant",
                        "center_lat": 37.3892,
                        "center_lon": -5.9844,
                        "area_sq_km": 140,
                    },
                },
            },
        ],
        "workflow_example": [
            {
                "step": 1,
                "action": "Inspect /customer-names, /customer-profiles, and /sensors to understand the fixed catalog.",
            },
            {
                "step": 2,
                "action": "Call POST /collection-requests/validate with a proposed request body.",
            },
            {
                "step": 3,
                "action": "Persist a valid request with POST /collection-requests.",
            },
            {
                "step": 4,
                "action": "call POST /collection-requests/conflict-validation to inspect acquisition_time conflicts with stored requests.",
            },
            {
                "step": 5,
                "action": "List or fetch created requests with GET /collection-requests or GET /collection-requests/{collection_request_id}.",
            },
        ],
        "endpoints": [
            {"method": "GET", "path": "/", "description": "Service summary and useful links."},
            {"method": "GET", "path": "/customer-names", "description": "List allowed customer names."},
            {"method": "GET", "path": "/customer-profiles", "description": "List per-customer policy profiles."},
            {"method": "GET", "path": "/sensors", "description": "List available SAR sensors."},
            {"method": "POST", "path": "/collection-requests/validate", "description": "Validate a collection request without persisting it."},
            {"method": "POST", "path": "/collection-requests/conflict-validation", "description": "Return existing collection requests whose acquisition_time conflicts within 10 minutes."},
            {"method": "GET", "path": "/collection-requests", "description": "List session-scoped collection requests."},
            {"method": "POST", "path": "/collection-requests", "description": "Persist a policy-compliant collection request."},
            {"method": "GET", "path": "/collection-requests/{collection_request_id}", "description": "Fetch one collection request."},
            {"method": "DELETE", "path": "/collection-requests/{collection_request_id}", "description": "Delete a session collection request."},
            {"method": "POST", "path": "/collection-requests/reset", "description": "Reset the collection request list back to the seeded demo records."},
        ],
        "starter_demo_records": {
            "collection_request_ids": sorted(COLLECTION_REQUESTS.keys()),
        },
    }