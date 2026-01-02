# usbman
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

### Display the current state
This list the channels which are ON:
````
usbman --device-path /dev/ttyUSB0
````

### Turn on some channels
This turns on channels 1 and 5:
````
usbman --device-path /dev/ttyUSB0 --on 1 5
````

### Turn off some channels
This turn off channel 1 and 5:
````
usbman --device-path /dev/ttyUSB0 --off 1 5
````


