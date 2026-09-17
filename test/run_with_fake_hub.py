"""Run the usbman command line against an in memory hub, in a process of its own.

`test_server.py` uses this for both roles of its equivalence test: once as a plain local
command, once as the server a client connects to. Running it out of process is what makes the
comparison honest, since it exercises `main`, the real logging setup and the real exit code.

    python test/run_with_fake_hub.py <initial state in hex> [usbman arguments]
"""

import sys

import usbman
from fakehub import FakeHub
from usbman.cli import main

if __name__ == '__main__':
    usbman.serial_command_response = FakeHub(int(sys.argv[1], 16))
    sys.argv = ['usbman', *sys.argv[2:]]
    main()
