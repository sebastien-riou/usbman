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


@pytest.mark.parametrize('value', ['0', '8', 'ALL', 'foo', '-1', '1.5', ''])
def test_channel_rejects_the_rest(value):
    with pytest.raises(argparse.ArgumentTypeError):
        cli.channel(value)


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
        (b'G03FFFFFF\r\n', 0x03),  # what WP answers, with the prefix
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


@pytest.mark.parametrize(
    ('args', 'expected'),
    [
        ([], (None, None, None)),
        (['--on', '1'], (None, None, None)),
        (['--device', '/dev/ttyUSB1'], ('/dev/ttyUSB1', None, None)),
        (['--serve'], (None, '', None)),
        (['--serve', '1.2.3.4:5'], (None, '1.2.3.4:5', None)),
        (['--serve', '--on', '1'], (None, '', None)),  # an option cannot be the value
        (['--connect', 'h:1'], (None, None, 'h:1')),
        (['--connect=h:1'], (None, None, 'h:1')),
    ],
)
def test_split_transport_recognises_its_options(args, expected):
    transport, _ = split_transport(args)
    assert (transport.device, transport.serve, transport.connect) == expected


@pytest.mark.parametrize(
    ('args', 'forwarded'),
    [
        (['--on', '1', '5'], ['--on', '1', '5']),
        (['--connect', 'h:1', '--on', '1'], ['--on', '1']),
        (['--on', '1', '--connect', 'h:1'], ['--on', '1']),
        (['--timeout', '5', '--off', 'all'], ['--off', 'all']),
        # the hub command keeps everything the transport parser does not claim
        (['--save', '--toff', '0.5', '--log-level', 'DEBUG'], ['--save', '--toff', '0.5', '--log-level', 'DEBUG']),
    ],
)
def test_split_transport_forwards_the_rest_untouched(args, forwarded):
    _, argv = split_transport(args)
    assert argv == forwarded


def test_split_transport_leaves_hub_abbreviations_alone():
    """`allow_abbrev` is off there, so `--s` still reaches the hub parser as `--save`."""
    _, argv = split_transport(['--s'])
    assert argv == ['--s']
    assert cli.build_parser().parse_args(argv).save is True


def test_timeout_defaults_to_blocking_forever():
    transport, _ = split_transport([])
    assert transport.timeout == -1


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


def test_help_mentions_the_transport_options():
    """They are not in the parser, so only the epilog can tell the user they exist."""
    text = cli.build_parser().format_help()
    for option in ('--device', '--serve', '--connect', '--timeout', 'USBMAN_SERVER'):
        assert option in text


def test_device_path_is_gone_from_the_hub_parser():
    parser = cli.build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(['--device-path', '/dev/ttyUSB0'])
