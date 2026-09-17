"""`execute_request`: running a hub command and framing what it produced."""

import threading
import time

import pytest
from usbman.server import EXIT_PREFIX, execute_request

DEVICE = '/dev/fake'


def run(argv, routing, device_path=DEVICE):
    """Return the framed lines and the exit code of one request."""
    lines = []
    with routing:
        code = execute_request(argv, device_path, lines.append, routing)
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
    lines, _ = run(['--on', 'all'], routing)
    out, _ = streams(lines)
    assert out == 'On: 1 2 3 4 5 6 7 \n'


def test_trailing_space_survives_the_framing(hub, routing):
    """`print('On: ', end='')` leaves a trailing space which must reach the client."""
    lines, _ = run(['--on', '1', '3'], routing)
    assert 'O On: 1 3 \n' in lines


def test_channels_are_switched(hub, routing):
    run(['--on', 'all'], routing)
    assert hub.state == 0x7F
    run(['--off', '1', '4', '6', '7'], routing)
    assert hub.state == 0x16


def test_save_comes_last_and_stores_the_resulting_state(hub, routing):
    _, code = run(['--on', '2', '3', '5', '--save'], routing)
    assert code == 0
    assert hub.saved == 0x16
    assert hub.commands[-1] == 'WPpass    \r'


def test_errors_reach_the_client_on_stderr(hub, routing):
    """They are reported through logging, so capturing the stdout alone would lose them."""
    lines, code = run(['--on', '1', '--off', '1'], routing)
    out, err = streams(lines)
    assert code == -1
    assert out == ''
    assert 'conflicting' in err


def test_argparse_errors_reach_the_client_too(hub, routing):
    """argparse writes straight to stderr and exits, bypassing logging entirely."""
    lines, code = run(['--on', '8'], routing)
    out, err = streams(lines)
    assert code == 2
    assert 'invalid channel' in err


def test_help_is_served(hub, routing):
    lines, code = run(['--help'], routing)
    out, _ = streams(lines)
    assert code == 0
    assert 'usage:' in out


def test_transport_options_are_refused_inside_a_request(hub, routing):
    """The server owns the hub and is not a client, so these cannot be forwarded."""
    for argv in (['--serve'], ['--connect', 'h:1'], ['--device', '/dev/ttyUSB1']):
        lines, code = run(argv, routing)
        _, err = streams(lines)
        assert code == 2
        assert 'unrecognized arguments' in err


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
    lines, code = run(['--on', '1'], routing)
    _, err = streams(lines)
    assert code == -2  # could not communicate, reported rather than raised
    assert 'went away' in err or 'Could not communicate' in err


def test_requests_are_serialised(hub, routing):
    """The lock spans the whole request: two pulses must not interleave mid pulse."""
    pulse = ['--off-pulse', 'all', '--toff', '0.2']
    started = time.monotonic()
    # installed once around every thread: the routing is process wide, so the threads must not
    # each install and restore it, which is also how the server uses it.
    with routing:
        threads = [
            threading.Thread(target=execute_request, args=(pulse, DEVICE, lambda line: None, routing))
            for _ in range(3)
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


@pytest.mark.parametrize('code', [0, 2, -1, -2])
def test_exit_codes_round_trip_as_signed_integers(code):
    assert int(f'{EXIT_PREFIX}{code}'[len(EXIT_PREFIX) :]) == code
