# Managed USB hub wire protocol

Everything known about the serial protocol of the managed hubs `usbman` controls. There is no
vendor documentation for it; see [Provenance](#provenance) for where this comes from and how to
re-derive it. Each claim below is marked **verified** (read out of the vendor binary or observed
on the wire) or **inferred** (a reading that fits the evidence but has not been confirmed).

## Transport

- The control interface is an FTDI FT232R (`0403:6001`) wired to a downstream port of the hub
  itself, appearing as `/dev/ttyUSB*`. On the 7-port StarTech hub it sits on port 4 of the
  downstream hub section `14b0:044c`. **Verified** (sysfs topology).
- **9600 baud, 8 data bits, no parity, 1 stop bit.** **Verified**: `cusbi` calls
  `set_opt(fd, 9600, 8, 'N', 1)`, and `usbman` has always talked to the hub at 9600 8N1.
- `cusbi` builds its `termios` from a zeroed struct and sets only speed and framing, so no flow
  control. **Verified** (`bzero` of the struct, then `cfsetispeed`/`cfsetospeed`).
- Commands and replies are printable ASCII.

### How `cusbi` reads a reply

`SendCommand` reads **one byte at a time** via `select()` with a **100 ms timeout per byte**,
stopping at a line feed (`\n`, 0x0A) or after 20 bytes, whichever comes first. If the last byte
read is not `\n` the command is reported as failed. **Verified** (`UART_Recv(fd, &c, 1, 100)`,
loop bound `cmpl $0x13`, terminator `cmp $0xa`).

Practical consequence: a reply is terminated by `\r\n` and is never longer than 20 bytes. Note
that `usbman` does *not* do this — [usbman/clicom.py](usbman/clicom.py) sleeps 100 ms and then
reads whatever arrived, which is adequate for these short replies but would truncate a slow one.

## Command framing

```
<opcode><password><payload>\r
```

| Field | Width | Notes |
| --- | --- | --- |
| opcode | 2 characters | see the table below |
| password | 8 characters | only on commands that write; factory default `pass` followed by 4 spaces |
| payload | 8 hex characters | only on the commands that carry channel states |
| terminator | 1 character | carriage return, `\r` (0x0D) |

**Verified**: the opcode strings, the literal `'pass    '`, and the concatenation
`opcode + password + payload + "\r"` in each `Do*` function of `cusbi`.

## Commands

| Wire | `cusbi` | `cusbi` function | Password | Meaning |
| --- | --- | --- | --- | --- |
| `GP\r` | `/G` | `DoGetPortState` | no | get the current channel states |
| `?Q\r` | `/Q` | `QueryHub` | no | identify the hub and report its port count and firmware |
| `SPpass    XXXXXXXX\r` | `/S` | `DoSetPortState` | yes | set the channel states |
| `FPpass    XXXXXXXX\r` | `/F` | `DoSetFlashPortState` | yes | set the channel states **and** save them as the power up states |
| `WPpass    \r` | `/W` | `DoSavePortState` | yes | save the current channel states as the power up states |
| `RDpass    \r` | `/D` | `DoRestoreDefault` | yes | restore the factory default settings |
| `RHpass    \r` | `/R` | `DoResetHub` | yes | reset the whole hub |
| `CPpass    <new password>\r` | `/P` | `DoChangePassword` | yes | change the password |

All **verified**: each opcode string is referenced from exactly one `Do*`/`Query*` function, and
`?Q\r` and `GP\r` are stored with their carriage return already in the literal.

> `CP` writes a new password using the same password field as every other command. Get it wrong
> and the hub is locked out for good, with only `RD` (which itself needs the password) to
> recover. `usbman` refuses to send it; see `OPCODES` in [usbman/\_\_init\_\_.py](usbman/__init__.py).

`RD` and `RH` take no payload. This is **inferred** for both from their `cusbi` usage
(`cusbi /D:ttyUSBn [pass]` and `/R:ttyUSBn [pass]` take no further argument), by analogy with
`WP`, whose empty payload is verified.

## Payload encoding

Four bytes, sent as 8 uppercase hex characters, **8 channels per byte, little endian**: channel
`n` is bit `(n - 1) % 8` of byte `(n - 1) // 8`. Four bytes therefore address up to 32 channels,
which is what the larger hubs of the family need; a 7-port hub uses only the first byte.

**Verified** two ways: `htos_PS64` emits `%02X` for `i = 0..3`, and `cusbi`'s own help documents
`H:A601` as "port 2, 3, 6, 8, 9 on" — `A6` = `1010 0110` gives channels 2, 3, 6, 8 and the
second byte `01` gives channel 9.

Channel states are carried internally by `cusbi` as an `unsigned long long` (`stoh_PS64` /
`htos_PS64` — "PS64", 64 channels' worth), of which only 32 reach the wire.

### The 0x80 bit

`usbman` sets bit 7 of byte 0 on every write (`state |= 0x80`) and masks it off on every read
(`state &= 0x7F`). Given the encoding above, **that bit is channel 8**, not a flag: on a 7-port
hub `usbman` is asking for a channel that does not exist, and hiding a channel that would exist
on a bigger one. Harmless here, wrong on a 14- or 28-port model. The trailing `FFFFFF` that
`usbman` sends is, by the same token, not a mystery register — it is channels 9 to 32, all on.

## Replies

A reply is at most 20 bytes and ends with `\r\n`.

| Shape | Length | Meaning |
| --- | --- | --- |
| `XXXXXXXX\r\n` | 8 hex characters | the 4 payload bytes, i.e. the channel states |
| `GXXXXXXXX\r\n` | `G` + 8 hex characters | the same, prefixed with `G` |
| `Enn\r\n` | 3 characters | failure, `nn` being an error code |

Observed asymmetry: `GP` answers **without** the `G` prefix (a real reply is
`b'FFFFFFFF\r\n'`), while `WP` answers **with** it — `DoSavePortState` treats a first byte other
than `'G'` (`cmp $0x47`) as "Error to Save Port States to Flash!". Both **verified**, the first
on the wire and the second in the binary. `usbman`'s `decode_result` has always stripped an
optional leading `G`, which is why it copes with both; that lone branch was the only surviving
hint of this whole command set before the binary was read.

### Error codes

| Code | Meaning | Status |
| --- | --- | --- |
| `E01` | wrong password | **verified** — `DoSavePortState` maps it to "Invalid Password!" |
| `EFF` | command refused | **inferred** — observed by `usbman` and hardcoded there since the first commit; the exact trigger is unknown |

Other codes very likely exist and are undocumented. Note that the **length is what separates an
error from a state**: byte 0 of a state always has bit 7 set, so a state reply can perfectly well
begin with `E` — `E5FFFFFF` is the valid state "channels 1, 3, 6, 7 on". Only a 3-character body
is an error.

## The `?Q` identification command

`?Q\r` needs no password and is how `cusbi` finds hubs: it scans the `/dev/ttyUSB*` devices
(its help documents `n = 1 to 255`), sends `?Q\r`, and requires the reply to match
**`CENTOS`**; anything else is
reported as "ID Err". The same reply yields the hub's **port count** and **firmware version** —
`DoQuery` prints them as `<n> ports, On=…, Off=…, FW=…`. **Verified** that `?Q\r` is sent and
that the reply is checked against `CENTOS`.

The exact field layout of the `?Q` reply is **not decoded**: the port count and firmware are
extracted with computed rather than constant offsets, so reading them off the disassembly alone
was not conclusive. Capturing one real `?Q` reply would settle it.

This would be a cheaper and more certain hub detection than what `usbman` does today (matching
USB ids and the downstream port the control interface sits on), but it means writing to a device
before knowing what it is, which `usbman` deliberately avoids.

## `cusbi` command line, for cross-checking

```
cusbi /Q                       query all managed hubs        (-F: formatted output)
cusbi /G:ttyUSBn [option]      get states                    (-B: binary, -H: little-endian hex)
cusbi /S:ttyUSBn [pass] states  set states
cusbi /F:ttyUSBn [pass] states  set states and save as initial
cusbi /W:ttyUSBn [pass]        save current states as initial
cusbi /P:ttyUSBn [old] new     change password (8 characters maximum)
cusbi /D:ttyUSBn [pass]        restore factory defaults
cusbi /R:ttyUSBn [pass]        reset the hub
```

`n` runs from 1 to 255, and the password defaults to `pass␣␣␣␣` when omitted. The `states`
argument accepts, per `cusbi`'s own help:

| Form | Meaning |
| --- | --- |
| `1:3,4` | channels 3 and 4 on |
| `0:3` | channel 3 off |
| `T:1,2` | toggle channels 1 and 2 |
| `0:ALL` | all channels off |
| `B:0101` | binary — channels 1 and 3 on, 2 and 4 off |
| `H:A601` | byte hex, little endian — channels 2, 3, 6, 8, 9 on, the rest off |

This is `cusbi`'s command line syntax, not the wire protocol: all of these are reduced to the
4-byte payload before being sent.

## What `usbman` implements

`GP`, `SP` and `WP`. `command()` in [usbman/\_\_init\_\_.py](usbman/__init__.py) refuses any
opcode absent from `OPCODES`, so `FP`, `RD`, `RH` and above all `CP` cannot go out by accident.
Add an opcode there only once it has been verified against `cusbi`.

`FP` would let `--on 1 5 --save` be a single command instead of `SP` followed by `WP`; it is not
used because one uniform `WP` at the end also covers `--off-pulse`, where the state worth saving
only exists once the pulse is over.

## Open questions

- The field layout of the `?Q` reply (port count, firmware version).
- Error codes other than `E01`, and what exactly provokes `EFF`.
- Whether the payload may be longer than 4 bytes. `cusbi` has a
  `%02X%02X%02X%02X%02X%s` format string — **five** `%02X` — used inside `DoQuery`, while
  `htos_PS64` emits exactly four. Unresolved, and irrelevant to a 7-port hub.
- Whether `RD` resets the password to the factory default as well as the states.
- The `12345678` string in `QueryHub` is **inferred** to be an 8-character placeholder for the
  state field, overwritten before use rather than sent. Worth confirming if `?Q` is ever
  implemented.

## Provenance

The vendor CLI, `cusbi` v1.03 for Linux/x86-64 (from the Coolgear "Managed USB Hub Software"
download), ships as an **unstripped ELF with debug info**, which is where all of the above comes
from. It is not redistributable, so it is gitignored rather than committed; keep a local copy at
the repository root to redo any of this:

```bash
file cusbi                                  # confirm: not stripped, with debug_info
strings -n 2 cusbi                          # command strings, error messages, full help text
nm -C --defined-only cusbi | grep ' T '     # function names: DoSavePortState, DoChangePassword, ...
objdump -d cusbi > cusbi.asm                # then find which function references which string
```

The string constants live in `.rodata` at virtual address `0x409800`; for this non-PIE binary a
`strings -t x` file offset maps to a virtual address by adding `0x400000`. Tracing a command
means finding the `mov $0x<addr>,%esi` that loads its string and checking which function the
instruction falls in, using the address ranges from `nm`.

Before this, the only knowledge of the protocol came from sniffing `cusbi` over USB with
Wireshark and decoding the export with [parse_usb_json](parse_usb_json) — which is how `GP` and
`SP` were originally found, and which remains the way to answer the open questions above.
