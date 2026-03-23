"""
APNs push notification notifier.

Sends push notifications to iOS devices via Apple Push Notification service
using HTTP/2 and JWT authentication.
"""

import json
import logging
import os
import time
import urllib.request

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


# ── Device token management ──────────────────────────────────────────────────

def _get_device_tokens():
    """Fetch active device tokens from Supabase."""
    try:
        url = f"{SUPABASE_URL}/rest/v1/device_tokens?active=eq.true&select=token"
        req = urllib.request.Request(url, headers=SUPABASE_HEADERS, method="GET")
        response = urllib.request.urlopen(req, timeout=10)
        rows = json.loads(response.read().decode("utf-8"))
        return [row["token"] for row in rows] if rows else []
    except Exception as e:
        log.error(f"Failed to fetch device tokens: {e}")
        return []


def _mark_token_inactive(token):
    """Mark a device token as inactive in Supabase."""
    try:
        url = f"{SUPABASE_URL}/rest/v1/device_tokens?token=eq.{token}"
        headers = {
            "apikey": SUPABASE_KEY,
            "Content-Type": "application/json",
            "Prefer": "return=minimal",
        }
        data = json.dumps({"active": False}).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers=headers, method="PATCH")
        urllib.request.urlopen(req, timeout=10)
        log.info(f"Marked token ...{token[-8:]} inactive")
    except Exception as e:
        log.error(f"Failed to mark token inactive: {e}")


# ── JWT management ───────────────────────────────────────────────────────────

_apns_token = None
_apns_token_time = 0


def _get_apns_token():
    """Return a cached APNs JWT, refreshing if older than 45 minutes."""
    global _apns_token, _apns_token_time
    import jwt
    if _apns_token and (time.time() - _apns_token_time) < 2700:
        return _apns_token
    with open(APNS_KEY_PATH, "r") as f:
        key = f.read()
    _apns_token = jwt.encode(
        {"iss": APNS_TEAM_ID, "iat": int(time.time())},
        key,
        algorithm="ES256",
        headers={"kid": APNS_KEY_ID},
    )
    _apns_token_time = time.time()
    log.info("APNs JWT refreshed")
    return _apns_token


# ── Send notification ────────────────────────────────────────────────────────

def send_notification(title, message, priority="10"):
    """Send push notification to all registered devices via APNs HTTP/2."""
    if not APNS_ENABLED:
        log.info(f"[apns disabled] {title}: {message}")
        return

    tokens = _get_device_tokens()
    if not tokens:
        log.info("No device tokens registered — skipping push")
        return

    import httpx

    apns_host = (
        "api.development.push.apple.com" if APNS_USE_SANDBOX
        else "api.push.apple.com"
    )
    apns_jwt = _get_apns_token()
    headers = {
        "authorization": f"bearer {apns_jwt}",
        "apns-topic": APNS_BUNDLE_ID,
        "apns-push-type": "alert",
        "apns-priority": priority,
        "apns-expiration": str(int(time.time()) + 3600),
    }
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
                    log.error(f"APNs error {resp.status_code}: {resp.text}")
    except Exception as e:
        log.error(f"Failed to send APNs push: {e}")


# ── Concrete implementation ──────────────────────────────────────────────────

class APNsNotifier(Notifier):
    """Sends push notifications for actionable state transitions."""

    def notify_state_change(self, old_state, new_state, data):
        if new_state == State.OUTAGE:
            send_notification(
                "Power Outage",
                f"Utility power lost. Generator is supplying the house.\n"
                f"Generator voltage: {data.emergency_voltage}V",
                priority="10",
            )
        elif new_state == State.CRITICAL:
            send_notification(
                "Generator Critical",
                "Utility power is DOWN and generator is NOT running!\n"
                "Immediate attention required.",
                priority="10",
            )
        elif new_state == State.NORMAL and old_state in (State.OUTAGE, State.CRITICAL):
            send_notification(
                "Power Restored",
                "Utility power is back. Generator has shut down.\n"
                "Check your weekly exercise schedule — the RDT may have cleared it.",
                priority="5",
            )

    def test_push(self):
        """Send a test push notification with verbose logging."""
        import httpx

        log.info("=== APNs Test Push ===")
        tokens = _get_device_tokens()
        log.info(f"Device tokens from Supabase: {tokens}")
        if not tokens:
            log.error("No active device tokens found — cannot test push")
            return
        apns_host = (
            "api.development.push.apple.com" if APNS_USE_SANDBOX
            else "api.push.apple.com"
        )
        log.info(f"APNs host: {apns_host}")
        log.info(f"Bundle ID: {APNS_BUNDLE_ID}")
        log.info(f"Key ID: {APNS_KEY_ID}, Team ID: {APNS_TEAM_ID}")
        apns_jwt = _get_apns_token()
        log.info(f"JWT generated (first 50 chars): {apns_jwt[:50]}...")
        headers = {
            "authorization": f"bearer {apns_jwt}",
            "apns-topic": APNS_BUNDLE_ID,
            "apns-push-type": "alert",
            "apns-priority": "10",
            "apns-expiration": str(int(time.time()) + 3600),
        }
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
