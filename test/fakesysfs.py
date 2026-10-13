"""A sysfs tree in a temporary directory, so the topology code can be tested without hardware.

It mirrors the real shape rather than a convenient one: `/sys/bus/usb/devices` holds symlinks
into a nested `/sys/devices` hierarchy, a tty points at an interface directory inside its USB
device, and `/dev/serial/by-id` holds symlinks to the device nodes. Every one of those
indirections is something the code under test has to see through.
"""

import os

# devpath -> (vendor, product, serial or None, product name). Modelled on the real tree: two
# managed hub sections sharing the serial 000000000, a device several hubs deep behind one
# socket, a device directly on the hub, a hub with no serial at all, and a device which is not
# behind a managed hub.
DEVICES = {
    '0': (0x1D6B, 0x0002, '0000:c6:00.4', 'xHCI Host Controller'),
    '1': (0x0BDA, 0x5411, None, 'USB2.1 Hub'),
    '1.2': (0x14B0, 0x044A, '000000000', 'USB2.0 4 Port HUB'),
    '1.2.2': (0x2E8A, 0x0009, '648326155B4B110B', 'Pico'),
    '1.2.4': (0x14B0, 0x044C, '000000000', 'USB2.0 4 Port HUB'),
    '1.2.4.1': (0x05E3, 0x0610, None, 'USB2.1 Hub'),
    '1.2.4.1.2': (0x05E3, 0x0610, None, 'USB2.1 Hub'),
    '1.2.4.1.2.1': (0x0403, 0x6015, 'FT1234XZ', 'TTL-234X-3V3'),
    '1.2.4.1.4': (0x0483, 0x3754, '004B00283532510831333430', 'STLINK-V3'),
    '1.2.4.4': (0x0403, 0x6001, 'B001DNH6', 'FT232R USB UART'),
    '3': (0x0A5C, 0x5865, 'ABCDEF', '58200'),  # on the root hub, no managed hub above it
}

# tty name -> the devpath of the USB device behind it
TTYS = {
    'ttyACM0': '1.2.4.1.4',  # several hubs deep, the case that matters
    'ttyUSB0': '1.2.4.4',  # the control interface, directly on the hub
    'ttyUSB1': '1.2.4.1.2.1',  # deeper still, behind the same socket as ttyACM0
    'ttyACM9': '3',  # not behind a managed hub at all
}

BY_ID = {'usb-STMicroelectronics_STLINK-V3_004B00283532510831333430-if01': 'ttyACM0'}


def node_name(devpath):
    """The sysfs name of a device, `5-1.2.4` style, or `usb5` for the root hub."""
    return 'usb5' if devpath == '0' else f'5-{devpath}'


def node_dir(root, devpath):
    """Where a device really lives, nested under its parents the way sysfs nests them."""
    parts = [] if devpath == '0' else devpath.split('.')
    ancestors = ['usb5'] + [node_name('.'.join(parts[: i + 1])) for i in range(len(parts))]
    return os.path.join(root, 'devices', *ancestors)


def build(root, devices=None, ttys=None):
    """Create the tree under `root` and return `(tty_sysfs, usb_sysfs, dev)` to point at."""
    devices = DEVICES if devices is None else devices
    ttys = TTYS if ttys is None else ttys
    usb_sysfs = os.path.join(root, 'bus', 'usb', 'devices')
    tty_sysfs = os.path.join(root, 'class', 'tty')
    dev = os.path.join(root, 'dev')
    for path in (usb_sysfs, tty_sysfs, os.path.join(dev, 'serial', 'by-id')):
        os.makedirs(path, exist_ok=True)

    for devpath, (vendor, product, serial, name) in devices.items():
        directory = node_dir(root, devpath)
        os.makedirs(directory, exist_ok=True)
        write(directory, 'idVendor', f'{vendor:04x}')
        write(directory, 'idProduct', f'{product:04x}')
        write(directory, 'devpath', devpath)
        write(directory, 'product', name)
        if serial is not None:
            write(directory, 'serial', serial)
        # the interface directory a tty hangs off, as in the real tree
        os.makedirs(os.path.join(directory, f'{node_name(devpath)}:1.0'), exist_ok=True)
        os.symlink(directory, os.path.join(usb_sysfs, node_name(devpath)))

    for tty, devpath in ttys.items():
        interface = os.path.join(node_dir(root, devpath), f'{node_name(devpath)}:1.0')
        os.makedirs(os.path.join(tty_sysfs, tty), exist_ok=True)
        os.symlink(interface, os.path.join(tty_sysfs, tty, 'device'))
        write(dev, tty, '')  # the device node itself, for the by-id symlinks to point at

    for link, tty in BY_ID.items():
        os.symlink(os.path.join('..', '..', tty), os.path.join(dev, 'serial', 'by-id', link))

    return (tty_sysfs, usb_sysfs, dev)


def write(directory, name, text):
    with open(os.path.join(directory, name), 'w') as f:
        f.write(f'{text}\n')
