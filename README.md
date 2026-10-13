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
Detection only reads USB identifiers, it never sends anything to a device, so whatever you have
plugged into the hub is left alone. It needs Linux, and it needs your hub model to be known —
see [AUTO-DETECT.md](AUTO-DETECT.md) if it does not find your hub.

### Check the version
````
usbman --version
````
Through `--connect` this reports the version of the server, which is the one actually driving
the hub.

### Display the current state
This list the channels which are ON:
````
usbman --device /dev/ttyUSB0
````

### Turn some channels on or off
`--set` turns channels on and `--clear` turns them off, both leaving every other channel as it
was. This turns channels 1 and 5 on, whatever the others are doing:
````
usbman --device /dev/ttyUSB0 --set 1 5
````
And this turns them off again:
````
usbman --device /dev/ttyUSB0 --clear 1 5
````
`--clr` is a shorter spelling of `--clear`. `all` stands for every channel of the hub, so this
turns everything off:
````
usbman --device /dev/ttyUSB0 --clr all
````

### Decide the state of every channel at once
`--on` is absolute: the channels you list end up on and **every other one ends up off**. This
leaves channels 2, 3 and 5 on and the rest off, whatever the hub was doing before:
````
usbman --device /dev/ttyUSB0 --on 2 3 5
````
Because it already decides every channel, `--on` cannot be combined with `--set`, `--clear` or
`--off-pulse`; asking for both is refused rather than silently resolved.

> **Changed in 2.0** — `--on` used to mean what `--set` means now. A command line such as
> `usbman --on 1 5` still works but no longer leaves the other channels alone: replace it with
> `--set 1 5` to keep the old behaviour.

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
usbman --device /dev/ttyUSB0 --set 1 5 --save
````
`--save` on its own stores the state the hub is currently in:
````
usbman --device /dev/ttyUSB0 --save
````
It applies last, after the channel options, so `--off-pulse ... --save` stores the state left by
the pulse, in which every pulsed channel is on.

### Name a device instead of a channel
Anywhere a channel number is accepted, you can instead name a device plugged into the hub and
let `usbman` work out which channel powers it:
````
usbman --off-pulse /dev/ttyACM0                       # power cycle whatever that board is
usbman --off-pulse myboard                            # the same board, by the name you gave it
usbman --channel-of /dev/ttyACM0                      # just print the channel
usbman --clear /dev/ttyACM0 3                         # mixed with plain channel numbers
````
Four ways to name a device, all equivalent:

| Form | Example |
| --- | --- |
| a nickname you chose | `myboard`, see [below](#give-your-devices-names) |
| a device path | `/dev/ttyACM0` |
| a symlink to one | `/dev/serial/by-id/usb-STMicroelectronics_STLINK-V3_004B0028...-if01` |
| a USB serial number | `004B00283532510831333430` |

A **nickname** is the one to reach for day to day: you choose it, it is short, and it keeps
working when the board is unplugged and plugged back in. It stands for a serial number, so
everything said below about serial numbers applies to it too.

Of the rest, the **serial number** is the one to use in a script: `ttyACM0` is handed out in
enumeration order and moves when you re-plug things, while the serial does not, and a serial
names a device even when it exposes no serial port at all. `lsusb -v` and the names under
`/dev/serial/by-id/` both show it.

A token of up to three digits is read as a channel number and anything longer as a nickname or
a serial, so `--clear 3` is channel 3 while `--clear 000000000` is a serial number.

Two things to expect:

- **A channel powers a whole socket.** If you plugged a hub into the managed hub, cycling any
  device behind it cycles all of them, because the hub can only switch its own socket.
- **Serial numbers are not unique.** Both sections of the StarTech hub report `000000000`, and
  cheap devices often share one too. If a serial matches more than one device, `usbman` refuses
  and lists them rather than guessing; name the one you mean by its path.

This needs the wiring of your hub model to be known to `usbman`. If it is not, the error says
so and points at `--characterize`, which works it out with a single peripheral you move from
socket to socket; [NOTES.md](NOTES.md) describes how to add a model.

### Find the /dev path to give another tool
The other way round from `--channel-of`: name a channel and get the serial port on it, so you
can hand it to whatever talks to the board.
````
$ usbman --path-of 4
/dev/ttyACM0
$ usbman --path-of numaker          # a nickname or a serial number names the channel too
/dev/ttyACM0
$ screen $(usbman --path-of numaker) 115200
````
`--id-path-of` answers the same question with the stable name udev builds from the device's
manufacturer, product and serial number, which does not move when things are re-plugged:
````
$ usbman --id-path-of numaker
/dev/serial/by-id/usb-Nuvoton_Nu-Link2_CMSIS-DAP_13150000000A25020450395D00000FCD-if01
````
That is the one to put in a script or a config file; `/dev/ttyACM0` is only true until the next
reboot. Not every device has one, since udev needs descriptors the device may not supply, and
`usbman` says so when that happens.

One path per line for both, and only paths on standard output, so they substitute cleanly. A
socket can hold more than one serial port — a composite board, or a hub with several boards
behind it — in which case all of them are printed and a warning goes to standard error.

The device has to be switched on to have a path at all. If the channel is off, or empty, or
holds something which exposes no serial port, `usbman` says which of those it is.

### Give your devices names
Serial numbers are unambiguous but unreadable. Put your own names for them in
`~/.config/usbman/nicknames`, and use those instead:
````
# ~/.config/usbman/nicknames
# nickname   serial
numaker      0005000C3338511034333935
myboard      004B00283532510831333430
pico         648326155B4B110B
````
````
usbman --off-pulse numaker        # power cycle the Numaker board
usbman --on myboard pico          # those two on, everything else off
usbman --channel-of numaker
````
A nickname can be used anywhere a channel number can, and it works for a device which is
switched off exactly as its serial number does, through the snapshot below.

**The file is yours**: usbman only ever reads it, so there are no commands to manage it — write
it with a text editor. Everything after a `#` is a comment. A nickname shaped like a channel number,
like `3`, or like `all` or a path is reported and ignored, because those are read as what they
look like long before nicknames are considered. Several names for one device are fine.

### Name a device which is switched off
Resolving a device means finding it on the USB tree, and a device on a channel which is off is
not there to be found. `--snapshot` records where everything is while it is still on, so you
can name it afterwards:
````
usbman --on all        # everything up, so everything can be seen
usbman --snapshot      # remember which channel each device is on
````
From then on a device can be named even while it is off, which is what lets you switch it back
on by name:
````
usbman --clear 004B00283532510831333430   # the board goes away
usbman --set 004B00283532510831333430     # and comes back, by name
````
`--list` shows what is on each channel, from the USB tree and from the snapshot together:
````
$ usbman --list
channel  nickname  source    serial                    device
1        myboard   live      004B00283532510831333430  STLINK-V3
1        -         live      -                         USB2.1 Hub
2        -         -         -                         -
5        pico      live      648326155B4B110B          Pico
6        numaker   snapshot  0005000C3338511034333935  Numaker M5531
7        -         live      B001DNH6                  FT232R USB UART
````
`live` is what is connected now, `snapshot` is what the file remembers about a device which is
not. A device seen now is listed once, where it actually is; if the snapshot disagrees, the
listing says so and tells you to take a new one. The nickname column shows the name you gave
the device in your nicknames file.

`--forget` deletes the snapshot.

Two things to know:

- **Only a serial number survives being switched off**, not a path: `/dev/ttyACM0` does not
  exist while the device is off, and the snapshot is keyed by serial. Use serials for anything
  you intend to switch on.
- **What is really connected always wins.** The snapshot is consulted only when the device
  cannot be found at all, so moving a board to another socket does not need a new snapshot —
  but a board which is *off* and has been moved will resolve to where it used to be, so take a
  new snapshot after rearranging things.

The snapshot is a plain text file at `~/.local/state/usbman/snapshot`, one channel and serial number
per line, which you can read or edit yourself:
````
# usbman snapshot, 2026-10-12T15:52:03
# channel  serial                            device
1          B001DNH6                          # FT232R USB UART
4          004B00283532510831333430          # STLINK-V3
````
`--snapshot` replaces it, so it reports which channels it saw nothing on rather than dropping
them quietly.

### Where the files are

| File | Written by | Looked for in |
| --- | --- | --- |
| `nicknames` | you | `~/.config/usbman/`, then `~/.local/state/usbman/` |
| `snapshot` | `--snapshot` | `~/.local/state/usbman/` |

The nicknames are looked for in two places so that both habits work: `~/.config` is where a
file you write belongs, and is used if it is there, while `~/.local/state` keeps both usbman
files together if you would rather only remember one directory. Put it in whichever you prefer
— if you somehow end up with both, the `~/.config` one is used and the other is reported as
ignored.

Those are the XDG defaults, so `$XDG_CONFIG_HOME` and `$XDG_STATE_HOME` are honoured if you
have set them, and `USBMAN_DIR` overrides everything and puts both files in one directory of
your choosing.

`--snapshot`, `--forget` and `--characterize` all act on the machine the hub is attached to, so
a client cannot ask a `usbman` server for them. Resolving a device *is* available remotely: the
server answers from its own USB tree and its own snapshot.

## Server mode
Only a process which can see the serial device may drive the hub, which leaves out remote users
and anything running in a sandbox. `--serve` hands the command line to them over a socket:
````
usbman --serve
````
The server owns the hub and runs the very same commands on behalf of its clients:
````
usbman --connect 127.0.0.1:9877 --set 1 5
````
Every option works exactly as it does locally, because the client forwards what you typed and
the server runs the same command line. Setting `USBMAN_SERVER` gets an existing script or an
automated agent onto a remote hub with no change at all:
````
export USBMAN_SERVER=127.0.0.1:9877
usbman --set 1 5
USBMAN_SERVER= usbman --set 1 5   # this one goes back to the local hub
````
**There is no authentication.** The server binds the loopback interface by default, so only
this machine can reach it; give it an address of its own only on a network you trust, since
anyone who can reach the port can cut the power to whatever is plugged into the hub. To reach
it from another machine, forward the port over ssh rather than exposing it:
````
ssh -L 9877:127.0.0.1:9877 the-machine-with-the-hub
````
[SERVER.md](SERVER.md) documents the wire protocol and the rest of the behaviour.

## Protocol
The hub speaks 9600 8N1 on the serial control interface. A command is a two character opcode,
then, for the ones that write, an 8 character password field (`pass` followed by 4 spaces by
default), then an optional payload as hex, then a carriage return. `usbman` uses three of them:
`GP` to read the channel states, `SP` to set them and `WP` to save them as the power up states.
It refuses to send any other opcode, `CP`, which changes the password, above all: a mistake
there locks the hub out for good.

[NOTES.md](NOTES.md) documents the protocol in full, including the commands `usbman` does not
use, and how to re-derive any of it from the vendor CLI.
