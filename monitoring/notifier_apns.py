"""
APNs push notification notifier.

Sends push notifications to iOS devices via Apple Push Notification service
using HTTP/2 and JWT authentication.
"""
from __future__ import annotations

import json
import logging
import os
import time
from urllib.parse import quote

import httpx
import jwt

from interfaces import Notifier, State, TransferSwitchData
from config_secrets import require_secret

log = logging.getLogger(__name__)


# ── Configuration ─────────────────────────────────────────────────────────────

APNS_ENABLED     = True
APNS_KEY_PATH    = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "AuthKey_Y4GY3CS3CF.p8")
APNS_KEY_ID      = "Y4GY3CS3CF"
APNS_TEAM_ID     = "4MUC8K263B"
APNS_BUNDLE_ID   = "studio.offbyone.KohlerStat"
APNS_USE_SANDBOX = True     # False for production

SUPABASE_URL = require_secret("SUPABASE_URL")
SUPABASE_KEY = require_secret("SUPABASE_KEY")
SUPABASE_HEADERS = {
    "apikey"        : SUPABASE_KEY,
    "Content-Type"  : "application/json",
    "Prefer"        : "return=minimal",
}

# JWT refresh interval — tokens are refreshed before APNs' 60-minute expiry
_JWT_REFRESH_SECONDS = 2700  # 45 minutes


# ── Device token management ──────────────────────────────────────────────────

def _get_device_tokens() -> list[str]:
    """Fetch active device tokens from Supabase."""
    url = f"{SUPABASE_URL}/rest/v1/device_tokens?active=eq.true&select=token"
    try:
        resp = httpx.get(url, headers=SUPABASE_HEADERS, timeout=10)
        resp.raise_for_status()
        rows = resp.json()
        return [row["token"] for row in rows] if rows else []
    except httpx.HTTPStatusError as e:
        log.error(f"Failed to fetch device tokens ({e.response.status_code}): {e.response.text}")
        return []
    except httpx.RequestError as e:
        log.error(f"Failed to fetch device tokens (network): {e}")
        return []


def _mark_token_inactive(token: str) -> None:
    """Mark a device token as inactive in Supabase."""
    url = f"{SUPABASE_URL}/rest/v1/device_tokens?token=eq.{quote(token, safe='')}"
    try:
        resp = httpx.patch(url, headers=SUPABASE_HEADERS, json={"active": False}, timeout=10)
        resp.raise_for_status()
        log.info(f"Marked token ...{token[-8:]} inactive")
    except httpx.HTTPStatusError as e:
        log.error(f"Failed to mark token inactive ({e.response.status_code}): {e.response.text}")
    except httpx.RequestError as e:
        log.error(f"Failed to mark token inactive (network): {e}")


# ── Concrete implementation ──────────────────────────────────────────────────

class APNsNotifier(Notifier):
    """Sends push notifications for actionable state transitions."""

    def __init__(self) -> None:
        self._jwt_token: str | None = None
        self._jwt_token_time: float = 0

    def _get_jwt(self) -> str:
        """Return a cached APNs JWT, refreshing if older than 45 minutes."""
        if self._jwt_token and (time.time() - self._jwt_token_time) < _JWT_REFRESH_SECONDS:
            return self._jwt_token
        with open(APNS_KEY_PATH, "r") as f:
            key = f.read()
        self._jwt_token = jwt.encode(
            {"iss": APNS_TEAM_ID, "iat": int(time.time())},
            key,
            algorithm="ES256",
            headers={"kid": APNS_KEY_ID},
        )
        self._jwt_token_time = time.time()
        log.info("APNs JWT refreshed")
        return self._jwt_token

    def _get_apns_host(self) -> str:
        """Return the APNs hostname for the configured environment."""
        return (
            "api.development.push.apple.com" if APNS_USE_SANDBOX
            else "api.push.apple.com"
        )

    def _build_headers(self, priority: str = "10") -> dict[str, str]:
        """Build APNs request headers with current JWT."""
        return {
            "authorization": f"bearer {self._get_jwt()}",
            "apns-topic": APNS_BUNDLE_ID,
            "apns-push-type": "alert",
            "apns-priority": priority,
            "apns-expiration": str(int(time.time()) + 3600),
        }

    def _send(self, title: str, message: str, priority: str = "10") -> None:
        """Send push notification to all registered devices via APNs HTTP/2."""
        if not APNS_ENABLED:
            log.info(f"[apns disabled] {title}: {message}")
            return

        tokens = _get_device_tokens()
        if not tokens:
            log.info("No device tokens registered — skipping push")
            return

        apns_host = self._get_apns_host()
        headers = self._build_headers(priority)
        payload = {
            "aps": {
                "alert": {"title": title, "body": message},
                "sound": "default",
                "interruption-level": "time-sensitive",
            }
        }

        try:
            with httpx.Client(http2=True) as client:
                for token in tokens:
                    url = f"https://{apns_host}/3/device/{token}"
                    resp = client.post(url, headers=headers, json=payload)
                    if resp.status_code == 200:
                        apns_id = resp.headers.get("apns-id", "unknown")
                        log.info(f"APNs push sent to ...{token[-8:]} (apns-id: {apns_id})")
                    elif resp.status_code == 410:
                        log.warning(f"Token expired: ...{token[-8:]}, marking inactive")
                        _mark_token_inactive(token)
                    else:
                        log.error(f"APNs error {resp.status_code} for ...{token[-8:]}: {resp.text}")
        except httpx.RequestError as e:
            log.error(f"Failed to send APNs push: {e}")

    def notify_state_change(self, old_state: State, new_state: State,
                            data: TransferSwitchData) -> None:
        """Send push notification for actionable state transitions."""
        if new_state == State.OUTAGE:
            self._send(
                "Power Outage",
                f"Utility power lost. Generator is supplying the house.\n"
                f"Generator voltage: {data.emergency_voltage}V",
                priority="10",
            )
        elif new_state == State.CRITICAL:
            self._send(
                "Generator Critical",
                "Utility power is DOWN and generator is NOT running!\n"
                "Immediate attention required.",
                priority="10",
            )
        elif new_state == State.NORMAL and old_state in (State.OUTAGE, State.CRITICAL):
            self._send(
                "Power Restored",
                "Utility power is back. Generator has shut down.\n"
                "Check your weekly exercise schedule — the RDT may have cleared it.",
                priority="5",
            )

    def test_push(self) -> None:
        """Send a test push notification with verbose logging."""
        log.info("=== APNs Test Push ===")
        tokens = _get_device_tokens()
        log.info(f"Device tokens: {len(tokens)} active")
        if not tokens:
            log.error("No active device tokens found — cannot test push")
            return
        for token in tokens:
            log.info(f"  ...{token[-8:]}")

        apns_host = self._get_apns_host()
        log.info(f"APNs host: {apns_host}")
        log.info(f"Bundle ID: {APNS_BUNDLE_ID}")
        log.info(f"Key ID: {APNS_KEY_ID}, Team ID: {APNS_TEAM_ID}")

        headers = self._build_headers("10")
        log.info(f"JWT generated (first 50 chars): {headers['authorization'][7:57]}...")

        payload = {
            "aps": {
                "alert": {"title": "GenStat Test", "body": "Push notification test — if you see this, it works!"},
                "sound": "default",
                "interruption-level": "time-sensitive",
            }
        }
        log.info(f"Payload: {json.dumps(payload)}")

        with httpx.Client(http2=True) as client:
            for token in tokens:
                url = f"https://{apns_host}/3/device/{token}"
                log.info(f"POST {url}")
                resp = client.post(url, headers=headers, json=payload)
                log.info(f"Status: {resp.status_code}")
                log.info(f"Response headers: {dict(resp.headers)}")
                if resp.text:
                    log.info(f"Response body: {resp.text}")
