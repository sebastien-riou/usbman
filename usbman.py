import os,argparse
from pysatl import Utils
import logging
from clicom import serial_command_response

def decode_result(res:str) -> int:
    logging.debug(f'res = {res}')
    if res == b'EFF\r\n':
        raise RuntimeError(f'Device returned "{res}"')
    if res.startswith(b'G'):
        res = res[1:]
    state = res[:2]
    state = state.decode()
    state = Utils.ba(state)
    state = int.from_bytes(state,byteorder='little')
    state &= 0x7F
    logging.debug(f'state = {state}')
    return state

def get_state(device_path) -> int:
    state = serial_command_response(device_path, send_str='GP\r')
    return decode_result(state)

def set_state(device_path, state: int) -> int:
    state |= 0x80
    state = Utils.hexstr(state.to_bytes(1,byteorder='little'))
    command = f'SPpass    {state}FFFFFF\r'
    logging.debug(f'set state command: {command}')
    state = serial_command_response(device_path, send_str=command)
    return decode_result(state)

if __name__ == '__main__':
    scriptname = os.path.basename(__file__)
    parser = argparse.ArgumentParser(scriptname)
    levels = ('DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL')
    parser.add_argument('--log-level', default='INFO', choices=levels)
    parser.add_argument(
        '--device-path', default='/dev/ttyUSB0', help='Path to the serial device', type=str
    )

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
            state &= ~(1 << (i-1))
    logging.debug(f'org_state = {org_state:#02x}, state = {state:#02x}')
    if org_state != state:
        final_state = set_state(device_path,state)
        logging.debug(f'final_state = {final_state:#02x}')
        current_state = final_state
    else:
        current_state = org_state
    if 0 == current_state:
        print('All off')
    else:
        print('On: ',end='')
        for i in range(1,8):
            if current_state & (1<<(i-1)):
                print(f'{i} ',end='')
        print('')
