"""Server and client for `usbman --serve` and `usbman --connect`.

The hub control interface is a serial device, so only a process which can see it may drive the
hub. The server owns that device and runs the very same command line on behalf of clients: the
client forwards its arguments verbatim and the server hands back the output and the exit code.
Nothing here knows what a channel is, so the two can never drift apart.

SERVER.md documents the wire protocol.
"""

import argparse
import contextlib
import logging
import shlex
import socket
import socketserver
import sys
import threading

from usbman import cli, find_device_path

DEFAULT_ENDPOINT = '127.0.0.1:9877'
DEFAULT_HOST = '127.0.0.1'
DEFAULT_PORT = 9877

# A request is one line, so a client which never sends one cannot make us buffer without end.
MAX_REQUEST = 4096

TAG_OUT = 'O'  # goes to the client stdout
TAG_ERR = 'E'  # goes to the client stderr
EXIT_PREFIX = 'EXIT '

# One hub, so one request at a time. The lock spans the whole request and not a single command:
# `--off-pulse` is several commands with a sleep in between, and two clients interleaving there
# would leave channels off. It is in process only, a local `usbman` run still interleaves.
LOCK = threading.Lock()


def split_transport(args):
    """Split the transport options off `args`, returning them and the hub command arguments.

    The transport options are deliberately absent from the hub command parser: they answer
    which hub and how to reach it, not what to do to it. `parse_known_args` hands back the rest
    untouched, so the client forwards exactly what the user typed. `allow_abbrev` is off so
    that this parser does not swallow abbreviations such as `--s`, which belong to the hub
    command parser.
    """
    parser = argparse.ArgumentParser(add_help=False, allow_abbrev=False)
    parser.add_argument('--device', default=None)
    parser.add_argument('--serve', nargs='?', const='', default=None)
    parser.add_argument('--connect', default=None)
    parser.add_argument('--timeout', type=float, default=-1)
    return parser.parse_known_args(list(args))


def peek_log_level(argv, default='INFO'):
    """Return the `--log-level` of `argv` without consuming it.

    The client forwards `--log-level` to the server, but it also wants it for its own log, so
    this looks rather than parses.
    """
    for index, argument in enumerate(argv):
        if argument == '--log-level' and index + 1 < len(argv):
            return argv[index + 1]
        if argument.startswith('--log-level='):
            return argument.split('=', 1)[1]
    return default


def parse_endpoint(text, default_host=DEFAULT_HOST, default_port=DEFAULT_PORT):
    """Return the `(host, port)` of `HOST:PORT`, `:PORT`, `PORT`, `HOST` or `[::1]:PORT`."""
    text = (text or '').strip()
    if not text:
        return (default_host, default_port)
    if text.startswith('['):  # bracketed IPv6, the only form where a colon is not a separator
        host, _, rest = text[1:].partition(']')
        port = rest.lstrip(':')
        return (host or default_host, int(port) if port else default_port)
    if ':' in text:
        host, _, port = text.rpartition(':')
        return (host or default_host, int(port) if port else default_port)
    if text.isdigit():
        return (default_host, int(text))
    return (text, default_port)


def address_family(host):
    """Return the socket family to reach or bind `host`."""
    return socket.AF_INET6 if ':' in host else socket.AF_INET


class ThreadStream:
    """A `sys.stdout` or `sys.stderr` stand in routing each thread's writes to its own sink.

    Installed once for the life of the server: replacing them per request, the way
    `contextlib.redirect_stdout` does, swaps them process wide and so cannot be thread safe.
    A thread with no sink writes to the real stream, which keeps the server own log on its
    console.
    """

    def __init__(self, fallback):
        self.fallback = fallback
        self.local = threading.local()

    def set_sink(self, sink):
        self.local.sink = sink

    def sink(self):
        return getattr(self.local, 'sink', None)

    def write(self, text):
        sink = self.sink()
        if sink is None:
            return self.fallback.write(text)
        sink.write(text)
        return len(text)

    def flush(self):
        if self.sink() is None:
            self.fallback.flush()

    def isatty(self):
        return False


class TaggedSink:
    """Collect writes into whole lines and emit them tagged, to keep the streams apart."""

    def __init__(self, tag, emit):
        self.tag = tag
        self.emit = emit
        self.pending = ''

    def write(self, text):
        self.pending += text
        while '\n' in self.pending:
            line, _, self.pending = self.pending.partition('\n')
            self.emit(f'{self.tag} {line}\n')

    def close(self):
        """Emit whatever was written without a closing newline."""
        if self.pending:
            self.emit(f'{self.tag} {self.pending}\n')
            self.pending = ''


class ThreadLevelFilter(logging.Filter):
    """Hold a log level per thread, so one client `--log-level` does not affect the others."""

    def __init__(self, default='INFO'):
        super().__init__()
        self.default = logging.getLevelName(default)
        self.local = threading.local()

    def set_level(self, level):
        self.local.level = logging.getLevelName(level) if isinstance(level, str) else level

    def clear_level(self):
        self.local.level = None

    def filter(self, record):
        level = getattr(self.local, 'level', None)
        return record.levelno >= (self.default if level is None else level)


class Routing:
    """Route the stdout, the stderr and the log of a serving thread into its socket.

    One object covers all three: the hub commands report their result with `print` but every
    error through `logging`, and argparse writes its usage errors straight to stderr. A client
    which only got the stdout would receive an exit code with no message at all.
    """

    def __init__(self, default_level='INFO'):
        self.stdout = ThreadStream(sys.stdout)
        self.stderr = ThreadStream(sys.stderr)
        self.level_filter = ThreadLevelFilter(default_level)
        self.handler = logging.StreamHandler(self.stderr)
        self.handler.setFormatter(logging.Formatter(cli.LOG_FORMAT, cli.LOG_DATEFMT))
        self.handler.addFilter(self.level_filter)

    def install(self):
        sys.stdout = self.stdout
        sys.stderr = self.stderr
        root = logging.getLogger()
        root.handlers = [self.handler]
        root.setLevel(logging.DEBUG)  # the per thread filter decides what is really emitted

    def restore(self):
        sys.stdout = self.stdout.fallback
        sys.stderr = self.stderr.fallback
        logging.getLogger().removeHandler(self.handler)

    def __enter__(self):
        self.install()
        return self

    def __exit__(self, *exception):
        self.restore()

    @contextlib.contextmanager
    def capture(self, emit):
        """Send everything this thread writes to `emit`, tagged by stream."""
        out = TaggedSink(TAG_OUT, emit)
        err = TaggedSink(TAG_ERR, emit)
        self.stdout.set_sink(out)
        self.stderr.set_sink(err)
        try:
            yield
        finally:
            out.close()
            err.close()
            self.stdout.set_sink(None)
            self.stderr.set_sink(None)
            self.level_filter.clear_level()


def execute_request(argv, device_path, emit, routing):
    """Run one hub command, stream its output to `emit`, and return its exit code."""
    with LOCK, routing.capture(emit):
        try:
            cli.run(argv, device_path=device_path, setup_logging=routing.level_filter.set_level)
        except SystemExit as e:  # argparse and every error path of the command line
            if e.code is None:
                return 0
            if isinstance(e.code, int):
                return e.code
            logging.error(f'{e.code}')
            return 1
        except Exception as e:  # a broken hub must not take the server down with it
            logging.error(f'{e}')
            return cli.EXIT_ERROR
        return 0


class Handler(socketserver.StreamRequestHandler):
    """One connection, one request per line, for as long as the client cares to stay."""

    def handle(self):
        timeout = self.server.request_timeout
        if timeout is not None and timeout >= 0:
            self.connection.settimeout(timeout)
        while True:
            try:
                line = self.rfile.readline(MAX_REQUEST)
            except OSError:
                return
            if not line:
                return
            if not line.endswith(b'\n'):
                # The line was cut at MAX_REQUEST, so the stream is out of step: say so and go.
                self.emit(f'{TAG_ERR} request longer than {MAX_REQUEST} bytes\n')
                self.emit(f'{EXIT_PREFIX}2\n')
                return
            # `replace` so that a port scanner or a TLS hello becomes an argparse error rather
            # than an exception.
            text = line.decode('utf-8', errors='replace').rstrip('\r\n')
            try:
                argv = shlex.split(text)
            except ValueError as e:
                self.emit(f'{TAG_ERR} {e}\n')
                self.emit(f'{EXIT_PREFIX}2\n')
                continue
            code = execute_request(argv, self.server.device_path, self.emit, self.server.routing)
            self.emit(f'{EXIT_PREFIX}{code}\n')

    def emit(self, text):
        """Write one framed line, tolerating a client which has gone away.

        Swallowing the error is what keeps a disconnect from aborting the hub operation: were
        it to propagate out of a `print` inside the command, an `--off-pulse` would stop with
        the channels still off.
        """
        try:
            self.wfile.write(text.encode())
        except OSError:
            self.server.logger.debug('client gone, finishing the request anyway')


class Server(socketserver.ThreadingTCPServer):
    """Accept in threads, so that an idle connection never holds the hub."""

    allow_reuse_address = True
    daemon_threads = True


def serve(endpoint=DEFAULT_ENDPOINT, argv=(), device_path=None, timeout=-1):
    """Serve the hub commands on `endpoint` until interrupted."""
    # Validate what is left of the command line with the real parser, so that `--serve` accepts
    # exactly the options it can honour and nothing silently does nothing.
    parser = cli.build_parser()
    args = parser.parse_args(list(argv))
    if args.on or args.off or args.off_pulse or args.save:
        parser.error('--serve takes no hub command, clients send those')

    cli.configure_logging(args.log_level)
    if device_path is None:
        device_path = find_device_path()

    host, port = parse_endpoint(endpoint)
    Server.address_family = address_family(host)
    routing = Routing(args.log_level)
    try:
        server = Server((host, port), Handler)
    except OSError as e:
        raise RuntimeError(f'cannot serve on {host}:{port}: {e}') from e

    server.device_path = device_path
    server.routing = routing
    server.request_timeout = timeout
    server.logger = logging.getLogger(__name__)

    logging.info(f'Serving {device_path} on {host}:{port}, no authentication')
    routing.install()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        routing.restore()
        server.server_close()
    logging.info('Stopped')
    return 0


def request(target, argv, timeout=-1):
    """Send one hub command to a usbman server, relay its output, and return its exit code."""
    host, port = parse_endpoint(target)
    line = ' '.join(shlex.quote(argument) for argument in argv)
    logging.debug(f'{host}:{port} <- {line}')
    try:
        with socket.socket(address_family(host), socket.SOCK_STREAM) as connection:
            if timeout is not None and timeout >= 0:
                connection.settimeout(timeout)
            connection.connect((host, port))
            connection.sendall(f'{line}\n'.encode())
            replies = connection.makefile('r', encoding='utf-8', errors='replace', newline='\n')
            for reply in replies:
                reply = reply.rstrip('\n')
                if reply.startswith(EXIT_PREFIX):
                    return int(reply[len(EXIT_PREFIX) :])
                if reply.startswith(f'{TAG_OUT} '):
                    sys.stdout.write(f'{reply[2:]}\n')
                elif reply.startswith(f'{TAG_ERR} '):
                    sys.stderr.write(f'{reply[2:]}\n')
                else:
                    logging.debug(f'ignored {reply!r}')
    except OSError as e:
        raise RuntimeError(f'cannot reach the usbman server at {host}:{port}: {e}') from e
    raise RuntimeError(f'the usbman server at {host}:{port} closed the connection mid answer')
