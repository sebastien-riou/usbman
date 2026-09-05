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
`--device` is optional: leave it out and `usbman` finds the hub on its own, so all the examples
below work the same way without it.
````
usbman
````
Give it when you have more than one managed hub, or when `usbman` tells you it could not find
one:
````
usbman --device /dev/ttyUSB0
````
`--device` is the short form of `--device-path`, and is used throughout this file.

Detection only reads USB identifiers, it never sends anything to a device, so whatever you have
plugged into the hub is left alone. It needs Linux, and it needs your hub model to be known —
see [AUTO-DETECT.md](AUTO-DETECT.md) if it does not find your hub.

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
default), then an optional payload as hex, then a carriage return. `usbman` uses three of them:
`GP` to read the channel states, `SP` to set them and `WP` to save them as the power up states.
It refuses to send any other opcode, `CP`, which changes the password, above all: a mistake
there locks the hub out for good.

[NOTES.md](NOTES.md) documents the protocol in full, including the commands `usbman` does not
use, and how to re-derive any of it from the vendor CLI.
