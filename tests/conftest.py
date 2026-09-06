"""Fixtures for PulsON Alarm tests."""

import pytest

# NOTE: do NOT declare pytest_plugins here. pytest-homeassistant-custom-component
# registers itself through an entry point; declaring it again raises
# "Plugin already registered under a different name".


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Enable loading of the custom integration in every test."""
