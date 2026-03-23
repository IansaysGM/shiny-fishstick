from __future__ import annotations

from datetime import UTC, datetime, timedelta
from enum import Enum
from typing import Literal
from uuid import uuid4

from fastapi import FastAPI, HTTPException, status
from pydantic import BaseModel, Field

SESSION_TTL_MINUTES = 20
ORDER_PROGRESS = {
    "validated": 10,
    "scheduled": 25,
    "tasking": 40,
    "capturing": 60,
    "processing": 80,
    "ready": 95,
    "delivered": 100,
    "failed": 100,
}
ORDER_FLOW = [
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


class OrderStatus(str, Enum):
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


class CollectionRequest(CollectionRequestInput):
    id: str
    status: Literal["approved"] = "approved"
    created_at: datetime
    updated_at: datetime
    expires_at: datetime
    source: Literal["seeded", "user"]


class OrderEvent(BaseModel):
    at: datetime
    status: OrderStatus
    note: str


class Order(BaseModel):
    id: str
    order_number: str
    collection_request_id: str
    customer_account_id: str
    customer_name: str
    policy_profile_id: str
    sensor_id: str
    priority: Priority
    status: OrderStatus
    progress_pct: int = Field(..., ge=0, le=100)
    created_at: datetime
    updated_at: datetime
    expires_at: datetime
    expected_delivery_at: datetime
    source: Literal["seeded", "user"]
    request_snapshot: CollectionRequest
    events: list[OrderEvent]


class CreateOrderPayload(BaseModel):
    collection_request_id: str
    requested_by: str = Field(..., min_length=2, max_length=80)
    note: str | None = Field(default=None, max_length=240)


class SimulateTickPayload(BaseModel):
    target_status: OrderStatus | None = None
    note: str | None = Field(default=None, max_length=240)


class DeleteResult(BaseModel):
    deleted: bool
    id: str
    resource: Literal["collection_request", "order"]


POLICY_PROFILES: dict[str, PolicyProfile] = {}
SENSORS: dict[str, Sensor] = {}
CUSTOMER_ACCOUNTS: dict[str, CustomerAccount] = {}
COLLECTION_REQUESTS: dict[str, CollectionRequest] = {}
ORDERS: dict[str, Order] = {}


app = FastAPI(
    title="OrbitalOps Mock API",
    summary="Mock satellite imagery ordering API for agent-tool assignments",
    description=(
        "A demo-friendly FastAPI service for validating satellite collection requests, "
        "creating short-lived orders, and tracking order progress."
    ),
    version="1.0.0",
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
                message=(
                    f"AOI exceeds the policy limit of {policy.max_aoi_sq_km} sq km."
                ),
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
    source: Literal["seeded", "user"],
    created_at: datetime | None = None,
    expires_at: datetime | None = None,
) -> CollectionRequest:
    created = created_at or utc_now()
    expiry = expires_at or session_expiry()
    return CollectionRequest(
        id=request_id or f"cr_{uuid4().hex[:10]}",
        created_at=created,
        updated_at=created,
        expires_at=expiry,
        source=source,
        **payload.model_dump(),
    )


def build_order(
    collection_request: CollectionRequest,
    *,
    order_id: str | None = None,
    order_number: str | None = None,
    status_value: OrderStatus = OrderStatus.validated,
    source: Literal["seeded", "user"],
    created_at: datetime | None = None,
    requested_by: str | None = None,
    note: str | None = None,
) -> Order:
    created = created_at or utc_now()
    customer = CUSTOMER_ACCOUNTS[collection_request.customer_account_id]
    events = [
        OrderEvent(
            at=created,
            status=status_value,
            note=note or f"Order created by {requested_by or 'system seed'}",
        )
    ]
    return Order(
        id=order_id or f"ord_{uuid4().hex[:10]}",
        order_number=order_number or f"OO-{created.strftime('%Y%m%d')}-{uuid4().hex[:4].upper()}",
        collection_request_id=collection_request.id,
        customer_account_id=customer.id,
        customer_name=customer.name,
        policy_profile_id=collection_request.policy_profile_id,
        sensor_id=collection_request.sensor_id,
        priority=collection_request.priority,
        status=status_value,
        progress_pct=ORDER_PROGRESS[status_value.value],
        created_at=created,
        updated_at=created,
        expires_at=session_expiry(),
        expected_delivery_at=collection_request.acquisition_window_end + timedelta(hours=12),
        source=source,
        request_snapshot=collection_request.model_copy(deep=True),
        events=events,
    )


def collection_request_input_from_record(
    collection_request: CollectionRequest,
) -> CollectionRequestInput:
    return CollectionRequestInput(
        **collection_request.model_dump(
            exclude={"id", "status", "created_at", "updated_at", "expires_at", "source"}
        )
    )


def advance_order(order: Order, target_status: OrderStatus | None = None, note: str | None = None) -> Order:
    if order.status is OrderStatus.failed:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Failed orders cannot be advanced.",
        )

    if order.status is OrderStatus.delivered and target_status is None:
        return order

    current_index = ORDER_FLOW.index(order.status.value)
    next_status = target_status

    if next_status is None:
        if current_index >= len(ORDER_FLOW) - 1:
            return order
        next_status = OrderStatus(ORDER_FLOW[current_index + 1])

    if next_status is OrderStatus.failed:
        order.status = OrderStatus.failed
    elif ORDER_FLOW.index(next_status.value) <= current_index:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Target status must be ahead of the current order status.",
        )
    else:
        order.status = next_status

    order.progress_pct = ORDER_PROGRESS[order.status.value]
    order.updated_at = utc_now()
    order.expires_at = session_expiry()
    order.events.append(
        OrderEvent(
            at=order.updated_at,
            status=order.status,
            note=note or f"Order advanced to {order.status.value}.",
        )
    )
    return order


def cleanup_expired_records() -> None:
    now = utc_now()
    expired_requests = [
        request_id
        for request_id, collection_request in COLLECTION_REQUESTS.items()
        if collection_request.expires_at <= now
    ]
    expired_orders = [
        order_id
        for order_id, order in ORDERS.items()
        if order.expires_at <= now
    ]
    for request_id in expired_requests:
        del COLLECTION_REQUESTS[request_id]
    for order_id in expired_orders:
        del ORDERS[order_id]


def get_collection_request_or_404(collection_request_id: str) -> CollectionRequest:
    cleanup_expired_records()
    collection_request = COLLECTION_REQUESTS.get(collection_request_id)
    if collection_request is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Collection request not found.",
        )
    return collection_request


def get_order_or_404(order_id: str) -> Order:
    cleanup_expired_records()
    order = ORDERS.get(order_id)
    if order is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Order not found.",
        )
    return order


def seed_session_data() -> None:
    global COLLECTION_REQUESTS, ORDERS

    COLLECTION_REQUESTS = {}
    ORDERS = {}

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
        source="seeded",
        created_at=now - timedelta(minutes=9),
        expires_at=now + timedelta(minutes=SESSION_TTL_MINUTES),
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
        source="seeded",
        created_at=now - timedelta(minutes=6),
        expires_at=now + timedelta(minutes=SESSION_TTL_MINUTES),
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
        source="seeded",
        created_at=now - timedelta(minutes=4),
        expires_at=now + timedelta(minutes=SESSION_TTL_MINUTES),
    )

    COLLECTION_REQUESTS = {
        request_one.id: request_one,
        request_two.id: request_two,
        request_three.id: request_three,
    }

    order_one = build_order(
        request_one,
        order_id="ord_demo_001",
        order_number="OO-DEMO-001",
        status_value=OrderStatus.processing,
        source="seeded",
        created_at=now - timedelta(minutes=8),
        note="Seeded demo order moved into processing for dashboard demos.",
    )
    order_one.events.append(
        OrderEvent(
            at=now - timedelta(minutes=7),
            status=OrderStatus.ready,
            note="Analyst review queued after image ingest.",
        )
    )
    order_one.status = OrderStatus.ready
    order_one.progress_pct = ORDER_PROGRESS[OrderStatus.ready.value]
    order_one.updated_at = now - timedelta(minutes=2)

    order_two = build_order(
        request_two,
        order_id="ord_demo_002",
        order_number="OO-DEMO-002",
        status_value=OrderStatus.capturing,
        source="seeded",
        created_at=now - timedelta(minutes=5),
        note="Priority mining request is actively being tasked.",
    )

    ORDERS = {
        order_one.id: order_one,
        order_two.id: order_two,
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
            "orders": len(ORDERS),
        },
        "links": {
            "interactive_docs": "/docs",
            "openapi": "/openapi.json",
            "assignment_docs": "/docs/assignment",
            "reference_data": "/reference-data",
        },
    }


@app.get("/reference-data")
def get_reference_data() -> dict[str, object]:
    return {
        "read_only": True,
        "policy_profiles": list(POLICY_PROFILES.values()),
        "customer_accounts": list(CUSTOMER_ACCOUNTS.values()),
        "sensors": list(SENSORS.values()),
        "starter_validation_examples": [
            {
                "name": "rush_not_allowed",
                "description": "Fails because Civic Planning can only use the standard policy and standard policy does not allow rush.",
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
    }


@app.get("/policy-profiles", response_model=list[PolicyProfile])
def list_policy_profiles() -> list[PolicyProfile]:
    return list(POLICY_PROFILES.values())


@app.get("/policy-profiles/{policy_id}", response_model=PolicyProfile)
def get_policy_profile(policy_id: str) -> PolicyProfile:
    policy = POLICY_PROFILES.get(policy_id)
    if policy is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Policy profile not found.",
        )
    return policy


@app.post("/collection-requests/validate", response_model=ValidationResult)
def validate_request(payload: CollectionRequestInput) -> ValidationResult:
    return validate_collection_request(payload)


@app.get("/collection-requests", response_model=list[CollectionRequest])
def list_collection_requests() -> list[CollectionRequest]:
    cleanup_expired_records()
    return sorted(
        COLLECTION_REQUESTS.values(),
        key=lambda request: request.updated_at,
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


@app.get("/orders", response_model=list[Order])
def list_orders() -> list[Order]:
    cleanup_expired_records()
    return sorted(ORDERS.values(), key=lambda order: order.updated_at, reverse=True)


@app.post("/orders", response_model=Order, status_code=status.HTTP_201_CREATED)
def create_order(payload: CreateOrderPayload) -> Order:
    cleanup_expired_records()
    collection_request = get_collection_request_or_404(payload.collection_request_id)
    validation = validate_collection_request(
        collection_request_input_from_record(collection_request)
    )
    if not validation.allowed:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "message": "Collection request is no longer policy compliant.",
                "violations": [violation.model_dump() for violation in validation.violations],
            },
        )

    order = build_order(
        collection_request,
        source="user",
        requested_by=payload.requested_by,
        note=payload.note,
    )
    ORDERS[order.id] = order
    return order


@app.get("/orders/{order_id}", response_model=Order)
def get_order(order_id: str) -> Order:
    return get_order_or_404(order_id)


@app.delete("/orders/{order_id}", response_model=DeleteResult)
def delete_order(order_id: str) -> DeleteResult:
    order = get_order_or_404(order_id)
    del ORDERS[order.id]
    return DeleteResult(deleted=True, id=order.id, resource="order")


@app.post("/orders/{order_id}/simulate-tick", response_model=Order)
def simulate_tick(order_id: str, payload: SimulateTickPayload | None = None) -> Order:
    order = get_order_or_404(order_id)
    updated_order = advance_order(
        order,
        target_status=payload.target_status if payload else None,
        note=payload.note if payload else None,
    )
    return updated_order


@app.get("/docs/assignment")
def assignment_docs() -> dict[str, object]:
    return {
        "title": "OrbitalOps assignment guide",
        "overview": (
            "This API simulates a satellite constellation company that validates "
            "collection requests before turning them into trackable orders."
        ),
        "objects": {
            "policy_profiles": {
                "mutable": False,
                "purpose": "Read-only policy rules that gate what each customer may request.",
            },
            "collection_requests": {
                "mutable": True,
                "purpose": "Validated imaging requests that can be turned into orders.",
            },
            "orders": {
                "mutable": True,
                "purpose": "Trackable commercial records with lifecycle status and event history.",
            },
        },
        "relationships": [
            "A customer account is assigned to a single policy profile.",
            "A collection request must use the customer account's assigned policy profile.",
            "An order is created from an approved collection request and stores a full request snapshot.",
            "Orders can advance through a status timeline for dashboards and workflow demos.",
        ],
        "mutable_session_data": {
            "ttl_minutes": SESSION_TTL_MINUTES,
            "notes": [
                "Seeded collection requests and orders are loaded when the app starts.",
                "Collection requests and orders may be deleted or replaced during the exercise.",
                "Reference data is hardcoded and exposed as read-only catalog data.",
            ],
        },
        "workflow": [
            {
                "step": 1,
                "action": "Inspect /reference-data and /policy-profiles to discover the allowed business context.",
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
                "action": "Create a trackable order with POST /orders using a collection_request_id.",
            },
            {
                "step": 5,
                "action": "Poll GET /orders or advance status with POST /orders/{order_id}/simulate-tick.",
            },
        ],
        "endpoints": [
            {"method": "GET", "path": "/", "description": "Service summary and useful links."},
            {"method": "GET", "path": "/reference-data", "description": "Read-only startup catalog and example payloads."},
            {"method": "GET", "path": "/policy-profiles", "description": "List policy profiles."},
            {"method": "GET", "path": "/policy-profiles/{policy_id}", "description": "Fetch one policy profile."},
            {"method": "POST", "path": "/collection-requests/validate", "description": "Validate a collection request without persisting it."},
            {"method": "GET", "path": "/collection-requests", "description": "List session-scoped collection requests."},
            {"method": "POST", "path": "/collection-requests", "description": "Persist a policy-compliant collection request."},
            {"method": "GET", "path": "/collection-requests/{collection_request_id}", "description": "Fetch one collection request."},
            {"method": "DELETE", "path": "/collection-requests/{collection_request_id}", "description": "Delete a session collection request."},
            {"method": "GET", "path": "/orders", "description": "List session-scoped orders."},
            {"method": "POST", "path": "/orders", "description": "Create an order from a collection request."},
            {"method": "GET", "path": "/orders/{order_id}", "description": "Fetch one order including its status history."},
            {"method": "DELETE", "path": "/orders/{order_id}", "description": "Delete a session order."},
            {"method": "POST", "path": "/orders/{order_id}/simulate-tick", "description": "Advance an order through the demo lifecycle."},
        ],
        "starter_demo_records": {
            "collection_request_ids": sorted(COLLECTION_REQUESTS.keys()),
            "order_ids": sorted(ORDERS.keys()),
        },
    }