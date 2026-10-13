"""Resolving a device reference to the channel which powers it."""

import os

import fakesysfs
import pytest
import usbman
from conftest import FAKE_CHANNEL_PORTS

STLINK_SERIAL = '004B00283532510831333430'
BY_ID = 'usb-STMicroelectronics_STLINK-V3_004B00283532510831333430-if01'


def test_the_three_references_agree(sysfs):
    """A device path, a by-id symlink and a serial number must name the same channel."""
    by_path = usbman.channel_of(sysfs.path('ttyACM0'))
    by_link = usbman.channel_of(os.path.join(sysfs.dev, 'serial', 'by-id', BY_ID))
    by_serial = usbman.channel_of(STLINK_SERIAL)
    assert by_path == by_link == by_serial == 1


def test_a_device_several_hubs_deep_resolves(sysfs):
    """The ST-LINK hangs off a Genesys hub, which hangs off the managed hub: port 1, channel 1."""
    hub_usb_id, port = usbman.usb_chain(usbman.usb_node(STLINK_SERIAL))
    assert (hub_usb_id, port) == ((0x14B0, 0x044C), 1)


def test_a_device_straight_on_the_hub_resolves(sysfs):
    assert usbman.channel_of('648326155B4B110B') == 5  # the Pico, port 2 of the upstream section
    assert usbman.channel_of(sysfs.path('ttyUSB0')) == 7  # the control interface, port 4


def test_everything_behind_one_socket_is_one_channel(sysfs):
    """A socket may hold a whole tree of hubs, and its channel switches all of it at once."""
    # The ST-LINK and the FTDI sit on different branches of the Genesys hubs behind socket 1.
    assert usbman.channel_of(STLINK_SERIAL) == 1
    assert usbman.channel_of('FT1234XZ') == 1
    assert usbman.channel_of(sysfs.path('ttyUSB1')) == 1


def test_a_device_not_behind_a_managed_hub_is_refused(sysfs):
    with pytest.raises(RuntimeError, match='not connected to a managed hub'):
        usbman.channel_of(sysfs.path('ttyACM9'))


def test_an_unknown_serial_is_refused(sysfs):
    with pytest.raises(RuntimeError, match="serial number 'NOSUCH'"):
        usbman.channel_of('NOSUCH')


def test_an_ambiguous_serial_is_refused_naming_the_matches(sysfs):
    """Both hub sections report 000000000, as they really do. Picking one would be a guess."""
    with pytest.raises(RuntimeError, match='shared by 2 devices') as refused:
        usbman.channel_of('000000000')
    assert '14b0:044a' in str(refused.value)
    assert '14b0:044c' in str(refused.value)


def test_a_path_which_is_not_a_device_is_refused(sysfs):
    with pytest.raises(RuntimeError, match='not a USB device'):
        usbman.channel_of(sysfs.path('ttyNOPE'))


def test_an_unknown_hub_model_names_characterize(sysfs, monkeypatch):
    monkeypatch.setattr(usbman, 'CHANNEL_PORTS', {})
    with pytest.raises(RuntimeError, match='--characterize'):
        usbman.channel_of(STLINK_SERIAL)


def test_a_port_no_channel_switches_says_so_rather_than_naming_characterize(sysfs, monkeypatch):
    """With a known model the table is complete, so a missing port is unswitched, not unmeasured."""
    monkeypatch.setattr(usbman, 'CHANNEL_PORTS', {(0x14B0, 0x044C): {2: 2}})
    with pytest.raises(RuntimeError, match='no channel switches'):
        usbman.channel_of(STLINK_SERIAL)  # it is on port 1, which that table does not mention


def test_the_control_interface_is_named_as_such(sysfs, monkeypatch):
    """Port 4 of the downstream section is the hub's own FT232R, deliberately unswitched."""
    monkeypatch.setattr(usbman, 'CHANNEL_PORTS', {(0x14B0, 0x044C): {4: 1}})
    with pytest.raises(RuntimeError, match='control interface'):
        usbman.channel_of('B001DNH6')


def test_the_hub_itself_is_not_a_device_on_a_socket(tmp_path, monkeypatch):
    """Naming the hub rather than something plugged into one of its sockets should say so."""
    devices = dict(fakesysfs.DEVICES)
    devices['1.2'] = (0x14B0, 0x044A, 'HUBSERIAL', 'USB2.0 4 Port HUB')  # unique, so nameable
    tty_sysfs, usb_sysfs, _ = fakesysfs.build(str(tmp_path), devices=devices)
    monkeypatch.setattr(usbman, 'TTY_SYSFS', tty_sysfs)
    monkeypatch.setattr(usbman, 'USB_SYSFS', usb_sysfs)
    monkeypatch.setattr(usbman, 'CHANNEL_PORTS', FAKE_CHANNEL_PORTS)
    with pytest.raises(RuntimeError, match='the managed hub itself'):
        usbman.channel_of('HUBSERIAL')


def test_occupied_hub_ports_sees_only_managed_hub_children(sysfs):
    occupied = usbman.occupied_hub_ports()
    assert occupied == {(0x14B0, 0x044A): {2, 4}, (0x14B0, 0x044C): {1, 4}}


def test_the_committed_channel_table_is_well_formed():
    """Guards the one thing a human pastes in by hand, once --characterize has been run."""
    for hub_usb_id, ports in usbman.CHANNEL_PORTS.items():
        assert hub_usb_id in usbman.MANAGED_HUB_USB_IDS
        assert all(channel in usbman.CHANNELS for channel in ports)
        assert len(set(ports.values())) == len(ports), f'two channels claim one port on {hub_usb_id}'
