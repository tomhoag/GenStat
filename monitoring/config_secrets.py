"""
Configuration and secrets loader for the generator monitoring system.

Loads two configuration sources:
- monitor.conf    — INI file with operational settings (committed to repo)
- Secrets.xcconfig — credentials for Supabase (gitignored, manually created)
"""
from __future__ import annotations

import configparser
import os

_script_dir = os.path.dirname(os.path.abspath(__file__))


# ── monitor.conf ─────────────────────────────────────────────────────────────

def load_config() -> configparser.ConfigParser:
    """Load monitor.conf from the monitoring directory."""
    config_path = os.path.join(_script_dir, "monitor.conf")
    if not os.path.exists(config_path):
        raise FileNotFoundError(
            f"monitor.conf not found at {config_path}\n"
            "This file should be in the monitoring/ directory."
        )
    config = configparser.ConfigParser()
    config.read(config_path)
    return config


config = load_config()


# ── Secrets.xcconfig ─────────────────────────────────────────────────────────

def load_secrets() -> dict[str, str]:
    """
    Parse Secrets.xcconfig from the project root and return a dict of key->value.
    The file format is one assignment per line:  KEY = value
    Lines starting with // are comments and are ignored.
    """
    secrets_path = os.path.normpath(os.path.join(_script_dir, "..", "Secrets.xcconfig"))

    if not os.path.exists(secrets_path):
        raise FileNotFoundError(
            f"Secrets.xcconfig not found at {secrets_path}\n"
            "Copy Secrets.xcconfig.template to Secrets.xcconfig and fill in your values."
        )

    secrets = {}
    with open(secrets_path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("//"):
                continue
            if "=" in line:
                key, _, value = line.partition("=")
                # Strip $() escapes used in xcconfig to prevent // being
                # treated as a comment (e.g. https:/$()/host -> https://host)
                secrets[key.strip()] = value.strip().replace("$()", "")
    return secrets


_secrets = load_secrets()


def require_secret(key: str) -> str:
    """Get a secret value or raise ValueError if missing/placeholder."""
    value = _secrets.get(key, "")
    if not value or value.startswith("<"):
        raise ValueError(
            f"Secret '{key}' is missing or still set to a placeholder value in Secrets.xcconfig."
        )
    return value
