"""The pure parts of the command line and of the hub protocol."""

import argparse

import pytest
import usbman
from usbman import cli
from usbman.server import parse_endpoint, peek_log_level, split_transport


def test_channel_accepts_numbers_and_all():
    assert cli.channel('1') == '1'
    assert cli.channel('7') == '7'
    assert cli.channel('all') == 'all'


@pytest.mark.parametrize('value', ['0', '8', '12', '123', ''])
def test_channel_rejects_bad_channel_numbers(value):
    """Short digit runs are channel numbers, so a typo says so instead of becoming a serial."""
    with pytest.raises(argparse.ArgumentTypeError):
        cli.channel(value)


@pytest.mark.parametrize(
    ('value', 'is_number'),
    [
        ('7', True),
        ('123', True),  # a channel number, out of range, caught as such
        ('1234', False),  # four digits: a serial, which is how 000000000 can be named
        ('000000000', False),
        ('B001DNH6', False),
        ('/dev/ttyACM0', False),
        ('all', False),
    ],
)
def test_the_four_digit_boundary(value, is_number):
    assert cli.is_channel_number(value) is is_number


@pytest.mark.parametrize('value', ['all', '/dev/ttyACM0', '/dev/serial/by-id/usb-x', 'B001DNH6', '1234', '000000000'])
def test_channel_accepts_references_without_resolving_them(value):
    """`channel()` checks the shape only: resolution needs sysfs and the configured logging."""
    assert cli.channel(value) == value


def test_channel_set_expands_all():
    assert cli.channel_set(['1', '5']) == {1, 5}
    assert cli.channel_set(['all']) == set(cli.CHANNELS)
    assert cli.channel_set(['2', 'all']) == set(cli.CHANNELS)
    assert cli.channel_set([]) == set()


def test_command_refuses_unverified_opcodes():
    """`CP` changes the password and would lock the hub out, so it must never go out."""
    for opcode in ('CP', 'FP', 'RD', 'RH', 'ZZ'):
        with pytest.raises(ValueError):
            usbman.command(opcode)


def test_command_builds_the_bytes_cusbi_sends():
    payload = bytes([0x80 | 0x16]) + b'\xff' * 3
    assert usbman.command('SP', payload) == 'SPpass    96FFFFFF\r'
    assert usbman.command('WP') == 'WPpass    \r'


def test_set_state_wire_format_is_unchanged_for_every_state(hub):
    for state in range(128):
        usbman.set_state('/dev/fake', state)
        assert hub.commands[-1] == f'SPpass    {0x80 | state:02X}FFFFFF\r'


@pytest.mark.parametrize(
    ('reply', 'state'),
    [
        (b'FFFFFFFF\r\n', 0x7F),  # what GP really answers, no prefix
        (b'G03FFFFFF\r\n', 0x03),  # behind a G, which is stripped
        (b'E5FFFFFF\r\n', 0x65),  # a state which merely starts with an E
        (b'EFFFFFFF\r\n', 0x6F),
    ],
)
def test_decode_result_reads_states(reply, state):
    assert usbman.decode_result(reply) == state


@pytest.mark.parametrize(('reply', 'reason'), [(b'E01\r\n', 'wrong password'), (b'EFF\r\n', 'command refused')])
def test_decode_result_raises_on_errors(reply, reason):
    with pytest.raises(RuntimeError, match=reason):
        usbman.decode_result(reply)


def test_decode_result_raises_when_the_hub_says_nothing():
    with pytest.raises(RuntimeError, match='did not answer'):
        usbman.decode_result(b'')


@pytest.mark.parametrize('reply', [b'G\r\n', b'?\r\n', b'ZZFFFFFF\r\n'])
def test_decode_result_reports_a_reply_without_states(reply):
    """As an error the command line reports, not as a traceback."""
    with pytest.raises(RuntimeError, match='holds no channel states'):
        usbman.decode_result(reply)


def hub_answering(monkeypatch, reply):
    """Make the hub answer every command with `reply`."""
    monkeypatch.setattr(usbman, 'serial_command_response', lambda device_path, **kwargs: reply)


def test_save_state_accepts_the_bare_g_a_real_hub_answers(monkeypatch):
    """Seen on the wire: unlike `GP`, `WP` answers no states at all."""
    hub_answering(monkeypatch, b'G\r\n')
    usbman.save_state('/dev/fake')


@pytest.mark.parametrize(
    ('reply', 'reason'),
    [(b'E01\r\n', 'wrong password'), (b'81FFFFFF\r\n', 'instead of confirming the save'), (b'', 'did not answer')],
)
def test_save_state_wants_the_g_cusbi_wants(monkeypatch, reply, reason):
    hub_answering(monkeypatch, reply)
    with pytest.raises(RuntimeError, match=reason):
        usbman.save_state('/dev/fake')


@pytest.mark.parametrize(
    ('args', 'expected'),
    [
        ([], (None, None)),
        (['switch', '--on', '1'], (None, None)),
        (['--device', '/dev/ttyUSB1'], ('/dev/ttyUSB1', None)),
        (['serve', '1.2.3.4:5'], (None, None)),  # a command now, not a transport option
        (['--connect', 'h:1'], (None, 'h:1')),
        (['--connect=h:1'], (None, 'h:1')),
    ],
)
def test_split_transport_recognises_its_options(args, expected):
    transport, _ = split_transport(args)
    assert (transport.device, transport.connect) == expected


@pytest.mark.parametrize(
    ('args', 'forwarded'),
    [
        (['switch', '--on', '1', '5'], ['switch', '--on', '1', '5']),
        (['--connect', 'h:1', 'switch', '--on', '1'], ['switch', '--on', '1']),
        (['switch', '--on', '1', '--connect', 'h:1'], ['switch', '--on', '1']),
        (['--timeout', '5', 'switch', '--off', 'all'], ['switch', '--off', 'all']),
        # the hub command keeps everything the transport parser does not claim
        (['--save', '--toff', '0.5', '--log-level', 'DEBUG'], ['--save', '--toff', '0.5', '--log-level', 'DEBUG']),
    ],
)
def test_split_transport_forwards_the_rest_untouched(args, forwarded):
    _, argv = split_transport(args)
    assert argv == forwarded


def test_split_transport_leaves_hub_abbreviations_alone():
    """`allow_abbrev` is off there, so `--t` reaches the command parser as `reset`'s `--toff`.

    The transport parser really does have a `--timeout` which would otherwise claim it.
    """
    _, argv = split_transport(['reset', '1', '--t', '0.5'])
    assert argv == ['reset', '1', '--t', '0.5']
    assert cli.build_parser().parse_args(argv).toff == 0.5


def test_timeout_defaults_to_blocking_forever():
    transport, _ = split_transport([])
    assert transport.timeout == -1


@pytest.mark.parametrize(
    'args', [['--token', 's3cret', '+1'], ['+1', '--token=s3cret'], ['serve', '--token', 's3cret']]
)
def test_split_transport_takes_the_token(args):
    transport, argv = split_transport(args)
    assert transport.token == 's3cret'
    assert 's3cret' not in argv


def test_there_is_no_token_unless_given():
    transport, _ = split_transport(['+1'])
    assert transport.token is None


def test_an_empty_token_is_a_usage_error():
    """`--token "$TOKEN"` with the variable unset: refused, rather than taken for no token."""
    with pytest.raises(SystemExit) as refused:
        split_transport(['--token', '', 'serve'])
    assert refused.value.code == cli.EXIT_USAGE


@pytest.mark.parametrize(
    ('text', 'endpoint'),
    [
        ('', ('127.0.0.1', 9877)),
        ('9999', ('127.0.0.1', 9999)),
        (':9999', ('127.0.0.1', 9999)),
        ('host', ('host', 9877)),
        ('host:9999', ('host', 9999)),
        ('1.2.3.4:5', ('1.2.3.4', 5)),
        ('[::1]:9999', ('::1', 9999)),
        ('[::1]', ('::1', 9877)),
    ],
)
def test_parse_endpoint(text, endpoint):
    assert parse_endpoint(text) == endpoint


@pytest.mark.parametrize(
    ('argv', 'level'),
    [([], 'INFO'), (['--log-level', 'DEBUG'], 'DEBUG'), (['--log-level=ERROR'], 'ERROR'), (['--log-level'], 'INFO')],
)
def test_peek_log_level(argv, level):
    assert peek_log_level(argv) == level


def test_version_prints_and_exits_cleanly(capsys):
    with pytest.raises(SystemExit) as finished:
        cli.build_parser().parse_args(['--version'])
    assert finished.value.code == 0
    out = capsys.readouterr().out
    assert out.startswith('usbman ')
    assert out.split()[1]  # a version of some sort, 'unknown' when run from a source tree


def test_the_version_is_the_one_the_package_reports():
    assert cli.__version__ == usbman.__version__


def test_help_mentions_the_transport_options():
    """They are not in the parser, so only the epilog can tell the user they exist."""
    text = cli.build_parser().format_help()
    for option in ('--device', '--connect', '--timeout', '--token', 'USBMAN_SERVER', 'USBMAN_TOKEN'):
        assert option in text


def test_device_path_is_gone_from_the_hub_parser():
    parser = cli.build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(['--device-path', '/dev/ttyUSB0'])


def test_no_command_means_print_the_state():
    assert cli.build_parser().parse_args([]).command is None


def test_save_is_both_a_command_and_a_modifier():
    """`save` stores what the hub holds; `--save` stores what the command just produced."""
    assert cli.build_parser().parse_args(['save']).command == 'save'
    for command in (['only', '1'], ['switch', '--on', '1'], ['reset', '1']):
        assert cli.build_parser().parse_args([*command, '--save']).save is True


def test_each_command_owns_its_modifiers():
    """The whole point of subcommands: a modifier cannot reach a command which ignores it."""
    for argv in (['list', '--toff', '5'], ['only', '1', '--settle', '5'], ['save', '--toff', '5']):
        with pytest.raises(SystemExit):
            cli.build_parser().parse_args(argv)


def test_only_one_command_at_a_time():
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args(['list', 'snapshot'])


def test_log_level_is_accepted_before_or_after_the_command():
    assert cli.build_parser().parse_args(['--log-level', 'DEBUG', 'list']).log_level == 'DEBUG'
    assert cli.build_parser().parse_args(['list', '--log-level', 'DEBUG']).log_level == 'DEBUG'
