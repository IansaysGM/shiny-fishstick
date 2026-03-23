from __future__ import annotations

from datetime import UTC, datetime, timedelta
from enum import Enum
from typing import Literal
from uuid import uuid4

from fastapi import FastAPI, HTTPException, status
from pydantic import BaseModel, Field

SESSION_TTL_MINUTES = 20
STATUS_PROGRESS = {
    "validated": 10,
    "scheduled": 25,
    "tasking": 40,
    "capturing": 60,
    "processing": 80,
    "ready": 95,
    "delivered": 100,
    "failed": 100,
}
STATUS_FLOW = [
    "validated",
    "scheduled",
    "tasking",
    "capturing",
    "processing",
    "ready",
    "delivered",
]
SESSION_STARTED_AT = datetime.now(UTC)


def utc_now() -> datetime:
    return datetime.now(UTC)


def session_expiry() -> datetime:
    return utc_now() + timedelta(minutes=SESSION_TTL_MINUTES)


class Priority(str, Enum):
    standard = "standard"
    rush = "rush"


class DeliveryFormat(str, Enum):
    geotiff = "geotiff"
    png_tiles = "png_tiles"
    analytic_bundle = "analytic_bundle"


class CollectionRequestStatus(str, Enum):
    validated = "validated"
    scheduled = "scheduled"
    tasking = "tasking"
    capturing = "capturing"
    processing = "processing"
    ready = "ready"
    delivered = "delivered"
    failed = "failed"


class Sensor(BaseModel):
    id: str
    constellation: str
    modality: Literal["optical", "sar"]
    resolution_m: float
    max_taskable_area_sq_km: float
    description: str


class CustomerAccount(BaseModel):
    id: str
    name: str
    sector: str
    region: str
    default_policy_profile_id: str


class PolicyProfile(BaseModel):
    id: str
    label: str
    description: str
    max_aoi_sq_km: float
    allowed_sensor_ids: list[str]
    max_cloud_cover_pct: int
    allows_rush: bool
    allowed_delivery_formats: list[DeliveryFormat]
    max_window_days: int


class AreaOfInterest(BaseModel):
    name: str = Field(..., min_length=3, max_length=80)
    center_lat: float = Field(..., ge=-90, le=90)
    center_lon: float = Field(..., ge=-180, le=180)
    area_sq_km: float = Field(..., gt=0, le=2500)


class PolicyViolation(BaseModel):
    code: str
    message: str
    field: str | None = None


class CollectionRequestInput(BaseModel):
    customer_account_id: str
    policy_profile_id: str
    sensor_id: str
    priority: Priority = Priority.standard
    delivery_format: DeliveryFormat
    acquisition_window_start: datetime
    acquisition_window_end: datetime
    cloud_cover_max_pct: int = Field(..., ge=0, le=100)
    area_of_interest: AreaOfInterest


class ValidationResult(BaseModel):
    allowed: bool
    violations: list[PolicyViolation]


class CollectionRequestEvent(BaseModel):
    at: datetime
    status: CollectionRequestStatus
    note: str


class CollectionRequest(CollectionRequestInput):
    id: str
    order_number: str
    customer_name: str
    status: CollectionRequestStatus
    progress_pct: int = Field(..., ge=0, le=100)
    expected_delivery_at: datetime
    events: list[CollectionRequestEvent]
    created_at: datetime
    updated_at: datetime
    expires_at: datetime
    source: Literal["seeded", "user"]


class SimulateTickPayload(BaseModel):
    target_status: CollectionRequestStatus | None = None
    note: str | None = Field(default=None, max_length=240)


class DeleteResult(BaseModel):
    deleted: bool
    id: str
    resource: Literal["collection_request"]


POLICY_PROFILES: dict[str, PolicyProfile] = {}
SENSORS: dict[str, Sensor] = {}
CUSTOMER_ACCOUNTS: dict[str, CustomerAccount] = {}
COLLECTION_REQUESTS: dict[str, CollectionRequest] = {}


app = FastAPI(
    title="OrbitalOps Mock API",
    summary="Mock satellite imagery ordering API for agent-tool assignments",
    description=(
        "A demo-friendly FastAPI service for validating and tracking short-lived "
        "satellite collection requests."
    ),
    version="1.1.0",
)


def seed_reference_data() -> None:
    global POLICY_PROFILES, SENSORS, CUSTOMER_ACCOUNTS

    SENSORS = {
        "aurora-optical-wide": Sensor(
            id="aurora-optical-wide",
            constellation="Aurora",
            modality="optical",
            resolution_m=1.5,
            max_taskable_area_sq_km=900,
            description="Fast revisit optical sensor for broad monitoring tasks.",
        ),
        "aurora-optical-hd": Sensor(
            id="aurora-optical-hd",
            constellation="Aurora",
            modality="optical",
            resolution_m=0.35,
            max_taskable_area_sq_km=120,
            description="High-resolution optical tasking for detailed site monitoring.",
        ),
        "nightwatch-sar": Sensor(
            id="nightwatch-sar",
            constellation="Nightwatch",
            modality="sar",
            resolution_m=0.8,
            max_taskable_area_sq_km=700,
            description="All-weather SAR sensor for low-visibility and night acquisitions.",
        ),
    }

    POLICY_PROFILES = {
        "policy-commercial-standard": PolicyProfile(
            id="policy-commercial-standard",
            label="Commercial Standard",
            description="Default commercial policy for routine monitoring programs.",
            max_aoi_sq_km=250,
            allowed_sensor_ids=["aurora-optical-wide", "nightwatch-sar"],
            max_cloud_cover_pct=35,
            allows_rush=False,
            allowed_delivery_formats=[
                DeliveryFormat.geotiff,
                DeliveryFormat.png_tiles,
            ],
            max_window_days=10,
        ),
        "policy-commercial-priority": PolicyProfile(
            id="policy-commercial-priority",
            label="Commercial Priority",
            description="Priority tasking policy for high-value commercial operations.",
            max_aoi_sq_km=450,
            allowed_sensor_ids=[
                "aurora-optical-wide",
                "aurora-optical-hd",
                "nightwatch-sar",
            ],
            max_cloud_cover_pct=45,
            allows_rush=True,
            allowed_delivery_formats=[
                DeliveryFormat.geotiff,
                DeliveryFormat.png_tiles,
                DeliveryFormat.analytic_bundle,
            ],
            max_window_days=14,
        ),
        "policy-humanitarian-response": PolicyProfile(
            id="policy-humanitarian-response",
            label="Humanitarian Response",
            description="Rapid response imagery policy for humanitarian field teams.",
            max_aoi_sq_km=600,
            allowed_sensor_ids=["aurora-optical-wide", "nightwatch-sar"],
            max_cloud_cover_pct=60,
            allows_rush=True,
            allowed_delivery_formats=[
                DeliveryFormat.geotiff,
                DeliveryFormat.png_tiles,
            ],
            max_window_days=7,
        ),
    }

    CUSTOMER_ACCOUNTS = {
        "acct-atlas-mining": CustomerAccount(
            id="acct-atlas-mining",
            name="Atlas Mining Group",
            sector="Mining",
            region="Latin America",
            default_policy_profile_id="policy-commercial-priority",
        ),
        "acct-civic-planning": CustomerAccount(
            id="acct-civic-planning",
            name="Civic Planning Office",
            sector="Public Sector",
            region="Southern Europe",
            default_policy_profile_id="policy-commercial-standard",
        ),
        "acct-relief-watch": CustomerAccount(
            id="acct-relief-watch",
            name="Relief Watch",
            sector="Humanitarian",
            region="Global",
            default_policy_profile_id="policy-humanitarian-response",
        ),
    }


def validate_collection_request(payload: CollectionRequestInput) -> ValidationResult:
    now = utc_now()
    violations: list[PolicyViolation] = []

    customer = CUSTOMER_ACCOUNTS.get(payload.customer_account_id)
    policy = POLICY_PROFILES.get(payload.policy_profile_id)
    sensor = SENSORS.get(payload.sensor_id)

    if customer is None:
        violations.append(
            PolicyViolation(
                code="UNKNOWN_CUSTOMER",
                message="Customer account does not exist.",
                field="customer_account_id",
            )
        )
    if policy is None:
        violations.append(
            PolicyViolation(
                code="UNKNOWN_POLICY",
                message="Policy profile does not exist.",
                field="policy_profile_id",
            )
        )
    if sensor is None:
        violations.append(
            PolicyViolation(
                code="UNKNOWN_SENSOR",
                message="Sensor does not exist.",
                field="sensor_id",
            )
        )

    if customer and policy and customer.default_policy_profile_id != policy.id:
        violations.append(
            PolicyViolation(
                code="POLICY_NOT_ASSIGNED",
                message=(
                    f"{customer.name} must use policy "
                    f"{customer.default_policy_profile_id}."
                ),
                field="policy_profile_id",
            )
        )

    if policy and sensor and sensor.id not in policy.allowed_sensor_ids:
        violations.append(
            PolicyViolation(
                code="SENSOR_NOT_ALLOWED",
                message=f"Sensor {sensor.id} is not allowed by this policy.",
                field="sensor_id",
            )
        )

    if policy and payload.area_of_interest.area_sq_km > policy.max_aoi_sq_km:
        violations.append(
            PolicyViolation(
                code="AOI_TOO_LARGE",
                message=f"AOI exceeds the policy limit of {policy.max_aoi_sq_km} sq km.",
                field="area_of_interest.area_sq_km",
            )
        )

    if sensor and payload.area_of_interest.area_sq_km > sensor.max_taskable_area_sq_km:
        violations.append(
            PolicyViolation(
                code="SENSOR_AOI_LIMIT_EXCEEDED",
                message=(
                    f"Sensor {sensor.id} cannot task an AOI larger than "
                    f"{sensor.max_taskable_area_sq_km} sq km."
                ),
                field="area_of_interest.area_sq_km",
            )
        )

    if policy and payload.cloud_cover_max_pct > policy.max_cloud_cover_pct:
        violations.append(
            PolicyViolation(
                code="CLOUD_COVER_TOO_HIGH",
                message=(
                    "Requested cloud cover threshold exceeds the policy maximum of "
                    f"{policy.max_cloud_cover_pct}%."
                ),
                field="cloud_cover_max_pct",
            )
        )

    if policy and payload.priority is Priority.rush and not policy.allows_rush:
        violations.append(
            PolicyViolation(
                code="RUSH_NOT_ALLOWED",
                message="Rush tasking is not allowed under this policy.",
                field="priority",
            )
        )

    if policy and payload.delivery_format not in policy.allowed_delivery_formats:
        violations.append(
            PolicyViolation(
                code="FORMAT_NOT_ALLOWED",
                message="Requested delivery format is not allowed under this policy.",
                field="delivery_format",
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

    if payload.acquisition_window_start < now:
        violations.append(
            PolicyViolation(
                code="WINDOW_IN_PAST",
                message="Acquisition window must start in the future.",
                field="acquisition_window_start",
            )
        )

    if policy:
        horizon = now + timedelta(days=policy.max_window_days)
        if payload.acquisition_window_end > horizon:
            violations.append(
                PolicyViolation(
                    code="WINDOW_TOO_FAR_OUT",
                    message=(
                        "Acquisition window exceeds the policy planning horizon of "
                        f"{policy.max_window_days} days."
                    ),
                    field="acquisition_window_end",
                )
            )

    return ValidationResult(allowed=not violations, violations=violations)


def build_collection_request(
    payload: CollectionRequestInput,
    *,
    request_id: str | None = None,
    order_number: str | None = None,
    status_value: CollectionRequestStatus = CollectionRequestStatus.validated,
    source: Literal["seeded", "user"],
    created_at: datetime | None = None,
    updated_at: datetime | None = None,
    expires_at: datetime | None = None,
    note: str | None = None,
    events: list[CollectionRequestEvent] | None = None,
) -> CollectionRequest:
    created = created_at or utc_now()
    updated = updated_at or created
    customer = CUSTOMER_ACCOUNTS[payload.customer_account_id]
    request_events = events or [
        CollectionRequestEvent(
            at=created,
            status=status_value,
            note=note or "Collection request validated and accepted into the workflow.",
        )
    ]
    return CollectionRequest(
        id=request_id or f"cr_{uuid4().hex[:10]}",
        order_number=order_number or f"OO-{created.strftime('%Y%m%d')}-{uuid4().hex[:4].upper()}",
        customer_name=customer.name,
        status=status_value,
        progress_pct=STATUS_PROGRESS[status_value.value],
        expected_delivery_at=payload.acquisition_window_end + timedelta(hours=12),
        events=request_events,
        created_at=created,
        updated_at=updated,
        expires_at=expires_at or session_expiry(),
        source=source,
        **payload.model_dump(),
    )


def advance_collection_request(
    collection_request: CollectionRequest,
    target_status: CollectionRequestStatus | None = None,
    note: str | None = None,
) -> CollectionRequest:
    if collection_request.status is CollectionRequestStatus.failed:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Failed collection requests cannot be advanced.",
        )

    if (
        collection_request.status is CollectionRequestStatus.delivered
        and target_status is None
    ):
        return collection_request

    current_index = STATUS_FLOW.index(collection_request.status.value)
    next_status = target_status

    if next_status is None:
        if current_index >= len(STATUS_FLOW) - 1:
            return collection_request
        next_status = CollectionRequestStatus(STATUS_FLOW[current_index + 1])

    if next_status is CollectionRequestStatus.failed:
        collection_request.status = CollectionRequestStatus.failed
    elif STATUS_FLOW.index(next_status.value) <= current_index:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Target status must be ahead of the current collection request status.",
        )
    else:
        collection_request.status = next_status

    collection_request.progress_pct = STATUS_PROGRESS[collection_request.status.value]
    collection_request.updated_at = utc_now()
    collection_request.expires_at = session_expiry()
    collection_request.events.append(
        CollectionRequestEvent(
            at=collection_request.updated_at,
            status=collection_request.status,
            note=note or f"Collection request advanced to {collection_request.status.value}.",
        )
    )
    return collection_request


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


def seed_session_data() -> None:
    global COLLECTION_REQUESTS

    COLLECTION_REQUESTS = {}
    now = utc_now()

    request_one = build_collection_request(
        CollectionRequestInput(
            customer_account_id="acct-civic-planning",
            policy_profile_id="policy-commercial-standard",
            sensor_id="aurora-optical-wide",
            priority=Priority.standard,
            delivery_format=DeliveryFormat.png_tiles,
            acquisition_window_start=now + timedelta(hours=6),
            acquisition_window_end=now + timedelta(days=1, hours=6),
            cloud_cover_max_pct=20,
            area_of_interest=AreaOfInterest(
                name="Seville expansion corridor",
                center_lat=37.3891,
                center_lon=-5.9845,
                area_sq_km=85,
            ),
        ),
        request_id="cr_demo_001",
        order_number="OO-DEMO-001",
        status_value=CollectionRequestStatus.ready,
        source="seeded",
        created_at=now - timedelta(minutes=9),
        updated_at=now - timedelta(minutes=2),
        expires_at=now + timedelta(minutes=SESSION_TTL_MINUTES),
        events=[
            CollectionRequestEvent(
                at=now - timedelta(minutes=9),
                status=CollectionRequestStatus.validated,
                note="Seeded request accepted for routine urban planning coverage.",
            ),
            CollectionRequestEvent(
                at=now - timedelta(minutes=7),
                status=CollectionRequestStatus.processing,
                note="Imagery ingested and queued for analyst review.",
            ),
            CollectionRequestEvent(
                at=now - timedelta(minutes=2),
                status=CollectionRequestStatus.ready,
                note="Products are ready for delivery to the planning dashboard.",
            ),
        ],
    )

    request_two = build_collection_request(
        CollectionRequestInput(
            customer_account_id="acct-atlas-mining",
            policy_profile_id="policy-commercial-priority",
            sensor_id="aurora-optical-hd",
            priority=Priority.rush,
            delivery_format=DeliveryFormat.analytic_bundle,
            acquisition_window_start=now + timedelta(hours=2),
            acquisition_window_end=now + timedelta(hours=16),
            cloud_cover_max_pct=30,
            area_of_interest=AreaOfInterest(
                name="Atacama pit expansion",
                center_lat=-22.9108,
                center_lon=-68.1997,
                area_sq_km=42,
            ),
        ),
        request_id="cr_demo_002",
        order_number="OO-DEMO-002",
        status_value=CollectionRequestStatus.capturing,
        source="seeded",
        created_at=now - timedelta(minutes=6),
        updated_at=now - timedelta(minutes=1),
        expires_at=now + timedelta(minutes=SESSION_TTL_MINUTES),
        events=[
            CollectionRequestEvent(
                at=now - timedelta(minutes=6),
                status=CollectionRequestStatus.validated,
                note="Priority mining task accepted under the commercial priority policy.",
            ),
            CollectionRequestEvent(
                at=now - timedelta(minutes=4),
                status=CollectionRequestStatus.tasking,
                note="Spacecraft reservation approved for next available pass.",
            ),
            CollectionRequestEvent(
                at=now - timedelta(minutes=1),
                status=CollectionRequestStatus.capturing,
                note="Constellation is actively acquiring imagery for the site.",
            ),
        ],
    )

    request_three = build_collection_request(
        CollectionRequestInput(
            customer_account_id="acct-relief-watch",
            policy_profile_id="policy-humanitarian-response",
            sensor_id="nightwatch-sar",
            priority=Priority.rush,
            delivery_format=DeliveryFormat.geotiff,
            acquisition_window_start=now + timedelta(hours=1),
            acquisition_window_end=now + timedelta(hours=10),
            cloud_cover_max_pct=55,
            area_of_interest=AreaOfInterest(
                name="Floodplain north sector",
                center_lat=14.5995,
                center_lon=120.9842,
                area_sq_km=160,
            ),
        ),
        request_id="cr_demo_003",
        order_number="OO-DEMO-003",
        status_value=CollectionRequestStatus.validated,
        source="seeded",
        created_at=now - timedelta(minutes=4),
        updated_at=now - timedelta(minutes=4),
        expires_at=now + timedelta(minutes=SESSION_TTL_MINUTES),
        note="Humanitarian response request validated and waiting for scheduling.",
    )

    COLLECTION_REQUESTS = {
        request_one.id: request_one,
        request_two.id: request_two,
        request_three.id: request_three,
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
        "purpose": "Demo API for agent-tool assignments around satellite imagery ordering.",
        "session_started_at": SESSION_STARTED_AT,
        "session_ttl_minutes": SESSION_TTL_MINUTES,
        "counts": {
            "policy_profiles": len(POLICY_PROFILES),
            "customer_accounts": len(CUSTOMER_ACCOUNTS),
            "sensors": len(SENSORS),
            "collection_requests": len(COLLECTION_REQUESTS),
        },
        "links": {
            "interactive_docs": "/docs",
            "openapi": "/openapi.json",
            "assignment_docs": "/docs/assignment",
            "policy_profiles": "/policy-profiles",
            "customer_accounts": "/customer-accounts",
            "sensors": "/sensors",
        },
    }


@app.get("/policy-profiles", response_model=list[PolicyProfile])
def list_policy_profiles() -> list[PolicyProfile]:
    return list(POLICY_PROFILES.values())


@app.get("/customer-accounts", response_model=list[CustomerAccount])
def list_customer_accounts() -> list[CustomerAccount]:
    return list(CUSTOMER_ACCOUNTS.values())


@app.get("/sensors", response_model=list[Sensor])
def list_sensors() -> list[Sensor]:
    return list(SENSORS.values())


@app.post("/collection-requests/validate", response_model=ValidationResult)
def validate_request(payload: CollectionRequestInput) -> ValidationResult:
    return validate_collection_request(payload)


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


@app.post(
    "/collection-requests/{collection_request_id}/simulate-tick",
    response_model=CollectionRequest,
)
def simulate_tick(
    collection_request_id: str,
    payload: SimulateTickPayload | None = None,
) -> CollectionRequest:
    collection_request = get_collection_request_or_404(collection_request_id)
    return advance_collection_request(
        collection_request,
        target_status=payload.target_status if payload else None,
        note=payload.note if payload else None,
    )


@app.get("/docs/assignment")
def assignment_docs() -> dict[str, object]:
    return {
        "title": "OrbitalOps assignment guide",
        "overview": (
            "This API simulates a satellite constellation company that validates and "
            "tracks collection requests as a single workflow object."
        ),
        "objects": {
            "policy_profiles": {
                "mutable": False,
                "purpose": "Read-only policy rules that gate what each customer may request.",
            },
            "customer_accounts": {
                "mutable": False,
                "purpose": "Read-only commercial accounts mapped to a default policy profile.",
            },
            "sensors": {
                "mutable": False,
                "purpose": "Read-only sensor catalog describing the imaging assets candidates can task.",
            },
            "collection_requests": {
                "mutable": True,
                "purpose": (
                    "A collection request is the main workflow object. It includes the "
                    "commercial tracking fields that would normally live on an order."
                ),
            },
        },
        "relationships": [
            "A customer account is assigned to a single policy profile.",
            "A collection request chooses one sensor from the read-only sensor catalog.",
            "A collection request must use the customer account's assigned policy profile.",
            "Collection requests move through an order-like lifecycle for demos and dashboards.",
            "Reference data is immutable, while collection requests are session-scoped and mutable.",
        ],
        "known_values": {
            "priority": [priority.value for priority in Priority],
            "delivery_format": [delivery_format.value for delivery_format in DeliveryFormat],
            "collection_request_status": [
                request_status.value for request_status in CollectionRequestStatus
            ],
        },
        "mutable_session_data": {
            "ttl_minutes": SESSION_TTL_MINUTES,
            "notes": [
                "Seeded collection requests are loaded when the app starts.",
                "Collection requests may be deleted or replaced during the exercise.",
                "Reference data is hardcoded and exposed as read-only catalog data.",
            ],
        },
        "starter_validation_examples": [
            {
                "name": "rush_not_allowed",
                "description": "Fails because Civic Planning uses the standard policy and standard policy does not allow rush.",
                "payload": {
                    "customer_account_id": "acct-civic-planning",
                    "policy_profile_id": "policy-commercial-standard",
                    "sensor_id": "aurora-optical-wide",
                    "priority": "rush",
                    "delivery_format": "png_tiles",
                    "acquisition_window_start": (utc_now() + timedelta(hours=5)).isoformat(),
                    "acquisition_window_end": (utc_now() + timedelta(days=1)).isoformat(),
                    "cloud_cover_max_pct": 20,
                    "area_of_interest": {
                        "name": "Seville emergency corridor",
                        "center_lat": 37.38,
                        "center_lon": -5.99,
                        "area_sq_km": 95,
                    },
                },
            }
        ],
        "workflow": [
            {
                "step": 1,
                "action": "Inspect /policy-profiles, /customer-accounts, and /sensors to discover the allowed business context.",
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
                "action": "Track progress with GET /collection-requests/{collection_request_id}.",
            },
            {
                "step": 5,
                "action": "Advance status with POST /collection-requests/{collection_request_id}/simulate-tick.",
            },
        ],
        "endpoints": [
            {"method": "GET", "path": "/", "description": "Service summary and useful links."},
            {"method": "GET", "path": "/policy-profiles", "description": "List policy profiles."},
            {"method": "GET", "path": "/customer-accounts", "description": "List customer accounts and their default policy assignments."},
            {"method": "GET", "path": "/sensors", "description": "List available imaging sensors."},
            {"method": "POST", "path": "/collection-requests/validate", "description": "Validate a collection request without persisting it."},
            {"method": "GET", "path": "/collection-requests", "description": "List session-scoped collection requests."},
            {"method": "POST", "path": "/collection-requests", "description": "Persist a policy-compliant collection request."},
            {"method": "GET", "path": "/collection-requests/{collection_request_id}", "description": "Fetch one collection request including workflow status."},
            {"method": "DELETE", "path": "/collection-requests/{collection_request_id}", "description": "Delete a session collection request."},
            {"method": "POST", "path": "/collection-requests/{collection_request_id}/simulate-tick", "description": "Advance a collection request through the demo lifecycle."},
        ],
        "starter_demo_records": {
            "collection_request_ids": sorted(COLLECTION_REQUESTS.keys()),
        },
    }