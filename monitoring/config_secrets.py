"""
Shared secrets loader for the generator monitoring system.

Parses credentials from Secrets.xcconfig in the project root.
Used by both the persistence and notification layers.
"""

import os


def load_secrets():
    """
    Parse Secrets.xcconfig from the project root and return a dict of key→value.
    The file format is one assignment per line:  KEY = value
    Lines starting with // are comments and are ignored.
    """
    script_dir   = os.path.dirname(os.path.abspath(__file__))
    secrets_path = os.path.join(script_dir, "..", "Secrets.xcconfig")
    secrets_path = os.path.normpath(secrets_path)

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
                # treated as a comment (e.g. https:/$()/host → https://host)
                secrets[key.strip()] = value.strip().replace("$()", "")
    return secrets


_secrets = load_secrets()


def require_secret(key):
    """Get a secret value or raise ValueError if missing/placeholder."""
    value = _secrets.get(key, "")
    if not value or value.startswith("<"):
        raise ValueError(
            f"Secret '{key}' is missing or still set to a placeholder value in Secrets.xcconfig."
        )
    return value
