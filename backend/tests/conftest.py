"""Unit tests must never reach reservation or notification services."""
import socket

import pytest


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def blocked(*args, **kwargs):
        raise AssertionError("External networking is disabled in unit tests; use an HTTP mock transport")

    monkeypatch.setattr(socket, "getaddrinfo", blocked)
