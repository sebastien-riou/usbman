import argparse
import logging
import os
import time

from usbman import CHANNELS, find_device_path, get_state, set_state

# Accepted in place of a channel number to designate every channel of the hub at once.
ALL_CHANNELS = 'all'


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


def main():
    scriptname = os.path.basename(__file__)
    parser = argparse.ArgumentParser(scriptname)
    levels = ('DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL')
    parser.add_argument('--log-level', default='INFO', choices=levels)
    # argparse accepts any unambiguous prefix, so this is also usable as '--device'. Keep it
    # the only option starting with '--d' for that shorter spelling to remain available.
    parser.add_argument(
        '--device-path', default=None, help='Path to the serial device, auto detected if not specified', type=str
    )

    channels_help = f"channel numbers, or '{ALL_CHANNELS}' for all of them"
    parser.add_argument('--on', default=[], help=f'turn channel(s) on: {channels_help}', nargs='+', type=channel)
    parser.add_argument('--off', default=[], help=f'turn channel(s) off: {channels_help}', nargs='+', type=channel)
    parser.add_argument(
        '--off-pulse', default=[], help=f'turn channel(s) off and on: {channels_help}', nargs='+', type=channel
    )
    parser.add_argument('--toff', default=1, help='off-pulse duration seconds', type=float)

    args = parser.parse_args()

    logformat = '%(asctime)s.%(msecs)03d %(levelname)s:\t%(message)s'
    logdatefmt = '%Y-%m-%d %H:%M:%S'
    logging.basicConfig(level=args.log_level, format=logformat, datefmt=logdatefmt)

    logging.debug(f'args = {args}')

    device_path = args.device_path
    if device_path is None:
        try:
            device_path = find_device_path()
        except RuntimeError as e:
            logging.error(f'{e}')
            exit(-1)
        logging.info(f'Using auto detected device {device_path}')

    set_on = channel_set(args.on)
    set_off = channel_set(args.off)
    set_off_pulse = channel_set(args.off_pulse)
    conflicts = set.intersection(set_on, set_off)
    if conflicts:
        logging.error(f'ON and OFF arguments are conflicting for channels {conflicts}')
        exit(-1)

    org_state = get_state(device_path)
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
