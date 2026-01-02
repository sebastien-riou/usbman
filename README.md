# usbman
Software to control 'managed' USB hubs compatible with 'cuspi' closed source binary.
For example  [startech 7 ports hub](https://www.startech.com/en-us/usb-hubs/5g7aindrm-usb-a-hub).

![StarTech.com managed hub](startech-hub-7.jpg?raw=true "StarTech.com managed hub")

## Installation

### Using pypi
````
pip install usbman
````

### Using pyinstaller
This build a native package.

````
pipenv run ./package_usbman
````

Add `dist/usbman` in your PATH.

### Using a pre-built release
Place the binary in your PATH.

## How to

### Display the current state
This list the channels which are ON:
````
usbman
````

### Turn on some channels
This turns on channels 1 and 5:
````
usbman --on 1 5
````

### Turn off some channels
This turn off channel 1 and 5:
````
usbman --off 1 5
````


