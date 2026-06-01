from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker, undefer

from grantora.db.models import (
    ACTIVE_STATUS,
    REVOKED_STATUS,
    Agent,
    ApisixRoute,
    ApisixSyncStatus,
    ApplicationInstance,
    AuditEvent,
    Base,
    Binding,
    Capability,
    Permission,
    Role,
    RolePermission,
    Secret,
    UsageEvent,
    User,
    Workspace,
)
from grantora.db.queries import (
    get_active_agent_by_token_hash,
    get_active_application_instance_by_slug,
    get_active_binding,
    get_active_capability_by_id,
    get_active_secret_for_owner,
    get_active_user_by_external_id,
    get_active_workspace_by_id,
    get_active_workspace_by_slug,
    list_active_capabilities_for_agent_user,
    role_grants_permission,
)
from grantora.secrets import SecretCipher


@pytest.fixture()
def session() -> Iterator[Session]:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)

    with session_factory() as database_session:
        yield database_session

    Base.metadata.drop_all(engine)
    engine.dispose()


@dataclass(frozen=True)
class CoreRecords:
    workspace: Workspace
    application: ApplicationInstance
    agent: Agent
    user: User
    capability: Capability
    role: Role
    binding: Binding


def empty_object_schema() -> dict[str, object]:
    return {"type": "object", "additionalProperties": False}


def test_workspace_can_be_created_read_and_filtered_by_active_status(session: Session) -> None:
    active_workspace = Workspace(slug="acme", display_name="Acme SRL")
    disabled_workspace = Workspace(
        slug="disabled-acme",
        display_name="Disabled Acme",
        status="disabled",
    )

    session.add_all([active_workspace, disabled_workspace])
    session.commit()

    assert get_active_workspace_by_slug(session, "acme") == active_workspace
    assert get_active_workspace_by_id(session, active_workspace.id) == active_workspace
    assert get_active_workspace_by_slug(session, "disabled-acme") is None


def test_application_instance_lookup_uses_workspace_and_slug(session: Session) -> None:
    records = add_core_records(session)
    other_workspace = Workspace(slug="other", display_name="Other")
    same_slug_elsewhere = ApplicationInstance(
        workspace=other_workspace,
        slug=records.application.slug,
        display_name="Other NethVoice",
        provider_type="nethvoice",
        base_url="https://voice.other.test",
    )
    disabled_application = ApplicationInstance(
        workspace=records.workspace,
        slug="disabled-voice",
        display_name="Disabled Voice",
        provider_type="nethvoice",
        status="disabled",
    )
    session.add_all([other_workspace, same_slug_elsewhere, disabled_application])
    session.commit()

    assert (
        get_active_application_instance_by_slug(session, records.workspace.id, "nethvoice")
        == records.application
    )
    assert (
        get_active_application_instance_by_slug(session, records.workspace.id, "disabled-voice")
        is None
    )
    assert (
        get_active_application_instance_by_slug(session, other_workspace.id, "nethvoice")
        == same_slug_elsewhere
    )


def test_active_agent_lookup_uses_token_hash_path(session: Session) -> None:
    records = add_core_records(session)
    disabled_agent = Agent(
        workspace=records.workspace,
        slug="disabled-agent",
        display_name="Disabled Agent",
        token_hash="sha256:disabled",
        token_hash_algorithm="sha256",
        status="disabled",
    )
    session.add(disabled_agent)
    session.commit()

    assert get_active_agent_by_token_hash(session, "sha256:agent") == records.agent
    assert get_active_agent_by_token_hash(session, "sha256:disabled") is None


def test_user_lookup_uses_workspace_external_id_and_active_status(session: Session) -> None:
    records = add_core_records(session)
    disabled_user = User(
        workspace=records.workspace,
        external_id="disabled-alice",
        display_name="Disabled Alice",
        status="disabled",
    )
    session.add(disabled_user)
    session.commit()

    assert get_active_user_by_external_id(session, records.workspace.id, "alice") == records.user
    assert get_active_user_by_external_id(session, records.workspace.id, "disabled-alice") is None


def test_active_capability_lookup_uses_id_and_workspace(session: Session) -> None:
    records = add_core_records(session)
    disabled_capability = Capability(
        id="nethvoice.phonebook.disabled",
        workspace=records.workspace,
        application_instance=records.application,
        name="Disabled phonebook",
        provider_type="nethvoice",
        adapter="nethvoice",
        operation="phonebook.disabled",
        auth_mode="user",
        risk_class="read_only",
        input_schema=empty_object_schema(),
        output_schema=empty_object_schema(),
        status="disabled",
    )
    session.add(disabled_capability)
    session.commit()

    assert (
        get_active_capability_by_id(
            session,
            records.workspace.id,
            "nethvoice.phonebook.search",
        )
        == records.capability
    )
    assert (
        get_active_capability_by_id(session, records.workspace.id, disabled_capability.id) is None
    )


def test_capability_listing_uses_active_binding_for_agent_and_user(session: Session) -> None:
    records = add_core_records(session)
    unbound_capability = Capability(
        id="nethvoice.phonebook.unbound",
        workspace=records.workspace,
        application_instance=records.application,
        name="Unbound phonebook",
        provider_type="nethvoice",
        adapter="nethvoice",
        operation="phonebook.unbound",
        auth_mode="user",
        risk_class="read_only",
        input_schema=empty_object_schema(),
        output_schema=empty_object_schema(),
    )
    disabled_capability = Capability(
        id="nethvoice.phonebook.disabled",
        workspace=records.workspace,
        application_instance=records.application,
        name="Disabled phonebook",
        provider_type="nethvoice",
        adapter="nethvoice",
        operation="phonebook.disabled",
        auth_mode="user",
        risk_class="read_only",
        input_schema=empty_object_schema(),
        output_schema=empty_object_schema(),
        status="disabled",
    )
    disabled_binding = Binding(
        workspace=records.workspace,
        agent=records.agent,
        user=records.user,
        capability=disabled_capability,
        role=records.role,
    )
    session.add_all([unbound_capability, disabled_capability, disabled_binding])
    session.commit()

    capabilities = list_active_capabilities_for_agent_user(
        session,
        records.workspace.id,
        records.agent.id,
        records.user.id,
    )

    assert capabilities == [records.capability]


def test_role_permission_lookup_grants_expected_runtime_permission(session: Session) -> None:
    records = add_core_records(session)

    assert role_grants_permission(session, records.role.id, "capability.invoke.read_only") is True
    assert (
        role_grants_permission(session, records.role.id, "capability.invoke.destructive") is False
    )


def test_binding_lookup_uses_workspace_agent_user_capability_and_status(session: Session) -> None:
    records = add_core_records(session)
    disabled_binding = Binding(
        workspace=records.workspace,
        agent=records.agent,
        user=records.user,
        capability=records.capability,
        role=records.role,
        status="disabled",
    )
    session.add(disabled_binding)
    session.commit()

    assert (
        get_active_binding(
            session,
            records.workspace.id,
            records.agent.id,
            records.user.id,
            records.capability.id,
        )
        == records.binding
    )
    assert (
        get_active_binding(
            session, records.workspace.id, records.agent.id, records.user.id, "missing"
        )
        is None
    )


def test_secret_value_is_encrypted_and_deferred_from_default_queries(session: Session) -> None:
    records = add_core_records(session)
    cipher = SecretCipher(SecretCipher.generate_key())
    plaintext = "nethvoice-token"
    encrypted_value = cipher.encrypt(plaintext)
    secret = Secret(
        workspace=records.workspace,
        application_instance=records.application,
        owner_type="user",
        owner_id=records.user.id,
        secret_type="bearer_token",
        encrypted_value=encrypted_value,
        status=ACTIVE_STATUS,
    )
    revoked_secret = Secret(
        workspace=records.workspace,
        application_instance=records.application,
        owner_type="agent",
        owner_id=records.agent.id,
        secret_type="api_key",
        encrypted_value=cipher.encrypt("revoked-token"),
        status=REVOKED_STATUS,
    )
    session.add_all([secret, revoked_secret])
    session.commit()

    secret_id = secret.id
    session.expunge_all()

    loaded_secret = session.scalar(select(Secret).where(Secret.id == secret_id))

    assert loaded_secret is not None
    assert "encrypted_value" not in loaded_secret.__dict__
    assert encrypted_value != plaintext

    session.expunge_all()
    loaded_with_value = session.scalar(
        select(Secret).options(undefer(Secret.encrypted_value)).where(Secret.id == secret_id)
    )

    assert loaded_with_value is not None
    assert loaded_with_value.encrypted_value == encrypted_value
    assert cipher.decrypt(loaded_with_value.encrypted_value) == plaintext

    active_secret = get_active_secret_for_owner(
        session,
        records.workspace.id,
        records.application.id,
        "user",
        records.user.id,
    )

    assert active_secret == loaded_with_value
    assert active_secret.encrypted_value == encrypted_value
    assert (
        get_active_secret_for_owner(
            session,
            records.workspace.id,
            records.application.id,
            "agent",
            records.agent.id,
        )
        is None
    )


def test_audit_and_usage_events_can_record_decisions_and_statuses(session: Session) -> None:
    records = add_core_records(session)
    session.add_all(
        [
            AuditEvent(
                request_id="req_denied",
                workspace=records.workspace,
                agent=records.agent,
                user=records.user,
                capability_id=records.capability.id,
                application_instance=records.application,
                decision="deny",
                outcome="error",
                error_code="capability_denied",
                latency_ms=4,
                remote_addr="127.0.0.1",
            ),
            AuditEvent(
                request_id="req_success",
                workspace=records.workspace,
                agent=records.agent,
                user=records.user,
                capability_id=records.capability.id,
                application_instance=records.application,
                decision="allow",
                outcome="success",
                latency_ms=9,
            ),
            UsageEvent(
                workspace=records.workspace,
                agent=records.agent,
                user=records.user,
                capability_id=records.capability.id,
                application_instance=records.application,
                status="success",
                latency_ms=9,
            ),
            UsageEvent(
                workspace=records.workspace,
                agent=records.agent,
                user=records.user,
                capability_id=records.capability.id,
                status="denied",
                latency_ms=4,
            ),
            UsageEvent(
                workspace=records.workspace,
                agent=records.agent,
                user=records.user,
                capability_id=records.capability.id,
                status="error",
                latency_ms=12,
            ),
        ]
    )
    session.commit()

    audit_decisions = set(session.scalars(select(AuditEvent.decision)).all())
    usage_statuses = set(session.scalars(select(UsageEvent.status)).all())

    assert audit_decisions == {"allow", "deny"}
    assert usage_statuses == {"success", "denied", "error"}


def test_apisix_route_definition_and_sync_status_round_trip(session: Session) -> None:
    route = ApisixRoute(
        id="gateway-runtime",
        name="Grantora runtime API",
        uri="/v1/*",
        upstream={"type": "roundrobin", "nodes": {"grantora-api:8080": 1}},
        plugins={
            "prometheus": {},
            "request-id": {},
            "limit-count": {"count": 1000, "time_window": 60, "rejected_code": 429},
        },
    )
    sync_status = ApisixSyncStatus(
        id="default",
        status="ok",
        checked_routes=1,
        changed_routes=1,
    )
    session.add_all([route, sync_status])
    session.commit()
    session.expunge_all()

    loaded_route = session.get(ApisixRoute, "gateway-runtime")
    loaded_status = session.get(ApisixSyncStatus, "default")

    assert loaded_route is not None
    assert loaded_route.uri == "/v1/*"
    assert loaded_route.upstream == {"type": "roundrobin", "nodes": {"grantora-api:8080": 1}}
    assert loaded_route.plugins["limit-count"] == {
        "count": 1000,
        "time_window": 60,
        "rejected_code": 429,
    }
    assert loaded_status is not None
    assert loaded_status.status == "ok"
    assert loaded_status.checked_routes == 1
    assert loaded_status.changed_routes == 1


def test_model_constraints_reject_duplicate_and_invalid_records(session: Session) -> None:
    records = add_core_records(session)
    cipher = SecretCipher(SecretCipher.generate_key())
    secret = Secret(
        workspace=records.workspace,
        application_instance=records.application,
        owner_type="user",
        owner_id=records.user.id,
        secret_type="bearer_token",
        encrypted_value=cipher.encrypt("active-token"),
    )
    session.add(secret)
    session.commit()

    expect_integrity_error(
        session,
        Workspace(slug=records.workspace.slug, display_name="Duplicate workspace"),
    )
    expect_integrity_error(
        session,
        ApplicationInstance(
            workspace=records.workspace,
            slug=records.application.slug,
            display_name="Duplicate application",
            provider_type="nethvoice",
        ),
    )
    expect_integrity_error(
        session,
        User(
            workspace=records.workspace,
            external_id=records.user.external_id,
            display_name="Duplicate Alice",
        ),
    )
    expect_integrity_error(
        session,
        Role(
            workspace=records.workspace,
            slug=records.role.slug,
            display_name="Duplicate reader",
        ),
    )
    expect_integrity_error(
        session,
        Binding(
            workspace=records.workspace,
            agent=records.agent,
            user=records.user,
            capability=records.capability,
            role=records.role,
        ),
    )
    expect_integrity_error(
        session,
        Secret(
            workspace=records.workspace,
            application_instance=records.application,
            owner_type="user",
            owner_id=records.user.id,
            secret_type="api_key",
            encrypted_value=cipher.encrypt("second-active-token"),
        ),
    )
    expect_integrity_error(
        session,
        Workspace(slug="invalid-status", display_name="Invalid", status="archived"),
    )


def test_capability_schema_defaults_and_validation(session: Session) -> None:
    records = add_core_records(session)
    defaulted_capability = Capability(
        id="nethvoice.phonebook.defaulted",
        workspace=records.workspace,
        application_instance=records.application,
        name="Default schema capability",
        provider_type="nethvoice",
        adapter="nethvoice",
        operation="phonebook.defaulted",
        auth_mode="user",
        risk_class="read_only",
    )
    session.add(defaulted_capability)
    session.commit()

    assert defaulted_capability.input_schema == empty_object_schema()
    assert defaulted_capability.output_schema == empty_object_schema()

    with pytest.raises(ValueError):
        Capability(
            id="nethvoice.phonebook.invalid_schema",
            workspace=records.workspace,
            application_instance=records.application,
            name="Invalid schema capability",
            provider_type="nethvoice",
            adapter="nethvoice",
            operation="phonebook.invalid_schema",
            auth_mode="user",
            risk_class="read_only",
            input_schema={"type": "object"},
            output_schema=empty_object_schema(),
        )


def test_model_timestamps_are_utc_aware(session: Session) -> None:
    records = add_core_records(session)
    workspace_id = records.workspace.id
    session.expunge_all()

    loaded_workspace = session.get(Workspace, workspace_id)

    assert loaded_workspace is not None
    assert loaded_workspace.created_at.tzinfo is not None
    assert loaded_workspace.updated_at.tzinfo is not None
    assert loaded_workspace.created_at.utcoffset() == UTC.utcoffset(None)
    assert loaded_workspace.updated_at.utcoffset() == UTC.utcoffset(None)


def add_core_records(session: Session) -> CoreRecords:
    workspace = Workspace(slug="acme", display_name="Acme SRL")
    application = ApplicationInstance(
        workspace=workspace,
        slug="nethvoice",
        display_name="NethVoice",
        provider_type="nethvoice",
        base_url="https://voice.example.test",
    )
    agent = Agent(
        workspace=workspace,
        slug="hermes-alice",
        display_name="Hermes Alice",
        token_hash="sha256:agent",
        token_hash_algorithm="sha256",
    )
    user = User(workspace=workspace, external_id="alice", display_name="Alice")
    capability = Capability(
        id="nethvoice.phonebook.search",
        workspace=workspace,
        application_instance=application,
        name="Search phonebook",
        provider_type="nethvoice",
        adapter="nethvoice",
        operation="phonebook.search",
        auth_mode="user",
        risk_class="read_only",
        input_schema={
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {"contacts": {"type": "array"}},
            "additionalProperties": False,
        },
    )
    role = Role(workspace=workspace, slug="phonebook-reader", display_name="Phonebook reader")
    permission = Permission(
        code="capability.invoke.read_only",
        description="Invoke read-only capabilities",
    )
    role_permission = RolePermission(role=role, permission=permission)
    binding = Binding(
        workspace=workspace,
        agent=agent,
        user=user,
        capability=capability,
        role=role,
    )
    session.add_all(
        [
            workspace,
            application,
            agent,
            user,
            capability,
            role,
            permission,
            role_permission,
            binding,
        ]
    )
    session.commit()
    return CoreRecords(
        workspace=workspace,
        application=application,
        agent=agent,
        user=user,
        capability=capability,
        role=role,
        binding=binding,
    )


def expect_integrity_error(session: Session, record: object) -> None:
    session.add(record)
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()
