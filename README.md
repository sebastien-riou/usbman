# usbman
[![OpenSSF Scorecard](https://api.scorecard.dev/projects/github.com/sebastien-riou/usbman/badge)](https://scorecard.dev/viewer/?uri=github.com/sebastien-riou/usbman)

Software to control 'managed' USB hubs compatible with 'cuspi' closed source binary.
For example:
- [startech 7 ports hub](https://www.startech.com/en-us/usb-hubs/5g7aindrm-usb-a-hub).
- [coolgear 7 ports hub](https://www.coolgear.com/product/7-port-managed-usb-3-hub-w-15kv-esd-surge-protection-on-off-per-port-control-software)

![StarTech.com managed hub](startech-hub-7.jpg?raw=true "StarTech.com managed hub")

## Installation

### Using pypi
````
pip install usbman
````

### Using a pre-built release
Place the binary in your PATH.

### From source, using pyinstaller
This build a native package.

````
git clone https://github.com/sebastien-riou/usbman.git
cd usbman
pipenv sync
pipenv run ./package_usbman
````

Add `dist/usbman` in your PATH.

## How to

### Select the device
`--device` is optional: when it is omitted, `usbman` locates the hub on the USB tree. The
control interface of a managed hub is a serial chip wired to one of the hub downstream ports, so it is recognized by the combination of
its own USB ids and of the ids of the hub it hangs on. Detection reads USB ids only, it never
sends anything to a device, so the devices you plugged into the managed hub are left alone.

Pass `--device` explicitly when detection finds nothing or finds several managed hubs, and on
the systems which do not expose the USB tree in sysfs the way Linux does. All the examples below
work the same way without `--device`. The full name of the option is `--device-path`, `--device`
is the abbreviation used throughout this file.

A USB to serial adapter plugged into a managed hub uses the same chips as the control
interface and hangs on the same hub, so the two look alike. They are told apart by the
downstream port they are on: a hub wires its control interface to a fixed port, which is never
one of the ports you can plug into. The port is only looked at to break such a tie, so a hub
whose control port is not recorded is still detected as long as it is the only candidate.

`usbman --log-level DEBUG` lists every serial device with the USB ids of the device itself and
the ids and downstream port of the hub it is connected to, as in:
````
DEBUG:  /dev/ttyUSB0 (0403:6001 on port 4 of hub 14b0:044c), FT232R USB UART
````
Supporting another managed hub model is a matter of adding what it reports to
`MANAGED_HUB_USB_IDS`, `CONTROL_UART_USB_IDS` and `CONTROL_UART_HUB_PORTS` in
[usbman/__init__.py](usbman/__init__.py).

### Display the current state
This list the channels which are ON:
````
usbman --device /dev/ttyUSB0
````

### Turn on some channels
This turns on channels 1 and 5:
````
usbman --device /dev/ttyUSB0 --on 1 5
````

### Turn off some channels
This turn off channel 1 and 5:
````
usbman --device /dev/ttyUSB0 --off 1 5
````

### Turn off some channels for some time and turn back on
This turn off channel 1 and 5 for 0.5 second:
````
usbman --device /dev/ttyUSB0 --off-pulse 1 5 --toff=0.5
````
