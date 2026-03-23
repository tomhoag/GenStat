"""
Shared types and abstract interfaces for the generator monitoring system.

This module defines the data structures and ABCs that all layers depend on:
- State enum and display messages
- TransferSwitchData container
- TransferSwitchReader, PersistenceBackend, and Notifier ABCs
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from enum import Enum


class State(Enum):
    UNKNOWN     = "unknown"
    NORMAL      = "normal"
    WEEKLY_TEST = "weekly_test"
    OUTAGE      = "outage"
    CRITICAL    = "critical"


STATE_MESSAGES = {
    State.NORMAL      : "✅ Normal — utility power, generator idle",
    State.WEEKLY_TEST : "🔄 Weekly test — generator running, utility present",
    State.OUTAGE      : "⚡ Outage — generator supplying house",
    State.CRITICAL    : "🚨 CRITICAL — utility down AND generator not running!",
}


class TransferSwitchData:
    """Parsed data from one status block."""

    def __init__(self):
        self.normal_voltage      = None   # float, utility volts
        self.normal_frequency    = None   # float, utility Hz
        self.emergency_voltage   = None   # float, generator volts
        self.emergency_frequency = None   # float, generator Hz
        self.position            = None   # "normal" or "emergency"
        self.exerciser_active    = False
        self.test_mode_active    = False

    def __repr__(self):
        return (
            f"TransferSwitchData("
            f"utility={self.normal_voltage}V, "
            f"generator={self.emergency_voltage}V, "
            f"position={self.position}, "
            f"exercise={self.exerciser_active}, "
            f"test={self.test_mode_active})"
        )


class TransferSwitchReader(ABC):
    """Interface for reading generator/transfer switch status."""

    @abstractmethod
    def read_status(self) -> "TransferSwitchData | None":
        """Read and return parsed transfer switch data, or None on failure."""
        ...

    @abstractmethod
    def determine_state(self, data: TransferSwitchData) -> State:
        """Map parsed data to a State enum value."""
        ...

    @abstractmethod
    def close(self) -> None:
        """Release hardware resources."""
        ...


class PersistenceBackend(ABC):
    """Interface for storing state changes, events, and device tokens."""

    @abstractmethod
    def publish_state_change(self, old_state: State, new_state: State,
                             data: TransferSwitchData, duration_seconds: int) -> None:
        """Record a state transition."""
        ...

    @abstractmethod
    def get_device_tokens(self) -> list[str]:
        """Return a list of active device tokens for push notifications."""
        ...

    @abstractmethod
    def mark_token_inactive(self, token: str) -> None:
        """Mark a device token as no longer valid."""
        ...


class Notifier(ABC):
    """Interface for sending notifications on state changes."""

    @abstractmethod
    def notify_state_change(self, old_state: State, new_state: State,
                            data: TransferSwitchData) -> None:
        """Send notification appropriate for this state transition."""
        ...
