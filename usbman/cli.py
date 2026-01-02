import os
import argparse
import logging
from usbman import get_state, set_state


def main():
    scriptname = os.path.basename(__file__)
    parser = argparse.ArgumentParser(scriptname)
    levels = ('DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL')
    parser.add_argument('--log-level', default='INFO', choices=levels)
    parser.add_argument('--device-path', default='/dev/ttyUSB0', help='Path to the serial device', type=str)

    parser.add_argument('--on', default=[], help='turn channel(s) on', nargs='+', type=int)
    parser.add_argument('--off', default=[], help='turn channel(s) off', nargs='+', type=int)

    args = parser.parse_args()
    device_path = args.device_path

    logformat = '%(asctime)s.%(msecs)03d %(levelname)s:\t%(message)s'
    logdatefmt = '%Y-%m-%d %H:%M:%S'
    logging.basicConfig(level=args.log_level, format=logformat, datefmt=logdatefmt)

    logging.debug(f'args = {args}')
    set_on = set(args.on)
    set_off = set(args.off)
    conflicts = set.intersection(set_on, set_off)
    if conflicts:
        logging.error(f'ON and OFF arguments are conflicting for channels {conflicts}')
        exit(-1)

    org_state = get_state(device_path)
    state = org_state
    logging.debug(f'org_state = {org_state:#02x}, state = {state:#02x}')
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
    if 0 == current_state:
        print('All off')
    else:
        print('On: ', end='')
        for i in range(1, 8):
            if current_state & (1 << (i - 1)):
                print(f'{i} ', end='')
        print('')

if __name__ == '__main__':
    main()
