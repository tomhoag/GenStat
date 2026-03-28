"""Tests for supabase_client.py — HTTP operations and retry logic."""

from unittest.mock import patch, MagicMock
import pytest
import httpx

import supabase_client as db


class TestRequestWithRetry:

    @patch("supabase_client.httpx.request")
    def test_success_on_first_attempt(self, mock_request):
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_request.return_value = mock_resp

        result = db.request_with_retry("GET", "http://example.com")
        assert result is mock_resp
        assert mock_request.call_count == 1

    @patch("supabase_client.time.sleep")
    @patch("supabase_client.httpx.request")
    def test_retries_on_network_error(self, mock_request, mock_sleep):
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_request.side_effect = [
            httpx.ConnectError("connection failed"),
            mock_resp,
        ]

        result = db.request_with_retry("GET", "http://example.com")
        assert result is mock_resp
        assert mock_request.call_count == 2
        mock_sleep.assert_called_once()

    @patch("supabase_client.httpx.request")
    def test_does_not_retry_http_status_error(self, mock_request):
        mock_resp = MagicMock()
        mock_resp.status_code = 400
        mock_request.side_effect = httpx.HTTPStatusError(
            "bad request", request=MagicMock(), response=mock_resp
        )

        with pytest.raises(httpx.HTTPStatusError):
            db.request_with_retry("GET", "http://example.com")
        assert mock_request.call_count == 1

    @patch("supabase_client.time.sleep")
    @patch("supabase_client.httpx.request")
    def test_raises_after_max_retries(self, mock_request, mock_sleep):
        mock_request.side_effect = httpx.ConnectError("connection failed")

        with pytest.raises(httpx.ConnectError):
            db.request_with_retry("GET", "http://example.com")
        assert mock_request.call_count == db.MAX_RETRIES

    @patch("supabase_client.time.sleep")
    @patch("supabase_client.httpx.request")
    def test_exponential_backoff_delays(self, mock_request, mock_sleep):
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_request.side_effect = [
            httpx.ConnectError("fail"),
            httpx.ConnectError("fail"),
            mock_resp,
        ]

        db.request_with_retry("GET", "http://example.com")
        delays = [call.args[0] for call in mock_sleep.call_args_list]
        assert delays[0] == db.RETRY_DELAY          # 2^0 * base
        assert delays[1] == db.RETRY_DELAY * 2       # 2^1 * base


class TestPost:

    @patch("supabase_client.request_with_retry")
    def test_posts_to_correct_url(self, mock_retry):
        db.post("generator_events", {"key": "value"})
        args = mock_retry.call_args
        assert args[0][0] == "POST"
        assert "generator_events" in args[0][1]
        assert args[1]["json"] == {"key": "value"}

    @patch("supabase_client.request_with_retry")
    def test_handles_http_error(self, mock_retry):
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_resp.text = "Internal Server Error"
        mock_retry.side_effect = httpx.HTTPStatusError(
            "error", request=MagicMock(), response=mock_resp
        )
        # Should not raise — post() handles the error internally
        db.post("generator_events", {"key": "value"})


class TestUpsert:

    @patch("supabase_client.request_with_retry")
    def test_returns_true_on_success(self, mock_retry):
        assert db.upsert("generator_status", {"id": 1}) is True

    @patch("supabase_client.request_with_retry")
    def test_returns_false_on_http_error(self, mock_retry):
        mock_resp = MagicMock()
        mock_resp.status_code = 409
        mock_resp.text = "conflict"
        mock_retry.side_effect = httpx.HTTPStatusError(
            "error", request=MagicMock(), response=mock_resp
        )
        assert db.upsert("generator_status", {"id": 1}) is False

    @patch("supabase_client.request_with_retry")
    def test_returns_false_on_network_error(self, mock_retry):
        mock_retry.side_effect = httpx.ConnectError("fail")
        assert db.upsert("generator_status", {"id": 1}) is False

    @patch("supabase_client.request_with_retry")
    def test_uses_merge_duplicates_header(self, mock_retry):
        db.upsert("generator_status", {"id": 1})
        headers = mock_retry.call_args[1]["headers"]
        assert "merge-duplicates" in headers["Prefer"]


class TestGet:

    @patch("supabase_client.request_with_retry")
    def test_returns_parsed_json(self, mock_retry):
        mock_resp = MagicMock()
        mock_resp.json.return_value = [{"id": 1, "state": "normal"}]
        mock_retry.return_value = mock_resp

        result = db.get("generator_status", "id=eq.1")
        assert result == [{"id": 1, "state": "normal"}]

    @patch("supabase_client.request_with_retry")
    def test_returns_none_on_error(self, mock_retry):
        mock_resp = MagicMock()
        mock_resp.status_code = 404
        mock_resp.text = "not found"
        mock_retry.side_effect = httpx.HTTPStatusError(
            "error", request=MagicMock(), response=mock_resp
        )
        assert db.get("generator_status") is None


class TestDeviceTokens:

    @patch("supabase_client.get")
    def test_get_device_tokens(self, mock_get):
        mock_get.return_value = [
            {"token": "token_aaa"},
            {"token": "token_bbb"},
        ]
        tokens = db.get_device_tokens()
        assert tokens == ["token_aaa", "token_bbb"]

    @patch("supabase_client.get")
    def test_get_device_tokens_empty(self, mock_get):
        mock_get.return_value = None
        assert db.get_device_tokens() == []

    @patch("supabase_client.patch")
    def test_mark_token_inactive(self, mock_patch):
        db.mark_token_inactive("abc123")
        mock_patch.assert_called_once()
        args = mock_patch.call_args
        assert args[0][2] == {"active": False}
