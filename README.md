# usbman
[![OpenSSF Scorecard](https://api.scorecard.dev/projects/github.com/sebastien-riou/usbman/badge)](https://scorecard.dev/viewer/?uri=github.com/sebastien-riou/usbman)

Software to control 'managed' USB hubs compatible with the 'cusbi' closed source binary.
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
`all` stands for every channel of the hub, so this turns them all on:
````
usbman --device /dev/ttyUSB0 --on all
````

### Turn off some channels
This turn off channel 1 and 5:
````
usbman --device /dev/ttyUSB0 --off 1 5
````
And this turns them all off:
````
usbman --device /dev/ttyUSB0 --off all
````

### Turn off some channels for some time and turn back on
This turn off channel 1 and 5 for 0.5 second:
````
usbman --device /dev/ttyUSB0 --off-pulse 1 5 --toff=0.5
````
`all` works here too, this power cycles the whole hub:
````
usbman --device /dev/ttyUSB0 --off-pulse all --toff=0.5
````
Note that the pulsed channels are all on when the command returns, whether they were on or off
to begin with.

### Persist the state across power down
The hub can store a state in its flash and come up in that state after a power down. `--save`
stores whatever state the command ends up with, so this turns channels 1 and 5 on and makes
that the state the hub powers up with:
````
usbman --device /dev/ttyUSB0 --on 1 5 --save
````
`--save` on its own stores the state the hub is currently in:
````
usbman --device /dev/ttyUSB0 --save
````
It applies last, after `--on`, `--off` and `--off-pulse`, so `--off-pulse ... --save` stores the
state left by the pulse, in which every pulsed channel is on.

## Protocol
The hub speaks 9600 8N1 on the serial control interface. A command is a two character opcode,
then, for the ones that write, an 8 character password field (`pass` followed by 4 spaces by
default), then an optional payload as hex, then a carriage return. A reply is the 4 payload
bytes as hex, sometimes prefixed with `G`, or `E` followed by a two character error code, `E01`
meaning the password was refused.

The payload holds 8 channels per byte, little endian, so its 4 bytes cover the 32 channels of
the largest hubs of the family. This one has 7, all in the first byte.

| Command | `cusbi` option | Meaning |
| --- | --- | --- |
| `GP\r` | `/G` | get the channel states, no password |
| `?Q…` | `/Q` | enumerate the hubs, no password |
| `SPpass    XXXXXXXX\r` | `/S` | set the channel states |
| `FPpass    XXXXXXXX\r` | `/F` | set the channel states and save them as the power up states |
| `WPpass    \r` | `/W` | save the current channel states as the power up states |
| `RDpass    \r` | `/D` | restore the factory defaults |
| `RHpass    \r` | `/R` | reset the whole hub |
| `CPpass    <new>\r` | `/P` | change the password |

`usbman` implements `GP`, `SP` and `WP`. It refuses to send any other opcode, `CP` above all:
it takes the same password field as the rest, so a mistake there locks the hub out for good.

This table was read out of the vendor CLI `cusbi` v1.03 for Linux, which ships as an unstripped
ELF with debug info: `strings` gives the command strings and its own help text, and `objdump -d`
shows which of them each of its `DoSetPortState` / `DoSavePortState` / ... functions uses and
what it expects back. Before that, what little was known had been obtained by sniffing `cusbi`
over USB with Wireshark and [parse_usb_json](parse_usb_json).
