import importlib.metadata
import logging
import os
import time
from typing import NamedTuple

from serial.tools import list_ports

from usbman.clicom import serial_command_response

try:
    __version__ = importlib.metadata.version('usbman')
except importlib.metadata.PackageNotFoundError:
    # Run straight from a source tree, never installed, so there is no metadata to read. The
    # frozen binary carries it: see `copy_metadata` in __main__.spec.
    __version__ = 'unknown'

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
    return f'{opcode}{PASSWORD}{payload.hex().upper()}\r'


# Failures are reported as 'E' followed by a two character code, 'E01' being a wrong password.
# The length matters: a state reply is 8 hex characters and may well start with an 'E' too,
# since the first byte is always 0x80 or above ('E5FFFFFF' is the perfectly valid state 1,3,6,7).
ERROR_LEN = 3
ERROR_REASONS = {b'E01': 'wrong password'}


def reply_body(res: bytes) -> bytes:
    """Return a reply without its line ending, raising if it is empty or reports a failure."""
    body = res.strip()
    if 0 == len(body):
        raise RuntimeError('Device did not answer')
    if body.startswith(b'E') and len(body) == ERROR_LEN:
        reason = ERROR_REASONS.get(body, 'command refused')
        raise RuntimeError(f'Device returned "{res}" ({reason})')
    return body


def decode_result(res: bytes) -> int:
    """Return the channel states a reply carries, with or without a leading 'G'."""
    logging.debug(f'res = {res}')
    body = reply_body(res)
    if body.startswith(b'G'):
        body = body[1:]
    # The first byte is the channel bitmap; bit 7 is channel 8, which a 7 channel hub has not.
    try:
        state = int(body[:2], 16) & 0x7F
    except ValueError:
        # A RuntimeError, which the command line reports, rather than a traceback.
        raise RuntimeError(f'Device returned "{res}", which holds no channel states') from None
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


def save_state(device_path) -> None:
    """Store the current channel states as the ones the hub powers up with.

    The hub acknowledges with a bare `G\\r\\n` which carries no states. `cusbi /W` checks for a
    wrong password, then for that `G`, and reads nothing else; so does this.
    """
    cmd = command('WP')
    logging.debug(f'save state command: {cmd}')
    res = serial_command_response(device_path, send_str=cmd)
    logging.debug(f'res = {res}')
    if not reply_body(res).startswith(b'G'):
        raise RuntimeError(f'Device returned "{res}" instead of confirming the save')


# Channels of a managed hub, channel `n` being the bit `n - 1` of the hub state.
CHANNELS = tuple(range(1, 8))

# How long to allow for a device to vanish once its power is cut. Unlike enumeration, which is
# slow and is what `--settle` is for, a disconnect is noticed in milliseconds, so trying a
# channel which turns out to switch nothing costs this rather than a full settle.
DISCONNECT_WAIT = 1.0

# What usbman writes goes in the XDG state directory. The nicknames, which you write and usbman
# only reads, are looked for in the XDG config directory first and beside the snapshot second,
# so that honouring the specification and keeping both files in one place are both possible.
# `USBMAN_DIR` overrides the lot and is then the only place looked at.
USBMAN_DIR_ENV = 'USBMAN_DIR'

# Where the USB tree is read from. Module level so the tests can point them at a fake tree.
TTY_SYSFS = '/sys/class/tty'
USB_SYSFS = '/sys/bus/usb/devices'

# Where udev keeps the stable names of the serial ports. Unlike a `/dev/ttyACM0`, these are
# made of the manufacturer, product and serial number, so they survive re-plugging.
SERIAL_BY_ID = '/dev/serial/by-id'

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

# Downstream port each hub section wires its control interface to, `None` for a section which
# wires none. This is what tells the built in control interface from anything plugged into one
# of the hub's own sockets: the chip ids are a claim any device can make, and a device on a
# socket has a managed hub as its parent just as the real one does.
#
# List every section of a model you add, so that a port on it can be checked. A section missing
# from here cannot be checked at all, and anything claiming to be a control interface on it is
# taken at its word.
CONTROL_UART_HUB_PORTS = {
    (0x14B0, 0x044A): None,  # StarTech.com 7 ports managed hub, upstream section: wires none
    (0x14B0, 0x044C): 4,  # StarTech.com 7 ports managed hub, downstream section
}

# Downstream port each channel switches, by hub section: channel -> port. Fixed by the wiring
# inside the hub, so it is the same on every unit of a model and is not configuration. Measured
# once per model with `usbman --characterize`; see "Which port each channel switches" in NOTES.md
# for the procedure and for what is known about each model.
#
# A model missing or empty here is an error naming `--characterize`, never a guess.
CHANNEL_PORTS = {
    # StarTech.com 7 ports managed hub. Sockets 1 to 6 on the case are channels 1 to 6, three
    # on each section in order. Channel 7 switches no port anything enumerates on; see NOTES.md.
    (0x14B0, 0x044A): {1: 1, 2: 2, 3: 3},  # upstream section, port 4 cascades to the next
    (0x14B0, 0x044C): {4: 1, 5: 2, 6: 3},  # downstream section, port 4 is the control interface
}


class SerialDevice(NamedTuple):
    """A serial device of the system, and where it sits on the USB tree."""

    path: str
    usb_id: tuple[int, int] | None  # ids of the serial device itself
    hub_usb_id: tuple[int, int] | None  # ids of the hub it is connected to
    hub_port: int | None  # downstream port of that hub it is connected to

    def is_hub_control_interface(self) -> bool:
        """Tell whether this device claims to be the control interface of a managed hub.

        A claim, not a finding: both the serial chip and the hub it hangs on must be known, but
        the same chips are used by plain USB to serial cables, and firmware on a board plugged
        into one of the hub's sockets can report them too — its parent is then a managed hub
        just as the real control interface's is. `is_on_control_interface_port` settles it.
        """
        return self.usb_id in CONTROL_UART_USB_IDS and self.hub_usb_id in MANAGED_HUB_USB_IDS

    def is_on_control_interface_port(self) -> bool:
        """Tell whether the port this device is on could carry its hub's control interface.

        True for a hub section which is not in `CONTROL_UART_HUB_PORTS`, since there is then
        nothing to check the port against.
        """
        if self.hub_usb_id not in CONTROL_UART_HUB_PORTS:
            return True
        return CONTROL_UART_HUB_PORTS[self.hub_usb_id] == self.hub_port

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
    node = os.path.realpath(os.path.join(TTY_SYSFS, os.path.basename(device_path), 'device'))
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
    for port in list_ports.comports():
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
    # The ids are only a claim, so the port is checked for every candidate and not merely to
    # break a tie between several. A board on one of the hub's sockets which reports a control
    # interface chip would otherwise be accepted whenever the real one is absent — while the
    # downstream section is still coming up, say — and usbman would then drive the board
    # instead of the hub, switching nothing while it believes it is switching.
    candidates = [device for device in devices if device.is_hub_control_interface()]
    hubs = [device for device in candidates if device.is_on_control_interface_port()]
    refused = [device for device in candidates if device not in hubs]
    logging.debug(f'{len(candidates)} candidate(s), {len(refused)} on a port carrying no control interface')
    if len(hubs) == 1:
        return hubs[0].path
    if hubs:
        found = ', '.join(str(hub) for hub in hubs)
        raise RuntimeError(f'Several managed USB hubs found ({found}), use --device to select one')
    if refused:
        rejected = ', '.join(str(device) for device in refused)
        raise RuntimeError(
            f'No managed USB hub found. Refused {rejected}: a control interface chip on a port which '
            f'carries none, so plugged into one of the hub sockets rather than being the hub itself. '
            f'Use --device to talk to one anyway'
        )
    seen = ', '.join(str(device) for device in devices) if devices else 'none'
    raise RuntimeError(
        f'No managed USB hub found among the serial devices of the system ({seen}), '
        f'use --device to specify the serial device'
    )


class DeviceNotFoundError(RuntimeError):
    """No such device in the USB tree.

    Its own type because it is the one failure a snapshot can answer: the device is absent,
    which is exactly what being on a switched off channel looks like. Every other failure means
    the device was found and something else is wrong, and a snapshot must not override that.
    """


def xdg_dir(variable: str, *default: str) -> str:
    """Return usbman's directory under an XDG base directory, honouring its variable."""
    base = os.environ.get(variable) or os.path.join(os.path.expanduser('~'), *default)
    return os.path.join(base, 'usbman')


def usbman_dir() -> str:
    """The directory usbman writes to: `$USBMAN_DIR`, else the XDG state directory."""
    override = os.environ.get(USBMAN_DIR_ENV)
    return os.path.expanduser(override) if override else xdg_dir('XDG_STATE_HOME', '.local', 'state')


def snapshot_path() -> str:
    """Where the snapshot lives: which channel each serial number was last seen on."""
    return os.path.join(usbman_dir(), 'snapshot')


def nicknames_paths() -> list:
    """Where the nicknames may live, in the order they are looked for.

    The XDG config directory first, which is where a file you write belongs, then beside the
    snapshot, for anyone who would rather keep both usbman files in one place. `$USBMAN_DIR`
    replaces both when it is set.
    """
    override = os.environ.get(USBMAN_DIR_ENV)
    if override:
        return [os.path.join(os.path.expanduser(override), 'nicknames')]
    return [os.path.join(xdg_dir('XDG_CONFIG_HOME', '.config'), 'nicknames'), os.path.join(usbman_dir(), 'nicknames')]


def nicknames_path() -> str:
    """The nicknames file to read: the first which exists, else the one that should."""
    paths = nicknames_paths()
    found = [path for path in paths if os.path.exists(path)]
    if len(found) > 1:
        logging.warning(f'Using the nicknames in {found[0]} and ignoring {", ".join(found[1:])}')
    return found[0] if found else paths[0]


def read_pairs(path: str, expected: str) -> list:
    """Return the `(first, second, comment)` of every usable line of a two column file.

    Both the snapshot and the nicknames are meant to be read and edited by hand, so a line
    which makes no sense names itself and is passed over rather than bringing the command
    down. `expected` describes the two columns, for that message.
    """
    try:
        with open(path) as f:
            lines = f.readlines()
    except OSError:
        return []
    pairs = []
    for number, line in enumerate(lines, start=1):
        text, _, comment = line.partition('#')
        fields = text.split()
        if not fields:
            continue
        if len(fields) != 2:
            logging.warning(f'{path} line {number}: expected "{expected}", ignoring {line.strip()!r}')
            continue
        pairs.append((fields[0], fields[1], comment.strip()))
    return pairs


def read_snapshot_entries(path: str | None = None) -> list:
    """Return the `(channel, serial, device)` lines of the snapshot, empty when there is none.

    The device name is only a comment, kept for whoever reads the file and for `--list`.
    """
    path = path or snapshot_path()
    entries = []
    for channel, serial, comment in read_pairs(path, 'channel serial'):
        if not channel.isdigit():
            logging.warning(f'{path}: {channel!r} is not a channel number, ignoring the line for {serial}')
            continue
        entries.append((int(channel), serial, comment or 'unknown device'))
    return entries


def read_snapshot(path: str | None = None) -> dict:
    """Return the `serial -> channel` map of the snapshot, empty when there is none."""
    path = path or snapshot_path()
    channels = {}
    for channel, serial, _ in read_snapshot_entries(path):
        if serial in channels and channels[serial] != channel:
            raise RuntimeError(
                f'{path} has {serial} on channels {channels[serial]} and {channel}, '
                f'run `usbman --snapshot` again to rebuild it'
            )
        channels[serial] = channel
    return channels


def write_snapshot(entries, path: str | None = None) -> str:
    """Write `(channel, serial, product)` entries, replacing any snapshot there was."""
    path = path or snapshot_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    when = time.strftime('%Y-%m-%dT%H:%M:%S')
    width = max((len(serial) for _, serial, _ in entries), default=8)
    with open(path, 'w') as f:
        f.write(f'# usbman snapshot, {when}\n')
        f.write(f'# {"channel":<9}{"serial":<{width + 2}}device\n')
        for channel, serial, product in sorted(entries):
            f.write(f'{channel:<11}{serial:<{width + 2}}# {product}\n')
    return path


def read_nicknames(path: str | None = None) -> dict:
    """Return the `nickname -> serial` map you wrote, empty when there is no file.

    Yours to edit: usbman only ever reads it. A nickname which could never be typed where a
    channel is expected is called out, since it would silently never work.
    """
    path = path or nicknames_path()
    nicknames = {}
    for nickname, serial, _ in read_pairs(path, 'nickname serial'):
        if nickname in nicknames and nicknames[nickname] != serial:
            raise RuntimeError(
                f'{path} gives the nickname {nickname!r} to both {nicknames[nickname]} and {serial}, '
                f'edit it so each nickname names one device'
            )
        if nickname == 'all' or nickname.startswith('/') or (nickname.isdigit() and len(nickname) <= 3):
            logging.warning(
                f'{path}: the nickname {nickname!r} looks like a channel, a path or "all", '
                f'so it would never be read as a nickname'
            )
            continue
        nicknames[nickname] = serial
    return nicknames


def nickname_serial(nickname: str, path: str | None = None) -> str | None:
    """Return the serial number a nickname stands for, or None when it is not one."""
    return read_nicknames(path).get(nickname)


def serial_nicknames(path: str | None = None) -> dict:
    """Return `serial -> nickname`, for showing a device by the name you gave it.

    Several nicknames may name one device; the first in alphabetical order is the one shown.
    """
    by_serial = {}
    for nickname, serial in sorted(read_nicknames(path).items()):
        by_serial.setdefault(serial, nickname)
    return by_serial


def snapshot_channel(serial: str, path: str | None = None) -> int | None:
    """Return the channel the snapshot remembers `serial` on, or None."""
    return read_snapshot(path).get(serial)


def usb_device_node(sysfs_dir: str) -> str | None:
    """Walk up from `sysfs_dir` to the USB device it belongs to, interfaces included."""
    node = os.path.realpath(sysfs_dir)
    while node != '/':
        if read_usb_id(node) is not None:
            return node
        node = os.path.dirname(node)
    return None


def usb_nodes_by_serial(serial: str) -> list[str]:
    """Return the sysfs directories of every USB device reporting `serial`.

    More than one is normal: both sections of the StarTech hub report `000000000`, and so do
    plenty of cheap devices. The caller has to refuse rather than pick one.
    """
    found = []
    for name in sorted(os.listdir(USB_SYSFS)):
        node = os.path.join(USB_SYSFS, name)
        try:
            with open(os.path.join(node, 'serial')) as f:
                if f.read().strip() == serial:
                    found.append(os.path.realpath(node))
        except OSError:
            continue  # no serial attribute, or it went away mid scan
    return found


def describe_usb_node(node: str) -> str:
    """Describe a USB device the way the ambiguity errors need to."""
    try:
        with open(os.path.join(node, 'product')) as f:
            product = f.read().strip()
    except OSError:
        product = 'unknown product'
    return f'{os.path.basename(node)} ({usb_id_str(read_usb_id(node))}, {product})'


def usb_node(reference: str) -> str:
    """Return the sysfs USB device directory a device reference names.

    A reference is a device path such as `/dev/ttyACM0`, a symlink to one such as the entries
    of `/dev/serial/by-id`, or a USB serial number.
    """
    if reference.startswith('/'):
        # `realpath` is what makes /dev/serial/by-id and /dev/serial/by-path work for free.
        name = os.path.basename(os.path.realpath(reference))
        node = usb_device_node(os.path.join(TTY_SYSFS, name, 'device'))
        if node is None:
            raise DeviceNotFoundError(
                f'{reference} is not a USB device the system knows about. A device which is off has no '
                f'path at all: name it by its USB serial number to reach it through a snapshot'
            )
        return node

    nodes = usb_nodes_by_serial(reference)
    if not nodes:
        raise DeviceNotFoundError(f'No USB device has the serial number {reference!r}')
    if len(nodes) > 1:
        shared = ', '.join(describe_usb_node(node) for node in nodes)
        raise RuntimeError(
            f'The serial number {reference!r} is shared by {len(nodes)} devices ({shared}), '
            f'name the one you mean by its device path instead'
        )
    return nodes[0]


def usb_chain(node: str) -> tuple:
    """Return the ids of the managed hub `node` hangs on, and the port it hangs on.

    The device needs not be a child of the hub: anything plugged into a socket may itself be a
    hub, so this walks up until it finds a managed hub and reports the port of the last node
    below it. Both are `None` when there is no managed hub above `node`.
    """
    port = None
    while node != '/':
        usb_id = read_usb_id(node)
        if usb_id is None:
            return (None, None)  # walked past the USB tree without meeting a managed hub
        if usb_id in MANAGED_HUB_USB_IDS:
            return (usb_id, port)
        port = read_hub_port(node)
        node = os.path.dirname(node)
    return (None, None)


def channel_of(reference: str) -> int:
    """Return the channel which powers the device `reference` names."""
    return channel_of_node(usb_node(reference), reference)


def channel_of_node(node: str, reference: str | None = None) -> int:
    """Return the channel which powers the device at the sysfs directory `node`."""
    reference = reference or os.path.basename(node)
    hub_usb_id, port = usb_chain(node)
    if hub_usb_id is None:
        raise RuntimeError(f'{reference} is not connected to a managed hub')
    if port is None:
        raise RuntimeError(f'{reference} is the managed hub itself, not something plugged into one of its sockets')
    ports = CHANNEL_PORTS.get(hub_usb_id)
    if not ports:
        raise RuntimeError(
            f'The channels of hub {usb_id_str(hub_usb_id)} are not known, '
            f'run `usbman --characterize` to work them out, see NOTES.md'
        )
    for channel, hub_port in ports.items():
        if hub_port == port:
            logging.debug(f'{reference} is on port {port} of hub {usb_id_str(hub_usb_id)}, channel {channel}')
            return channel
    # The table is complete for a known model, so a port missing from it is one the hub does
    # not switch rather than one nobody has measured.
    if CONTROL_UART_HUB_PORTS.get(hub_usb_id) == port:
        raise RuntimeError(f'{reference} is the control interface of the hub, on a port no channel switches')
    raise RuntimeError(
        f'{reference} is on port {port} of hub {usb_id_str(hub_usb_id)}, which no channel switches: '
        f'it is internal to the hub rather than one of its sockets'
    )


def occupied_hub_ports() -> dict:
    """Return the ports of every managed hub which currently have a device attached.

    Keyed by hub ids, each holding a set of port numbers. This is what characterization compares
    before and after switching a channel: a socket may hold a whole tree of hubs and devices,
    and cutting its channel takes all of it away at once, so occupancy is the right grain.
    """
    occupied = {}
    for name in sorted(os.listdir(USB_SYSFS)):
        node = os.path.join(USB_SYSFS, name)
        usb_id = read_usb_id(node)
        if usb_id is None:
            continue
        parent_id = read_usb_id(os.path.dirname(os.path.realpath(node)))
        if parent_id in MANAGED_HUB_USB_IDS:
            occupied.setdefault(parent_id, set()).add(read_hub_port(node))
    return occupied


def missing_hub_ports(before: dict, after: dict) -> list:
    """Return the `(hub ids, port)` pairs occupied in `before` and empty in `after`."""
    gone = []
    for hub_usb_id, ports in before.items():
        for port in sorted(ports - after.get(hub_usb_id, set())):
            gone.append((hub_usb_id, port))
    return gone


def wait_for_ports(expected: dict, settle: float, poll: float = 0.1) -> dict:
    """Wait for every port of `expected` to be occupied again, and return what is.

    Enumeration is slow and uneven — a board can take many seconds to come back while its
    neighbours take one — so this waits for a known set to return rather than for the tree to
    merely stop changing, which cannot tell "not yet" from "not at all". Gives up after
    `settle` seconds and returns what there is.
    """
    deadline = time.monotonic() + settle
    while True:
        current = occupied_hub_ports()
        if not missing_hub_ports(expected, current) or time.monotonic() >= deadline:
            return current
        time.sleep(poll)


def wait_for_new_port(before: dict, settle: float, poll: float = 0.1) -> dict:
    """Wait for a port absent from `before` to fill, and return the occupancy once it has.

    This is how a peripheral just plugged in is waited for: watching for a port which was not
    there before says "it has arrived" unambiguously, where waiting a fixed time cannot tell a
    board slow to enumerate from a socket with nothing in it. Gives up after `settle` seconds
    and returns what there is, which still works when the peripheral never moved.
    """
    deadline = time.monotonic() + settle
    while True:
        current = occupied_hub_ports()
        if missing_hub_ports(current, before) or time.monotonic() >= deadline:
            return current
        time.sleep(poll)


def wait_for_fewer_ports(before: dict, settle: float, poll: float = 0.1) -> dict:
    """Wait for a port of `before` to empty, and return what is left.

    Cutting the power disconnects in milliseconds, so this normally returns at once. The full
    wait is only spent on a channel which switches nothing, which is a legitimate outcome.
    """
    deadline = time.monotonic() + settle
    while True:
        current = occupied_hub_ports()
        if missing_hub_ports(before, current):
            time.sleep(min(poll, settle))  # let anything else on the same socket go too
            return occupied_hub_ports()
        if time.monotonic() >= deadline:
            return current
        time.sleep(poll)


class Socket(NamedTuple):
    """What one socket of the hub turned out to be."""

    label: int  # the number printed on the hub case
    channel: int | None  # the channel which switches it, None when nothing identified it
    hub_usb_id: tuple[int, int] | None  # the section it hangs on
    port: int | None  # its downstream port on that section


def find_switching_channel(device_path, present: dict, candidates, settle: float, on_progress=None):
    """Return the `(channel, hub ids, port)` which switching off empties a port of `present`.

    Cuts one candidate channel at a time and puts it back, so the peripheral is only off for as
    long as it takes to notice. Returns `(None, None, None)` when no candidate changes anything.
    """
    all_on = sum(1 << (channel - 1) for channel in CHANNELS)
    for channel in candidates:
        set_state(device_path, all_on & ~(1 << (channel - 1)))
        gone = missing_hub_ports(present, wait_for_fewer_ports(present, min(settle, DISCONNECT_WAIT)))
        set_state(device_path, all_on)
        if len(gone) == 1:
            hub_usb_id, port = gone[0]
            return (channel, hub_usb_id, port)
        if gone:
            # One socket is one channel, so this should not happen. Say so rather than guess.
            emptied = ', '.join(f'port {port} of {usb_id_str(hub)}' for hub, port in gone)
            if on_progress is not None:
                on_progress(f'channel {channel} emptied several ports ({emptied}), ignoring it')
        wait_for_ports(present, settle)  # let the peripheral come back before the next try
    return (None, None, None)


def characterize_hub(device_path, prompt, settle: float = 5.0, on_progress=None) -> list:
    """Work out which channel and port each socket of the hub is, with one peripheral.

    Asks for a peripheral to be plugged into each socket of the case in turn, then finds the
    channel which switches it. One peripheral at a time is what makes this reliable: there is
    only ever one port to watch, so nothing else enumerating can be mistaken for it.

    `prompt(label)` is called for each socket and returns 'skip' or 'stop' to say so. Returns
    one `Socket` per socket that was looked at, and restores the channel states it found.
    """

    def progress(message):
        logging.info(message)
        if on_progress is not None:
            on_progress(message)

    all_on = sum(1 << (channel - 1) for channel in CHANNELS)
    original = get_state(device_path)
    sockets = []
    remaining = list(CHANNELS)
    try:
        set_state(device_path, all_on)
        time.sleep(settle)
        for label in CHANNELS:
            if not remaining:
                break
            before = occupied_hub_ports()
            answer = prompt(label)
            if answer == 'stop':
                break
            if answer == 'skip':
                continue

            # Snapshotting before the prompt and then waiting for a port to appear is what
            # copes with a board which takes several seconds to enumerate.
            present = wait_for_new_port(before, settle)
            channel, hub_usb_id, port = find_switching_channel(
                device_path, present, remaining, settle, on_progress=progress
            )
            if channel is None:
                progress(f'socket {label}: nothing switched off anything, is the peripheral plugged in and up?')
            else:
                remaining.remove(channel)
                progress(f'socket {label} is channel {channel}, port {port} of hub {usb_id_str(hub_usb_id)}')
            sockets.append(Socket(label, channel, hub_usb_id, port))
    finally:
        set_state(device_path, original)
        progress('Restored the channel states')
    return sockets


def channel_ports_table(sockets) -> dict:
    """Turn what `characterize_hub` found into the `CHANNEL_PORTS` shape."""
    table = {}
    for socket in sockets:
        if socket.channel is not None:
            table.setdefault(socket.hub_usb_id, {})[socket.channel] = socket.port
    return table


def read_attribute(node: str, name: str) -> str | None:
    """Return a sysfs attribute of a USB device, or None when it has none."""
    try:
        with open(os.path.join(node, name)) as f:
            return f.read().strip()
    except OSError:
        return None


def tty_paths_on_channel(channel: int) -> list:
    """Return the `/dev` paths of the serial ports the given channel powers.

    More than one is possible and normal: a composite board can expose several, and a socket
    may hold a hub with several boards behind it. Only devices which are on and enumerated
    have a path at all.
    """
    paths = []
    for name in sorted(os.listdir(TTY_SYSFS)):
        node = usb_device_node(os.path.join(TTY_SYSFS, name, 'device'))
        if node is None:
            continue
        try:
            if channel_of_node(node) == channel:
                paths.append(os.path.join('/dev', name))
        except RuntimeError:
            continue  # not behind a managed hub, or on a port no channel switches
    return paths


def id_paths_for(tty_paths) -> list:
    """Return the `/dev/serial/by-id` names which point at the given `/dev` paths.

    A port can be missing from here: udev builds these names out of the USB descriptors, and a
    device which does not supply them gets no entry.
    """
    wanted = {os.path.basename(path) for path in tty_paths}
    paths = []
    try:
        names = sorted(os.listdir(SERIAL_BY_ID))
    except OSError:
        return []  # no USB serial device has ever been seen, so the directory is not there
    for name in names:
        link = os.path.join(SERIAL_BY_ID, name)
        if os.path.basename(os.path.realpath(link)) in wanted:
            paths.append(link)
    return paths


def live_devices() -> list:
    """Return the `(channel, serial, device)` of everything the hub currently powers.

    Pure sysfs: a device's channel follows from where it sits on the USB tree and from
    `CHANNEL_PORTS`, so nothing is switched and the hub is not even opened. Only devices which
    are on and enumerated can be seen. `serial` is None for a device which reports none.
    """
    devices = []
    for name in sorted(os.listdir(USB_SYSFS)):
        node = os.path.realpath(os.path.join(USB_SYSFS, name))
        if read_usb_id(node) is None:
            continue
        try:
            channel = channel_of_node(node)
        except RuntimeError:
            continue  # not behind a managed hub, or on a port no channel switches
        devices.append((channel, read_attribute(node, 'serial'), read_attribute(node, 'product') or 'unknown device'))
    return devices


def capture_snapshot() -> tuple:
    """Return what belongs in a snapshot, and how many devices could not go into one.

    A device with no serial number cannot be named afterwards, so it is counted rather than
    recorded, and said out loud instead of passed over in silence.
    """
    devices = live_devices()
    entries = [(channel, serial, product) for channel, serial, product in devices if serial is not None]
    return (entries, len(devices) - len(entries))


def resolve_channel(reference: str) -> int:
    """Return the channel for a device reference, expanding a nickname and using the snapshot.

    A nickname stands for a serial number and is expanded first, so everything downstream deals
    only with the three references it knows. The live tree then wins: it says where the device
    is now, where the snapshot says only where it was. The snapshot is consulted when the
    device is nowhere to be found, which is exactly what a device on a switched off channel
    looks like.
    """
    serial = nickname_serial(reference)
    named = reference if serial is None else f'{reference} ({serial})'
    if serial is not None:
        logging.debug(f'{reference} is the nickname of {serial}')
        reference = serial
    try:
        return channel_of(reference)
    except DeviceNotFoundError as absent:
        channel = snapshot_channel(reference)
        if channel is None:
            if serial is None:
                raise
            # Keep what went wrong and add which nickname led there, rather than replacing it.
            raise DeviceNotFoundError(f'{absent} (the nickname {named.split()[0]!r})') from absent
        logging.info(f'{named} is not connected, the snapshot puts it on channel {channel}')
        return channel
