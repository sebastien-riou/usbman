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
import threading
import time

import pytest
from usbman.server import request

# Every log line starts with the time it was written, which of course differs between two runs.
TIMESTAMP = re.compile(r'^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3} ', re.MULTILINE)

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEST = os.path.join(REPO, 'test')
RUNNER = os.path.join(TEST, 'run_with_fake_hub.py')
ALL_OFF = '00'  # both sides start here, so a local and a remote run must agree
TOKEN = '6c1f9e0d4b8a27353e5d0c9f8b7a6e1d'


def environment():
    """Let the child import usbman and the fake hub, whatever installed the dependencies."""
    child = dict(os.environ)
    child['PYTHONPATH'] = os.pathsep.join([REPO, TEST, child.get('PYTHONPATH', '')])
    child.pop('USBMAN_SERVER', None)
    child.pop('USBMAN_TOKEN', None)
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


def start_server(port, *options, env=None):
    """Start a usbman server in its own process, serving an in memory hub, and wait for it."""
    process = subprocess.Popen(
        [sys.executable, RUNNER, ALL_OFF, 'serve', f'127.0.0.1:{port}', '--device', '/dev/fake', *options],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env or environment(),
    )
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if process.poll() is not None:
            pytest.fail(f'the server died: {process.communicate()[1]}')
        try:
            with socket.create_connection(('127.0.0.1', port), timeout=0.2):
                return process
        except OSError:
            time.sleep(0.05)
    process.kill()
    pytest.fail('the server never came up')


def stop_server(process):
    """Stop a server, and return what it wrote on its stdout and its stderr."""
    process.terminate()
    return process.communicate(timeout=10)


@pytest.fixture
def server(free_port):
    """A usbman server in its own process, serving an in memory hub."""
    process = start_server(free_port)
    yield free_port
    stop_server(process)


@pytest.fixture
def token_server(free_port):
    """The same, started with a token."""
    process = start_server(free_port, '--token', TOKEN)
    yield free_port
    stop_server(process)


@pytest.mark.parametrize(
    'arguments',
    [
        [],
        ['switch', '--on', '1', '5'],
        ['only', '2', '3'],
        ['only', '1', 'switch', '--on', '3'],  # refused combination
        ['switch', '--off', 'all'],
        ['switch', '--on', '2', '3', '5', '--save'],
        ['reset', '1', '--toff', '0.05'],
        ['switch', '--on', '1', 'switch', '--off', '1'],  # conflict, reported through logging
        ['switch', '--on', '8'],  # argparse error, written straight to stderr
        ['--help'],
        ['--log-level', 'DEBUG', 'switch', '--on', '1'],
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
    expected = run_locally(['switch', '--on', '1', '5'])
    child = environment()
    child['USBMAN_SERVER'] = f'127.0.0.1:{server}'
    through_environment = run_usbman(['switch', '--on', '1', '5'], env=child)
    assert through_environment.stdout == expected.stdout
    assert through_environment.returncode == expected.returncode


def test_an_empty_usbman_server_goes_back_to_local(server):
    child = environment()
    child['USBMAN_SERVER'] = ''
    result = run_usbman(['--device', '/dev/fake', 'switch', '--on', '1'], env=child)
    assert result.returncode == 0
    assert result.stdout == run_locally(['switch', '--on', '1']).stdout


def test_device_cannot_be_given_to_a_client(server):
    result = run_usbman(['--connect', f'127.0.0.1:{server}', '--device', '/dev/ttyUSB9', 'switch', '--on', '1'])
    assert result.returncode == 255  # sys.exit(-1)
    assert '--device cannot be used with --connect' in result.stderr


def test_channel_of_resolves_on_the_server(server):
    """The devices and the hub are both on the server, so it must resolve there, not here."""
    result = run_usbman(['--connect', f'127.0.0.1:{server}', 'channel-of', 'NOSUCHSERIAL'])
    assert result.returncode == 255
    assert "serial number 'NOSUCHSERIAL'" in result.stderr


@pytest.mark.parametrize('option', ['snapshot', 'forget'])
def test_the_local_only_options_are_refused_over_the_socket(server, option):
    """They write to the machine the hub is on, so a client must not be able to ask for them."""
    result = run_usbman(['--connect', f'127.0.0.1:{server}', option])
    assert result.returncode == 255
    assert 'acts on the machine the hub is attached to' in result.stderr


def test_an_unreachable_server_is_reported_without_a_traceback(free_port):
    result = run_usbman(['--connect', f'127.0.0.1:{free_port}', 'switch', '--on', '1'])
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
    answer = talk(server, 'switch --on 1 3')
    assert 'O On: 1 3 \n' in answer
    assert answer.endswith('EXIT 0\n')


def test_several_requests_share_one_connection(server):
    answer = talk(server, 'switch --off all', 'switch --on 1', '')
    assert answer.count('EXIT 0') == 3
    assert 'O All off\n' in answer
    assert 'O On: 1 \n' in answer


def test_an_unbalanced_quote_ends_the_connection(server):
    answer = talk(server, 'switch --on "1', 'switch --on 1')
    assert answer.endswith('EXIT 2\n')
    assert 'EXIT 0' not in answer
    assert 'O All off\n' in talk(server, '')  # the second line never ran


def test_a_request_which_does_not_parse_ends_the_connection(server):
    """Whatever sent it is not speaking the protocol, so what it sends next must not run."""
    answer = talk(server, '+8', '+1')
    assert 'invalid channel' in answer
    assert answer.endswith('EXIT 2\n')
    assert 'O All off\n' in talk(server, '')  # the +1 after it never ran


def test_a_request_which_fails_keeps_the_connection(server):
    """It parsed, so it was meant for usbman: only a line which is refused ends the connection."""
    answer = talk(server, 'serve', '+1')
    assert 'EXIT -1\n' in answer
    assert answer.endswith('O On: 1 \nEXIT 0\n')


def test_an_http_request_runs_nothing(server):
    """What a web page can make a browser send: commands in the body, behind lines which never parse."""
    body = 'switch --on all'
    request = [
        'POST / HTTP/1.1',
        f'Host: 127.0.0.1:{server}',
        'Content-Type: text/plain',
        f'Content-Length: {len(body) + 2}',
        '',
        body,
    ]
    answer = talk(server, *(f'{line}\r' for line in request))
    assert answer.count('EXIT') == 1  # the request line, and nothing after it
    assert answer.endswith('EXIT 2\n')
    assert 'O All off\n' in talk(server, '')


def test_garbage_does_not_upset_the_server(server):
    answer = talk(server, 'GET / HTTP/1.1')
    assert 'EXIT 2' in answer
    assert talk(server, '').endswith('EXIT 0\n')  # still serving


def test_an_oversized_request_is_refused(server):
    answer = talk(server, 'switch --on ' + 'x' * 5000)
    assert 'request longer than' in answer
    assert 'EXIT 2' in answer


def test_a_disconnected_client_does_not_abort_the_pulse(server):
    """The channels must come back on even though nobody is listening any more."""
    with socket.create_connection(('127.0.0.1', server), timeout=10) as connection:
        connection.sendall(b'reset all --toff 1.5\n')
        time.sleep(0.4)  # mid pulse, with the channels off
    time.sleep(2.0)
    assert talk(server, '').count('On: 1 2 3 4 5 6 7') == 1


def test_a_server_with_a_token_refuses_whatever_comes_before_it(token_server):
    """Even the right token is too late once a line has been refused: the connection is gone."""
    for first in ('+1', ''):
        answer = talk(token_server, first, f'token {TOKEN}', '+1')
        assert 'requires a token' in answer
        assert answer.endswith('EXIT 2\n')
        assert answer.count('EXIT') == 1
    assert 'O All off\n' in talk(token_server, f'token {TOKEN}', '')


@pytest.mark.parametrize(
    'line', ['token nope', 'token', f'token {TOKEN} {TOKEN}', f'token {TOKEN[:-1]}', f'token {TOKEN}0']
)
def test_a_wrong_token_ends_the_connection(token_server, line):
    answer = talk(token_server, line, '+1')
    assert 'wrong token' in answer
    assert answer.endswith('EXIT 2\n')
    assert 'O All off\n' in talk(token_server, f'token {TOKEN}', '')


def test_the_token_opens_the_connection_to_every_request_after_it(token_server):
    answer = talk(token_server, f'token {TOKEN}', '+1', '+3')
    assert answer == 'EXIT 0\nO On: 1 \nEXIT 0\nO On: 1 3 \nEXIT 0\n'


def test_an_http_request_cannot_give_the_token_in_time(token_server):
    answer = talk(token_server, 'POST / HTTP/1.1\r', f'token {TOKEN}\r', '+1\r')
    assert 'requires a token' in answer
    assert answer.count('EXIT') == 1


def test_a_token_sent_to_a_server_without_one_is_refused(server):
    """The client believes the hub is protected, and must hear that it is not."""
    answer = talk(server, 'token whatever', '+1')
    assert 'takes no token' in answer
    assert answer.endswith('EXIT 2\n')
    assert 'O All off\n' in talk(server, '')


def test_the_client_sends_the_token(token_server):
    result = run_usbman(['--connect', f'127.0.0.1:{token_server}', '--token', TOKEN, '+1'])
    assert (result.returncode, result.stdout) == (0, 'On: 1 \n')


@pytest.mark.parametrize(
    ('option', 'variable'),
    [
        ([], TOKEN),  # USBMAN_TOKEN alone does it
        (['--token', TOKEN], 'wrong'),  # and the command line wins over it
    ],
)
def test_usbman_token_acts_as_token(token_server, option, variable):
    child = environment()
    child['USBMAN_TOKEN'] = variable
    result = run_usbman(['--connect', f'127.0.0.1:{token_server}', *option, '+1'], env=child)
    assert (result.returncode, result.stdout) == (0, 'On: 1 \n')


def test_the_command_is_not_sent_until_the_token_is_accepted():
    """A server refusing the token must never see the command, not even unread in its buffer."""
    received = []

    def refuse_the_token(listener):
        connection, _ = listener.accept()
        with connection, connection.makefile('rb') as lines:
            received.append(lines.readline())
            connection.sendall(b'E wrong token\nEXIT 2\n')
            received.append(lines.readline())  # empty once the client has gone, unless it sent more

    with socket.create_server(('127.0.0.1', 0)) as listener:
        thread = threading.Thread(target=refuse_the_token, args=(listener,))
        thread.start()
        code = request(f'127.0.0.1:{listener.getsockname()[1]}', ['switch', '--on', '1'], token='nope')
        thread.join(timeout=10)
    assert code == 2
    assert received == [b'token nope\n', b'']


def test_an_empty_usbman_token_means_none(server):
    child = environment()
    child['USBMAN_TOKEN'] = ''
    result = run_usbman(['--connect', f'127.0.0.1:{server}', '+1'], env=child)
    assert (result.returncode, result.stdout) == (0, 'On: 1 \n')


@pytest.mark.parametrize(('option', 'reason'), [([], 'requires a token'), (['--token', 'nope'], 'wrong token')])
def test_a_refused_client_says_why(token_server, option, reason):
    result = run_usbman(['--connect', f'127.0.0.1:{token_server}', *option, '+1'])
    assert result.returncode == 2
    assert reason in result.stderr
    assert 'Traceback' not in result.stderr
    assert 'O All off\n' in talk(token_server, f'token {TOKEN}', '')


def test_an_empty_token_is_refused_rather_than_serving_without_one(free_port):
    """`--token "$TOKEN"` with the variable unset must not start a server open to anybody."""
    result = run_usbman(['serve', f'127.0.0.1:{free_port}', '--device', '/dev/fake', '--token', ''])
    assert result.returncode == 2
    assert 'the token cannot be empty' in result.stderr


@pytest.mark.parametrize(
    ('options', 'variable', 'access'),
    [
        ([], None, 'no authentication'),
        (['--token', TOKEN], None, 'token required, from --token'),
        ([], TOKEN, 'token required, from USBMAN_TOKEN'),
        (['--token', TOKEN], 'another', 'token required, from --token'),  # the command line wins
    ],
)
def test_the_server_says_whether_it_requires_a_token_and_where_it_came_from(free_port, options, variable, access):
    """USBMAN_TOKEN exported for the clients is easy to forget, and a server takes it too."""
    child = environment()
    if variable is not None:
        child['USBMAN_TOKEN'] = variable
    _, err = stop_server(start_server(free_port, *options, env=child))
    assert f'Serving /dev/fake on 127.0.0.1:{free_port}, {access}\n' in err
    assert TOKEN not in err


def test_refusals_are_logged_at_debug_level(free_port):
    process = start_server(free_port, '--token', TOKEN, '--log-level', 'DEBUG')
    talk(free_port, '+1')
    talk(free_port, 'token nope')
    talk(free_port, f'token {TOKEN}', 'POST / HTTP/1.1')
    _, err = stop_server(process)
    refusals = [line for line in err.splitlines() if 'DEBUG:\trefused 127.0.0.1:' in line]
    assert len(refusals) == 3
    assert 'this server requires a token' in refusals[0]
    assert refusals[1].endswith(': wrong token')
    assert refusals[2].endswith(': the request does not parse')


def test_refusals_are_not_logged_at_the_default_level(free_port):
    """Anybody can be refused as often as they like, which must not be a way to fill the log."""
    process = start_server(free_port, '--token', TOKEN)
    talk(free_port, 'token nope')
    _, err = stop_server(process)
    assert 'refused' not in err


def test_the_token_stays_out_of_every_log(free_port):
    process = start_server(free_port, '--token', TOKEN, '--log-level', 'DEBUG')
    try:
        target = f'127.0.0.1:{free_port}'
        accepted = run_usbman(['--connect', target, '--token', TOKEN, '--log-level', 'DEBUG', '+1'])
        # The wrong token contains the right one, so that leaking either of them is caught.
        refused = run_usbman(['--connect', target, '--token', f'{TOKEN}0', '--log-level', 'DEBUG', '+1'])
    finally:
        server_out, server_err = stop_server(process)
    assert accepted.returncode == 0  # so there was a request, and its log, to leak it into
    assert 'DEBUG' in accepted.stderr
    assert refused.returncode == 2
    for text in (server_out, server_err, accepted.stdout, accepted.stderr, refused.stdout, refused.stderr):
        assert TOKEN not in text
