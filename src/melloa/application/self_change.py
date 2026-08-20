"""Deterministic Telegram controls for bounded source-change proposals."""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import datetime

from melloa.domain.base import RecordId, new_record_id, utc_now
from melloa.domain.self_change import (
    SelfChange,
    SelfChangeState,
    self_change_request_digest,
)
from melloa.ports.self_change import (
    SelfChangeConflictError,
    SelfChangeNotFoundError,
    SelfChangeStore,
)

_APPROVAL_TOKEN = re.compile(r"^[0-9a-f]{16}$")
_CHANGE_ID = re.compile(r"^change_[0-9a-f]{32}$")
_USAGE = (
    "Change controls\n"
    "/change propose <public-safe request>\n"
    "/change show <change_id>\n"
    "/change diff <change_id>\n"
    "/change approve <change_id> <16-character proposal token>\n"
    "/change cancel <change_id>\n\n"
    "A proposal sends only that explicit request and repository code to the configured coding "
    "agent—never your private chat history. Nothing is committed, pushed, or deployed before "
    "exact approval."
)


class OwnerSelfChangeService:
    def __init__(
        self,
        *,
        owner_id: RecordId,
        store: SelfChangeStore,
        clock: Callable[[], datetime] = utc_now,
        id_factory: Callable[[str], str] = new_record_id,
    ) -> None:
        self._owner_id = owner_id
        self._store = store
        self._clock = clock
        self._id_factory = id_factory

    def handle(self, text: str, *, update_id: int) -> str:
        command = text.strip()
        if command == "/change":
            latest = self._store.latest(self._owner_id)
            return _USAGE if latest is None else self._render(latest)
        if command.startswith("/change propose "):
            return self._propose(command.removeprefix("/change propose "), update_id)
        parts = command.split()
        if len(parts) == 3 and parts[:2] == ["/change", "show"]:
            return self._show(parts[2], include_patch=False)
        if len(parts) == 3 and parts[:2] == ["/change", "diff"]:
            return self._show(parts[2], include_patch=True)
        if len(parts) == 4 and parts[:2] == ["/change", "approve"]:
            return self._approve(parts[2], parts[3], update_id)
        if len(parts) == 3 and parts[:2] == ["/change", "cancel"]:
            return self._cancel(parts[2], update_id)
        return _USAGE

    def _propose(self, request_text: str, update_id: int) -> str:
        request = " ".join(request_text.split())
        if not 10 <= len(request) <= 2_000:
            return "Change requests must contain between 10 and 2,000 characters.\n\n" + _USAGE
        now = self._clock()
        change = SelfChange(
            change_id=self._id_factory("change"),
            owner_id=self._owner_id,
            request_text=request,
            request_digest=self_change_request_digest(request),
            requested_update_id=update_id,
            state=SelfChangeState.REQUESTED,
            available_at=now,
            requested_at=now,
            updated_at=now,
        )
        try:
            stored = self._store.create(change)
        except SelfChangeConflictError:
            return "That Telegram update conflicts with an existing change request."
        return (
            f"Change requested: {stored.change_id}\n"
            "State: requested\n\n"
            "Only this request and repository code may be sent to the configured coding agent. "
            "Private conversation history is excluded. I will return a reviewable diff and fixed "
            "approval token; no commit, push, or deployment is authorized yet."
        )

    def _show(self, raw_change_id: str, *, include_patch: bool) -> str:
        change = self._find(raw_change_id)
        if change is None:
            return "That change ID was not found."
        rendered = self._render(change)
        if not include_patch:
            return rendered
        if change.proposal_patch is None:
            return rendered + "\n\nNo proposal diff is available yet."
        return rendered + "\n\nExact proposal diff\n" + change.proposal_patch

    def _approve(self, raw_change_id: str, token: str, update_id: int) -> str:
        if _APPROVAL_TOKEN.fullmatch(token) is None:
            return "Approval requires the exact 16-character token shown with the proposal."
        change = self._find(raw_change_id)
        if change is None:
            return "That change ID was not found."
        if change.proposal_digest is None:
            return "That change has no proposal ready for approval."
        expected = change.proposal_digest.removeprefix("sha256:")[:16]
        if token != expected:
            return "Approval token does not match the current proposal. Nothing was authorized."
        try:
            approved = self._store.approve(
                self._owner_id,
                change.change_id,
                proposal_digest=change.proposal_digest,
                approval_update_id=update_id,
                now=self._clock(),
            )
        except SelfChangeConflictError:
            return "That proposal is no longer awaiting approval. Nothing was authorized."
        return (
            f"Change approved: {approved.change_id}\n"
            f"Proposal: {approved.proposal_digest}\n"
            "The worker may now test, commit, push, and deploy only this exact diff. "
            "A changed diff requires a new approval."
        )

    def _cancel(self, raw_change_id: str, update_id: int) -> str:
        change = self._find(raw_change_id)
        if change is None:
            return "That change ID was not found."
        try:
            cancelled = self._store.cancel(
                self._owner_id,
                change.change_id,
                cancellation_update_id=update_id,
                now=self._clock(),
            )
        except SelfChangeConflictError:
            return "That change can no longer be cancelled from Telegram."
        return f"Change cancelled: {cancelled.change_id}"

    def _find(self, raw_change_id: str) -> SelfChange | None:
        if _CHANGE_ID.fullmatch(raw_change_id) is None:
            return None
        try:
            return self._store.get(self._owner_id, raw_change_id)
        except SelfChangeNotFoundError:
            return None

    @staticmethod
    def _render(change: SelfChange) -> str:
        lines = [
            f"Change: {change.change_id}",
            f"State: {change.state.value}",
            f"Request: {change.request_text}",
        ]
        if change.proposal_summary is not None and change.proposal_digest is not None:
            token = change.proposal_digest.removeprefix("sha256:")[:16]
            lines.extend(
                (
                    f"Proposal: {change.proposal_summary}",
                    f"Digest: {change.proposal_digest}",
                    f"Approval token: {token}",
                )
            )
        if change.candidate_revision is not None:
            lines.append(f"Revision: {change.candidate_revision}")
        if change.failure_reason is not None:
            lines.append(f"Failure: {change.failure_reason}")
        return "\n".join(lines)


__all__ = ["OwnerSelfChangeService"]
