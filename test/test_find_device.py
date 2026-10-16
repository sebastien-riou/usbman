"""Picking the hub's control interface out of the system's serial devices.

A board plugged into one of the hub's sockets can enumerate as the same chip the control
interface uses, so its own USB ids prove nothing. The port it sits on is what tells them apart.
"""

import os

import fakesysfs
import pytest
import usbman

# The real control interface: port 4 of the downstream section, which no socket reaches.
REAL = {
    '0': (0x1D6B, 0x0002, None, 'xHCI Host Controller'),
    '1.2': (0x14B0, 0x044A, '000000000', 'USB2.0 4 Port HUB'),
    '1.2.4': (0x14B0, 0x044C, '000000000', 'USB2.0 4 Port HUB'),
    '1.2.4.4': (0x0403, 0x6001, 'B001DNH6', 'FT232R USB UART'),
}
# A board on socket 2 of the downstream section, claiming to be an FT232R.
IMPOSTOR_DOWNSTREAM = {'1.2.4.2': (0x0403, 0x6001, 'FAKE0001', 'FT232R USB UART')}
# And one on a socket of the upstream section, which has no control interface at all.
IMPOSTOR_UPSTREAM = {'1.2.1': (0x0403, 0x6001, 'FAKE0002', 'FT232R USB UART')}


def tree(monkeypatch, tmp_path, devices, ttys):
    """Point usbman at a fake USB tree, and at the ttys of the devices in it."""
    tty_sysfs, usb_sysfs, _ = fakesysfs.build(str(tmp_path), devices=devices, ttys=ttys)
    monkeypatch.setattr(usbman, 'TTY_SYSFS', tty_sysfs)
    monkeypatch.setattr(usbman, 'USB_SYSFS', usb_sysfs)

    class Port:
        def __init__(self, name):
            self.device = os.path.join('/dev', name)
            self.description = devices[ttys[name]][3]

    monkeypatch.setattr(usbman.list_ports, 'comports', lambda: [Port(name) for name in ttys])


def test_the_real_control_interface_is_found(monkeypatch, tmp_path):
    tree(monkeypatch, tmp_path, REAL, {'ttyUSB0': '1.2.4.4'})
    assert usbman.find_device_path() == '/dev/ttyUSB0'


def test_an_impostor_on_a_socket_is_refused_when_it_is_alone(monkeypatch, tmp_path):
    """The bug: with the real one absent, a board on a socket used to be accepted."""
    devices = {k: v for k, v in REAL.items() if k != '1.2.4.4'} | IMPOSTOR_DOWNSTREAM
    tree(monkeypatch, tmp_path, devices, {'ttyUSB0': '1.2.4.2'})
    with pytest.raises(RuntimeError, match='No managed USB hub'):
        usbman.find_device_path()


def test_an_impostor_on_the_upstream_section_is_refused_when_it_is_alone(monkeypatch, tmp_path):
    """That section has no control interface at all, so no port on it can be one."""
    devices = {k: v for k, v in REAL.items() if k != '1.2.4.4'} | IMPOSTOR_UPSTREAM
    tree(monkeypatch, tmp_path, devices, {'ttyUSB0': '1.2.1'})
    with pytest.raises(RuntimeError, match='No managed USB hub'):
        usbman.find_device_path()


def test_the_impostor_loses_to_the_real_one(monkeypatch, tmp_path):
    devices = REAL | IMPOSTOR_DOWNSTREAM
    tree(monkeypatch, tmp_path, devices, {'ttyUSB0': '1.2.4.2', 'ttyUSB1': '1.2.4.4'})
    assert usbman.find_device_path() == '/dev/ttyUSB1'


def test_the_refused_candidates_are_named(monkeypatch, tmp_path):
    """Saying only "none found" would hide the interesting part."""
    devices = {k: v for k, v in REAL.items() if k != '1.2.4.4'} | IMPOSTOR_DOWNSTREAM
    tree(monkeypatch, tmp_path, devices, {'ttyUSB0': '1.2.4.2'})
    with pytest.raises(RuntimeError) as refused:
        usbman.find_device_path()
    assert '/dev/ttyUSB0' in str(refused.value)
    assert '--device' in str(refused.value)  # the way to override it anyway


def test_a_hub_model_with_no_known_port_is_left_as_it_was(monkeypatch, tmp_path):
    """An unknown model has nothing to check against, so it keeps today's behaviour."""
    devices = {
        '0': (0x1D6B, 0x0002, None, 'xHCI Host Controller'),
        '1.2': (0x14B0, 0x044A, '000000000', 'USB2.0 4 Port HUB'),
        '1.2.4': (0x14B0, 0x044C, '000000000', 'USB2.0 4 Port HUB'),
        '1.2.4.2': (0x0403, 0x6001, 'ONLYONE', 'FT232R USB UART'),
    }
    monkeypatch.setattr(usbman, 'CONTROL_UART_HUB_PORTS', {})
    tree(monkeypatch, tmp_path, devices, {'ttyUSB0': '1.2.4.2'})
    assert usbman.find_device_path() == '/dev/ttyUSB0'
