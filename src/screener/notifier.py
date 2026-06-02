import logging
import os
import time

import requests

logger = logging.getLogger(__name__)

LINE_PUSH_API_URL = "https://api.line.me/v2/bot/message/push"
LINE_BROADCAST_API_URL = "https://api.line.me/v2/bot/message/broadcast"
LINE_FOLLOWERS_API_URL = "https://api.line.me/v2/bot/insight/followers"

MAX_RETRIES = 2
RETRY_DELAY_SECONDS = 3


def _is_notify_enabled() -> bool:
    """Return True unless LINE_NOTIFY_ENABLED is explicitly set to 'false'."""
    return os.environ.get("LINE_NOTIFY_ENABLED", "true").strip().lower() != "false"


def _is_broadcast_enabled() -> bool:
    """Return True unless LINE_BROADCAST_ENABLED is explicitly set to 'false'.

    When True (the default), notifications are sent to all followers via the
    Broadcast API. When False, the Push API is used with a specific LINE_USER_ID.
    """
    return os.environ.get("LINE_BROADCAST_ENABLED", "true").strip().lower() != "false"


class LineNotifier:
    """LINE Messaging API client for sending push or broadcast messages.

    Supports two delivery modes controlled by the LINE_BROADCAST_ENABLED
    environment variable:

    - **Broadcast mode** (default, ``LINE_BROADCAST_ENABLED=true``): Sends
      messages to all followers of the LINE Official Account using the
      Broadcast API. ``LINE_USER_ID`` is not required in this mode.

    - **Push mode** (``LINE_BROADCAST_ENABLED=false``): Sends messages to a
      single user via the Push API. ``LINE_USER_ID`` is required.

    In both modes, notifications can be fully disabled by setting
    ``LINE_NOTIFY_ENABLED=false`` (dry-run / testing).

    Attributes:
        enabled: Whether LINE notifications are active.
        broadcast_enabled: Whether to use the Broadcast API (vs Push API).
        channel_access_token: LINE channel access token.
        user_id: LINE user ID used in push mode only.
    """

    def __init__(
        self,
        channel_access_token: str | None = None,
        user_id: str | None = None,
    ) -> None:
        """Initialize the LINE notifier.

        When ``LINE_NOTIFY_ENABLED=false`` the notifier operates in dry-run
        mode: credentials are not required and all send methods are no-ops.

        In broadcast mode (``LINE_BROADCAST_ENABLED=true``, the default),
        ``LINE_USER_ID`` is not required.

        Args:
            channel_access_token: LINE channel access token. Falls back to
                ``LINE_CHANNEL_ACCESS_TOKEN`` env var.
            user_id: LINE user ID (push mode only). Falls back to
                ``LINE_USER_ID`` env var.

        Raises:
            ValueError: If notifications are enabled but required credentials
                are missing.
        """
        self.enabled = _is_notify_enabled()

        if not self.enabled:
            logger.warning("LINE notifications are DISABLED (LINE_NOTIFY_ENABLED=false). No messages will be sent.")
            self.channel_access_token = ""
            self.user_id = ""
            self.broadcast_enabled = False
            return

        self.broadcast_enabled = _is_broadcast_enabled()
        self.channel_access_token = channel_access_token or os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "")
        self.user_id = user_id or os.environ.get("LINE_USER_ID", "")

        if not self.channel_access_token:
            raise ValueError("LINE_CHANNEL_ACCESS_TOKEN is required (set via argument or environment variable)")

        if not self.broadcast_enabled and not self.user_id:
            raise ValueError(
                "LINE_USER_ID is required when LINE_BROADCAST_ENABLED=false "
                "(set via argument or environment variable)"
            )

        mode = "broadcast" if self.broadcast_enabled else f"push (user_id={self.user_id})"
        logger.info("LINE notifier initialized — delivery mode: %s", mode)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _auth_headers(self) -> dict[str, str]:
        """Return standard authorization headers for LINE API requests."""
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.channel_access_token}",
        }

    def _get_follower_stats(self) -> dict | None:
        """Fetch follower statistics from the LINE insight API.

        Calls ``GET /v2/bot/insight/followers`` and returns the parsed response
        body. Logs the statistics at INFO level if successful.

        If the API is unavailable or returns a non-200 status, logs a warning
        and returns ``None`` so the caller can continue without stats.

        Returns:
            Dict with keys ``followers``, ``targetedReaches``, ``blocks``, or
            ``None`` on any error.
        """
        try:
            response = requests.get(LINE_FOLLOWERS_API_URL, headers=self._auth_headers(), timeout=10)

            if response.status_code == 200:
                data = response.json()
                logger.info(
                    "LINE Followers:\n  followers: %s\n  targetedReaches: %s\n  blocks: %s",
                    data.get("followers", "N/A"),
                    data.get("targetedReaches", "N/A"),
                    data.get("blocks", "N/A"),
                )
                return data

            logger.warning(
                "LINE follower insight API returned status %d: %s",
                response.status_code,
                response.text,
            )
            return None

        except requests.RequestException as e:
            logger.warning("Failed to fetch LINE follower stats: %s", e)
            return None

    def _send_broadcast(self, messages: list[dict]) -> None:
        """Send a broadcast message to all followers via LINE Messaging API.

        Uses the same retry policy as ``_send_push``. Before sending, fetches
        and logs follower statistics from the insight API (failures are
        non-fatal).

        Args:
            messages: List of message objects to broadcast.

        Raises:
            RuntimeError: If all retry attempts fail.
        """
        logger.info("Broadcasting stock screener notification...")

        # Fetch follower stats (non-blocking — errors are warned and ignored)
        stats = self._get_follower_stats()
        if stats is not None:
            logger.info("Followers: %s", stats.get("followers", "N/A"))

        logger.info("Messages: %d", len(messages))

        payload: dict = {"messages": messages}
        last_error: Exception | None = None

        for attempt in range(1, MAX_RETRIES + 2):  # +2: range is exclusive; attempt 1 is the initial try
            try:
                response = requests.post(
                    LINE_BROADCAST_API_URL,
                    json=payload,
                    headers=self._auth_headers(),
                    timeout=30,
                )

                if response.status_code == 200:
                    logger.info("Broadcast successful. (attempt %d)", attempt)
                    return

                logger.warning(
                    "LINE Broadcast API returned status %d (attempt %d): %s",
                    response.status_code,
                    attempt,
                    response.text,
                )
                last_error = RuntimeError(f"LINE Broadcast API error {response.status_code}: {response.text}")

            except requests.RequestException as e:
                logger.warning("LINE Broadcast API request failed (attempt %d): %s", attempt, e)
                last_error = e

            if attempt <= MAX_RETRIES:
                wait = RETRY_DELAY_SECONDS * attempt
                logger.info("Retrying broadcast in %d seconds...", wait)
                time.sleep(wait)

        raise RuntimeError(f"Failed to broadcast LINE message after {MAX_RETRIES + 1} attempts") from last_error

    def _send_push(self, messages: list[dict]) -> None:
        """Send a push message to a single user via LINE Messaging API.

        Uses retry logic with exponential back-off. Requires ``self.user_id``
        to be set (push mode only).

        Args:
            messages: List of message objects to send.

        Raises:
            RuntimeError: If all retry attempts fail.
        """
        headers = self._auth_headers()
        payload = {
            "to": self.user_id,
            "messages": messages,
        }

        last_error: Exception | None = None
        for attempt in range(1, MAX_RETRIES + 2):  # +2 because range is exclusive and attempt 1 is the initial try
            try:
                response = requests.post(LINE_PUSH_API_URL, json=payload, headers=headers, timeout=30)

                if response.status_code == 200:
                    logger.info("LINE push message sent successfully (attempt %d)", attempt)
                    return

                logger.warning(
                    "LINE Push API returned status %d (attempt %d): %s",
                    response.status_code,
                    attempt,
                    response.text,
                )
                last_error = RuntimeError(f"LINE Push API error {response.status_code}: {response.text}")

            except requests.RequestException as e:
                logger.warning("LINE Push API request failed (attempt %d): %s", attempt, e)
                last_error = e

            if attempt <= MAX_RETRIES:
                wait = RETRY_DELAY_SECONDS * attempt
                logger.info("Retrying in %d seconds...", wait)
                time.sleep(wait)

        raise RuntimeError(f"Failed to send LINE push message after {MAX_RETRIES + 1} attempts") from last_error

    def _dispatch(self, messages: list[dict]) -> None:
        """Route a batch of messages to broadcast or push based on current mode.

        Args:
            messages: List of LINE message objects to send.
        """
        if self.broadcast_enabled:
            self._send_broadcast(messages)
        else:
            self._send_push(messages)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def send_flex_messages(self, flex_messages: list[dict]) -> None:
        """Send Flex Messages to followers (broadcast) or a user (push).

        LINE API allows max 5 messages per request. Automatically splits
        larger batches into multiple requests.

        Does nothing when notifications are disabled (``LINE_NOTIFY_ENABLED=false``).

        Args:
            flex_messages: List of Flex Message dicts from
                ``formatter.build_flex_messages()``.
        """
        if not self.enabled:
            logger.info("Skipping %d LINE flex message(s) — notifications disabled.", len(flex_messages))
            return

        # LINE allows max 5 messages per push/broadcast request
        for i in range(0, len(flex_messages), 5):
            batch = flex_messages[i : i + 5]
            self._dispatch(batch)

    def send_error_alert(self, error_message: str) -> None:
        """Send a plain-text error alert directly to the bot owner via Push API.

        Error alerts are **always** sent via the Push API to the configured
        ``LINE_USER_ID``, even when ``LINE_BROADCAST_ENABLED=true``. This
        ensures error notifications reach only you, not all followers.

        Does nothing when notifications are disabled.

        Args:
            error_message: Error description to send.
        """
        if not self.enabled:
            logger.info("Skipping LINE error alert — notifications disabled.")
            return

        if not self.user_id:
            logger.warning(
                "Cannot send error alert: LINE_USER_ID is not configured. "
                "Set LINE_USER_ID to receive error alerts directly."
            )
            return

        try:
            self._send_push([{
                "type": "text",
                "text": f"⚠️ Market Screener Error\n\n{error_message}",
            }])
        except Exception as e:
            logger.error("Failed to send error alert via LINE: %s", e)
