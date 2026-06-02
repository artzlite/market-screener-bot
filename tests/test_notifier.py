"""Tests for the LINE notifier module.

Covers both broadcast mode (default) and push mode (backward compat),
follower stats fetching, retry logic, routing, and disabled mode.
"""

from unittest.mock import MagicMock, call, patch

import pytest
import requests

from screener.notifier import LineNotifier


# ---------------------------------------------------------------------------
# Helpers / shared constants
# ---------------------------------------------------------------------------

FAKE_TOKEN = "fake-channel-access-token"
FAKE_USER_ID = "Ufake000000000000000000000000000"

SAMPLE_FLEX = [{"type": "flex", "altText": "test", "contents": {}}]
SAMPLE_TEXT = [{"type": "text", "text": "hello"}]

FOLLOWERS_RESPONSE = {
    "followers": 25,
    "targetedReaches": 24,
    "blocks": 1,
}


def _make_response(status_code: int, json_data: dict | None = None, text: str = "") -> MagicMock:
    """Build a mock requests.Response."""
    mock = MagicMock()
    mock.status_code = status_code
    mock.text = text or str(json_data or {})
    mock.json.return_value = json_data or {}
    return mock


# ---------------------------------------------------------------------------
# Initialization tests
# ---------------------------------------------------------------------------


class TestLineNotifierInit:
    """Tests for LineNotifier.__init__."""

    def test_broadcast_mode_does_not_require_user_id(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Broadcast mode should not raise when LINE_USER_ID is absent."""
        monkeypatch.setenv("LINE_NOTIFY_ENABLED", "true")
        monkeypatch.setenv("LINE_BROADCAST_ENABLED", "true")
        monkeypatch.setenv("LINE_CHANNEL_ACCESS_TOKEN", FAKE_TOKEN)
        monkeypatch.delenv("LINE_USER_ID", raising=False)

        notifier = LineNotifier()

        assert notifier.enabled is True
        assert notifier.broadcast_enabled is True
        assert notifier.channel_access_token == FAKE_TOKEN

    def test_push_mode_requires_user_id(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Push mode should raise ValueError when LINE_USER_ID is missing."""
        monkeypatch.setenv("LINE_NOTIFY_ENABLED", "true")
        monkeypatch.setenv("LINE_BROADCAST_ENABLED", "false")
        monkeypatch.setenv("LINE_CHANNEL_ACCESS_TOKEN", FAKE_TOKEN)
        monkeypatch.delenv("LINE_USER_ID", raising=False)

        with pytest.raises(ValueError, match="LINE_USER_ID is required"):
            LineNotifier()

    def test_push_mode_accepts_user_id(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Push mode should succeed when all credentials are present."""
        monkeypatch.setenv("LINE_NOTIFY_ENABLED", "true")
        monkeypatch.setenv("LINE_BROADCAST_ENABLED", "false")
        monkeypatch.setenv("LINE_CHANNEL_ACCESS_TOKEN", FAKE_TOKEN)
        monkeypatch.setenv("LINE_USER_ID", FAKE_USER_ID)

        notifier = LineNotifier()

        assert notifier.broadcast_enabled is False
        assert notifier.user_id == FAKE_USER_ID

    def test_missing_token_always_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Missing channel access token should raise regardless of mode."""
        monkeypatch.setenv("LINE_NOTIFY_ENABLED", "true")
        monkeypatch.setenv("LINE_BROADCAST_ENABLED", "true")
        monkeypatch.delenv("LINE_CHANNEL_ACCESS_TOKEN", raising=False)

        with pytest.raises(ValueError, match="LINE_CHANNEL_ACCESS_TOKEN is required"):
            LineNotifier()

    def test_disabled_mode_skips_credential_checks(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """When notifications are disabled, no credentials should be required."""
        monkeypatch.setenv("LINE_NOTIFY_ENABLED", "false")
        monkeypatch.delenv("LINE_CHANNEL_ACCESS_TOKEN", raising=False)
        monkeypatch.delenv("LINE_USER_ID", raising=False)

        notifier = LineNotifier()

        assert notifier.enabled is False
        assert notifier.channel_access_token == ""

    def test_constructor_args_take_precedence_over_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Explicit constructor args should override environment variables."""
        monkeypatch.setenv("LINE_NOTIFY_ENABLED", "true")
        monkeypatch.setenv("LINE_BROADCAST_ENABLED", "false")
        monkeypatch.setenv("LINE_CHANNEL_ACCESS_TOKEN", "env-token")
        monkeypatch.setenv("LINE_USER_ID", "env-user")

        notifier = LineNotifier(channel_access_token="arg-token", user_id="arg-user")

        assert notifier.channel_access_token == "arg-token"
        assert notifier.user_id == "arg-user"


# ---------------------------------------------------------------------------
# _get_follower_stats tests
# ---------------------------------------------------------------------------


class TestGetFollowerStats:
    """Tests for LineNotifier._get_follower_stats."""

    def _make_notifier(self, monkeypatch: pytest.MonkeyPatch) -> LineNotifier:
        monkeypatch.setenv("LINE_NOTIFY_ENABLED", "true")
        monkeypatch.setenv("LINE_BROADCAST_ENABLED", "true")
        monkeypatch.setenv("LINE_CHANNEL_ACCESS_TOKEN", FAKE_TOKEN)
        monkeypatch.delenv("LINE_USER_ID", raising=False)
        return LineNotifier()

    def test_returns_parsed_data_on_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Should return the parsed JSON dict when the API returns 200."""
        notifier = self._make_notifier(monkeypatch)

        with patch("screener.notifier.requests.get", return_value=_make_response(200, FOLLOWERS_RESPONSE)) as mock_get:
            result = notifier._get_follower_stats()

        assert result == FOLLOWERS_RESPONSE
        mock_get.assert_called_once()
        kwargs = mock_get.call_args.kwargs
        assert "params" in kwargs
        assert "date" in kwargs["params"]
        assert len(kwargs["params"]["date"]) == 8
        assert kwargs["params"]["date"].isdigit()

    def test_returns_none_on_non_200_status(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Should return None and log a warning when the API returns non-200."""
        notifier = self._make_notifier(monkeypatch)

        with patch("screener.notifier.requests.get", return_value=_make_response(403, text="Forbidden")):
            result = notifier._get_follower_stats()

        assert result is None

    def test_returns_none_on_request_exception(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Should return None and log a warning on network error."""
        notifier = self._make_notifier(monkeypatch)

        with patch("screener.notifier.requests.get", side_effect=requests.RequestException("timeout")):
            result = notifier._get_follower_stats()

        assert result is None

    def test_logs_followers_info(self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
        """Should log followers, targetedReaches, and blocks on success."""
        notifier = self._make_notifier(monkeypatch)

        import logging

        with patch("screener.notifier.requests.get", return_value=_make_response(200, FOLLOWERS_RESPONSE)):
            with caplog.at_level(logging.INFO, logger="screener.notifier"):
                notifier._get_follower_stats()

        assert "followers: 25" in caplog.text
        assert "targetedReaches: 24" in caplog.text
        assert "blocks: 1" in caplog.text


# ---------------------------------------------------------------------------
# _send_broadcast tests
# ---------------------------------------------------------------------------


class TestSendBroadcast:
    """Tests for LineNotifier._send_broadcast."""

    def _make_notifier(self, monkeypatch: pytest.MonkeyPatch) -> LineNotifier:
        monkeypatch.setenv("LINE_NOTIFY_ENABLED", "true")
        monkeypatch.setenv("LINE_BROADCAST_ENABLED", "true")
        monkeypatch.setenv("LINE_CHANNEL_ACCESS_TOKEN", FAKE_TOKEN)
        monkeypatch.delenv("LINE_USER_ID", raising=False)
        return LineNotifier()

    def test_succeeds_on_first_attempt(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Should call the broadcast endpoint once and return on 200."""
        notifier = self._make_notifier(monkeypatch)

        with (
            patch("screener.notifier.requests.get", return_value=_make_response(200, FOLLOWERS_RESPONSE)),
            patch("screener.notifier.requests.post", return_value=_make_response(200)) as mock_post,
        ):
            notifier._send_broadcast(SAMPLE_FLEX)

        mock_post.assert_called_once()
        call_url = mock_post.call_args[0][0]
        assert "broadcast" in call_url

    def test_payload_does_not_contain_to_field(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Broadcast payload must NOT include a 'to' field."""
        notifier = self._make_notifier(monkeypatch)

        with (
            patch("screener.notifier.requests.get", return_value=_make_response(200, FOLLOWERS_RESPONSE)),
            patch("screener.notifier.requests.post", return_value=_make_response(200)) as mock_post,
        ):
            notifier._send_broadcast(SAMPLE_FLEX)

        sent_payload = mock_post.call_args.kwargs["json"]
        assert "to" not in sent_payload
        assert "messages" in sent_payload
        assert sent_payload["messages"] == SAMPLE_FLEX

    def test_retries_and_succeeds_on_second_attempt(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Should retry after first failure and succeed on the second attempt."""
        notifier = self._make_notifier(monkeypatch)

        responses = [_make_response(500, text="Server Error"), _make_response(200)]

        with (
            patch("screener.notifier.requests.get", return_value=_make_response(200, FOLLOWERS_RESPONSE)),
            patch("screener.notifier.requests.post", side_effect=responses) as mock_post,
            patch("screener.notifier.time.sleep"),  # avoid real delays
        ):
            notifier._send_broadcast(SAMPLE_FLEX)  # should not raise

        assert mock_post.call_count == 2

    def test_raises_after_all_retries_exhausted(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Should raise RuntimeError when all attempts fail with non-200 status."""
        notifier = self._make_notifier(monkeypatch)

        always_fail = _make_response(500, text="Server Error")

        with (
            patch("screener.notifier.requests.get", return_value=_make_response(200, FOLLOWERS_RESPONSE)),
            patch("screener.notifier.requests.post", return_value=always_fail),
            patch("screener.notifier.time.sleep"),
        ):
            with pytest.raises(RuntimeError, match="Failed to broadcast LINE message"):
                notifier._send_broadcast(SAMPLE_FLEX)

    def test_raises_after_all_retries_on_network_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Should raise RuntimeError when all attempts raise RequestException."""
        notifier = self._make_notifier(monkeypatch)

        with (
            patch("screener.notifier.requests.get", return_value=_make_response(200, FOLLOWERS_RESPONSE)),
            patch("screener.notifier.requests.post", side_effect=requests.RequestException("connect timeout")),
            patch("screener.notifier.time.sleep"),
        ):
            with pytest.raises(RuntimeError, match="Failed to broadcast"):
                notifier._send_broadcast(SAMPLE_FLEX)

    def test_follower_stats_failure_does_not_prevent_broadcast(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Broadcast should proceed even when the follower insight API fails."""
        notifier = self._make_notifier(monkeypatch)

        with (
            patch("screener.notifier.requests.get", return_value=_make_response(403)),
            patch("screener.notifier.requests.post", return_value=_make_response(200)) as mock_post,
        ):
            notifier._send_broadcast(SAMPLE_FLEX)

        mock_post.assert_called_once()

    def test_logs_message_count(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Should log the number of messages being broadcast."""
        import logging

        notifier = self._make_notifier(monkeypatch)
        two_messages = SAMPLE_FLEX + SAMPLE_FLEX

        with (
            patch("screener.notifier.requests.get", return_value=_make_response(200, FOLLOWERS_RESPONSE)),
            patch("screener.notifier.requests.post", return_value=_make_response(200)),
            caplog.at_level(logging.INFO, logger="screener.notifier"),
        ):
            notifier._send_broadcast(two_messages)

        assert "Messages: 2" in caplog.text


# ---------------------------------------------------------------------------
# _send_push tests (backward compat)
# ---------------------------------------------------------------------------


class TestSendPush:
    """Tests for LineNotifier._send_push (push/legacy mode)."""

    def _make_push_notifier(self, monkeypatch: pytest.MonkeyPatch) -> LineNotifier:
        monkeypatch.setenv("LINE_NOTIFY_ENABLED", "true")
        monkeypatch.setenv("LINE_BROADCAST_ENABLED", "false")
        monkeypatch.setenv("LINE_CHANNEL_ACCESS_TOKEN", FAKE_TOKEN)
        monkeypatch.setenv("LINE_USER_ID", FAKE_USER_ID)
        return LineNotifier()

    def test_sends_to_configured_user(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Push payload must include the configured user ID in the 'to' field."""
        notifier = self._make_push_notifier(monkeypatch)

        with patch("screener.notifier.requests.post", return_value=_make_response(200)) as mock_post:
            notifier._send_push(SAMPLE_TEXT)

        sent_payload = mock_post.call_args.kwargs["json"]
        assert sent_payload["to"] == FAKE_USER_ID

    def test_uses_push_endpoint(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Push mode must call the push (not broadcast) endpoint."""
        notifier = self._make_push_notifier(monkeypatch)

        with patch("screener.notifier.requests.post", return_value=_make_response(200)) as mock_post:
            notifier._send_push(SAMPLE_TEXT)

        call_url = mock_post.call_args[0][0]
        assert "push" in call_url
        assert "broadcast" not in call_url

    def test_raises_after_all_retries(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Should raise RuntimeError when all push attempts fail."""
        notifier = self._make_push_notifier(monkeypatch)

        with (
            patch("screener.notifier.requests.post", return_value=_make_response(500, text="error")),
            patch("screener.notifier.time.sleep"),
        ):
            with pytest.raises(RuntimeError, match="Failed to send LINE push message"):
                notifier._send_push(SAMPLE_TEXT)


# ---------------------------------------------------------------------------
# send_flex_messages routing tests
# ---------------------------------------------------------------------------


class TestSendFlexMessages:
    """Tests for LineNotifier.send_flex_messages routing and batching."""

    def test_routes_to_broadcast_when_broadcast_enabled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """send_flex_messages should call _send_broadcast in broadcast mode."""
        monkeypatch.setenv("LINE_NOTIFY_ENABLED", "true")
        monkeypatch.setenv("LINE_BROADCAST_ENABLED", "true")
        monkeypatch.setenv("LINE_CHANNEL_ACCESS_TOKEN", FAKE_TOKEN)
        monkeypatch.delenv("LINE_USER_ID", raising=False)
        notifier = LineNotifier()

        with patch.object(notifier, "_send_broadcast") as mock_broadcast:
            notifier.send_flex_messages(SAMPLE_FLEX)

        mock_broadcast.assert_called_once_with(SAMPLE_FLEX)

    def test_routes_to_push_when_broadcast_disabled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """send_flex_messages should call _send_push in push mode."""
        monkeypatch.setenv("LINE_NOTIFY_ENABLED", "true")
        monkeypatch.setenv("LINE_BROADCAST_ENABLED", "false")
        monkeypatch.setenv("LINE_CHANNEL_ACCESS_TOKEN", FAKE_TOKEN)
        monkeypatch.setenv("LINE_USER_ID", FAKE_USER_ID)
        notifier = LineNotifier()

        with patch.object(notifier, "_send_push") as mock_push:
            notifier.send_flex_messages(SAMPLE_FLEX)

        mock_push.assert_called_once_with(SAMPLE_FLEX)

    def test_batches_more_than_5_messages(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """6 messages should be split into two batches: 5 + 1."""
        monkeypatch.setenv("LINE_NOTIFY_ENABLED", "true")
        monkeypatch.setenv("LINE_BROADCAST_ENABLED", "true")
        monkeypatch.setenv("LINE_CHANNEL_ACCESS_TOKEN", FAKE_TOKEN)
        monkeypatch.delenv("LINE_USER_ID", raising=False)
        notifier = LineNotifier()

        six_messages = SAMPLE_FLEX * 6

        with patch.object(notifier, "_send_broadcast") as mock_broadcast:
            notifier.send_flex_messages(six_messages)

        assert mock_broadcast.call_count == 2
        first_batch = mock_broadcast.call_args_list[0][0][0]
        second_batch = mock_broadcast.call_args_list[1][0][0]
        assert len(first_batch) == 5
        assert len(second_batch) == 1

    def test_skips_when_notifications_disabled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """send_flex_messages must be a no-op when notifications are disabled."""
        monkeypatch.setenv("LINE_NOTIFY_ENABLED", "false")
        monkeypatch.delenv("LINE_CHANNEL_ACCESS_TOKEN", raising=False)
        notifier = LineNotifier()

        # No patch needed — real request would fail if called
        notifier.send_flex_messages(SAMPLE_FLEX)  # should not raise


# ---------------------------------------------------------------------------
# send_error_alert tests
# ---------------------------------------------------------------------------


class TestSendErrorAlert:
    """Tests for LineNotifier.send_error_alert — always uses Push API."""

    def test_always_uses_push_even_in_broadcast_mode(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Error alert must use _send_push even when broadcast_enabled is True."""
        monkeypatch.setenv("LINE_NOTIFY_ENABLED", "true")
        monkeypatch.setenv("LINE_BROADCAST_ENABLED", "true")
        monkeypatch.setenv("LINE_CHANNEL_ACCESS_TOKEN", FAKE_TOKEN)
        monkeypatch.setenv("LINE_USER_ID", FAKE_USER_ID)
        notifier = LineNotifier()

        with (
            patch.object(notifier, "_send_push") as mock_push,
            patch.object(notifier, "_send_broadcast") as mock_broadcast,
        ):
            notifier.send_error_alert("Something went wrong")

        mock_push.assert_called_once()
        mock_broadcast.assert_not_called()

    def test_push_payload_contains_error_message(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Error alert payload must include the error message and warning emoji."""
        monkeypatch.setenv("LINE_NOTIFY_ENABLED", "true")
        monkeypatch.setenv("LINE_BROADCAST_ENABLED", "true")
        monkeypatch.setenv("LINE_CHANNEL_ACCESS_TOKEN", FAKE_TOKEN)
        monkeypatch.setenv("LINE_USER_ID", FAKE_USER_ID)
        notifier = LineNotifier()

        with patch.object(notifier, "_send_push") as mock_push:
            notifier.send_error_alert("Something went wrong")

        sent_message = mock_push.call_args[0][0][0]
        assert "⚠️" in sent_message["text"]
        assert "Something went wrong" in sent_message["text"]

    def test_also_uses_push_in_push_mode(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Error alert should also use push when broadcast_enabled is False."""
        monkeypatch.setenv("LINE_NOTIFY_ENABLED", "true")
        monkeypatch.setenv("LINE_BROADCAST_ENABLED", "false")
        monkeypatch.setenv("LINE_CHANNEL_ACCESS_TOKEN", FAKE_TOKEN)
        monkeypatch.setenv("LINE_USER_ID", FAKE_USER_ID)
        notifier = LineNotifier()

        with patch.object(notifier, "_send_push") as mock_push:
            notifier.send_error_alert("Something went wrong")

        mock_push.assert_called_once()

    def test_warns_and_skips_when_no_user_id_in_broadcast_mode(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """When in broadcast mode with no user_id, should warn and not crash."""
        import logging

        monkeypatch.setenv("LINE_NOTIFY_ENABLED", "true")
        monkeypatch.setenv("LINE_BROADCAST_ENABLED", "true")
        monkeypatch.setenv("LINE_CHANNEL_ACCESS_TOKEN", FAKE_TOKEN)
        monkeypatch.delenv("LINE_USER_ID", raising=False)
        notifier = LineNotifier()

        with (
            patch.object(notifier, "_send_push") as mock_push,
            caplog.at_level(logging.WARNING, logger="screener.notifier"),
        ):
            notifier.send_error_alert("Error with no user_id set")

        mock_push.assert_not_called()
        assert "LINE_USER_ID is not configured" in caplog.text

    def test_does_not_raise_on_send_failure(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """send_error_alert must swallow exceptions so the caller is unaffected."""
        monkeypatch.setenv("LINE_NOTIFY_ENABLED", "true")
        monkeypatch.setenv("LINE_BROADCAST_ENABLED", "true")
        monkeypatch.setenv("LINE_CHANNEL_ACCESS_TOKEN", FAKE_TOKEN)
        monkeypatch.setenv("LINE_USER_ID", FAKE_USER_ID)
        notifier = LineNotifier()

        with patch.object(notifier, "_send_push", side_effect=RuntimeError("boom")):
            notifier.send_error_alert("Error message")  # must NOT raise

    def test_skips_when_notifications_disabled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """send_error_alert must be a no-op when notifications are disabled."""
        monkeypatch.setenv("LINE_NOTIFY_ENABLED", "false")
        monkeypatch.delenv("LINE_CHANNEL_ACCESS_TOKEN", raising=False)
        notifier = LineNotifier()

        notifier.send_error_alert("should be ignored")  # must NOT raise

