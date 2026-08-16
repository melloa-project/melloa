from __future__ import annotations

from fastapi.testclient import TestClient

from melloa.adapters.fakes.auth import InMemoryOwnerSessionManager
from melloa.adapters.fakes.guardian import FakeGuardianStatusReader
from melloa.adapters.fakes.model import FakeModelGateway
from melloa.application.routing import (
    DeterministicModelRouter,
    ModelRouteBinding,
    OwnerModelRouteService,
)
from melloa.apps.core import create_app
from melloa.domain.classification import Sensitivity
from melloa.domain.guardian import GuardianMode, GuardianStatusPayload
from melloa.domain.models import ProcessingLocation, RegisteredModelRoute
from tests.conftest import record_id

_BOOTSTRAP_TOKEN = "synthetic-owner-bootstrap-token-value-0001"


def test_authenticated_owner_can_inspect_configured_model_routes(fixed_time) -> None:
    owner_id = record_id("owner", 1)
    route = RegisteredModelRoute(
        route_id="model.local.test",
        provider_id="provider.local-test",
        model_id="qwen-test",
        processing_location=ProcessingLocation.DEVICE,
        supported_modalities=frozenset({"text"}),
        quality_profiles=frozenset({"quality.conversation"}),
        allowed_sensitivities=frozenset(Sensitivity),
        provider_retention_policies=frozenset({"retention.no-training"}),
        max_input_tokens=8_192,
        max_output_tokens=2_048,
        estimated_max_cost_gbp=0.0,
        reliability=1.0,
        priority=0,
        external_disclosure=False,
    )
    router = DeterministicModelRouter(
        (
            ModelRouteBinding(
                route,
                FakeModelGateway(
                    {"text": "synthetic"},
                    route_id=route.route_id,
                    provider_id=route.provider_id,
                    model_id=route.model_id,
                    clock=lambda: fixed_time,
                ),
                display_name="Local test model",
            ),
        ),
        clock=lambda: fixed_time,
    )
    sessions = InMemoryOwnerSessionManager(owner_id, _BOOTSTRAP_TOKEN, clock=lambda: fixed_time)
    guardian = FakeGuardianStatusReader.from_payload(
        GuardianStatusPayload(
            instance_id="home-guardian",
            mode=GuardianMode.NORMAL,
            sequence=1,
            changed_at=fixed_time,
            reason_code="guardian.synthetic-normal",
        ),
        receipt_hash="sha256:" + "1" * 64,
    )
    app = create_app(
        guardian,
        sessions,
        model_route_service=OwnerModelRouteService(
            owner_id=owner_id,
            router=router,
            clock=lambda: fixed_time,
        ),
    )
    client = TestClient(app, base_url="https://testserver")

    assert client.get("/api/v1/providers/routes").status_code == 401
    login = client.post("/api/v1/auth/session", json={"credential": _BOOTSTRAP_TOKEN})
    assert login.status_code == 200
    response = client.get("/api/v1/providers/routes")
    assert response.status_code == 200
    document = response.json()
    assert document["owner_id"] == owner_id
    assert document["routes"][0]["route_id"] == "model.local.test"
    assert document["routes"][0]["health"]["state"] == "healthy"


def test_model_route_report_is_explicitly_unavailable_when_not_configured(fixed_time) -> None:
    owner_id = record_id("owner", 1)
    sessions = InMemoryOwnerSessionManager(owner_id, _BOOTSTRAP_TOKEN, clock=lambda: fixed_time)
    guardian = FakeGuardianStatusReader.from_payload(
        GuardianStatusPayload(
            instance_id="home-guardian",
            mode=GuardianMode.NO_ACTIONS,
            sequence=1,
            changed_at=fixed_time,
            reason_code="guardian.synthetic-no-actions",
        ),
        receipt_hash="sha256:" + "2" * 64,
    )
    client = TestClient(create_app(guardian, sessions), base_url="https://testserver")
    assert (
        client.post("/api/v1/auth/session", json={"credential": _BOOTSTRAP_TOKEN}).status_code
        == 200
    )
    assert client.get("/api/v1/providers/routes").status_code == 503
