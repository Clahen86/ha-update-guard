"""Fixtures for Update Guard tests."""

import re

import pytest


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield


@pytest.fixture(autouse=True)
def github_fallback(aioclient_mock):
    """Anything on GitHub a test didn't mock answers 404 ("nothing known"). Mocks added later still win."""
    aioclient_mock.get(re.compile(r"https://api\.github\.com/.*"), status=404)
    aioclient_mock.get(re.compile(r"https://raw\.githubusercontent\.com/.*"), status=404)
    fallbacks = 2
    original = aioclient_mock.request

    def request(*args, **kwargs):
        original(*args, **kwargs)
        aioclient_mock._mocks.insert(len(aioclient_mock._mocks) - 1 - fallbacks, aioclient_mock._mocks.pop())

    aioclient_mock.request = request
    yield
