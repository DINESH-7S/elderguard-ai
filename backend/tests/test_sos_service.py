"""Unit tests for the SOS escalation policy and event lifecycle.

They run entirely against the in-memory fallback store: no database, no network.
"""
import pytest
from fastapi import HTTPException

from app.emergency import service
from app.emergency.models import SOSStatus

CAREGIVER = {"user_id": "cg-1", "role": "caregiver"}


@pytest.fixture(autouse=True)
def isolated_store(monkeypatch):
    monkeypatch.setattr(service, "supabase", None)
    monkeypatch.setattr(service, "local_engine", None)
    monkeypatch.setattr(service, "broadcast_notification", lambda *a, **k: None)
    monkeypatch.setattr(service, "SOS_DEMO_SECONDS", 0)
    for store in (service._mock_sos_events_db, service._mock_elder_profiles):
        store.clear()
    service._mock_sos_logs_db.clear()
    service._mock_elder_caregiver_links.clear()


def test_default_policy_matches_documented_timings():
    tiers = service.get_escalation_policy("elder-1")
    assert [(t.recipient_type.value, t.timeout_minutes) for t in tiers] == [
        ("caregiver", 0),
        ("secondary_caregiver", 2),
        ("hospital", 5),
        ("emergency_services", 10),
    ]


def test_demo_mode_compresses_tier_delays(monkeypatch):
    monkeypatch.setattr(service, "SOS_DEMO_SECONDS", 15)
    raw = service._get_tiers_for_elder("elder-1")
    assert [t["delay_seconds"] for t in raw] == [0, 15, 30, 45]


def test_trigger_creates_active_event_at_tier_one():
    event = service.trigger_sos("elder-1", location_lat=10.9, location_lng=78.7)
    assert event.status == SOSStatus.ACTIVE
    assert event.current_escalation_tier == 1
    assert event.elder_id == "elder-1"


def test_second_trigger_returns_the_existing_event():
    first = service.trigger_sos("elder-1")
    second = service.trigger_sos("elder-1")
    assert second.id == first.id
    assert len(service._mock_sos_events_db) == 1


def test_events_for_different_elders_are_independent():
    a = service.trigger_sos("elder-1")
    b = service.trigger_sos("elder-2")
    assert a.id != b.id


def test_acknowledge_then_resolve():
    event = service.trigger_sos("elder-1")
    acked = service.acknowledge_sos(event.id, CAREGIVER)
    assert acked.status == SOSStatus.ACKNOWLEDGED
    done = service.resolve_sos(event.id, CAREGIVER, resolution_note="Checked in by phone")
    assert done.status == SOSStatus.RESOLVED
    assert done.resolution_note == "Checked in by phone"


def test_resolve_is_idempotent():
    event = service.trigger_sos("elder-1")
    service.resolve_sos(event.id, CAREGIVER)
    again = service.resolve_sos(event.id, CAREGIVER)
    assert again.status == SOSStatus.RESOLVED


def test_cannot_acknowledge_a_resolved_event():
    event = service.trigger_sos("elder-1")
    service.resolve_sos(event.id, CAREGIVER)
    with pytest.raises(HTTPException) as exc:
        service.acknowledge_sos(event.id, CAREGIVER)
    assert exc.value.status_code == 400


def test_unknown_event_is_404():
    with pytest.raises(HTTPException) as exc:
        service.acknowledge_sos("missing", CAREGIVER)
    assert exc.value.status_code == 404


def test_new_sos_allowed_after_previous_is_resolved():
    first = service.trigger_sos("elder-1")
    service.resolve_sos(first.id, CAREGIVER)
    second = service.trigger_sos("elder-1")
    assert second.id != first.id
