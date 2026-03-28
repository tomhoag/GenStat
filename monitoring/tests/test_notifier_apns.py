"""Tests for notifier_apns.py — APNs notification policy and sending."""

from unittest.mock import patch, MagicMock
import pytest

from interfaces import State, TransferSwitchData
from notifier_apns import APNsNotifier


def _make_data(normal_v=222.0, emergency_v=0.0):
    data = TransferSwitchData()
    data.normal_voltage = normal_v
    data.emergency_voltage = emergency_v
    return data


def _make_notifier():
    mock_persistence = MagicMock()
    mock_persistence.get_device_tokens.return_value = []
    return APNsNotifier(mock_persistence)


class TestNotificationPolicy:
    """Verify which state transitions trigger push notifications."""

    def test_outage_sends_notification(self):
        notifier = _make_notifier()
        with patch.object(notifier, "_send") as mock_send:
            notifier.notify_state_change(State.NORMAL, State.OUTAGE, _make_data(0, 240))
            mock_send.assert_called_once()
            assert "Power Outage" in mock_send.call_args[0][0]
            assert mock_send.call_args[1]["priority"] == "10"

    def test_critical_sends_notification(self):
        notifier = _make_notifier()
        with patch.object(notifier, "_send") as mock_send:
            notifier.notify_state_change(State.NORMAL, State.CRITICAL, _make_data(0, 0))
            mock_send.assert_called_once()
            assert "Critical" in mock_send.call_args[0][0]

    def test_restore_from_outage_sends_notification(self):
        notifier = _make_notifier()
        with patch.object(notifier, "_send") as mock_send:
            notifier.notify_state_change(State.OUTAGE, State.NORMAL, _make_data())
            mock_send.assert_called_once()
            assert "Restored" in mock_send.call_args[0][0]
            assert mock_send.call_args[1]["priority"] == "5"

    def test_restore_from_critical_sends_notification(self):
        notifier = _make_notifier()
        with patch.object(notifier, "_send") as mock_send:
            notifier.notify_state_change(State.CRITICAL, State.NORMAL, _make_data())
            mock_send.assert_called_once()

    def test_weekly_test_does_not_send(self):
        notifier = _make_notifier()
        with patch.object(notifier, "_send") as mock_send:
            notifier.notify_state_change(State.NORMAL, State.WEEKLY_TEST, _make_data(222, 240))
            mock_send.assert_not_called()

    def test_normal_to_normal_does_not_send(self):
        notifier = _make_notifier()
        with patch.object(notifier, "_send") as mock_send:
            notifier.notify_state_change(State.NORMAL, State.NORMAL, _make_data())
            mock_send.assert_not_called()

    def test_weekly_test_to_normal_does_not_send(self):
        """Routine end of exercise cycle — no notification."""
        notifier = _make_notifier()
        with patch.object(notifier, "_send") as mock_send:
            notifier.notify_state_change(State.WEEKLY_TEST, State.NORMAL, _make_data())
            mock_send.assert_not_called()

    def test_unknown_to_normal_does_not_send(self):
        """Initial startup transition — no notification."""
        notifier = _make_notifier()
        with patch.object(notifier, "_send") as mock_send:
            notifier.notify_state_change(State.UNKNOWN, State.NORMAL, _make_data())
            mock_send.assert_not_called()


class TestSend:

    @patch("notifier_apns.APNS_ENABLED", False)
    def test_disabled_skips_send(self):
        notifier = _make_notifier()
        # Should not raise or try to connect
        notifier._send("Test", "test message")

    @patch("notifier_apns.APNS_ENABLED", True)
    def test_no_tokens_skips_send(self):
        notifier = _make_notifier()
        notifier._persistence.get_device_tokens.return_value = []
        # Should log and return without error
        notifier._send("Test", "test message")

    @patch("notifier_apns.APNS_ENABLED", True)
    @patch("notifier_apns.httpx.Client")
    def test_sends_to_all_tokens(self, mock_client_cls):
        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.headers = {"apns-id": "test-id"}
        mock_client.post.return_value = mock_resp
        mock_client_cls.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)

        notifier = _make_notifier()
        notifier._persistence.get_device_tokens.return_value = ["token_a", "token_b"]
        notifier._get_jwt = MagicMock(return_value="fake.jwt.token")

        notifier._send("Title", "Body")
        assert mock_client.post.call_count == 2

    @patch("notifier_apns.APNS_ENABLED", True)
    @patch("notifier_apns.httpx.Client")
    def test_marks_expired_token_inactive(self, mock_client_cls):
        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 410
        mock_client.post.return_value = mock_resp
        mock_client_cls.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)

        notifier = _make_notifier()
        notifier._persistence.get_device_tokens.return_value = ["expired_token"]
        notifier._get_jwt = MagicMock(return_value="fake.jwt.token")

        notifier._send("Title", "Body")
        notifier._persistence.mark_token_inactive.assert_called_once_with("expired_token")


class TestJWTCaching:

    def test_jwt_is_cached(self):
        notifier = _make_notifier()
        notifier._jwt_token = "cached_token"
        notifier._jwt_token_time = __import__("time").time()

        result = notifier._get_jwt()
        assert result == "cached_token"

    def test_jwt_refreshes_when_expired(self):
        notifier = _make_notifier()
        notifier._jwt_token = "old_token"
        notifier._jwt_token_time = 0  # epoch — definitely expired

        with patch("notifier_apns.open", create=True) as mock_open, \
             patch("notifier_apns.jwt.encode", return_value="new_token"):
            mock_open.return_value.__enter__ = MagicMock(
                return_value=MagicMock(read=MagicMock(return_value="fake_key"))
            )
            mock_open.return_value.__exit__ = MagicMock(return_value=False)
            result = notifier._get_jwt()

        assert result == "new_token"
