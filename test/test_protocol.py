"""`execute_request`: running a hub command and framing what it produced."""

import logging
import socket
import threading
import time
import types

import pytest
from usbman import cli
from usbman.server import EXIT_PREFIX, LOCK, Handler, execute_request, token_digest

DEVICE = '/dev/fake'


def run(argv, routing, device_path=DEVICE, max_toff=None, allow_save=True):
    """Return the framed lines and the exit code of one request."""
    lines = []
    with routing:
        code = execute_request(argv, device_path, lines.append, routing, max_toff=max_toff, allow_save=allow_save)
    return lines, code


def streams(lines):
    """Split framed lines back into the stdout and stderr the client would print."""
    out = ''.join(line[2:] for line in lines if line.startswith('O '))
    err = ''.join(line[2:] for line in lines if line.startswith('E '))
    return out, err


def test_state_is_reported_on_stdout(hub, routing):
    lines, code = run([], routing)
    out, err = streams(lines)
    assert code == 0
    assert out == 'All off\n'
    assert err == ''


def test_every_channel_is_listed(hub, routing):
    lines, _ = run(['switch', '--on', 'all'], routing)
    out, _ = streams(lines)
    assert out == 'On: 1 2 3 4 5 6 7 \n'


def test_trailing_space_survives_the_framing(hub, routing):
    """`print('On: ', end='')` leaves a trailing space which must reach the client."""
    lines, _ = run(['switch', '--on', '1', '3'], routing)
    assert 'O On: 1 3 \n' in lines


def test_channels_are_switched(hub, routing):
    run(['switch', '--on', 'all'], routing)
    assert hub.state == 0x7F
    run(['switch', '--off', '1', '4', '6', '7'], routing)
    assert hub.state == 0x16


def test_on_decides_every_channel(hub, routing):
    """Unlike --set, which only adds, --on turns everything else off."""
    run(['switch', '--on', 'all'], routing)
    lines, code = run(['only', '2'], routing)
    out, _ = streams(lines)
    assert code == 0
    assert out == 'On: 2 \n'
    assert hub.state == 0b10


def test_set_and_clear_leave_the_other_channels_alone(hub, routing):
    run(['only', '1', '3'], routing)
    run(['switch', '--on', '5'], routing)
    assert hub.state == 0b10101
    run(['switch', '--off', '1'], routing)
    assert hub.state == 0b10100


@pytest.mark.parametrize(
    'argv',
    [
        ['only', '1', 'switch', '--on', '3'],  # two commands at once
        ['only', '1', '--on', '3'],  # --on belongs to switch, not only
        ['only', '1', '--toff', '2'],  # --toff belongs to reset
        ['list', 'snapshot'],  # used to run `list` and ignore `snapshot` in silence
        ['list', '--toff', '5'],  # used to accept --toff and ignore it
        ['characterize', '--save'],
    ],
)
def test_argparse_refuses_what_used_to_pass_silently(hub, routing, argv):
    """One command, and only the options that command has. The parser enforces both now."""
    lines, code = run(argv, routing)
    _, err = streams(lines)
    assert code == 2
    assert hub.commands == []  # refused before anything reached the hub
    assert err


def test_on_may_still_be_saved(hub, routing):
    _, code = run(['only', '1', '3', '--save'], routing)
    assert code == 0
    assert hub.saved == 0b101


def test_channel_of_prints_the_channel(hub, routing, sysfs):
    lines, code = run(['channel-of', '004B00283532510831333430'], routing)
    out, _ = streams(lines)
    assert code == 0
    assert out == '1\n'


def test_channel_of_needs_no_hub(hub, routing, sysfs):
    """It reads sysfs only, so it answers with no device path and nothing to detect."""
    lines, code = run(['channel-of', sysfs.path('ttyACM0')], routing, device_path=None)
    out, _ = streams(lines)
    assert (code, out) == (0, '1\n')
    assert hub.commands == []


def test_a_device_reference_works_wherever_a_channel_does(hub, routing, sysfs):
    run(['only', 'all'], routing)
    run(['switch', '--off', sysfs.path('ttyACM0')], routing)
    assert hub.state == 0x7F & ~0b1  # the ST-LINK is on channel 1


def test_references_and_numbers_mix(hub, routing, sysfs):
    run(['only', 'all'], routing)
    run(['switch', '--off', '004B00283532510831333430', '3'], routing)
    assert hub.state == 0x7F & ~0b101


def test_an_unresolvable_reference_is_reported(hub, routing, sysfs):
    lines, code = run(['switch', '--off', 'NOSUCH'], routing)
    _, err = streams(lines)
    assert code == -1
    assert 'NOSUCH' in err
    assert hub.commands == []  # refused before anything reached the hub


@pytest.mark.parametrize('command', [['switch', '--on'], ['path-of'], ['channel-of']])
@pytest.mark.parametrize('value', ['²', '٣'])
def test_only_ascii_digits_are_a_channel_number(hub, routing, sysfs, command, value):
    """`isdigit` takes these: '²' then crashed in `int`, and '٣' switched channel 3."""
    lines, code = run([*command, value], routing)
    _, err = streams(lines)
    assert code == -1
    assert value in err  # looked up as a device, and not found
    assert 'invalid literal' not in err
    assert hub.commands == []


def test_save_comes_last_and_stores_the_resulting_state(hub, routing):
    _, code = run(['switch', '--on', '2', '3', '5', '--save'], routing)
    assert code == 0
    assert hub.saved == 0x16
    assert hub.commands[-1] == 'WPpass    \r'


def test_save_prints_the_state_it_saved(hub, routing):
    """The hub's answer to a save carries no states, so what is printed is what was saved."""
    run(['switch', '--on', '1', '3'], routing)
    lines, code = run(['save'], routing)
    out, _ = streams(lines)
    assert (code, out) == (0, 'On: 1 3 \n')
    assert hub.saved == 0b101


def test_errors_reach_the_client_on_stderr(hub, routing):
    """They are reported through logging, so capturing the stdout alone would lose them."""
    lines, code = run(['switch', '--on', '1', '--off', '1'], routing)
    out, err = streams(lines)
    assert code == -1
    assert out == ''
    assert 'conflicting' in err


def test_argparse_errors_reach_the_client_too(hub, routing):
    """argparse writes straight to stderr and exits, bypassing logging entirely."""
    lines, code = run(['switch', '--on', '8'], routing)
    out, err = streams(lines)
    assert code == 2
    assert 'invalid channel' in err


def test_a_request_which_does_not_parse_exits_with_the_code_the_server_closes_on(hub, routing):
    """The server knows a request it could not make sense of by this code alone."""
    for argv in (['POST', '/', 'HTTP/1.1'], ['token', 'x'], ['switch', '--on', '8']):
        _, code = run(argv, routing)
        assert code == cli.EXIT_USAGE


def test_help_is_served(hub, routing):
    lines, code = run(['--help'], routing)
    out, _ = streams(lines)
    assert code == 0
    assert 'usage:' in out


def test_transport_options_are_refused_inside_a_request(hub, routing):
    """The server owns the hub and is not a client, so these cannot be forwarded."""
    for argv in (['--connect', 'h:1'], ['--device', '/dev/ttyUSB1']):
        lines, code = run(argv, routing)
        _, err = streams(lines)
        assert code == 2
        assert err  # argparse says so, whichever way it words it


def test_serve_is_refused_inside_a_request(hub, routing):
    """A client must not be able to make the server start another server."""
    lines, code = run(['serve'], routing)
    _, err = streams(lines)
    assert code == -1
    assert 'acts on the machine the hub is attached to' in err


def test_log_level_of_the_request_is_honoured(hub, routing):
    """`basicConfig` being a no op after the first call, this would silently stop working."""
    quiet, _ = run(['--log-level', 'INFO'], routing)
    verbose, _ = run(['--log-level', 'DEBUG'], routing)
    assert not any('DEBUG' in line for line in quiet)
    assert any('DEBUG' in line for line in verbose)


def test_the_level_does_not_leak_into_the_next_request(hub, routing):
    run(['--log-level', 'DEBUG'], routing)
    after, _ = run([], routing)
    assert not any('DEBUG' in line for line in after)


def test_a_hub_failure_becomes_an_exit_code_not_a_crash(hub, routing, monkeypatch):
    import usbman

    def broken(*args, **kwargs):
        raise OSError('the port went away')

    monkeypatch.setattr(usbman, 'serial_command_response', broken)
    lines, code = run(['switch', '--on', '1'], routing)
    _, err = streams(lines)
    assert code == -2  # could not communicate, reported rather than raised
    assert 'went away' in err or 'Could not communicate' in err


def test_requests_are_serialised(hub, routing):
    """The lock spans the whole request: two pulses must not interleave mid pulse."""
    pulse = ['reset', 'all', '--toff', '0.2']
    started = time.monotonic()
    # installed once around every thread: the routing is process wide, so the threads must not
    # each install and restore it, which is also how the server uses it.
    with routing:
        threads = [
            threading.Thread(target=execute_request, args=(pulse, DEVICE, lambda line: None, routing)) for _ in range(3)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
    assert time.monotonic() - started >= 0.6
    # every pulse is a pair of SP commands, and no other SP may fall between them
    writes = [c for c in hub.commands if c.startswith('SP')]
    assert len(writes) == 6
    for first, second in zip(writes[::2], writes[1::2]):
        assert first == 'SPpass    80FFFFFF\r'  # all off
        assert second == 'SPpass    FFFFFFFF\r'  # and back on


@pytest.mark.parametrize('toff', ['nan', 'inf', '-1'])
def test_an_invalid_toff_switches_nothing(hub, routing, toff):
    """It used to switch the channels off, then fail to wait and leave them so."""
    hub.state = 0x7F
    lines, code = run(['reset', 'all', '--toff', toff], routing)
    _, err = streams(lines)
    assert code == cli.EXIT_USAGE
    assert f"invalid duration '{toff}'" in err
    assert hub.state == 0x7F
    assert not any(command.startswith('SP') for command in hub.commands)


def test_a_toff_above_the_limit_is_refused_before_anything_is_switched(hub, routing, monkeypatch):
    """Nobody could cut it short, so it would hold the hub, and its channels off, for good."""
    hub.state = 0x7F

    def asleep(seconds):
        raise AssertionError(f'slept {seconds}s')  # fail now rather than wait as long as asked

    monkeypatch.setattr(cli.time, 'sleep', asleep)
    lines, code = run(['reset', 'all', '--toff', '1e9'], routing, max_toff=60)
    _, err = streams(lines)
    assert code == cli.EXIT_ERROR
    assert '--toff 1e+09 is longer than this server allows, 60 seconds at most' in err
    assert hub.commands == []


def test_a_toff_at_the_limit_is_granted(hub, routing):
    lines, code = run(['reset', '1', '--toff', '0.1'], routing, max_toff=0.1)
    out, _ = streams(lines)
    assert code == 0
    assert out == 'On: 1 \n'


@pytest.mark.parametrize(
    'argv', [['save'], ['switch', '--on', '1', '--save'], ['only', '1', '--save'], ['reset', '1', '--save']]
)
def test_a_server_refuses_to_save_unless_allowed(hub, routing, argv):
    """Refused whole, before the hub hears anything: no half done request switching but not saving."""
    lines, code = run(argv, routing, allow_save=False)
    _, err = streams(lines)
    assert code == cli.EXIT_ERROR
    assert 'changes the state the hub powers up with' in err
    assert '--allow-save' in err
    assert hub.commands == []


def serve_one_connection(routing, request_timeout=-1, token=None, token_timeout=None):
    """Run one `Handler` in a thread over a socket pair, and return the client end and the thread.

    The server end gets a small send buffer, so that its writes block after a few KB which the
    client does not read. To be called with the routing installed, as a server runs.
    """
    client, server_end = socket.socketpair()
    server_end.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 4096)
    server = types.SimpleNamespace(
        device_path=DEVICE,
        routing=routing,
        request_timeout=request_timeout,
        token_digest=None if token is None else token_digest(token),
        token_timeout=token_timeout,
        max_toff=None,
        allow_save=False,
        logger=logging.getLogger('usbman.server'),
    )

    def handle():
        try:
            Handler(server_end, ('test', 0), server)  # handles the connection from the constructor
        finally:
            server_end.close()

    thread = threading.Thread(target=handle, daemon=True)
    thread.start()
    return client, thread


def test_a_client_which_does_not_read_never_holds_the_hub_lock(hub, routing):
    """Writing an answer blocks for as long as the client does not read: that client alone waits."""
    with routing:
        client, thread = serve_one_connection(routing)
        client.sendall(b'--help\n' * 100)  # a few hundred KB of answers, which nobody reads
        time.sleep(0.5)  # for the handler to fill the buffers and block
        acquired = LOCK.acquire(timeout=5)
        if acquired:
            LOCK.release()
        client.close()
        thread.join(timeout=10)
    assert acquired
    assert not thread.is_alive()


def test_a_client_which_stops_reading_is_dropped_at_its_first_timed_out_write(hub, routing):
    """Rather than the server spending another timeout on every line still to come."""
    with routing:
        client, thread = serve_one_connection(routing, request_timeout=0.5)
        client.sendall(b'--help\n' * 100)
        thread.join(timeout=5)
        dropped = not thread.is_alive()
        client.close()
        thread.join(timeout=60)
    assert dropped


def test_a_connection_which_does_not_give_the_token_in_time_is_dropped(hub, routing):
    """Or a client without the token could hold one of the server's slots just by saying nothing."""
    with routing:
        client, thread = serve_one_connection(routing, token='secret', token_timeout=0.3)
        thread.join(timeout=5)
        dropped = not thread.is_alive()
        client.settimeout(1)
        closed = client.recv(4096) == b''
        client.close()
    assert dropped
    assert closed


def test_sending_the_token_a_byte_at_a_time_does_not_stretch_the_deadline(hub, routing):
    """Each byte would restart a socket timeout; the deadline is for the line as a whole."""
    with routing:
        client, thread = serve_one_connection(routing, token='secret', token_timeout=0.3)
        started = time.monotonic()
        try:
            while thread.is_alive() and time.monotonic() - started < 3:
                client.sendall(b't')  # never a whole line
                time.sleep(0.05)
        except OSError:
            pass  # the server has dropped the connection
        thread.join(timeout=5)
        dropped = not thread.is_alive()
        client.close()
    assert dropped
    assert time.monotonic() - started < 2


def test_once_the_token_is_given_a_connection_may_stay_idle(hub, routing):
    with routing:
        client, thread = serve_one_connection(routing, token='secret', token_timeout=0.3)
        replies = client.makefile('r')
        client.sendall(b'token secret\n')
        given = replies.readline()
        time.sleep(0.6)  # twice the deadline
        client.sendall(b'\n')
        answer = [replies.readline(), replies.readline()]
        client.close()
        thread.join(timeout=5)
    assert given == 'EXIT 0\n'
    assert answer == ['O All off\n', 'EXIT 0\n']


@pytest.mark.parametrize('code', [0, 2, -1, -2])
def test_exit_codes_round_trip_as_signed_integers(code):
    assert int(f'{EXIT_PREFIX}{code}'[len(EXIT_PREFIX) :]) == code
