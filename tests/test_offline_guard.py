"""Proves the offline guard actually fires (CLAUDE.md: tests must run fully
offline). Without a test proving the guard works, "run with network
disabled" (PROJECT_SPEC.md §M2's acceptance criterion) would rely on a
human remembering to unplug the network by hand.
"""

from __future__ import annotations

import socket

import pytest

from tests.conftest import OfflineGuardError


def test_create_connection_is_blocked() -> None:
    with pytest.raises(OfflineGuardError, match="example.com"):
        socket.create_connection(("example.com", 80))


def test_socket_connect_is_blocked() -> None:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        with pytest.raises(OfflineGuardError, match="1.2.3.4"):
            sock.connect(("1.2.3.4", 443))
    finally:
        sock.close()


def test_guard_fails_the_test_rather_than_skipping() -> None:
    """A guard that downgrades to `pytest.skip` would make the offline
    guarantee unenforced by default -- assert it is a hard exception, not a
    skip outcome.
    """
    with pytest.raises(OfflineGuardError):
        socket.create_connection(("example.com", 80))
    assert not issubclass(OfflineGuardError, pytest.skip.Exception)
