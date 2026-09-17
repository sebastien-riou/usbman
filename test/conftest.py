"""Fixtures shared by the usbman tests."""

import socket

import pytest
import usbman
from fakehub import FakeHub
from usbman.server import Routing

ALL_OFF = 0x00


@pytest.fixture
def hub(monkeypatch):
    """Replace the serial layer with an in memory hub, all channels off."""
    fake = FakeHub(ALL_OFF)
    monkeypatch.setattr(usbman, 'serial_command_response', fake)
    return fake


@pytest.fixture
def routing():
    """A stream routing, to be installed inside the test with `with routing:`.

    It is not installed here: installing replaces `sys.stdout` and `sys.stderr` process wide,
    and pytest points those back at its own capture when the test body starts, which would
    undo anything a fixture did during setup.
    """
    return Routing()


@pytest.fixture
def free_port():
    """Return a port which was free a moment ago, for a server to bind."""
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        return probe.getsockname()[1]
