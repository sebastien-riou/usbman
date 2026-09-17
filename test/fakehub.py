"""A managed hub which lives in memory, so the tests need no hardware.

It speaks the wire protocol documented in NOTES.md: a two character opcode, a password field
for the commands which write, an optional payload as hex, and a carriage return.
"""

import threading


class FakeHub:
    """Stand in for `usbman.serial_command_response`.

    Patch it in the `usbman` namespace, where the name was imported, and not in
    `usbman.clicom` where it is defined, otherwise the real one keeps being called.
    """

    def __init__(self, state=0):
        self.state = state  # the live channel states
        self.saved = state  # what the hub would power up with
        self.commands = []  # every command received, in order, for the ordering tests
        self.lock = threading.Lock()

    def __call__(self, device_path, *, send_str=None, **kwargs):
        with self.lock:
            self.commands.append(send_str)
        if send_str.startswith('SP'):
            self.state = int(send_str[10:12], 16) & 0x7F
        elif send_str.startswith('WP'):
            self.saved = self.state
        elif not send_str.startswith('GP'):
            return b'EFF\r\n'
        # `WP` answers with the 'G' prefix and `GP` without it; both are accepted, so use the
        # prefixed form throughout to keep exercising the stripping.
        return f'G{0x80 | self.state:02X}FFFFFF\r\n'.encode()
