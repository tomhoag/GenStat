"""Tests for config_secrets.py — configuration and secrets loading."""

import configparser
import os
import pytest

from config_secrets import load_config, load_secrets, require_secret, config


class TestLoadConfig:

    def test_returns_config_parser(self):
        result = load_config()
        assert isinstance(result, configparser.ConfigParser)

    def test_has_required_sections(self):
        result = load_config()
        assert result.has_section("serial")
        assert result.has_section("monitor")
        assert result.has_section("apns")
        assert result.has_section("network")

    def test_serial_values(self):
        result = load_config()
        assert result.get("serial", "port") == "/dev/ttyUSB0"
        assert result.getint("serial", "baud_rate") == 19200

    def test_module_level_config_is_loaded(self):
        """The module-level `config` singleton should already be populated."""
        assert config.has_section("serial")


class TestLoadSecrets:

    def test_returns_dict(self):
        result = load_secrets()
        assert isinstance(result, dict)

    def test_contains_supabase_keys(self):
        result = load_secrets()
        assert "SUPABASE_URL" in result
        assert "SUPABASE_KEY" in result

    def test_strips_xcconfig_escapes(self):
        """$() escapes should be removed from values."""
        result = load_secrets()
        for value in result.values():
            assert "$()" not in value


class TestRequireSecret:

    def test_missing_key_raises(self):
        with pytest.raises(ValueError, match="missing"):
            require_secret("TOTALLY_FAKE_KEY_THAT_DOES_NOT_EXIST")

    def test_placeholder_value_raises(self):
        """Values starting with '<' are treated as unfilled placeholders."""
        # This tests the logic — the actual secrets file may or may not
        # have placeholders, so we test via the function's behavior
        import config_secrets
        original = config_secrets._secrets.copy()
        try:
            config_secrets._secrets["_TEST_KEY"] = "<placeholder>"
            with pytest.raises(ValueError, match="placeholder"):
                require_secret("_TEST_KEY")
        finally:
            config_secrets._secrets = original
