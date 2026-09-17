# The usbman server

`usbman --serve` owns the serial device and runs hub commands for clients which cannot reach it
themselves: users on another machine, and anything inside a sandbox. README.md shows how to use
it; this documents how it behaves and what goes over the socket.

## Why it forwards arguments rather than a command set of its own

The client sends its argument list and the server runs **the same command line parser** on it,
handing back the output and the exit code. Nothing in the protocol knows what a channel is, so a
new option works remotely the day it is added, and the two can never drift apart. The test which
matters most, in `test/test_server.py`, runs a command locally and remotely and compares the two
byte for byte.

The consequence is that `--connect` accepts anything the local command accepts, including
`--help`, and that a bad argument is reported by the server exactly as it would be locally.

## The wire protocol

Line oriented, and meant to be usable by hand.

```
request    one line, split the way a shell would; an empty line reports the state
response   "O <text>"   a line for the client stdout
           "E <text>"   a line for the client stderr
           "EXIT <n>"   end of the answer, the exit code as a signed integer
```

```
$ nc 127.0.0.1 9877
--on 1 3
O On: 1 3 
EXIT 0
--on 8
E usage: usbman [-h] [--log-level {DEBUG,INFO,WARNING,ERROR,CRITICAL}]
E               [--on ON [ON ...]] [--off OFF [OFF ...]]
E               [--off-pulse OFF_PULSE [OFF_PULSE ...]] [--toff TOFF] [--save]
E usbman: error: argument --on: invalid channel '8', expected 1 to 7 or 'all'
EXIT 2
--off all
O All off
EXIT 0
```

Details worth knowing:

- **The two streams stay apart.** The commands print their result but report every error through
  the log, and argparse writes its usage errors straight to stderr. A client which merged them
  would add log noise to `usbman --on 1 | grep`, and the point of `USBMAN_SERVER` is that a
  pipeline cannot tell the difference.
- **Content after the tag is verbatim.** `On: 1 3 ` really does end with a space.
- **One connection carries as many requests as you like**, so a session with `nc` is a small
  REPL and a script can hold one connection open.
- Lines are sent as they are produced, so a long `--off-pulse` shows its progress.
- A request is capped at 4096 bytes; a longer one is refused and the connection closed, since
  the stream is then out of step.
- Anything which is not valid UTF-8 is replaced rather than raising, so a port scanner or a
  stray TLS handshake becomes an argparse error instead of an exception.
- Exit codes round trip signed: `-1` is a usbman error and `-2` means it could not talk to the
  hub, which the shell reports as 255 and 254 exactly as it does locally.

## One request at a time

A lock is held for the **whole request**, not for each command sent to the hub. `--off-pulse` is
several commands with a wait in between, so two clients pulsing at once would otherwise
interleave and leave channels off.

The lock is in process only. It does not stop a plain `usbman` run on the machine hosting the
server, nor a second server, from talking to the same hub at the same time. Run one server for a
hub and drive it through that.

## A request cannot be cancelled

If the client disconnects, the hub operation still **runs to its end**. This is deliberate: were
a broken connection allowed to interrupt the command, a client which vanished in the middle of an
`--off-pulse` would leave the channels off for good. Interrupting the client is safe, and the
pulse completes without it.

## Timeouts

`--timeout` takes seconds and defaults to `-1`, which blocks forever.

| Side | What it bounds | Default |
| --- | --- | --- |
| `--connect` | connecting, and each read of the answer | `-1`, wait indefinitely |
| `--serve` | waiting for the next request on an idle connection | `-1`, never drop a client |

Nothing bounds how long a request may run: `--toff` is yours to choose, and any cap would cut a
legitimate long pulse short.

## The device is resolved once

The server picks its device at startup, from `--device` or by auto detection, and keeps it for
its lifetime. If the hub is unplugged and plugged back in, its `/dev/ttyUSB*` number may change
and the server will report that it cannot talk to it; restart the server. If no hub is found at
startup, the server refuses to start rather than accepting clients it cannot serve.

`--device` is rejected on a client: the server owns the hub, and accepting it would let
`--connect somewhere --device /dev/ttyUSB1` look as though it had worked on a different hub.

## Security

There is none. Anyone who can open the port can switch the channels, which for a managed hub
means cutting the power to whatever is plugged in. The default bind is `127.0.0.1`, so nothing
off the machine can reach it; to use it from elsewhere, forward the port over ssh rather than
binding a public address:

```
ssh -L 9877:127.0.0.1:9877 the-machine-with-the-hub
```

## Running it under systemd

```ini
[Unit]
Description=usbman server
After=network.target

[Service]
ExecStart=/usr/local/bin/usbman --serve 127.0.0.1:9877
Restart=on-failure
User=yourself            # must be in the group owning /dev/ttyUSB*, usually dialout

[Install]
WantedBy=multi-user.target
```

`SIGTERM` and Ctrl-C both stop the server cleanly, so `systemctl stop` needs nothing special.
Restarting is also how you recover after re-plugging the hub.
