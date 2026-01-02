import argparse
import logging
import os
import time

import serial
from pysatl import Utils


def serial_command_response(device_path, *, send_hexstr=None, send_str=None, send_bytes=None) -> bytes:
    data_to_send = None
    if send_hexstr:
        data_to_send = Utils.ba(send_hexstr)
    if send_str:
        data_to_send = bytes(send_str, 'utf-8').decode('unicode_escape').encode()
    if send_bytes:
        data_to_send = send_bytes

    with serial.Serial(device_path, exclusive=True, baudrate=9600) as device:
        if data_to_send:
            logging.debug(f'Data to send: {Utils.hexstr(data_to_send)}')
            logging.debug(f'Data to send: {data_to_send}')
            device.write(data_to_send)
            device.flush()
        time.sleep(0.1)
        out = device.read_all()
        logging.debug(f'{out}')
    return out


if __name__ == '__main__':
    scriptname = os.path.basename(__file__)
    parser = argparse.ArgumentParser(scriptname)
    levels = ('DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL')
    parser.add_argument('--log-level', default='INFO', choices=levels)
    parser.add_argument('device', metavar='device-path', default=None, help='Path to the serial device', type=str)

    group = parser.add_mutually_exclusive_group()
    group.add_argument('--send-x', default=None, help='hexstr to send', type=str)
    group.add_argument('--send-a', default=None, help='string to send', type=str)

    args = parser.parse_args()

    device_path = args.device

    logformat = '%(asctime)s.%(msecs)03d %(levelname)s:\t%(message)s'
    logdatefmt = '%Y-%m-%d %H:%M:%S'
    logging.basicConfig(level='INFO', format=logformat, datefmt=logdatefmt)

    serial_command_response(device_path, send_hexstr=args.send_x, send_str=args.send_a)
