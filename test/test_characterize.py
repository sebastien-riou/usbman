"""Working out a hub's wiring with one peripheral, without a hub."""

import time

import pytest
import usbman
from fakehub import FakeHub

UPSTREAM = (0x14B0, 0x044A)
DOWNSTREAM = (0x14B0, 0x044C)


class OneSocket:
    """A fake USB tree holding one peripheral, in a socket the test chooses.

    `slow` is how many seconds it takes to appear after being powered, the way a Numaker M5531
    takes several, which is what broke measuring every socket at once.
    """

    def __init__(self, hub, channel, hub_usb_id, port, slow=0.0):
        self.hub = hub
        self.channel = channel
        self.hub_usb_id = hub_usb_id
        self.port = port
        self.slow = slow
        self.powered_since = None

    def move_to(self, channel, hub_usb_id, port):
        self.channel, self.hub_usb_id, self.port = channel, hub_usb_id, port
        self.powered_since = None

    def __call__(self):
        if not self.hub.state & (1 << (self.channel - 1)):
            self.powered_since = None
            return {}
        if self.powered_since is None:
            self.powered_since = time.monotonic()
        if time.monotonic() - self.powered_since >= self.slow:
            return {self.hub_usb_id: {self.port}}
        return {}


def prompter(answers):
    """A `prompt` which replays answers, so the loop can be driven without a terminal."""
    return lambda label: answers.get(label, 'stop')


@pytest.fixture
def hub(monkeypatch):
    fake = FakeHub(0x00)
    monkeypatch.setattr(usbman, 'serial_command_response', fake)
    return fake


def test_one_socket_is_identified(hub, monkeypatch):
    monkeypatch.setattr(usbman, 'occupied_hub_ports', OneSocket(hub, channel=6, hub_usb_id=DOWNSTREAM, port=3))
    sockets = usbman.characterize_hub('/dev/fake', prompter({1: 'go'}), settle=0)
    assert sockets == [usbman.Socket(label=1, channel=6, hub_usb_id=DOWNSTREAM, port=3)]


def test_a_slow_peripheral_is_still_identified(hub, monkeypatch):
    """The failure that broke the all-at-once version: a board slow to enumerate."""
    tree = OneSocket(hub, channel=5, hub_usb_id=UPSTREAM, port=2, slow=0.1)
    monkeypatch.setattr(usbman, 'occupied_hub_ports', tree)
    sockets = usbman.characterize_hub('/dev/fake', prompter({1: 'go'}), settle=0.3)
    assert sockets[0].channel == 5


def test_the_peripheral_is_followed_from_socket_to_socket(hub, monkeypatch):
    tree = OneSocket(hub, channel=1, hub_usb_id=DOWNSTREAM, port=1)
    monkeypatch.setattr(usbman, 'occupied_hub_ports', tree)
    moves = {1: (1, DOWNSTREAM, 1), 2: (6, DOWNSTREAM, 3), 3: (5, UPSTREAM, 2)}

    def prompt(label):
        if label not in moves:
            return 'stop'
        tree.move_to(*moves[label])
        return 'go'

    sockets = usbman.characterize_hub('/dev/fake', prompt, settle=0)
    assert [(s.label, s.channel, s.port) for s in sockets] == [(1, 1, 1), (2, 6, 3), (3, 5, 2)]
    assert usbman.channel_ports_table(sockets) == {DOWNSTREAM: {1: 1, 6: 3}, UPSTREAM: {5: 2}}


def test_a_channel_already_found_is_not_tried_again(hub, monkeypatch):
    """Each channel belongs to one socket, so once placed it is out of the running."""
    tree = OneSocket(hub, channel=1, hub_usb_id=DOWNSTREAM, port=1)
    monkeypatch.setattr(usbman, 'occupied_hub_ports', tree)

    def prompt(label):
        if label > 2:
            return 'stop'
        tree.move_to(7, DOWNSTREAM, 4) if label == 2 else None
        return 'go'

    sockets = usbman.characterize_hub('/dev/fake', prompt, settle=0)
    assert [s.channel for s in sockets] == [1, 7]


def test_an_empty_socket_is_reported_rather_than_guessed(hub, monkeypatch):
    monkeypatch.setattr(usbman, 'occupied_hub_ports', lambda: {})
    said = []
    sockets = usbman.characterize_hub('/dev/fake', prompter({1: 'go'}), settle=0, on_progress=said.append)
    assert sockets == [usbman.Socket(label=1, channel=None, hub_usb_id=None, port=None)]
    assert any('nothing switched off anything' in line for line in said)


def test_skip_and_stop_are_obeyed(hub, monkeypatch):
    monkeypatch.setattr(usbman, 'occupied_hub_ports', OneSocket(hub, channel=2, hub_usb_id=UPSTREAM, port=2))
    sockets = usbman.characterize_hub('/dev/fake', prompter({1: 'skip', 2: 'go', 3: 'stop'}), settle=0)
    assert [s.label for s in sockets] == [2]


def test_it_restores_the_channels_it_found(hub, monkeypatch):
    monkeypatch.setattr(usbman, 'occupied_hub_ports', OneSocket(hub, channel=1, hub_usb_id=DOWNSTREAM, port=1))
    hub.state = 0x25
    usbman.characterize_hub('/dev/fake', prompter({1: 'go'}), settle=0)
    assert hub.state == 0x25


def test_it_restores_them_even_when_it_fails(hub, monkeypatch):
    hub.state = 0x12

    def explode():
        raise OSError('the tree went away')

    monkeypatch.setattr(usbman, 'occupied_hub_ports', explode)
    with pytest.raises(OSError):
        usbman.characterize_hub('/dev/fake', prompter({1: 'go'}), settle=0)
    assert hub.state == 0x12


def test_the_peripheral_is_put_back_after_each_try(hub, monkeypatch):
    """It is only off for as long as it takes to notice, not for the whole sweep."""
    tree = OneSocket(hub, channel=7, hub_usb_id=DOWNSTREAM, port=4)
    monkeypatch.setattr(usbman, 'occupied_hub_ports', tree)
    usbman.characterize_hub('/dev/fake', prompter({1: 'go'}), settle=0)
    # channel 7 is tried last, so every earlier channel must have been switched back on
    assert hub.state == 0x00  # the state it started from, restored at the end
