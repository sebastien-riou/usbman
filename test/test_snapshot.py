"""Remembering which channel a device is on, so it can be named while switched off."""

import os
import re

import pytest
import usbman
import usbman.cli

STLINK = '004B00283532510831333430'
FT232R = 'B001DNH6'
PICO = '648326155B4B110B'


def write(path, text):
    with open(path, 'w') as f:
        f.write(text)


def test_capture_sees_the_devices_the_hub_powers(sysfs):
    entries, unnamed = usbman.capture_snapshot()
    recorded = {serial: channel for channel, serial, _ in entries}
    assert recorded == {STLINK: 1, 'FT1234XZ': 1, PICO: 5, FT232R: 7}
    assert unnamed == 2  # the two Genesys hubs behind socket 1 report no serial


def test_capture_skips_the_hub_and_anything_not_behind_it(sysfs):
    entries, _ = usbman.capture_snapshot()
    serials = {serial for _, serial, _ in entries}
    assert '000000000' not in serials  # the hub sections themselves
    assert 'ABCDEF' not in serials  # on the root hub, no managed hub above it


def test_a_snapshot_round_trips(sysfs):
    entries, _ = usbman.capture_snapshot()
    usbman.write_snapshot(entries)
    assert usbman.read_snapshot()[STLINK] == 1
    assert usbman.snapshot_channel(PICO) == 5


def test_the_file_is_readable_and_hand_editable(sysfs):
    entries, _ = usbman.capture_snapshot()
    path = usbman.write_snapshot(entries)
    with open(path) as f:
        text = f.read()
    assert text.startswith('# usbman snapshot, ')
    assert 'STLINK-V3' in text  # the device name rides along as a comment
    assert f'1          {STLINK}' in text.replace('\t', ' ') or STLINK in text


@pytest.mark.parametrize(
    ('text', 'expected'),
    [
        ('', {}),
        ('# nothing but a comment\n', {}),
        ('\n\n   \n', {}),
        (f'4 {STLINK}\n', {STLINK: 4}),
        (f'4   {STLINK}   # STLINK-V3\n', {STLINK: 4}),
        (f'# head\n\n1 {FT232R}  # one\n4 {STLINK}# two\n', {FT232R: 1, STLINK: 4}),
        (f'4 {STLINK} extra field\n1 {FT232R}\n', {FT232R: 1}),  # the bad line is skipped
        (f'notanumber {STLINK}\n1 {FT232R}\n', {FT232R: 1}),
    ],
)
def test_the_format_is_forgiving(sysfs, text, expected):
    write(sysfs.snapshot, text)
    assert usbman.read_snapshot() == expected


def test_a_malformed_line_names_itself(sysfs, caplog):
    write(sysfs.snapshot, f'1 {FT232R}\nrubbish\n')
    usbman.read_snapshot()
    assert 'line 2' in caplog.text


def test_one_serial_on_two_channels_is_refused(sysfs):
    write(sysfs.snapshot, f'1 {STLINK}\n4 {STLINK}\n')
    with pytest.raises(RuntimeError, match='channels 1 and 4'):
        usbman.read_snapshot()


def test_the_same_serial_twice_on_one_channel_is_fine(sysfs):
    write(sysfs.snapshot, f'4 {STLINK}\n4 {STLINK}\n')
    assert usbman.read_snapshot() == {STLINK: 4}


def test_the_live_tree_wins_over_a_stale_snapshot(sysfs):
    """The ST-LINK is really on channel 1. A snapshot saying 4 must not override that."""
    write(sysfs.snapshot, f'4 {STLINK}\n')
    assert usbman.resolve_channel(STLINK) == 1


def test_a_device_which_is_not_connected_comes_from_the_snapshot(sysfs):
    write(sysfs.snapshot, '6 GONEAWAY\n')
    assert usbman.resolve_channel('GONEAWAY') == 6


def test_an_unknown_device_still_fails_with_the_live_error(sysfs):
    write(sysfs.snapshot, f'6 {STLINK}\n')
    with pytest.raises(usbman.DeviceNotFoundError, match='NOSUCH'):
        usbman.resolve_channel('NOSUCH')


def test_a_device_found_somewhere_else_does_not_fall_back(sysfs):
    """Only absence falls through. The root hub device is present, just not behind the hub."""
    write(sysfs.snapshot, '6 ABCDEF\n')
    with pytest.raises(RuntimeError, match='not connected to a managed hub'):
        usbman.resolve_channel('ABCDEF')


def test_an_absent_path_says_to_use_a_serial(sysfs):
    """A path cannot be looked up: it does not exist when the device is off."""
    write(sysfs.snapshot, f'6 {STLINK}\n')
    with pytest.raises(usbman.DeviceNotFoundError, match='serial number'):
        usbman.resolve_channel(sysfs.path('ttyGONE'))


def test_writing_replaces_what_was_there(sysfs):
    write(sysfs.snapshot, '7 OLDENTRY\n')
    usbman.write_snapshot([(1, FT232R, 'FT232R USB UART')])
    assert usbman.read_snapshot() == {FT232R: 1}


def test_reading_a_snapshot_which_is_not_there_is_empty(sysfs):
    assert not os.path.exists(sysfs.snapshot)
    assert usbman.read_snapshot() == {}


def test_a_request_from_a_client_cannot_write_the_snapshot(sysfs):
    """`local=False` is how the server says a request came in over the socket."""
    for option in ('--snapshot', '--forget'):
        with pytest.raises(SystemExit) as refused:
            usbman.cli.run([option], device_path='/dev/fake', local=False, setup_logging=lambda level: None)
        assert refused.value.code == usbman.cli.EXIT_ERROR


def test_a_client_can_still_resolve_against_the_snapshot(sysfs, hub, capsys):
    """Only writing is local. Looking a device up is what a remote client needs most."""
    write(sysfs.snapshot, '6 GONEAWAY\n')
    usbman.cli.run(['--channel-of', 'GONEAWAY'], device_path='/dev/fake', local=False, setup_logging=lambda level: None)
    assert capsys.readouterr().out == '6\n'


def test_snapshot_is_refused_next_to_a_switching_option(sysfs):
    with pytest.raises(SystemExit):
        usbman.cli.run(['--snapshot', '--set', '1'], device_path='/dev/fake', setup_logging=lambda level: None)


def test_forget_removes_the_snapshot(sysfs, capsys):
    write(sysfs.snapshot, f'1 {FT232R}\n')
    usbman.cli.run(['--forget'], device_path='/dev/fake', setup_logging=lambda level: None)
    assert not os.path.exists(sysfs.snapshot)
    assert 'Removed' in capsys.readouterr().out


def test_forget_says_so_when_there_is_nothing(sysfs, capsys):
    usbman.cli.run(['--forget'], device_path='/dev/fake', setup_logging=lambda level: None)
    assert 'no snapshot' in capsys.readouterr().out


def test_setting_a_channel_by_a_disconnected_serial(sysfs, hub):
    """The point of the whole feature: switch on a board which is off, by name."""
    write(sysfs.snapshot, '3 GONEAWAY\n')
    usbman.cli.run(['--set', 'GONEAWAY'], device_path='/dev/fake', setup_logging=lambda level: None)
    assert hub.state == 0b100


def listing(capsys):
    usbman.cli.run(['--list'], device_path='/dev/fake', setup_logging=lambda level: None)
    return capsys.readouterr().out


def test_list_shows_every_channel_including_the_empty_ones(sysfs, capsys):
    out = listing(capsys)
    for channel in usbman.CHANNELS:
        assert any(line.startswith(f'{channel} ') for line in out.splitlines())


def test_list_shows_connected_devices_as_live(sysfs, capsys):
    out = listing(capsys)
    assert f'live      {STLINK}' in out.replace('  ', '  ')
    assert 'STLINK-V3' in out


def test_list_shows_a_device_with_no_serial(sysfs, capsys):
    """The Genesys hubs are really there, they just cannot be named."""
    assert 'USB2.1 Hub' in listing(capsys)


def test_list_shows_a_disconnected_device_from_the_snapshot(sysfs, capsys):
    write(sysfs.snapshot, '6 GONEAWAY # a board which is off\n')
    out = listing(capsys)
    assert 'snapshot' in out
    assert 'GONEAWAY' in out
    assert 'a board which is off' in out


def test_the_live_tree_overrides_the_snapshot_in_the_listing(sysfs, capsys):
    """A device seen now is listed once, where it is, not where the file remembers it."""
    write(sysfs.snapshot, f'4 {STLINK} # STLINK-V3\n')
    out = listing(capsys)
    rows = [line for line in out.splitlines() if STLINK in line and re.match(r'^\d+\s', line)]
    assert len(rows) == 1  # one table row, whatever the footnote below the table says
    assert rows[0].startswith('1 ')  # really on channel 1
    assert 'live' in rows[0]


def test_a_stale_snapshot_line_is_called_out(sysfs, capsys):
    write(sysfs.snapshot, f'4 {STLINK} # STLINK-V3\n')
    out = listing(capsys)
    assert 'has moved' in out
    assert 'says channel 4' in out
    assert 'usbman --snapshot' in out


def test_nothing_is_called_stale_when_the_snapshot_agrees(sysfs, capsys):
    write(sysfs.snapshot, f'1 {STLINK} # STLINK-V3\n')
    assert 'has moved' not in listing(capsys)


def test_list_works_without_a_snapshot(sysfs, capsys):
    assert not os.path.exists(sysfs.snapshot)
    assert 'live' in listing(capsys)


def test_a_client_may_list(sysfs, capsys):
    """Read only, and answered from the server's own tree and file, so it is not local only."""
    usbman.cli.run(['--list'], device_path='/dev/fake', local=False, setup_logging=lambda level: None)
    assert 'live' in capsys.readouterr().out
