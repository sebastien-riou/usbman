"""Fixtures shared by the usbman tests."""

import os
import socket
import types

import fakesysfs
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


# What the fake tree is wired as, matching fakesysfs.DEVICES: the ST-LINK and the control
# interface sit on ports 1 and 4 of the downstream section, the Pico on port 2 of the upstream
# one. Stands in for the measured table while CHANNEL_PORTS is still empty.
FAKE_CHANNEL_PORTS = {
    (0x14B0, 0x044C): {1: 1, 2: 2, 3: 3, 7: 4},
    (0x14B0, 0x044A): {4: 1, 5: 2, 6: 3},
}


@pytest.fixture
def sysfs(tmp_path, monkeypatch):
    """Point usbman at a fake USB tree, and give it a channel table to look things up in."""
    tty_sysfs, usb_sysfs, dev = fakesysfs.build(str(tmp_path))
    monkeypatch.setattr(usbman, 'TTY_SYSFS', tty_sysfs)
    monkeypatch.setattr(usbman, 'USB_SYSFS', usb_sysfs)
    monkeypatch.setattr(usbman, 'CHANNEL_PORTS', FAKE_CHANNEL_PORTS)
    # No test may touch the real snapshot, so point it into the temporary directory too.
    monkeypatch.setenv(usbman.USBMAN_DIR_ENV, str(tmp_path))
    snapshot = usbman.snapshot_path()
    nicknames = usbman.nicknames_path()
    return types.SimpleNamespace(
        tty=tty_sysfs,
        usb=usb_sysfs,
        dev=dev,
        snapshot=snapshot,
        nicknames=nicknames,
        path=lambda n: os.path.join(dev, n),
    )
