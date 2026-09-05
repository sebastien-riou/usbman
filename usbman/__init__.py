import logging
import os
from typing import NamedTuple

import serial.tools.list_ports
from pysatl import Utils

from usbman.clicom import serial_command_response

# The 8 character password field every write command carries. This is the factory default of
# the hubs; the `CP` command changes it, see `OPCODES` below.
PASSWORD = 'pass    '

# Wire commands of the hub, as read out of the vendor CLI `cusbi` v1.03: it is an unstripped
# ELF, so its command strings and the functions using them are readable with `strings` and
# `objdump`. A command is a two character opcode, then the 8 character password field for the
# ones that write, then an optional payload as hex, then a carriage return.
#
# `CP`, which changes the password, is deliberately absent: it takes the very same password
# field as the commands below, so a mistake there locks the hub out for good. Add an opcode
# here only once it has been verified in `cusbi`.
OPCODES = {
    'GP': 'get the channel states',  # cusbi /G, no password
    'SP': 'set the channel states',  # cusbi /S
    'WP': 'save the channel states as the power up states',  # cusbi /W
}

# Number of payload bytes a command carries: 8 channels per byte, little endian, so the 4 bytes
# cover the 32 channels of the largest hubs of the family. Taken from `htos_PS64` in `cusbi`.
PAYLOAD_LEN = 4


def command(opcode: str, payload: bytes = b'') -> str:
    """Return the command string for `opcode`, with its password field and optional payload."""
    if opcode not in OPCODES:
        raise ValueError(f'Refusing to send the unverified command {opcode!r}, see OPCODES')
    # `payload.hex()` and not `Utils.hexstr`, which separates the bytes with spaces.
    return f'{opcode}{PASSWORD}{payload.hex().upper()}\r'


# Failures are reported as 'E' followed by a two character code, 'E01' being a wrong password.
# The length matters: a state reply is 8 hex characters and may well start with an 'E' too,
# since the first byte is always 0x80 or above ('E5FFFFFF' is the perfectly valid state 1,3,6,7).
ERROR_LEN = 3
ERROR_REASONS = {b'E01': 'wrong password'}


def decode_result(res: str) -> int:
    logging.debug(f'res = {res}')
    body = res.strip()
    if body.startswith(b'E') and len(body) == ERROR_LEN:
        reason = ERROR_REASONS.get(body, 'command refused')
        raise RuntimeError(f'Device returned "{res}" ({reason})')
    if res.startswith(b'G'):
        res = res[1:]
    state = res[:2]
    state = state.decode()
    state = Utils.ba(state)
    state = int.from_bytes(state, byteorder='little')
    state &= 0x7F
    logging.debug(f'state = {state}')
    return state


def get_state(device_path) -> int:
    state = serial_command_response(device_path, send_str='GP\r')
    return decode_result(state)


def set_state(device_path, state: int) -> int:
    payload = bytes([0x80 | state]) + b'\xff' * (PAYLOAD_LEN - 1)
    cmd = command('SP', payload)
    logging.debug(f'set state command: {cmd}')
    state = serial_command_response(device_path, send_str=cmd)
    return decode_result(state)


def save_state(device_path) -> int:
    """Store the current channel states as the ones the hub powers up with.

    Return the states the hub reports back. This is what `cusbi /W` does.
    """
    cmd = command('WP')
    logging.debug(f'save state command: {cmd}')
    state = serial_command_response(device_path, send_str=cmd)
    return decode_result(state)


# Channels of a managed hub, channel `n` being the bit `n - 1` of the hub state.
CHANNELS = tuple(range(1, 8))

# USB ids of the hubs known to embed a managed control interface.
# The managed hub appears as one or several plain USB hubs; the control interface is a serial
# chip wired to one of their downstream ports. `lsusb` reports these ids, and `usbman
# --log-level DEBUG` lists the id of the hub each serial device is connected to.
MANAGED_HUB_USB_IDS = frozenset(
    {
        (0x14B0, 0x044A),  # StarTech.com 7 ports managed hub, upstream section
        (0x14B0, 0x044C),  # StarTech.com 7 ports managed hub, downstream section
    }
)

# USB ids of the serial chips used as control interface by the hubs above.
CONTROL_UART_USB_IDS = frozenset(
    {
        (0x0403, 0x6001),  # FTDI FT232R
    }
)

# Downstream port each hub wires its control interface to, when known. This tells the built in
# control interface from a USB to serial adapter plugged into the very same hub, which uses the
# same chips and so is otherwise indistinguishable. Only used to break such a tie, a hub
# missing from this table is still detected as long as it is the only candidate.
CONTROL_UART_HUB_PORTS = {
    (0x14B0, 0x044C): 4,  # StarTech.com 7 ports managed hub
}


class SerialDevice(NamedTuple):
    """A serial device of the system, and where it sits on the USB tree."""

    path: str
    usb_id: tuple[int, int] | None  # ids of the serial device itself
    hub_usb_id: tuple[int, int] | None  # ids of the hub it is connected to
    hub_port: int | None  # downstream port of that hub it is connected to

    def is_hub_control_interface(self) -> bool:
        """Tell whether this device is the control interface of a managed hub.

        Both the serial chip and the hub it hangs on must be known: devices merely plugged
        into a managed hub also have a managed hub as parent, and the same serial chips are
        also used by plain USB to serial cables.
        """
        return self.usb_id in CONTROL_UART_USB_IDS and self.hub_usb_id in MANAGED_HUB_USB_IDS

    def is_on_control_interface_port(self) -> bool:
        """Tell whether this device sits on the port its hub wires its control interface to."""
        return CONTROL_UART_HUB_PORTS.get(self.hub_usb_id) == self.hub_port

    def __str__(self) -> str:
        return (
            f'{self.path} ({usb_id_str(self.usb_id)} on port {self.hub_port} ' f'of hub {usb_id_str(self.hub_usb_id)})'
        )


def usb_id_str(usb_id) -> str:
    """Format a `(vendor, product)` pair the way `lsusb` does."""
    if usb_id is None:
        return 'unknown'
    return f'{usb_id[0]:04x}:{usb_id[1]:04x}'


def read_usb_id(sysfs_dir: str) -> tuple[int, int] | None:
    """Return the `(vendor, product)` ids of the USB device described by `sysfs_dir`.

    Return `None` if `sysfs_dir` does not describe a USB device.
    """
    try:
        with open(os.path.join(sysfs_dir, 'idVendor')) as f:
            vendor = int(f.read(), 16)
        with open(os.path.join(sysfs_dir, 'idProduct')) as f:
            product = int(f.read(), 16)
    except (OSError, ValueError):
        return None
    return (vendor, product)


def read_hub_port(sysfs_dir: str) -> int | None:
    """Return the downstream port of its parent hub the USB device at `sysfs_dir` is on."""
    try:
        with open(os.path.join(sysfs_dir, 'devpath')) as f:
            return int(f.read().strip().rsplit('.', maxsplit=1)[-1])
    except (OSError, ValueError):
        return None


def usb_topology(device_path: str) -> tuple:
    """Return where the serial device at `device_path` sits on the USB tree.

    That is its own USB ids, and the ids and downstream port of the hub it hangs on. All are
    `None` when the topology cannot be read, which is the case on the systems which do not
    expose it in sysfs the way Linux does.
    """
    node = os.path.realpath(os.path.join('/sys/class/tty', os.path.basename(device_path), 'device'))
    # `node` is the USB interface, or a device below it: walk up to the USB device itself.
    while node != '/':
        usb_id = read_usb_id(node)
        if usb_id is not None:
            return (usb_id, read_usb_id(os.path.dirname(node)), read_hub_port(node))
        node = os.path.dirname(node)
    return (None, None, None)


def serial_devices() -> list[SerialDevice]:
    """Return all the serial devices of the system, with their place on the USB tree."""
    devices = []
    for port in serial.tools.list_ports.comports():
        device = SerialDevice(port.device, *usb_topology(port.device))
        logging.debug(f'{device}, {port.description}')
        devices.append(device)
    return devices


def find_device_path() -> str:
    """Return the path of the control interface of the single managed hub of the system.

    Detection relies on USB ids only, so nothing is ever sent to a device which is not a
    managed hub. Raise a `RuntimeError` if the hub cannot be identified with certainty, be it
    because none or several were found.
    """
    devices = serial_devices()
    hubs = [device for device in devices if device.is_hub_control_interface()]
    if len(hubs) > 1:
        # A USB to serial adapter plugged into a managed hub looks just like the control
        # interface of that hub, tell them apart by the port they are on.
        on_control_port = [hub for hub in hubs if hub.is_on_control_interface_port()]
        logging.debug(f'{len(hubs)} candidates, {len(on_control_port)} on a control interface port')
        if len(on_control_port) == 1:
            hubs = on_control_port
    if len(hubs) == 1:
        return hubs[0].path
    if hubs:
        found = ', '.join(str(hub) for hub in hubs)
        raise RuntimeError(f'Several managed USB hubs found ({found}), use --device-path to select one')
    seen = ', '.join(str(device) for device in devices) if devices else 'none'
    raise RuntimeError(
        f'No managed USB hub found among the serial devices of the system ({seen}), '
        f'use --device-path to specify the serial device'
    )
