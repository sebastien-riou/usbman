# How `usbman` finds the hub

When `--device` is omitted, `usbman` locates the control interface of the managed hub itself.
This documents how, why it works that way, and what to do when it does not.

## The problem

The control interface of a managed hub is not a device of its own that you plug in: it is a
serial chip wired to one of the hub's own downstream ports, so it appears as a `/dev/ttyUSB*`
among all the other serial devices of the system. Nothing in its name says which one it is, and
the order in which they are enumerated is not stable.

Sending a harmless query to each candidate and keeping whichever answers would be the obvious
approach, and it is the wrong one: the other candidates are somebody else's hardware — a
debugger, a board, an instrument — and a stray write can do real damage. **Detection therefore
reads USB identifiers only and never sends a byte to any device.**

## The signature

Two facts have to hold together:

1. the serial device's own USB ids are those of a chip these hubs use as control interface
   (`CONTROL_UART_USB_IDS`), and
2. the USB device it hangs on — its parent, i.e. the hub it is wired into — has the ids of a
   known managed hub (`MANAGED_HUB_USB_IDS`).

Neither half is enough on its own. The chip is an ordinary FT232R, the same one in countless USB
to serial cables, so the first test alone matches any of them. And everything you plug into the
managed hub is *also* a child of that hub, so the second test alone matches all of them. On a
typical desk that means an ST-Link, a Nu-Link2 and a Pico all pass test 2 and are correctly
rejected by test 1.

## Telling the control interface from an adapter on the same hub

A USB to serial adapter plugged into the managed hub satisfies both tests: same chip, same parent
hub. It is genuinely indistinguishable by ids alone.

What separates them is the **downstream port**. A hub wires its control interface to one fixed
port, and that port is not one of the sockets on the case — so an adapter you plug in can never
land on it. `CONTROL_UART_HUB_PORTS` records that port per hub model, and it is consulted **only
to break a tie**: with a single candidate the port is never looked at, so a hub model missing
from the table is still detected as long as it is the only candidate.

If the tie cannot be broken — no candidate on a known control port, or several — `usbman` refuses
rather than guessing, and asks for `--device`.

`removable` in sysfs would have been a cleaner discriminator, but these hubs report `unknown` for
every downstream device, so it is unusable.

## Implementation

In [usbman/\_\_init\_\_.py](usbman/__init__.py):

- `usb_topology()` resolves `/sys/class/tty/<name>/device`, walks up to the first node carrying
  an `idVendor`, and reads that node's ids, its `devpath` port number, and its parent's ids.
- `SerialDevice.is_hub_control_interface()` applies the two tests above;
  `is_on_control_interface_port()` is the tie-breaker.
- `find_device_path()` requires exactly one match and raises otherwise.

This reads the USB tree from sysfs, so it works on Linux. Elsewhere the topology comes back
empty, no device qualifies, and `--device` is required.

## Diagnosing

`usbman --log-level DEBUG` lists every serial device with its own ids and the ids and port of the
hub it is connected to:

````
DEBUG:  /dev/ttyACM0 (0483:3754 on port 3 of hub 14b0:044a), STLINK-V3
DEBUG:  /dev/ttyACM1 (2e8a:0009 on port 3 of hub 14b0:044c), Pico
DEBUG:  /dev/ttyACM2 (0416:2004 on port 2 of hub 14b0:044c), Nu-Link2 CMSIS-DAP
DEBUG:  /dev/ttyUSB0 (0403:6001 on port 4 of hub 14b0:044c), FT232R USB UART
````

Here only `/dev/ttyUSB0` passes both tests. When detection finds nothing, the error message
lists the same information, so `--log-level DEBUG` is rarely needed.

`lsusb` and `lsusb -t` show the same tree from the other side, which is the quickest way to read
off the ids of a hub that is not recognized yet.

## Supporting another hub model

Add what the hub reports to the three tables in [usbman/\_\_init\_\_.py](usbman/__init__.py):

| Table | What to add |
| --- | --- |
| `MANAGED_HUB_USB_IDS` | the ids of each USB hub the managed hub presents (a 7-port model appears as two cascaded 4-port hubs, so both) |
| `CONTROL_UART_USB_IDS` | the ids of the serial chip, if it is not the FT232R already listed |
| `CONTROL_UART_HUB_PORTS` | the downstream port the control interface is wired to, if you can determine it |

The last one is optional: without it the hub is still detected whenever it is the only candidate.
To determine it, note the port reported for the control interface in the DEBUG listing above,
then confirm by plugging a USB to serial adapter into each socket of the hub and checking that
none of them ever reports that port.

The reference values, from a StarTech 7-port hub:

| | |
| --- | --- |
| upstream hub section | `14b0:044a` |
| downstream hub section | `14b0:044c` |
| control interface | `0403:6001` (FTDI FT232R) |
| control interface port | 4, on `14b0:044c` |
