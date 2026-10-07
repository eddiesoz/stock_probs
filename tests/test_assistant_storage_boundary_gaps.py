"""Direct persistence-boundary regressions for assistant owner and restart guarantees."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from stock_probs.assistant.storage import (
    AssistantStorage,
    AssistantStorageConflict,
    AssistantStorageNotFound,
    AssistantStorageQuotaExceeded,
)
from stock_probs.repository import Repository

NOW = datetime(2026, 10, 5, 12, 0, tzinfo=UTC)
CONTEXT_VERSION = "a" * 64
CONTEXT = {"route": "/overview", "summary": "disposable boundary fixture"}


def _repository(settings) -> tuple[Repository, AssistantStorage]:
    repository = Repository(settings.database_path)
    repository.migrate()
    return repository, AssistantStorage(repository)


def _owner(repository: Repository, github_id: int) -> int:
    row = repository.create_user(
        github_user_id=github_id,
        login=f"storage-owner-{github_id}",
        display_name=f"Storage owner {github_id}",
        password_hash=None,
        created_at=NOW,
    )
    return int(row["id"])


def _conversation(
    storage: AssistantStorage,
    user_id: int,
    *,
    title: str = "Boundary conversation",
    created_at: datetime = NOW,
) -> dict[str, object]:
    return storage.create_conversation(
        user_id,
        title=title,
        context=CONTEXT,
        context_version=CONTEXT_VERSION,
        created_at=created_at,
    )["conversation"]


def _turn(
    storage: AssistantStorage,
    user_id: int,
    conversation_id: str,
    *,
    session_id: str,
    created_at: datetime = NOW,
) -> dict[str, object]:
    return storage.create_turn(
        user_id,
        conversation_id,
        prompt="A disposable assistant storage prompt.",
        model_id="fixture/free-model",
        policy_version="fixture-policy-v1",
        context=CONTEXT,
        context_version=CONTEXT_VERSION,
        session_id=session_id,
        session_token_hash="b" * 64,
        capability="fixture-capability-" + "c" * 40,
        now=created_at,
        expires_at=created_at + timedelta(seconds=120),
    )


def _action(
    storage: AssistantStorage,
    user_id: int,
    conversation_id: str,
    turn: dict[str, object],
    *,
    session_id: str,
    expires_at: datetime = NOW + timedelta(minutes=5),
    action_type: str = "theme.set",
    payload: dict[str, object] | None = None,
) -> dict[str, object]:
    return storage.create_action(
        user_id,
        conversation_id,
        str(turn["id"]),
        action_type=action_type,
        payload=payload or {"theme": "dark"},
        action_version=1,
        session_id=session_id,
        context_version=CONTEXT_VERSION,
        execution_id=str(turn["execution_id"]),
        confirmation_phrase="ignored by the storage-generated confirmation",
        now=NOW,
        expires_at=expires_at,
    )


def test_conversation_listing_rename_and_delete_stay_owner_scoped(settings):
    repository, storage = _repository(settings)
    owner_id = _owner(repository, 88101)
    other_id = _owner(repository, 88102)
    conversations = [
        _conversation(
            storage,
            owner_id,
            title=f"Owner conversation {index}",
            created_at=NOW + timedelta(seconds=index),
        )
        for index in range(1, 4)
    ]
    other_conversation = _conversation(storage, other_id, title="Other owner's record")

    first_page = storage.list_conversations(owner_id, page=1, page_size=2)
    second_page = storage.list_conversations(owner_id, page=2, page_size=2)
    assert first_page["total"] == 3
    assert second_page["total"] == 3
    assert [item["id"] for item in first_page["items"]] == [
        conversations[2]["id"],
        conversations[1]["id"],
    ]
    assert [item["id"] for item in second_page["items"]] == [conversations[0]["id"]]
    assert (
        storage.list_conversations(other_id, page=1, page_size=2)["items"][0]["id"]
        == (other_conversation["id"])
    )
    with pytest.raises(ValueError):
        storage.list_conversations(owner_id, page=0, page_size=2)

    target_id = str(conversations[0]["id"])
    turn = _turn(
        storage,
        owner_id,
        target_id,
        session_id="owner-session-0001",
        created_at=NOW + timedelta(seconds=2),
    )
    assert storage.get_turn(owner_id, target_id, str(turn["id"]))["status"] == "queued"
    with pytest.raises(AssistantStorageNotFound):
        storage.get_conversation(other_id, target_id)
    with pytest.raises(AssistantStorageNotFound):
        storage.rename_conversation(
            other_id,
            target_id,
            title="Cross-owner rename",
            expected_revision=2,
            updated_at=NOW + timedelta(seconds=5),
        )

    renamed = storage.rename_conversation(
        owner_id,
        target_id,
        title="  Renamed by owner  ",
        expected_revision=2,
        updated_at=NOW + timedelta(seconds=5),
    )
    assert renamed["conversation"]["title"] == "Renamed by owner"
    assert renamed["conversation"]["revision"] == 3
    with pytest.raises(AssistantStorageConflict, match="conversation_revision"):
        storage.rename_conversation(
            owner_id,
            target_id,
            title="Stale rename",
            expected_revision=2,
            updated_at=NOW + timedelta(seconds=6),
        )

    phrase = str(renamed["conversation"]["delete_confirmation_phrase"])
    with pytest.raises(AssistantStorageConflict, match="delete_confirmation"):
        storage.delete_conversation(
            owner_id,
            target_id,
            expected_revision=3,
            confirmation_phrase="wrong phrase",
            deleted_at=NOW + timedelta(seconds=7),
        )
    with pytest.raises(AssistantStorageConflict, match="conversation_revision"):
        storage.delete_conversation(
            owner_id,
            target_id,
            expected_revision=2,
            confirmation_phrase=phrase,
            deleted_at=NOW + timedelta(seconds=7),
        )
    with pytest.raises(AssistantStorageNotFound):
        storage.validate_conversation_delete(
            other_id,
            target_id,
            expected_revision=3,
            confirmation_phrase=phrase,
        )

    storage.validate_conversation_delete(
        owner_id,
        target_id,
        expected_revision=3,
        confirmation_phrase=phrase,
    )
    deleted = storage.delete_conversation(
        owner_id,
        target_id,
        expected_revision=3,
        confirmation_phrase=phrase,
        deleted_at=NOW + timedelta(seconds=7),
    )
    assert deleted["canonical_content_removed"] is True
    assert len(str(deleted["content_digest"])) == 64
    with pytest.raises(AssistantStorageNotFound):
        storage.get_conversation(owner_id, target_id)
    remaining_owner_ids = {
        item["id"] for item in storage.list_conversations(owner_id, page=1, page_size=50)["items"]
    }
    assert remaining_owner_ids == {conversations[1]["id"], conversations[2]["id"]}
    assert (
        storage.get_conversation(other_id, str(other_conversation["id"]))["conversation"]["title"]
        == "Other owner's record"
    )

    with repository.connect() as connection:
        tombstone = connection.execute(
            "SELECT user_id, content_digest, deleted_bytes FROM assistant_conversation_deletions "
            "WHERE conversation_id = ?",
            (target_id,),
        ).fetchone()
        assert tombstone is not None
        assert int(tombstone["user_id"]) == owner_id
        assert str(tombstone["content_digest"]) == deleted["content_digest"]
        assert int(tombstone["deleted_bytes"]) > 0
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM assistant_messages WHERE conversation_id = ?", (target_id,)
            ).fetchone()[0]
            == 0
        )


def test_terminal_receipts_revalidate_persisted_browser_action_destinations(settings):
    repository, storage = _repository(settings)
    owner_id = _owner(repository, 88103)
    other_id = _owner(repository, 88104)
    conversation = _conversation(storage, owner_id)
    conversation_id = str(conversation["id"])
    turn = _turn(storage, owner_id, conversation_id, session_id="owner-session-0003")

    unsafe = _action(
        storage,
        owner_id,
        conversation_id,
        turn,
        session_id="owner-session-0003",
        payload={"theme": "dark"},
    )
    storage.claim_action(
        owner_id,
        str(unsafe["id"]),
        action_version=1,
        confirmation_phrase=str(unsafe["confirmation_phrase"]),
        session_id="owner-session-0003",
        context_version=CONTEXT_VERSION,
        now=NOW,
    )
    storage.finish_action(
        owner_id,
        str(unsafe["id"]),
        outcome="applied",
        result={
            "message": "A saved browser receipt.",
            "destination": "https://untrusted.invalid/private",
            "browser_action": {
                "type": "filters.apply",
                "payload": {
                    "query": "ACDC",
                    "symbol": "ACDC",
                    "asset_type": "stock",
                    "status": "successful",
                },
                "destination": {
                    "kind": "current-page",
                    "route": "//untrusted.invalid/",
                    "focus": "history-heading",
                },
            },
        },
        now=NOW + timedelta(seconds=1),
    )

    notes_payload = {
        "symbol": "ACDC",
        "asset_type": "stock",
        "provider": "Fixture Markets",
        "exchange": "NASDAQ",
    }
    extra_destination = _action(
        storage,
        owner_id,
        conversation_id,
        turn,
        session_id="owner-session-0003",
        action_type="notes.set",
        payload=notes_payload,
    )
    storage.claim_action(
        owner_id,
        str(extra_destination["id"]),
        action_version=1,
        confirmation_phrase=str(extra_destination["confirmation_phrase"]),
        session_id="owner-session-0003",
        context_version=CONTEXT_VERSION,
        now=NOW + timedelta(seconds=2),
    )
    storage.finish_action(
        owner_id,
        str(extra_destination["id"]),
        outcome="applied",
        result={
            "message": "An unknown destination field must be rejected.",
            "browser_action": {
                "type": "notes.set",
                "payload": notes_payload,
                "destination": {
                    "kind": "current-page",
                    "route": "/tools/live-trading",
                    "focus": "notes-heading",
                    "untrusted_extra": "discard this field",
                },
            },
        },
        now=NOW + timedelta(seconds=3),
    )

    safe = _action(
        storage,
        owner_id,
        conversation_id,
        turn,
        session_id="owner-session-0003",
        action_type="notes.set",
        payload=notes_payload,
    )
    storage.claim_action(
        owner_id,
        str(safe["id"]),
        action_version=1,
        confirmation_phrase=str(safe["confirmation_phrase"]),
        session_id="owner-session-0003",
        context_version=CONTEXT_VERSION,
        now=NOW + timedelta(seconds=4),
    )
    storage.finish_action(
        owner_id,
        str(safe["id"]),
        outcome="applied",
        result={
            "message": "The note was saved.",
            "browser_action": {
                "type": "notes.set",
                "payload": notes_payload,
                "destination": {
                    "kind": "current-page",
                    "route": "/tools/live-trading",
                    "focus": "notes-heading",
                },
            },
        },
        now=NOW + timedelta(seconds=5),
    )

    detail = storage.get_conversation(owner_id, conversation_id)
    receipts = {str(action["action_id"]): action["receipt"] for action in detail["actions"]}
    unsafe_receipt = receipts[str(unsafe["id"])]
    assert unsafe_receipt["message"] == "A saved browser receipt."
    assert "destination" not in unsafe_receipt
    assert "browser_action" not in unsafe_receipt
    malformed_receipt = receipts[str(extra_destination["id"])]
    assert malformed_receipt["message"] == "An unknown destination field must be rejected."
    assert "destination" not in malformed_receipt
    assert "browser_action" not in malformed_receipt
    safe_receipt = receipts[str(safe["id"])]
    assert safe_receipt["browser_action"] == {
        "type": "notes.set",
        "payload": {
            "symbol": "ACDC",
            "asset_type": "stock",
            "provider": "Fixture Markets",
            "exchange": "NASDAQ",
        },
        "destination": {
            "kind": "current-page",
            "route": "/tools/live-trading",
            "focus": "notes-heading",
        },
    }
    assert storage.get_action_receipt(other_id, str(safe["id"])) is None
    assert storage.get_action_receipt(owner_id, str(safe["id"]))["outcome"] == "applied"


def test_action_approval_expiry_and_terminal_transitions_are_durable(settings):
    repository, storage = _repository(settings)
    owner_id = _owner(repository, 88105)
    other_id = _owner(repository, 88106)
    owner_conversation = _conversation(storage, owner_id)
    other_conversation = _conversation(storage, other_id)
    owner_turn = _turn(
        storage,
        owner_id,
        str(owner_conversation["id"]),
        session_id="owner-session-0005",
    )
    other_turn = _turn(
        storage,
        other_id,
        str(other_conversation["id"]),
        session_id="other-session-0006",
    )
    pending = _action(
        storage,
        owner_id,
        str(owner_conversation["id"]),
        owner_turn,
        session_id="owner-session-0005",
    )
    expired = _action(
        storage,
        owner_id,
        str(owner_conversation["id"]),
        owner_turn,
        session_id="owner-session-0005",
        expires_at=NOW,
        payload={"theme": "light"},
    )
    other_action = _action(
        storage,
        other_id,
        str(other_conversation["id"]),
        other_turn,
        session_id="other-session-0006",
    )

    with pytest.raises(AssistantStorageNotFound):
        storage.get_action(other_id, str(pending["id"]))
    with pytest.raises(AssistantStorageNotFound):
        storage.claim_action(
            other_id,
            str(pending["id"]),
            action_version=1,
            confirmation_phrase=str(pending["confirmation_phrase"]),
            session_id="owner-session-0005",
            context_version=CONTEXT_VERSION,
            now=NOW,
        )
    with pytest.raises(AssistantStorageConflict, match="action_context_stale"):
        storage.claim_action(
            owner_id,
            str(pending["id"]),
            action_version=1,
            confirmation_phrase=str(pending["confirmation_phrase"]),
            session_id="different-session-0005",
            context_version=CONTEXT_VERSION,
            now=NOW,
        )
    with pytest.raises(AssistantStorageConflict, match="action_version"):
        storage.claim_action(
            owner_id,
            str(pending["id"]),
            action_version=2,
            confirmation_phrase=str(pending["confirmation_phrase"]),
            session_id="owner-session-0005",
            context_version=CONTEXT_VERSION,
            now=NOW,
        )
    with pytest.raises(AssistantStorageConflict, match="action_confirmation"):
        storage.claim_action(
            owner_id,
            str(pending["id"]),
            action_version=1,
            confirmation_phrase="CONFIRM invalid phrase",
            session_id="owner-session-0005",
            context_version=CONTEXT_VERSION,
            now=NOW,
        )
    with pytest.raises(AssistantStorageConflict, match="action_not_executing"):
        storage.finish_action(
            owner_id,
            str(pending["id"]),
            outcome="applied",
            result={"message": "No dispatch happened."},
            now=NOW,
        )
    assert storage.get_action(owner_id, str(pending["id"]))["status"] == "pending"
    assert storage.get_action_receipt(owner_id, str(pending["id"])) is None

    with pytest.raises(AssistantStorageConflict, match="action_expired"):
        storage.claim_action(
            owner_id,
            str(expired["id"]),
            action_version=1,
            confirmation_phrase=str(expired["confirmation_phrase"]),
            session_id="owner-session-0005",
            context_version=CONTEXT_VERSION,
            now=NOW,
        )
    assert storage.get_action(owner_id, str(expired["id"]))["status"] == "expired"
    assert storage.get_action_receipt(owner_id, str(expired["id"])) is None

    claimed = storage.claim_action(
        owner_id,
        str(pending["id"]),
        action_version=1,
        confirmation_phrase=str(pending["confirmation_phrase"]),
        session_id="owner-session-0005",
        context_version=CONTEXT_VERSION,
        now=NOW,
    )
    assert claimed["payload"] == {"theme": "dark"}
    finalized = storage.finish_action(
        owner_id,
        str(pending["id"]),
        outcome="applied",
        result={"message": "Applied once."},
        now=NOW + timedelta(seconds=1),
    )
    assert finalized["outcome"] == "applied"
    with pytest.raises(AssistantStorageConflict, match="action_replayed"):
        storage.claim_action(
            owner_id,
            str(pending["id"]),
            action_version=1,
            confirmation_phrase=str(pending["confirmation_phrase"]),
            session_id="owner-session-0005",
            context_version=CONTEXT_VERSION,
            now=NOW + timedelta(seconds=2),
        )
    with pytest.raises(AssistantStorageConflict, match="action_not_executing"):
        storage.finish_action(
            owner_id,
            str(pending["id"]),
            outcome="applied",
            result={"message": "Duplicate finalization."},
            now=NOW + timedelta(seconds=2),
        )
    assert storage.get_action_receipt(owner_id, str(pending["id"])) == {
        "id": finalized["id"],
        "action_id": pending["id"],
        "outcome": "applied",
        "created_at": (NOW + timedelta(seconds=1)).isoformat(),
        "result": {"message": "Applied once."},
    }

    with pytest.raises(AssistantStorageConflict, match="action_context_stale"):
        storage.deny_action(
            other_id,
            str(other_action["id"]),
            action_version=1,
            session_id="owner-session-0005",
            context_version=CONTEXT_VERSION,
            now=NOW,
        )
    assert storage.get_action(other_id, str(other_action["id"]))["status"] == "pending"
    denied = storage.deny_action(
        other_id,
        str(other_action["id"]),
        action_version=1,
        session_id="other-session-0006",
        context_version=CONTEXT_VERSION,
        now=NOW,
    )
    assert denied["outcome"] == "denied"
    with pytest.raises(AssistantStorageConflict, match="action_replayed"):
        storage.deny_action(
            other_id,
            str(other_action["id"]),
            action_version=1,
            session_id="other-session-0006",
            context_version=CONTEXT_VERSION,
            now=NOW + timedelta(seconds=1),
        )
    assert storage.get_action(owner_id, str(pending["id"]))["status"] == "applied"
    assert storage.get_action_receipt(other_id, str(other_action["id"]))["outcome"] == "denied"
    assert storage.get_action_receipt(owner_id, str(other_action["id"])) is None


def test_search_approval_rejects_other_owner_stale_and_expired_previews(settings):
    repository, storage = _repository(settings)
    owner_id = _owner(repository, 88107)
    other_id = _owner(repository, 88108)
    owner_conversation = _conversation(storage, owner_id)
    other_conversation = _conversation(storage, other_id)
    owner_turn = _turn(
        storage,
        owner_id,
        str(owner_conversation["id"]),
        session_id="owner-session-0007",
    )
    other_turn = _turn(
        storage,
        other_id,
        str(other_conversation["id"]),
        session_id="other-session-0008",
    )
    approved = storage.create_search_preview(
        owner_id,
        str(owner_conversation["id"]),
        str(owner_turn["id"]),
        str(owner_turn["execution_id"]),
        query_text="bounded search query for owner one",
        context_version=CONTEXT_VERSION,
        confirmation_phrase="ignored by storage-generated confirmation",
        now=NOW,
        expires_at=NOW + timedelta(seconds=30),
    )
    expired = storage.create_search_preview(
        owner_id,
        str(owner_conversation["id"]),
        str(owner_turn["id"]),
        str(owner_turn["execution_id"]),
        query_text="expired disposable query",
        context_version=CONTEXT_VERSION,
        confirmation_phrase="ignored by storage-generated confirmation",
        now=NOW,
        expires_at=NOW,
    )
    denied = storage.create_search_preview(
        other_id,
        str(other_conversation["id"]),
        str(other_turn["id"]),
        str(other_turn["execution_id"]),
        query_text="owner two private query",
        context_version=CONTEXT_VERSION,
        confirmation_phrase="ignored by storage-generated confirmation",
        now=NOW,
        expires_at=NOW + timedelta(seconds=30),
    )

    with pytest.raises(AssistantStorageNotFound):
        storage.get_search_preview(
            other_id,
            str(owner_conversation["id"]),
            str(owner_turn["id"]),
            str(approved["id"]),
        )
    with pytest.raises(AssistantStorageNotFound):
        storage.resolve_search_preview(
            other_id,
            str(owner_conversation["id"]),
            str(owner_turn["id"]),
            str(approved["id"]),
            context_version=CONTEXT_VERSION,
            confirmation_phrase=str(approved["confirmation_phrase"]),
            allow=True,
            now=NOW,
        )
    with pytest.raises(AssistantStorageConflict, match="search_context_stale"):
        storage.resolve_search_preview(
            owner_id,
            str(owner_conversation["id"]),
            str(owner_turn["id"]),
            str(approved["id"]),
            context_version="d" * 64,
            confirmation_phrase=str(approved["confirmation_phrase"]),
            allow=True,
            now=NOW,
        )
    with pytest.raises(AssistantStorageConflict, match="search_preview_confirmation"):
        storage.resolve_search_preview(
            owner_id,
            str(owner_conversation["id"]),
            str(owner_turn["id"]),
            str(approved["id"]),
            context_version=CONTEXT_VERSION,
            confirmation_phrase="SEARCH invalid phrase",
            allow=True,
            now=NOW,
        )
    assert (
        storage.get_search_preview(
            owner_id,
            str(owner_conversation["id"]),
            str(owner_turn["id"]),
            str(approved["id"]),
        )["status"]
        == "pending"
    )

    allowed = storage.resolve_search_preview(
        owner_id,
        str(owner_conversation["id"]),
        str(owner_turn["id"]),
        str(approved["id"]),
        context_version=CONTEXT_VERSION,
        confirmation_phrase=str(approved["confirmation_phrase"]),
        allow=True,
        now=NOW,
    )
    assert allowed["status"] == "approved"
    assert allowed["query_text"] == "bounded search query for owner one"
    with pytest.raises(AssistantStorageConflict, match="search_preview_replayed"):
        storage.resolve_search_preview(
            owner_id,
            str(owner_conversation["id"]),
            str(owner_turn["id"]),
            str(approved["id"]),
            context_version=CONTEXT_VERSION,
            confirmation_phrase=str(approved["confirmation_phrase"]),
            allow=True,
            now=NOW + timedelta(seconds=1),
        )

    with pytest.raises(AssistantStorageConflict, match="search_preview_expired"):
        storage.resolve_search_preview(
            owner_id,
            str(owner_conversation["id"]),
            str(owner_turn["id"]),
            str(expired["id"]),
            context_version=CONTEXT_VERSION,
            confirmation_phrase=str(expired["confirmation_phrase"]),
            allow=True,
            now=NOW,
        )
    assert (
        storage.get_search_preview(
            owner_id,
            str(owner_conversation["id"]),
            str(owner_turn["id"]),
            str(expired["id"]),
        )["status"]
        == "expired"
    )

    rejected = storage.resolve_search_preview(
        other_id,
        str(other_conversation["id"]),
        str(other_turn["id"]),
        str(denied["id"]),
        context_version=CONTEXT_VERSION,
        confirmation_phrase="no phrase required for an explicit denial",
        allow=False,
        now=NOW,
    )
    assert rejected["status"] == "denied"
    assert (
        storage.get_search_preview(
            other_id,
            str(other_conversation["id"]),
            str(other_turn["id"]),
            str(denied["id"]),
        )["status"]
        == "denied"
    )
    with pytest.raises(AssistantStorageConflict, match="search_preview_replayed"):
        storage.resolve_search_preview(
            other_id,
            str(other_conversation["id"]),
            str(other_turn["id"]),
            str(denied["id"]),
            context_version=CONTEXT_VERSION,
            confirmation_phrase="no phrase required for an explicit denial",
            allow=False,
            now=NOW + timedelta(seconds=1),
        )
    with pytest.raises(AssistantStorageNotFound):
        storage.get_search_preview(
            owner_id,
            str(other_conversation["id"]),
            str(other_turn["id"]),
            str(denied["id"]),
        )


def test_restart_reconciles_only_executing_receipts_once(settings):
    repository, storage = _repository(settings)
    first_owner = _owner(repository, 88109)
    second_owner = _owner(repository, 88110)
    first_conversation = _conversation(storage, first_owner, title="Restart owner one")
    second_conversation = _conversation(storage, second_owner, title="Restart owner two")
    first_turn = _turn(
        storage,
        first_owner,
        str(first_conversation["id"]),
        session_id="restart-session-0009",
    )
    second_turn = _turn(
        storage,
        second_owner,
        str(second_conversation["id"]),
        session_id="restart-session-0010",
    )
    interrupted = _action(
        storage,
        first_owner,
        str(first_conversation["id"]),
        first_turn,
        session_id="restart-session-0009",
    )
    finalized = _action(
        storage,
        second_owner,
        str(second_conversation["id"]),
        second_turn,
        session_id="restart-session-0010",
    )
    for user_id, session_id, action in (
        (first_owner, "restart-session-0009", interrupted),
        (second_owner, "restart-session-0010", finalized),
    ):
        storage.claim_action(
            user_id,
            str(action["id"]),
            action_version=1,
            confirmation_phrase=str(action["confirmation_phrase"]),
            session_id=session_id,
            context_version=CONTEXT_VERSION,
            now=NOW,
        )
    committed = storage.finish_action(
        second_owner,
        str(finalized["id"]),
        outcome="applied",
        result={"message": "Durable before restart."},
        now=NOW + timedelta(seconds=1),
    )

    restarted_repository = Repository(repository.database_path)
    restarted_storage = AssistantStorage(restarted_repository)
    restarted = restarted_storage.interrupt_active_turns(now=NOW + timedelta(seconds=2))
    assert {int(item["user_id"]) for item in restarted} == {first_owner, second_owner}
    assert (
        restarted_storage.get_turn(
            first_owner, str(first_conversation["id"]), str(first_turn["id"])
        )["error_code"]
        == "runtime_restarted"
    )
    assert (
        restarted_storage.get_turn(
            second_owner, str(second_conversation["id"]), str(second_turn["id"])
        )["status"]
        == "failed"
    )
    assert restarted_storage.reconcile_interrupted_actions(now=NOW + timedelta(seconds=2)) == 1
    assert restarted_storage.reconcile_interrupted_actions(now=NOW + timedelta(seconds=3)) == 0
    assert restarted_storage.get_action(first_owner, str(interrupted["id"]))["status"] == "unknown"
    assert (
        restarted_storage.get_action_receipt(first_owner, str(interrupted["id"]))["outcome"]
        == "unknown"
    )
    assert restarted_storage.get_action(second_owner, str(finalized["id"]))["status"] == "applied"
    assert restarted_storage.get_action_receipt(second_owner, str(finalized["id"])) == {
        "id": committed["id"],
        "action_id": finalized["id"],
        "outcome": "applied",
        "created_at": (NOW + timedelta(seconds=1)).isoformat(),
        "result": {"message": "Durable before restart."},
    }
    with pytest.raises(AssistantStorageConflict, match="action_replayed"):
        restarted_storage.claim_action(
            first_owner,
            str(interrupted["id"]),
            action_version=1,
            confirmation_phrase=str(interrupted["confirmation_phrase"]),
            session_id="restart-session-0009",
            context_version=CONTEXT_VERSION,
            now=NOW + timedelta(seconds=4),
        )
    with restarted_repository.connect() as connection:
        counts = connection.execute(
            "SELECT outcome, COUNT(*) AS count FROM assistant_action_receipts "
            "GROUP BY outcome ORDER BY outcome"
        ).fetchall()
    assert {str(row["outcome"]): int(row["count"]) for row in counts} == {
        "applied": 1,
        "unknown": 1,
    }


def test_public_conversation_writes_fail_closed_at_owner_global_and_database_quotas(
    settings, monkeypatch
):
    from stock_probs.assistant import storage as storage_module

    repository, storage = _repository(settings)
    owner_id = _owner(repository, 88111)
    other_id = _owner(repository, 88112)
    existing = _conversation(storage, owner_id, title="Existing owner record")
    original_user_limit = storage_module.ASSISTANT_USER_HISTORY_LIMIT
    original_global_limit = storage_module.ASSISTANT_GLOBAL_HISTORY_LIMIT

    owner_usage = storage.usage(owner_id)
    monkeypatch.setattr(
        storage_module,
        "ASSISTANT_USER_HISTORY_LIMIT",
        owner_usage["user_bytes"] + 1,
    )
    with pytest.raises(AssistantStorageQuotaExceeded) as user_limit:
        _conversation(storage, owner_id, title="Rejected at owner quota")
    assert user_limit.value.scope == "user_history"
    assert storage.get_conversation(owner_id, str(existing["id"]))["conversation"]["title"] == (
        "Existing owner record"
    )
    monkeypatch.setattr(
        storage_module,
        "ASSISTANT_USER_HISTORY_LIMIT",
        original_user_limit,
    )
    other_allowed = _conversation(storage, other_id, title="Other owner still has room")
    assert storage.get_conversation(other_id, str(other_allowed["id"]))["conversation"][
        "title"
    ] == ("Other owner still has room")

    monkeypatch.setattr(
        storage_module,
        "ASSISTANT_USER_HISTORY_LIMIT",
        original_user_limit,
    )
    global_usage = storage.usage(owner_id)
    monkeypatch.setattr(
        storage_module,
        "ASSISTANT_GLOBAL_HISTORY_LIMIT",
        global_usage["global_bytes"] + 1,
    )
    with pytest.raises(AssistantStorageQuotaExceeded) as global_limit:
        _conversation(storage, other_id, title="Rejected at global quota")
    assert global_limit.value.scope == "global_history"
    assert storage.get_conversation(other_id, str(other_allowed["id"]))["conversation"][
        "title"
    ] == ("Other owner still has room")

    monkeypatch.setattr(
        storage_module,
        "ASSISTANT_GLOBAL_HISTORY_LIMIT",
        original_global_limit,
    )
    database_usage = storage.usage(owner_id)
    monkeypatch.setattr(
        storage_module,
        "ASSISTANT_DATABASE_LIMIT",
        database_usage["database_bytes"],
    )
    with pytest.raises(AssistantStorageQuotaExceeded) as database_limit:
        _conversation(storage, other_id, title="Rejected at database quota")
    assert database_limit.value.scope == "database"
    assert storage.list_conversations(other_id, page=1, page_size=50)["total"] == 1
