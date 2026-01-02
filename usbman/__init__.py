import logging

from pysatl import Utils

from usbman.clicom import serial_command_response


def decode_result(res: str) -> int:
    logging.debug(f'res = {res}')
    if res == b'EFF\r\n':
        raise RuntimeError(f'Device returned "{res}"')
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
    state |= 0x80
    state = Utils.hexstr(state.to_bytes(1, byteorder='little'))
    command = f'SPpass    {state}FFFFFF\r'
    logging.debug(f'set state command: {command}')
    state = serial_command_response(device_path, send_str=command)
    return decode_result(state)
