import logging
import os
import time

import requests

logger = logging.getLogger(__name__)

LINE_API_URL = "https://api.line.me/v2/bot/message/push"
MAX_RETRIES = 2
RETRY_DELAY_SECONDS = 3


def _is_notify_enabled() -> bool:
    """Return True unless LINE_NOTIFY_ENABLED is explicitly set to 'false'."""
    return os.environ.get("LINE_NOTIFY_ENABLED", "true").strip().lower() != "false"


class LineNotifier:
    """LINE Messaging API client for sending push messages.

    Attributes:
        enabled: Whether LINE notifications are active (controlled by LINE_NOTIFY_ENABLED env var).
        channel_access_token: LINE channel access token.
        user_id: LINE user ID to send messages to.
    """

    def __init__(self, channel_access_token: str | None = None, user_id: str | None = None) -> None:
        """Initialize the LINE notifier.

        When ``LINE_NOTIFY_ENABLED=false`` the notifier operates in dry-run mode:
        credentials are not required and all send methods are no-ops.

        Args:
            channel_access_token: LINE channel access token. Falls back to LINE_CHANNEL_ACCESS_TOKEN env var.
            user_id: LINE user ID. Falls back to LINE_USER_ID env var.

        Raises:
            ValueError: If notifications are enabled but credentials are missing.
        """
        self.enabled = _is_notify_enabled()

        if not self.enabled:
            logger.warning("LINE notifications are DISABLED (LINE_NOTIFY_ENABLED=false). No messages will be sent.")
            self.channel_access_token = ""
            self.user_id = ""
            return

        self.channel_access_token = channel_access_token or os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "")
        self.user_id = user_id or os.environ.get("LINE_USER_ID", "")

        if not self.channel_access_token:
            raise ValueError("LINE_CHANNEL_ACCESS_TOKEN is required (set via argument or environment variable)")
        if not self.user_id:
            raise ValueError("LINE_USER_ID is required (set via argument or environment variable)")

    def _send_push(self, messages: list[dict]) -> None:
        """Send a push message via LINE Messaging API with retry logic.

        Args:
            messages: List of message objects to send.

        Raises:
            RuntimeError: If all retry attempts fail.
        """
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.channel_access_token}",
        }
        payload = {
            "to": self.user_id,
            "messages": messages,
        }

        last_error: Exception | None = None
        for attempt in range(1, MAX_RETRIES + 2):  # +2 because range is exclusive and attempt 1 is the initial try
            try:
                response = requests.post(LINE_API_URL, json=payload, headers=headers, timeout=30)

                if response.status_code == 200:
                    logger.info("LINE message sent successfully (attempt %d)", attempt)
                    return

                logger.warning(
                    "LINE API returned status %d (attempt %d): %s",
                    response.status_code,
                    attempt,
                    response.text,
                )
                last_error = RuntimeError(f"LINE API error {response.status_code}: {response.text}")

            except requests.RequestException as e:
                logger.warning("LINE API request failed (attempt %d): %s", attempt, e)
                last_error = e

            if attempt <= MAX_RETRIES:
                wait = RETRY_DELAY_SECONDS * attempt
                logger.info("Retrying in %d seconds...", wait)
                time.sleep(wait)

        raise RuntimeError(f"Failed to send LINE message after {MAX_RETRIES + 1} attempts") from last_error

    def send_flex_messages(self, flex_messages: list[dict]) -> None:
        """Send Flex Messages to the configured user.

        LINE API allows max 5 messages per push. Splits if needed.
        Does nothing when notifications are disabled.

        Args:
            flex_messages: List of Flex Message dicts from formatter.build_flex_messages().
        """
        if not self.enabled:
            logger.info("Skipping %d LINE flex message(s) — notifications disabled.", len(flex_messages))
            return

        # LINE allows max 5 messages per push request
        for i in range(0, len(flex_messages), 5):
            batch = flex_messages[i : i + 5]
            self._send_push(batch)

    def send_error_alert(self, error_message: str) -> None:
        """Send a simple text error alert via LINE.

        Does nothing when notifications are disabled.

        Args:
            error_message: Error description to send.
        """
        if not self.enabled:
            logger.info("Skipping LINE error alert — notifications disabled.")
            return

        try:
            self._send_push([{
                "type": "text",
                "text": f"⚠️ Market Screener Error\n\n{error_message}",
            }])
        except Exception as e:
            logger.error("Failed to send error alert via LINE: %s", e)
