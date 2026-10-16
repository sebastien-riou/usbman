"""`usbman +1 -3`, the shorthand for `usbman switch --on 1 --off 3`."""

import pytest
import usbman
import usbman.cli as cli
from usbman.server import split_transport


@pytest.mark.parametrize(
    ('argv', 'expanded'),
    [
        (['+1'], ['switch', '--on', '1']),
        (['+1', '+2', '-3'], ['switch', '--on', '1', '2', '--off', '3']),
        (['-3'], ['switch', '--off', '3']),
        (['+all'], ['switch', '--on', 'all']),
        (['-all'], ['switch', '--off', 'all']),
        (['+numaker'], ['switch', '--on', 'numaker']),  # a reference passes through untouched
        (['+004B00283532510831333430'], ['switch', '--on', '004B00283532510831333430']),
        (['+1', '--save'], ['switch', '--on', '1', '--save']),
        (['+1', '--log-level', 'DEBUG'], ['switch', '--on', '1', '--log-level', 'DEBUG']),
    ],
)
def test_it_expands_to_switch(argv, expanded):
    assert cli.expand_shorthand(argv) == expanded


@pytest.mark.parametrize(
    'argv',
    [
        [],  # a bare usbman still means "print the state"
        ['list'],
        ['-h'],  # the help, never channel 'h' off
        ['--help'],
        ['--version'],
        ['switch', '--on', '1'],
        ['characterize', '--settle', '-1'],  # a command is named, so -1 is its option's value
        ['reset', '1', '--toff', '-1'],
    ],
)
def test_it_leaves_everything_else_alone(argv):
    assert cli.expand_shorthand(argv) == argv


def test_the_transport_scan_runs_first_so_a_negative_timeout_survives():
    """`--timeout -1` is the documented "block forever", and must not become "channel 1 off"."""
    transport, rest = split_transport(['--timeout', '-1', '+1'])
    assert transport.timeout == -1
    assert cli.expand_shorthand(rest) == ['switch', '--on', '1']


def test_what_it_expands_to_actually_parses():
    args = cli.build_parser().parse_args(cli.expand_shorthand(['+1', '+2', '-3', '--save']))
    assert (args.command, args.on, args.off, args.save) == ('switch', ['1', '2'], ['3'], True)


def test_the_shorthand_and_the_long_form_switch_the_same_channels(sysfs, hub):
    cli.run(cli.expand_shorthand(['+1', '+3']), device_path='/dev/fake', setup_logging=lambda level: None)
    shorthand = hub.state
    hub.state = 0
    cli.run(['switch', '--on', '1', '3'], device_path='/dev/fake', setup_logging=lambda level: None)
    assert hub.state == shorthand


def test_a_nickname_works_in_the_shorthand(sysfs, hub):
    with open(sysfs.nicknames, 'w') as f:
        f.write('stlink 004B00283532510831333430\n')
    cli.run(cli.expand_shorthand(['+stlink']), device_path='/dev/fake', setup_logging=lambda level: None)
    assert hub.state == 0b1  # the ST-LINK is on channel 1 in the fake tree
