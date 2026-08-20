from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import Mock

import pytest
from pydantic import ValidationError

from melloa.application.self_change import OwnerSelfChangeService
from melloa.domain.self_change import (
    SelfChange,
    SelfChangeState,
    self_change_proposal_digest,
    self_change_request_digest,
)
from melloa.ports.self_change import SelfChangeConflictError, SelfChangeNotFoundError

_NOW = datetime(2026, 8, 20, 12, 0, tzinfo=UTC)
_OWNER_ID = "owner_00000000000000000000000000000001"
_CHANGE_ID = "change_11111111111111111111111111111111"
_BASE_REVISION = "a" * 40
_SUMMARY = "Keep owner-approved changes exact."
_PATCH = "diff --git a/example b/example\n+owner approved\n"


def _requested(**updates: object) -> SelfChange:
    request = "Add one bounded owner-approved behavior."
    values: dict[str, object] = {
        "change_id": _CHANGE_ID,
        "owner_id": _OWNER_ID,
        "request_text": request,
        "request_digest": self_change_request_digest(request),
        "requested_update_id": 10,
        "state": SelfChangeState.REQUESTED,
        "available_at": _NOW,
        "requested_at": _NOW,
        "updated_at": _NOW,
    }
    values.update(updates)
    return SelfChange.model_validate(values)


def _proposal(**updates: object) -> SelfChange:
    digest = self_change_proposal_digest(
        base_revision=_BASE_REVISION,
        summary=_SUMMARY,
        patch=_PATCH,
    )
    values: dict[str, object] = {
        "state": SelfChangeState.PROPOSAL_READY,
        "base_revision": _BASE_REVISION,
        "proposal_summary": _SUMMARY,
        "proposal_patch": _PATCH,
        "proposal_digest": digest,
    }
    values.update(updates)
    return _requested(**values)


def _service(store: Mock) -> OwnerSelfChangeService:
    return OwnerSelfChangeService(
        owner_id=_OWNER_ID,
        store=store,
        clock=lambda: _NOW + timedelta(minutes=5),
        id_factory=lambda prefix: _CHANGE_ID if prefix == "change" else "",
    )


def test_propose_normalizes_and_hashes_only_the_explicit_request() -> None:
    store = Mock()
    store.create.side_effect = lambda change: change

    response = _service(store).handle(
        "/change propose   Add   a public-safe status command.  ",
        update_id=12,
    )

    change = store.create.call_args.args[0]
    assert change.request_text == "Add a public-safe status command."
    assert change.request_digest == self_change_request_digest(change.request_text)
    assert change.requested_update_id == 12
    assert change.state is SelfChangeState.REQUESTED
    assert _CHANGE_ID in response
    assert "Private conversation history is excluded" in response
    assert "no commit, push, or deployment is authorized" in response


def test_propose_reports_idempotency_conflicts_without_authorizing_work() -> None:
    store = Mock()
    store.create.side_effect = SelfChangeConflictError

    response = _service(store).handle(
        "/change propose Add one deterministic owner control.",
        update_id=12,
    )

    assert response == "That Telegram update conflicts with an existing change request."


def test_show_diff_and_exact_approval_use_the_current_proposal_digest() -> None:
    proposal = _proposal()
    approved = proposal.model_copy(
        update={
            "state": SelfChangeState.APPROVED,
            "approval_update_id": 13,
            "approved_digest": proposal.proposal_digest,
            "approved_at": _NOW + timedelta(minutes=5),
            "updated_at": _NOW + timedelta(minutes=5),
        }
    )
    store = Mock()
    store.get.return_value = proposal
    store.approve.return_value = approved
    service = _service(store)

    diff = service.handle(f"/change diff {_CHANGE_ID}", update_id=12)
    assert _PATCH in diff
    assert proposal.proposal_digest in diff
    token = proposal.proposal_digest.removeprefix("sha256:")[:16]

    wrong = service.handle(f"/change approve {_CHANGE_ID} 0000000000000000", update_id=13)
    assert wrong == "Approval token does not match the current proposal. Nothing was authorized."
    store.approve.assert_not_called()

    response = service.handle(f"/change approve {_CHANGE_ID} {token}", update_id=13)
    store.approve.assert_called_once_with(
        _OWNER_ID,
        _CHANGE_ID,
        proposal_digest=proposal.proposal_digest,
        approval_update_id=13,
        now=_NOW + timedelta(minutes=5),
    )
    assert "test, commit, push, and deploy only this exact diff" in response
    assert "changed diff requires a new approval" in response


def test_missing_and_conflicting_changes_fail_closed() -> None:
    store = Mock()
    store.get.side_effect = SelfChangeNotFoundError
    service = _service(store)

    assert service.handle(f"/change show {_CHANGE_ID}", update_id=14) == (
        "That change ID was not found."
    )

    store.get.side_effect = None
    store.get.return_value = _proposal()
    store.cancel.side_effect = SelfChangeConflictError
    assert service.handle(f"/change cancel {_CHANGE_ID}", update_id=14) == (
        "That change can no longer be cancelled from Telegram."
    )


@pytest.mark.parametrize(
    "updates,match",
    [
        ({"request_digest": "sha256:" + "0" * 64}, "request digest"),
        (
            {
                "state": SelfChangeState.PROPOSAL_READY,
                "base_revision": _BASE_REVISION,
            },
            "proposal fields",
        ),
        (
            {
                "state": SelfChangeState.CANCELLED,
                "cancelled_update_id": 11,
            },
            "cancellation evidence",
        ),
    ],
)
def test_contract_rejects_partial_or_forged_evidence(
    updates: dict[str, object],
    match: str,
) -> None:
    with pytest.raises(ValidationError, match=match):
        _requested(**updates)


def test_contract_rejects_approval_from_the_request_update() -> None:
    proposal = _proposal()
    document = proposal.model_dump() | {
        "state": SelfChangeState.APPROVED,
        "approval_update_id": proposal.requested_update_id,
        "approved_digest": proposal.proposal_digest,
        "approved_at": _NOW,
    }
    with pytest.raises(ValidationError, match="approval must follow"):
        SelfChange.model_validate(document)


def test_contract_rejects_partial_approval_evidence() -> None:
    proposal = _proposal()
    with pytest.raises(ValidationError, match="approval evidence"):
        SelfChange.model_validate(
            proposal.model_dump()
            | {
                "state": SelfChangeState.APPROVED,
                "approval_update_id": 11,
                "approved_at": _NOW,
            }
        )


def test_deployed_contract_cannot_also_claim_rollback() -> None:
    proposal = _proposal()
    digest = proposal.proposal_digest
    with pytest.raises(ValidationError, match="deployed self-change"):
        SelfChange.model_validate(
            proposal.model_dump()
            | {
                "state": SelfChangeState.DEPLOYED,
                "approval_update_id": 11,
                "approved_digest": digest,
                "approved_at": _NOW,
                "candidate_revision": "b" * 40,
                "deployed_at": _NOW,
                "rolled_back_at": _NOW,
            }
        )
