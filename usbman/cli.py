import argparse
import logging
import os
import sys
import time

from usbman import CHANNELS, find_device_path, get_state, save_state, set_state

# Accepted in place of a channel number to designate every channel of the hub at once.
ALL_CHANNELS = 'all'

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


def channel(value: str) -> str:
    """argparse type of the `--on`, `--off` and `--off-pulse` values: a channel number or 'all'."""
    if value == ALL_CHANNELS:
        return value
    if not value.isdigit() or int(value) not in CHANNELS:
        raise argparse.ArgumentTypeError(
            f"invalid channel '{value}', expected {CHANNELS[0]} to {CHANNELS[-1]} or '{ALL_CHANNELS}'"
        )
    return value


def channel_set(values) -> set:
    """Return the channels designated by a `--on`, `--off` or `--off-pulse` argument."""
    if ALL_CHANNELS in values:
        return set(CHANNELS)
    return {int(value) for value in values}


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

    channels_help = f"channel numbers, or '{ALL_CHANNELS}' for all of them"
    parser.add_argument('--on', default=[], help=f'turn channel(s) on: {channels_help}', nargs='+', type=channel)
    parser.add_argument('--off', default=[], help=f'turn channel(s) off: {channels_help}', nargs='+', type=channel)
    parser.add_argument(
        '--off-pulse', default=[], help=f'turn channel(s) off and on: {channels_help}', nargs='+', type=channel
    )
    parser.add_argument('--toff', default=1, help='off-pulse duration seconds', type=float)
    parser.add_argument(
        '--save', action='store_true', help='store the resulting state as the one the hub powers up with'
    )
    return parser


def run(argv=None, *, device_path=None, setup_logging=configure_logging):
    """Run one hub command.

    `device_path` comes from the caller, never from `argv`: locally from the `--device`
    transport option, in a server from the device it resolved at startup. It is resolved here
    rather than by the caller when it is `None`, so that the auto detection message obeys the
    `--log-level` of this very command.
    """
    parser = build_parser()
    args = parser.parse_args(argv)

    setup_logging(args.log_level)

    logging.debug(f'args = {args}')

    if device_path is None:
        try:
            device_path = find_device_path()
        except RuntimeError as e:
            logging.error(f'{e}')
            sys.exit(EXIT_ERROR)
        logging.info(f'Using auto detected device {device_path}')

    set_on = channel_set(args.on)
    set_off = channel_set(args.off)
    set_off_pulse = channel_set(args.off_pulse)
    conflicts = set.intersection(set_on, set_off)
    if conflicts:
        logging.error(f'ON and OFF arguments are conflicting for channels {conflicts}')
        sys.exit(EXIT_ERROR)

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
    if set_on:
        for i in set_on:
            state |= 1 << (i - 1)
        logging.debug(f'ON = {set_on}, state = {state:#02x}')
    if set_off:
        for i in set_off:
            state &= ~(1 << (i - 1))
    logging.debug(f'org_state = {org_state:#02x}, state = {state:#02x}')
    if org_state != state:
        final_state = set_state(device_path, state)
        logging.debug(f'final_state = {final_state:#02x}')
        current_state = final_state
    else:
        current_state = org_state

    if set_off_pulse:
        for i in set_off_pulse:
            state &= ~(1 << (i - 1))
        tmp_state = set_state(device_path, state)
        logging.debug(f'tmp_state = {tmp_state:#02x}')
        time.sleep(args.toff)
        for i in set_off_pulse:
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
