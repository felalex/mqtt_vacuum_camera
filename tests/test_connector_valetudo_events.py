"""Tests for Valetudo event dismiss propagation in ValetudoConnector."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.mqtt_vacuum_camera.utils.connection.connector import (
    ValetudoConnector,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_connector():
    """Build a ValetudoConnector with minimal mocks."""
    hass = MagicMock()
    hass.async_create_task = MagicMock()

    shared = MagicMock()
    shared.file_name = "test_vacuum"
    shared.camera_mode = MagicMock()

    with patch(
        "custom_components.mqtt_vacuum_camera.utils.connection.connector.RoomStore"
    ):
        connector = ValetudoConnector(
            mqtt_topic="valetudo/TestRobot",
            hass=hass,
            camera_shared=shared,
        )

    return connector


def _make_error_event(event_id, processed=False, message="Test error"):
    return {
        "__class": "ErrorStateValetudoEvent",
        "id": event_id,
        "timestamp": "2026-01-01T00:00:00.000Z",
        "processed": processed,
        "message": message,
        "metaData": {},
    }


def _make_consumable_event(event_id, processed=False):
    return {
        "__class": "ConsumableDepletedValetudoEvent",
        "id": event_id,
        "timestamp": "2026-01-01T00:00:00.000Z",
        "processed": processed,
        "type": "cleaning",
        "subType": "wheel",
        "metaData": {},
    }


# ---------------------------------------------------------------------------
# _hypfer_handle_valetudo_events
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_creates_notification_for_unprocessed_error():
    """An unprocessed ErrorStateValetudoEvent creates a persistent notification."""
    connector = _make_connector()
    events = {"evt-1": _make_error_event("evt-1", processed=False, message="Mop pad failure")}

    with patch(
        "custom_components.mqtt_vacuum_camera.utils.connection.connector.persistent_notification"
    ) as mock_pn, patch(
        "custom_components.mqtt_vacuum_camera.utils.connection.connector.async_track_state_change_event"
    ) as mock_track:
        mock_track.return_value = MagicMock()
        await connector._hypfer_handle_valetudo_events(events)

    mock_pn.async_create.assert_called_once()
    call_kwargs = mock_pn.async_create.call_args
    assert call_kwargs[1]["notification_id"] == "valetudo_error_evt-1"
    assert "Mop pad failure" in call_kwargs[1]["message"]


@pytest.mark.asyncio
async def test_dismisses_ha_notification_when_event_becomes_processed():
    """When Valetudo marks an event processed, the HA notification is dismissed."""
    connector = _make_connector()
    events = {"evt-1": _make_error_event("evt-1", processed=True)}

    with patch(
        "custom_components.mqtt_vacuum_camera.utils.connection.connector.persistent_notification"
    ) as mock_pn:
        await connector._hypfer_handle_valetudo_events(events)

    mock_pn.async_dismiss.assert_called_once_with(
        connector.connector_data.hass,
        notification_id="valetudo_error_evt-1",
    )
    mock_pn.async_create.assert_not_called()


@pytest.mark.asyncio
async def test_ignores_non_error_classes():
    """Non-error event classes that aren't handled don't create notifications."""
    connector = _make_connector()
    events = {"evt-x": _make_consumable_event("evt-x", processed=False)}

    with patch(
        "custom_components.mqtt_vacuum_camera.utils.connection.connector.persistent_notification"
    ) as mock_pn:
        await connector._hypfer_handle_valetudo_events(events)

    mock_pn.async_create.assert_not_called()


@pytest.mark.asyncio
async def test_does_nothing_on_empty_events():
    """Empty or None events payload is handled gracefully."""
    connector = _make_connector()
    with patch(
        "custom_components.mqtt_vacuum_camera.utils.connection.connector.persistent_notification"
    ) as mock_pn:
        await connector._hypfer_handle_valetudo_events(None)
        await connector._hypfer_handle_valetudo_events({})

    mock_pn.async_create.assert_not_called()
    mock_pn.async_dismiss.assert_not_called()


# ---------------------------------------------------------------------------
# _register_notification_dismiss_listener
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_listener_registered_only_once_per_notification():
    """Calling register twice for the same notification_id is a no-op the second time."""
    connector = _make_connector()

    with patch(
        "custom_components.mqtt_vacuum_camera.utils.connection.connector.async_track_state_change_event"
    ) as mock_track:
        mock_track.return_value = MagicMock()
        connector._register_notification_dismiss_listener("evt-1", "ok", "valetudo_error_evt-1")
        connector._register_notification_dismiss_listener("evt-1", "ok", "valetudo_error_evt-1")

    assert mock_track.call_count == 1


@pytest.mark.asyncio
async def test_listener_unsubscribe_added_to_handlers():
    """The unsubscribe callable from async_track_state_change_event is stored."""
    connector = _make_connector()
    mock_unsub = MagicMock()

    with patch(
        "custom_components.mqtt_vacuum_camera.utils.connection.connector.async_track_state_change_event",
        return_value=mock_unsub,
    ):
        connector._register_notification_dismiss_listener("evt-1", "ok", "valetudo_error_evt-1")

    assert mock_unsub in connector.connector_data.unsubscribe_handlers


# ---------------------------------------------------------------------------
# _dismiss_valetudo_event
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_dismiss_publishes_to_mqtt_interact_topic():
    """_dismiss_valetudo_event publishes the correct payload to the MQTT interact topic."""
    connector = _make_connector()
    connector.publish_to_broker = AsyncMock()

    await connector._dismiss_valetudo_event("evt-1", "ok")

    connector.publish_to_broker.assert_called_once_with(
        "valetudo/TestRobot/ValetudoEvents/valetudo_events/interact/set",
        {"id": "evt-1", "interaction": "ok"},
    )


@pytest.mark.asyncio
async def test_dismiss_uses_correct_interaction_per_event_type():
    """Different interaction values are forwarded as-is to the MQTT topic."""
    connector = _make_connector()
    connector.publish_to_broker = AsyncMock()

    await connector._dismiss_valetudo_event("consumable-1", "reset")

    connector.publish_to_broker.assert_called_once_with(
        "valetudo/TestRobot/ValetudoEvents/valetudo_events/interact/set",
        {"id": "consumable-1", "interaction": "reset"},
    )
