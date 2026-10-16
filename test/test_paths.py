"""Finding the /dev path to hand to another tool."""

import os

import pytest
import usbman
import usbman.cli

STLINK = '004B00283532510831333430'


def paths(capsys, reference):
    usbman.cli.run(['path-of', reference], device_path='/dev/fake', setup_logging=lambda level: None)
    return capsys.readouterr().out.split()


def test_a_channel_gives_the_path_of_its_serial_port(sysfs, capsys):
    assert paths(capsys, '7') == ['/dev/ttyUSB0']


def test_every_port_on_a_channel_is_listed(sysfs, capsys):
    """One socket may hold several, and all of them are switched together."""
    assert paths(capsys, '1') == ['/dev/ttyACM0', '/dev/ttyUSB1']


def test_several_ports_are_warned_about_on_stderr(sysfs, capsys, caplog):
    paths(capsys, '1')
    assert 'has 2 serial ports' in caplog.text


def test_only_the_paths_go_to_stdout(sysfs, capsys):
    """So that `$(usbman --path-of x)` substitutes cleanly into another command."""
    usbman.cli.run(['path-of', '7'], device_path='/dev/fake', setup_logging=lambda level: None)
    assert capsys.readouterr().out == '/dev/ttyUSB0\n'


def test_a_nickname_names_the_channel_too(sysfs, capsys):
    with open(sysfs.nicknames, 'w') as f:
        f.write(f'stlink {STLINK}\n')
    assert paths(capsys, 'stlink') == ['/dev/ttyACM0', '/dev/ttyUSB1']


def test_a_serial_names_the_channel_too(sysfs, capsys):
    assert paths(capsys, STLINK) == ['/dev/ttyACM0', '/dev/ttyUSB1']


def test_a_device_with_no_serial_port_says_so(sysfs, capsys):
    """The Pico is on channel 5 and is really there, it just exposes no tty in this tree."""
    with pytest.raises(RuntimeError, match='no serial port'):
        paths(capsys, '5')


def test_an_empty_channel_says_so(sysfs, capsys):
    with pytest.raises(RuntimeError, match='nothing is connected'):
        paths(capsys, '2')


def test_all_is_refused(sysfs, capsys):
    with pytest.raises(SystemExit):
        paths(capsys, 'all')


def test_an_invalid_channel_is_refused_by_the_parser(sysfs):
    with pytest.raises(SystemExit):
        usbman.cli.build_parser().parse_args(['path-of', '8'])


def test_a_client_may_ask_for_a_path(sysfs, capsys):
    """Read only, and the devices are on the server, so it answers from there."""
    usbman.cli.run(['path-of', '7'], device_path='/dev/fake', local=False, setup_logging=lambda level: None)
    assert capsys.readouterr().out == '/dev/ttyUSB0\n'


def id_paths(capsys, reference):
    usbman.cli.run(['id-path-of', reference], device_path='/dev/fake', setup_logging=lambda level: None)
    return capsys.readouterr().out.split()


def test_the_stable_name_is_given_for_a_channel(sysfs, capsys):
    found = id_paths(capsys, '1')
    assert all(path.startswith(sysfs.dev) and '/serial/by-id/' in path for path in found)
    assert any('STLINK-V3_004B00283532510831333430' in path for path in found)


def test_every_stable_name_on_a_channel_is_listed(sysfs, capsys):
    assert len(id_paths(capsys, '1')) == 2  # the ST-LINK and the FTDI behind the same socket


def test_the_stable_name_points_at_the_plain_path(sysfs, capsys):
    """The two options must agree about which ports are on the channel."""
    plain = set(paths(capsys, '1'))
    resolved = {os.path.join('/dev', os.path.basename(os.path.realpath(p))) for p in id_paths(capsys, '1')}
    assert resolved == plain


def test_a_port_with_no_stable_name_says_so(sysfs, capsys):
    """udev builds these out of the USB descriptors, and not every device supplies them."""
    with pytest.raises(RuntimeError, match='by-id'):
        id_paths(capsys, '7')  # ttyUSB0 has a plain path but no by-id entry in this tree


def test_an_empty_channel_says_so_for_the_stable_name_too(sysfs, capsys):
    with pytest.raises(RuntimeError, match='nothing is connected'):
        id_paths(capsys, '2')


def test_a_nickname_works_for_the_stable_name_too(sysfs, capsys):
    with open(sysfs.nicknames, 'w') as f:
        f.write(f'stlink {STLINK}\n')
    assert len(id_paths(capsys, 'stlink')) == 2


def test_a_missing_by_id_directory_is_not_a_crash(sysfs, capsys, monkeypatch):
    """No USB serial device has ever been seen, so udev never made the directory."""
    monkeypatch.setattr(usbman, 'SERIAL_BY_ID', os.path.join(sysfs.dev, 'nosuchdir'))
    with pytest.raises(RuntimeError, match='nosuchdir'):
        id_paths(capsys, '1')
