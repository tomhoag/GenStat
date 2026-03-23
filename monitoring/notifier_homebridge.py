"""
Homebridge webhook notifier.

Updates HomeKit occupancy sensors via the homebridge-http-webhooks plugin
to reflect generator state in the iOS Home app.
"""

import logging

import httpx

from interfaces import Notifier, State, TransferSwitchData

log = logging.getLogger(__name__)


class HomebridgeNotifier(Notifier):
    """Updates Homebridge occupancy sensors on every state change."""

    def __init__(self, host: str = "192.168.1.35", port: int = 51828, enabled: bool = True,
                 generator_id: str = "generator_active", utility_id: str = "utility_power") -> None:
        self.enabled = enabled
        self.url = f"http://{host}:{port}"
        self.generator_id = generator_id
        self.utility_id = utility_id

    def notify_state_change(self, old_state: State, new_state: State,
                            data: TransferSwitchData) -> None:
        """Update Homebridge occupancy sensors for every state change."""
        state_map = {
            State.NORMAL:      (False, True),   # generator off, utility on
            State.WEEKLY_TEST: (True,  True),   # generator on,  utility on
            State.OUTAGE:      (True,  False),  # generator on,  utility off
            State.CRITICAL:    (False, False),  # generator off,  utility off
        }
        gen_state, util_state = state_map.get(new_state, (False, False))
        self._update(self.generator_id, gen_state)
        self._update(self.utility_id, util_state)

    def _update(self, accessory_id: str, state: bool) -> None:
        if not self.enabled:
            log.info(f"[homebridge disabled] {accessory_id} = {state}")
            return
        state_str = "true" if state else "false"
        url = f"{self.url}/?accessoryId={accessory_id}&state={state_str}"
        try:
            resp = httpx.get(url, timeout=5)
            resp.raise_for_status()
            log.info(f"Homebridge updated: {accessory_id} = {state_str}")
        except httpx.HTTPStatusError as e:
            log.error(f"Homebridge update failed ({e.response.status_code}): {accessory_id}")
        except httpx.RequestError as e:
            log.error(f"Homebridge update failed (network): {e}")
