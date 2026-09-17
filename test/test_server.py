"""The whole way round: a real server, a real socket, a real client.

The point of forwarding argv is that a remote command is indistinguishable from a local one.
These tests run both out of process and compare them byte for byte, which is the only check
that can prove the two have not drifted.
"""

import os
import re
import socket
import subprocess
import sys
import time

import pytest

# Every log line starts with the time it was written, which of course differs between two runs.
TIMESTAMP = re.compile(r'^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3} ', re.MULTILINE)

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEST = os.path.join(REPO, 'test')
RUNNER = os.path.join(TEST, 'run_with_fake_hub.py')
ALL_OFF = '00'  # both sides start here, so a local and a remote run must agree


def environment():
    """Let the child import usbman and the fake hub, whatever installed the dependencies."""
    child = dict(os.environ)
    child['PYTHONPATH'] = os.pathsep.join([REPO, TEST, child.get('PYTHONPATH', '')])
    child.pop('USBMAN_SERVER', None)
    return child


def run_usbman(arguments, state=ALL_OFF, env=None):
    command = [sys.executable, RUNNER, state, *arguments]
    return subprocess.run(command, capture_output=True, text=True, env=env or environment(), timeout=60)


def log_lines(text):
    """Return the log lines without their timestamps, so two runs can be compared."""
    return [TIMESTAMP.sub('', line) for line in text.splitlines()]


def run_locally(arguments):
    """Run against a local hub. The device is given, there is no real one to detect."""
    return run_usbman(['--device', '/dev/fake', *arguments])


@pytest.fixture
def server(free_port):
    """A usbman server in its own process, serving an in memory hub."""
    process = subprocess.Popen(
        [sys.executable, RUNNER, ALL_OFF, '--serve', f'127.0.0.1:{free_port}', '--device', '/dev/fake'],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=environment(),
    )
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if process.poll() is not None:
            pytest.fail(f'the server died: {process.communicate()[1]}')
        try:
            with socket.create_connection(('127.0.0.1', free_port), timeout=0.2):
                break
        except OSError:
            time.sleep(0.05)
    else:
        pytest.fail('the server never came up')
    yield free_port
    process.terminate()
    process.wait(timeout=10)


@pytest.mark.parametrize(
    'arguments',
    [
        [],
        ['--on', '1', '5'],
        ['--off', 'all'],
        ['--on', '2', '3', '5', '--save'],
        ['--off-pulse', '1', '--toff', '0.05'],
        ['--on', '1', '--off', '1'],  # conflict, reported through logging
        ['--on', '8'],  # argparse error, written straight to stderr
        ['--help'],
        ['--log-level', 'DEBUG', '--on', '1'],
    ],
)
def test_remote_is_identical_to_local(server, arguments):
    local = run_locally(arguments)
    remote = run_usbman(['--connect', f'127.0.0.1:{server}', *arguments])
    assert remote.stdout == local.stdout
    assert remote.returncode == local.returncode
    # Every line the local command logs must reach the client too. The remote run may add a
    # line of its own about the connection, which is why this is not an equality.
    assert set(log_lines(local.stderr)) <= set(log_lines(remote.stderr))


def test_usbman_server_environment_variable_is_equivalent_to_connect(server):
    expected = run_locally(['--on', '1', '5'])
    child = environment()
    child['USBMAN_SERVER'] = f'127.0.0.1:{server}'
    through_environment = run_usbman(['--on', '1', '5'], env=child)
    assert through_environment.stdout == expected.stdout
    assert through_environment.returncode == expected.returncode


def test_an_empty_usbman_server_goes_back_to_local(server):
    child = environment()
    child['USBMAN_SERVER'] = ''
    result = run_usbman(['--device', '/dev/fake', '--on', '1'], env=child)
    assert result.returncode == 0
    assert result.stdout == run_locally(['--on', '1']).stdout


def test_device_cannot_be_given_to_a_client(server):
    result = run_usbman(['--connect', f'127.0.0.1:{server}', '--device', '/dev/ttyUSB9', '--on', '1'])
    assert result.returncode == 255  # sys.exit(-1)
    assert '--device cannot be used with --connect' in result.stderr


def test_an_unreachable_server_is_reported_without_a_traceback(free_port):
    result = run_usbman(['--connect', f'127.0.0.1:{free_port}', '--on', '1'])
    assert result.returncode == 255
    assert 'Traceback' not in result.stderr
    assert 'cannot reach the usbman server' in result.stderr


def talk(port, *requests, timeout=10):
    """Send raw request lines the way a person with nc would, and read the framed answer."""
    with socket.create_connection(('127.0.0.1', port), timeout=timeout) as connection:
        connection.sendall(''.join(f'{request}\n' for request in requests).encode())
        connection.shutdown(socket.SHUT_WR)
        received = b''
        while True:
            chunk = connection.recv(4096)
            if not chunk:
                return received.decode()
            received += chunk


def test_the_protocol_is_usable_by_hand(server):
    answer = talk(server, '--on 1 3')
    assert 'O On: 1 3 \n' in answer
    assert answer.endswith('EXIT 0\n')


def test_several_requests_share_one_connection(server):
    answer = talk(server, '--off all', '--on 1', '')
    assert answer.count('EXIT 0') == 3
    assert 'O All off\n' in answer
    assert 'O On: 1 \n' in answer


def test_an_unbalanced_quote_is_an_error_and_not_a_disconnection(server):
    answer = talk(server, '--on "1', '--on 1')
    assert 'EXIT 2' in answer
    assert answer.endswith('EXIT 0\n')  # the connection carried on afterwards


def test_garbage_does_not_upset_the_server(server):
    answer = talk(server, 'GET / HTTP/1.1')
    assert 'EXIT 2' in answer
    assert talk(server, '').endswith('EXIT 0\n')  # still serving


def test_an_oversized_request_is_refused(server):
    answer = talk(server, '--on ' + 'x' * 5000)
    assert 'request longer than' in answer
    assert 'EXIT 2' in answer


def test_a_disconnected_client_does_not_abort_the_pulse(server):
    """The channels must come back on even though nobody is listening any more."""
    with socket.create_connection(('127.0.0.1', server), timeout=10) as connection:
        connection.sendall(b'--off-pulse all --toff 1.5\n')
        time.sleep(0.4)  # mid pulse, with the channels off
    time.sleep(2.0)
    assert talk(server, '').count('On: 1 2 3 4 5 6 7') == 1
