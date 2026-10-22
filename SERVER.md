# The usbman server

`usbman serve` owns the serial device and runs hub commands for clients which cannot reach it
themselves: users on another machine, and anything inside a sandbox. README.md shows how to use
it; this documents how it behaves and what goes over the socket.

## Why it forwards arguments rather than a command set of its own

The client sends its argument list and the server runs **the same command line parser** on it,
handing back the output and the exit code. Nothing in the protocol knows what a channel is, so a
new option works remotely the day it is added, and the two can never drift apart. The test which
matters most, in `test/test_server.py`, runs a command locally and remotely and compares the two
byte for byte.

The consequence is that `--connect` accepts anything the local command accepts, including
`--help`, and that a bad argument is reported by the server exactly as it would be locally. The
`+1 -3` shorthand is expanded at both ends, so it works typed straight at the socket too.

## The wire protocol

Line oriented, and meant to be usable by hand.

```
request    one line, split the way a shell would; an empty line reports the state
           "token <token>" gives the token, to a server started with --token
response   "O <text>"   a line for the client stdout
           "E <text>"   a line for the client stderr
           "EXIT <n>"   end of the answer, the exit code as a signed integer
```

```
$ nc 127.0.0.1 9877
+1 +3
O On: 1 3 
EXIT 0
switch --off all
O All off
EXIT 0
+8
E usage: usbman switch [-h] [--log-level {DEBUG,INFO,WARNING,ERROR,CRITICAL}]
E                      [--save] [--on CHANNEL [CHANNEL ...]]
E                      [--off CHANNEL [CHANNEL ...]]
E usbman switch: error: argument --on: invalid channel '8', expected 1 to 7 or 'all'
EXIT 2
$
```

Details worth knowing:

- **A refused line ends the connection.** `EXIT 2` means the server could not make sense of the
  line: it does not parse, it is longer than 4096 bytes, or the token is wrong or has not been
  given yet. The server closes the connection after answering it, and nothing sent after it
  runs, which is why the session above ends at `+8`. Whatever sent such a line is not speaking
  this protocol, so the lines which follow are not to be trusted either; [Security](#security)
  has the case which makes this matter. A request which parses and then fails, `EXIT -1` say,
  leaves the connection open.
- **Every line is answered**, the token line included, which gets `EXIT 0` when it is right.
- **The two streams stay apart.** The commands print their result but report every error through
  the log, and argparse writes its usage errors straight to stderr. A client which merged them
  would add log noise to `usbman +1 | grep`, and the point of `USBMAN_SERVER` is that a
  pipeline cannot tell the difference.
- **Content after the tag is verbatim.** `On: 1 3 ` really does end with a space.
- **One connection carries as many requests as you like**, so a session with `nc` is a small
  REPL and a script can hold one connection open.
- Lines are sent as they are produced, so a long `--reset` shows its progress.
- Anything which is not valid UTF-8 is replaced rather than raising, so a port scanner or a
  stray TLS handshake becomes a refused line instead of an exception.
- Exit codes round trip signed: `-1` is a usbman error and `-2` means it could not talk to the
  hub, which the shell reports as 255 and 254 exactly as it does locally.

## One request at a time

A lock is held for the **whole request**, not for each command sent to the hub. `--reset` is
several commands with a wait in between, so two clients pulsing at once would otherwise
interleave and leave channels off.

The lock is in process only. It does not stop a plain `usbman` run on the machine hosting the
server, nor a second server, from talking to the same hub at the same time. Run one server for a
hub and drive it through that.

## A request cannot be cancelled

If the client disconnects, the hub operation still **runs to its end**. This is deliberate: were
a broken connection allowed to interrupt the command, a client which vanished in the middle of an
`--reset` would leave the channels off for good. Interrupting the client is safe, and the
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

## What a client may not ask for

`snapshot`, `forget`, `characterize` and `serve` act on the machine the hub is attached to — they
write a file there, or ask someone standing at the hub to move a peripheral — so a request
carrying any of them is refused. The server tells `run()` that the request did not originate
locally and it declines.

Resolving a device is *not* local: a client naming a device by path or serial number is answered
from the server's USB tree and, failing that, the server's snapshot. That is the right way
round, since the devices and the hub are both on the server's machine. So
`usbman --connect … +004B0028…` switches on a board which is currently off, while
`usbman --connect … snapshot` is refused.

## Security

**Without `--token` there is none.** Anyone who can open the port can switch the channels,
which for a managed hub means cutting the power to whatever is plugged in. The default bind is
`127.0.0.1`, so nothing off the machine can reach it, but every user and every program on it
can.

**With `--token`, a connection must give the token before anything else**, as the line
`token <token>`. Any other line before it is refused, and so ends the connection. `--connect`
sends the token for you:

```
TOKEN=$(python3 -c 'import secrets; print(secrets.token_hex(16))')
usbman serve --token "$TOKEN"
usbman --connect 127.0.0.1:9877 --token "$TOKEN" +1
```

- **Use a long random token**, as above: nothing limits how fast a client may guess.
- **`USBMAN_TOKEN` stands for `--token`** at both ends. It keeps the token off the command line,
  where every user of the machine can read it with `ps`, and it lets a script written for
  `USBMAN_SERVER` reach a server with a token with no change.
- **The server says when it starts whether it requires a token, and where it got it**, without
  ever showing the token itself:

  ```
  Serving /dev/ttyUSB0 on 127.0.0.1:9877, token required, from USBMAN_TOKEN
  ```

  The line ends `from --token` when the token came from the command line, and
  `no authentication` when there is none. The environment is the source to watch for: a token
  exported for your clients is easy to forget, and a server started from the same shell takes
  it too.
- **With `--log-level DEBUG`, every refused line is logged**, with the address of the client
  which sent it and the reason it was given, so that a client being turned away shows on the
  server too. Only at that level, since any client can be refused as often as it likes.
- **An empty `--token` is refused.** It is what `--token "$TOKEN"` gives when the variable is
  unset, and the server would otherwise start open to anybody. An empty `USBMAN_TOKEN` means no
  token, the way an empty `USBMAN_SERVER` means no server.
- **A server without a token refuses one.** A client sending a token believes the hub is
  protected, and is told that it is not rather than left to believe it.
- **The token travels in clear.** It keeps out whoever does not know it, not whoever can watch
  the traffic. To use the server from elsewhere, forward the port over ssh rather than binding
  a public address:

  ```
  ssh -L 9877:127.0.0.1:9877 the-machine-with-the-hub
  ```

**A web page cannot drive the hub, with a token or without.** A browser can be made to send an
HTTP request to the port with commands in its body, but the request line comes first and never
parses, so the connection ends before any of the body runs. That holds for a browser only: a
program which chooses every line it sends, the first one included, is kept out by the token
alone.

## Running it under systemd

```ini
[Unit]
Description=usbman server
After=network.target

[Service]
ExecStart=/usr/local/bin/usbman serve 127.0.0.1:9877
Restart=on-failure
# must be in the group owning /dev/ttyUSB*, usually dialout
User=yourself
# holds the line USBMAN_TOKEN=...; leave this out to serve without a token
EnvironmentFile=/etc/usbman.env

[Install]
WantedBy=multi-user.target
```

systemd reads the `EnvironmentFile` before it switches to the `User`, so the file can belong to
root with mode `600`, which keeps the token from every other user of the machine.

`SIGTERM` and Ctrl-C both stop the server cleanly, so `systemctl stop` needs nothing special.
Restarting is also how you recover after re-plugging the hub.
