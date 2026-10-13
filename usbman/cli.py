import argparse
import logging
import os
import sys
import time

import usbman
from usbman import (
    CHANNELS,
    __version__,
    capture_snapshot,
    channel_ports_table,
    characterize_hub,
    find_device_path,
    get_state,
    live_devices,
    read_snapshot_entries,
    id_paths_for,
    serial_nicknames,
    tty_paths_on_channel,
    resolve_channel,
    save_state,
    set_state,
    snapshot_path,
    usb_id_str,
    write_snapshot,
)

# Accepted in place of a channel number to designate every channel of the hub at once.
ALL_CHANNELS = 'all'

# A run of up to this many digits is a channel number; a longer one is a USB serial number.
# The boundary is what lets an all digit serial such as '000000000' be named directly, while
# keeping the common typo `--set 8` an invalid channel rather than a serial nobody has.
CHANNEL_NUMBER_DIGITS = 3

LOG_FORMAT = '%(asctime)s.%(msecs)03d %(levelname)s:\t%(message)s'
LOG_DATEFMT = '%Y-%m-%d %H:%M:%S'
LOG_LEVELS = ('DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL')

# `exit` comes from the `site` module, which PyInstaller does not ship, so the frozen binary
# raises NameError on every error path. Always `sys.exit`, never the bare builtin.
EXIT_ERROR = -1
EXIT_NO_COMMUNICATION = -2

# The options below are consumed before the hub command parser runs, by `split_transport` in
# usbman/server.py, so they do not appear in the help argparse generates.
TRANSPORT_HELP = """transport options, which must be spelled in full:
  --device PATH        serial device of the hub, auto detected when not given
  --serve [HOST:PORT]  serve the commands above on a socket, default 127.0.0.1:9877
  --connect HOST:PORT  send the command to a usbman server instead of a local hub
  --timeout SECONDS    socket timeout, -1 (the default) blocks forever

The USBMAN_SERVER environment variable acts as --connect, so an existing script needs no
change to drive a remote hub. USBMAN_SERVER= (empty) forces one command back to local."""


def is_channel_number(value: str) -> bool:
    """Tell whether a token is meant as a channel number rather than a device reference."""
    return value.isdigit() and len(value) <= CHANNEL_NUMBER_DIGITS


def channel(value: str) -> str:
    """argparse type of every channel valued option.

    Accepts a channel number, `all`, or a device reference: a path such as `/dev/ttyACM0`, a
    symlink to one such as the entries of `/dev/serial/by-id`, or a USB serial number. Only the
    shape is checked here. Resolving a reference reads sysfs and can fail, and an argparse type
    runs before the logging is configured, so `channel_set` does that instead.
    """
    if value == ALL_CHANNELS or value.startswith('/'):
        return value
    if is_channel_number(value):
        if int(value) not in CHANNELS:
            raise argparse.ArgumentTypeError(
                f"invalid channel '{value}', expected {CHANNELS[0]} to {CHANNELS[-1]} or '{ALL_CHANNELS}'"
            )
        return value
    if not value:
        raise argparse.ArgumentTypeError('expected a channel number, a device path or a USB serial number')
    return value  # a serial number, looked up later


def one_channel(value: str) -> int:
    """Return the channel a single value names: a channel number, or a device reference."""
    return int(value) if is_channel_number(value) else resolve_channel(value)


def channel_set(values) -> set:
    """Return the channels designated by a channel valued argument, resolving any reference."""
    if ALL_CHANNELS in values:
        return set(CHANNELS)
    return {one_channel(value) for value in values}


def configure_logging(level) -> None:
    """Send the log to stderr the way a single command does.

    Only the first call in a process has any effect, `basicConfig` being a no op afterwards.
    That is why `run` takes the hook below instead of calling this itself: a server needs a
    level per request, not one for the life of the process.
    """
    logging.basicConfig(level=level, format=LOG_FORMAT, datefmt=LOG_DATEFMT)


def main():
    """Run the command line, reporting the errors the hub reports without a traceback."""
    from usbman.server import DEFAULT_ENDPOINT, peek_log_level, request, serve, split_transport

    try:
        transport, argv = split_transport(sys.argv[1:])
        if transport.serve is not None:
            sys.exit(serve(transport.serve or DEFAULT_ENDPOINT, argv, transport.device, transport.timeout))
        target = transport.connect or os.environ.get('USBMAN_SERVER') or None
        if target is not None:
            # `--log-level` is forwarded to the server as well, it is only peeked at here so
            # that the client own messages obey it too. Set up before anything can fail, so
            # that every message of this branch is formatted alike.
            configure_logging(peek_log_level(argv))
            if transport.device is not None:
                raise RuntimeError('--device cannot be used with --connect, the server owns the hub')
            sys.exit(request(target, argv, transport.timeout))
        # Deliberately no configure_logging here: it would make the one inside `run` a no op
        # and so silently kill `--log-level` for the plain command line.
        run(argv, device_path=transport.device)
    except RuntimeError as e:
        logging.error(f'{e}')
        sys.exit(EXIT_ERROR)


def build_parser() -> argparse.ArgumentParser:
    """Return the parser of the hub commands, the one source of the command line grammar."""
    parser = argparse.ArgumentParser(
        'usbman', epilog=TRANSPORT_HELP, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument('--log-level', default='INFO', choices=LOG_LEVELS)
    # Through --connect this reports the server's version, as every forwarded option reports
    # the server's answer. That is the useful one: it says what is really driving the hub.
    parser.add_argument('--version', action='version', version=f'usbman {__version__}')

    channels_help = f"channel numbers, or '{ALL_CHANNELS}' for all of them"
    parser.add_argument(
        '--on',
        default=[],
        help=f'turn exactly these channel(s) on and every other one off: {channels_help}',
        nargs='+',
        type=channel,
    )
    parser.add_argument(
        '--set',
        default=[],
        help=f'turn channel(s) on, leaving the others as they are: {channels_help}',
        nargs='+',
        type=channel,
    )
    # '--clr' is a real alias and not an abbreviation, '--clr' not being a prefix of '--clear'.
    # It costs the abbreviations '--c' and '--cl', which become ambiguous between the two.
    parser.add_argument(
        '--clear',
        '--clr',
        default=[],
        help=f'turn channel(s) off, leaving the others as they are: {channels_help}',
        nargs='+',
        type=channel,
    )
    parser.add_argument(
        '--off-pulse', default=[], help=f'turn channel(s) off and on: {channels_help}', nargs='+', type=channel
    )
    parser.add_argument('--toff', default=1, help='off-pulse duration seconds', type=float)
    parser.add_argument(
        '--channel-of',
        default=None,
        metavar='DEVICE',
        help='print the channel powering a device, named by path or USB serial number, and exit',
        type=str,
    )
    parser.add_argument(
        '--path-of',
        default=None,
        metavar='CHANNEL',
        help='print the /dev path of the serial port(s) on a channel, named by number, nickname or serial',
        type=channel,
    )
    parser.add_argument(
        '--id-path-of',
        default=None,
        metavar='CHANNEL',
        help='the same, as a stable /dev/serial/by-id path which survives re-plugging',
        type=channel,
    )
    parser.add_argument(
        '--list',
        action='store_true',
        help='show which device is on which channel, from the USB tree and from the snapshot',
    )
    parser.add_argument(
        '--snapshot',
        action='store_true',
        help='record which channel each connected device is on, so it can be named while switched off',
    )
    parser.add_argument('--forget', action='store_true', help='delete the snapshot')
    parser.add_argument(
        '--characterize',
        action='store_true',
        help='work out the wiring of a hub model, to add it to usbman (see NOTES.md), needs a terminal',
    )
    parser.add_argument(
        '--settle',
        default=5.0,
        help='seconds --characterize allows a peripheral to enumerate; raise it for a slow board',
        type=float,
    )
    parser.add_argument(
        '--save', action='store_true', help='store the resulting state as the one the hub powers up with'
    )
    return parser


def print_paths(channel: int, by_id: bool = False) -> None:
    """Print the path of every serial port on a channel, one per line.

    One per line so that the usual case substitutes straight into another command. When there
    is more than one the warning goes to stderr, leaving stdout parseable.
    """
    ttys = tty_paths_on_channel(channel)
    if not ttys:
        on_channel = [product for number, _, product in live_devices() if number == channel]
        if on_channel:
            raise RuntimeError(f'channel {channel} has {", ".join(on_channel)} on it, but no serial port')
        raise RuntimeError(f'nothing is connected to channel {channel}, or the channel is switched off')

    paths = id_paths_for(ttys) if by_id else ttys
    if not paths:
        raise RuntimeError(
            # read through the module, so that a test pointing it elsewhere is named correctly
            f'channel {channel} has {", ".join(ttys)}, but nothing in {usbman.SERIAL_BY_ID} points there: '
            f'the device does not give udev the descriptors it names these after'
        )
    if len(paths) > 1:
        logging.warning(f'channel {channel} has {len(paths)} serial ports, listing all of them')
    for path in paths:
        print(path)


def print_listing(live, snapshot) -> None:
    """Show every channel, what is on it, and whether that is what is there or what was.

    The live tree overrides the snapshot the same way resolving a device does: a serial seen
    now is reported where it now is, and its snapshot line is left out. A snapshot line which
    disagrees with the tree is worth saying out loud, since it means the file is stale.
    """
    seen = {serial: channel for channel, serial, _ in live if serial is not None}
    rows = [(channel, 'live', serial, product) for channel, serial, product in live]
    rows += [
        (channel, 'snapshot', serial, product)
        for channel, serial, product in snapshot
        if serial not in seen  # the tree wins, so a device seen now is only listed once
    ]

    nicknames = serial_nicknames()
    serial_width = max((len(serial) for _, _, serial, _ in rows if serial), default=6)
    nick_width = max([len(nick) for nick in nicknames.values()] + [len('nickname')])
    header = f'{"channel":<9}{"nickname":<{nick_width + 2}}{"source":<10}{"serial":<{serial_width + 2}}device'
    print(header)
    for channel in CHANNELS:
        # a device with no serial sorts as empty rather than blowing up against a string
        on_channel = sorted((row for row in rows if row[0] == channel), key=lambda row: (row[1], row[2] or ''))
        if not on_channel:
            print(f'{channel:<9}{"-":<{nick_width + 2}}{"-":<10}{"-":<{serial_width + 2}}-')
        for _, source, serial, product in on_channel:
            nickname = nicknames.get(serial, '-')
            print(f'{channel:<9}{nickname:<{nick_width + 2}}{source:<10}{serial or "-":<{serial_width + 2}}{product}')

    stale = [
        (serial, channel, seen[serial]) for channel, serial, _ in snapshot if serial in seen and seen[serial] != channel
    ]
    for serial, remembered, really in stale:
        print(f'{serial} has moved: the snapshot says channel {remembered}, it is on {really}')
    if stale:
        print('Run `usbman --snapshot` to bring the file up to date.')


def print_snapshot(entries, unnamed: int) -> None:
    """Write the snapshot and say what went into it, and what did not.

    It replaces whatever was there, so being loud about the channels nothing was seen on is
    what stops a forgotten `usbman --on all` from quietly throwing entries away.
    """
    path = write_snapshot(entries)
    recorded = sorted({channel for channel, _, _ in entries})
    print(f'Recorded {len(entries)} device(s) on channel(s) {recorded or "none"} in {path}')
    missing = [channel for channel in CHANNELS if channel not in recorded]
    if missing:
        print(
            f'Channel(s) {missing} had nothing visible: if something is plugged into them, '
            f'turn them on, wait for them to come up, and snapshot again.'
        )
    if unnamed:
        print(f'{unnamed} device(s) were skipped for having no serial number, they cannot be named.')


def socket_prompt(label: int) -> str:
    """Ask for the peripheral to be moved to one socket. Returns 'go', 'skip' or 'stop'."""
    answer = (
        input(
            f'Plug the peripheral into the socket labelled {label} on the hub, then press Enter '
            f'(s to skip this socket, q to stop): '
        )
        .strip()
        .lower()
    )
    if answer.startswith('q'):
        return 'stop'
    return 'skip' if answer.startswith('s') else 'go'


def print_characterization(sockets) -> None:
    """Print what was found as the source to paste into `CHANNEL_PORTS`.

    It is written out rather than saved: the wiring is the same on every unit of the model, so
    it belongs in the repository, not on one machine. NOTES.md says what else to record.
    """
    table = channel_ports_table(sockets)
    print('')
    for socket in sockets:
        if socket.channel is None:
            print(f'socket {socket.label}: not identified')
        else:
            hub = usb_id_str(socket.hub_usb_id)
            print(f'socket {socket.label}: channel {socket.channel}, port {socket.port} of hub {hub}')
    print('')
    print('To paste into CHANNEL_PORTS in usbman/__init__.py:')
    print('')
    for hub_usb_id, ports in sorted(table.items()):
        channels = ', '.join(f'{channel}: {port}' for channel, port in sorted(ports.items()))
        print(f'    (0x{hub_usb_id[0]:04X}, 0x{hub_usb_id[1]:04X}): {{{channels}}},')
    print('')
    missing = [channel for channel in CHANNELS if channel not in {c for ports in table.values() for c in ports}]
    if missing:
        print(f'Channels {missing} were never seen: sockets you skipped, or channels with no socket.')
    print('Record the table and what it settles in NOTES.md, then commit it.')


def run(argv=None, *, device_path=None, local=True, setup_logging=configure_logging):
    """Run one hub command.

    `local` is false for a request which arrived over a socket: the options which write to
    this machine are refused then, while resolving a device against it stays available.

    `device_path` comes from the caller, never from `argv`: locally from the `--device`
    transport option, in a server from the device it resolved at startup. It is resolved here
    rather than by the caller when it is `None`, so that the auto detection message obeys the
    `--log-level` of this very command.
    """
    parser = build_parser()
    args = parser.parse_args(argv)

    setup_logging(args.log_level)

    logging.debug(f'args = {args}')

    local_only = [name for name in ('snapshot', 'forget', 'characterize') if getattr(args, name)]
    if local_only and not local:
        names = ', '.join(f'--{name}' for name in local_only)
        logging.error(f'{names} acts on the machine the hub is attached to, it cannot be asked for from here')
        sys.exit(EXIT_ERROR)

    for option, reference in (('--path-of', args.path_of), ('--id-path-of', args.id_path_of)):
        if reference is None:
            continue
        if reference == ALL_CHANNELS:
            logging.error(f'{option} takes one channel, not {ALL_CHANNELS!r}')
            sys.exit(EXIT_ERROR)
        print_paths(one_channel(reference), by_id=option == '--id-path-of')
        return

    if args.list:
        print_listing(live_devices(), read_snapshot_entries())
        return

    if args.snapshot:
        if args.on or args.set or args.clear or args.off_pulse or args.save:
            # Switching and recording in one command would record the state before the boards
            # that just came back have finished enumerating, which is the failure that broke
            # the first --characterize. Two commands, with the wait in between.
            logging.error('--snapshot records what is already connected, run it after the command which switches')
            sys.exit(EXIT_ERROR)
        print_snapshot(*capture_snapshot())
        return

    if args.forget:
        path = snapshot_path()
        try:
            os.remove(path)
            print(f'Removed {path}')
        except OSError:
            print(f'There was no snapshot at {path}')
        return

    if args.channel_of is not None:
        # Pure sysfs and the snapshot: no hub is opened, so this answers even with the hub
        # unplugged, and for a device which is switched off and therefore invisible.
        print(resolve_channel(args.channel_of))
        return

    # Resolve and check every argument first. None of this needs the hub, so a bad channel or
    # an unknown device says so instead of hiding behind "no managed USB hub found".
    exclusive = channel_set(args.on)
    to_set = channel_set(args.set)
    to_clear = channel_set(args.clear)
    to_pulse = channel_set(args.off_pulse)
    if exclusive and (to_set or to_clear or to_pulse):
        # A pulse ends with its channels on whatever they were, so it would contradict --on
        # just as --set and --clear do.
        logging.error('--on cannot be combined with --set, --clear or --off-pulse, it alone decides every channel')
        sys.exit(EXIT_ERROR)
    conflicts = set.intersection(to_set, to_clear)
    if conflicts:
        logging.error(f'--set and --clear are conflicting for channels {conflicts}')
        sys.exit(EXIT_ERROR)
    if args.characterize and (exclusive or to_set or to_clear or to_pulse or args.save):
        logging.error('--characterize switches every channel itself, it takes no other channel option')
        sys.exit(EXIT_ERROR)
    if args.characterize and not sys.stdin.isatty():
        # It asks for a peripheral to be moved from socket to socket, so it cannot run down a
        # pipe, and in particular not as a request to a usbman server.
        logging.error('--characterize has to ask you to move a peripheral, run it in a terminal')
        sys.exit(EXIT_ERROR)

    if device_path is None:
        try:
            device_path = find_device_path()
        except RuntimeError as e:
            logging.error(f'{e}')
            sys.exit(EXIT_ERROR)
        logging.info(f'Using auto detected device {device_path}')

    if args.characterize:
        print_characterization(characterize_hub(device_path, socket_prompt, args.settle))
        return

    get_state_errors = []
    org_state = None
    for i in range(3):
        try:
            org_state = get_state(device_path)
            if i > 0:
                logging.info('Device communication succesfully restored')
            break
        except Exception as e:
            logging.warning(e)
            get_state_errors.append(e)

    if org_state is None:
        # fatal error
        logging.critical('Could not communicate with the device')
        sys.exit(EXIT_NO_COMMUNICATION)

    state = org_state
    if exclusive:
        # Absolute: the channels asked for and no others, whatever the hub was doing before.
        state = 0
        for i in exclusive:
            state |= 1 << (i - 1)
        logging.debug(f'ON = {exclusive}, state = {state:#02x}')
    for i in to_set:
        state |= 1 << (i - 1)
    for i in to_clear:
        state &= ~(1 << (i - 1))
    logging.debug(f'org_state = {org_state:#02x}, state = {state:#02x}')
    if org_state != state:
        final_state = set_state(device_path, state)
        logging.debug(f'final_state = {final_state:#02x}')
        current_state = final_state
    else:
        current_state = org_state

    if to_pulse:
        for i in to_pulse:
            state &= ~(1 << (i - 1))
        tmp_state = set_state(device_path, state)
        logging.debug(f'tmp_state = {tmp_state:#02x}')
        time.sleep(args.toff)
        for i in to_pulse:
            state |= 1 << (i - 1)
        current_state = set_state(device_path, state)
        logging.debug(f'current_state = {current_state:#02x}')

    # Last, so that the state saved is the one every other argument has just produced.
    if args.save:
        current_state = save_state(device_path)
        logging.debug(f'saved_state = {current_state:#02x}')

    if 0 == current_state:
        print('All off')
    else:
        print('On: ', end='')
        for i in CHANNELS:
            if current_state & (1 << (i - 1)):
                print(f'{i} ', end='')
        print('')


if __name__ == '__main__':
    main()
