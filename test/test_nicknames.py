"""Names you give your boards, so commands can talk about them rather than serial numbers."""

import types

import pytest
import usbman
import usbman.cli

STLINK = '004B00283532510831333430'
PICO = '648326155B4B110B'


def write(path, text):
    with open(path, 'w') as f:
        f.write(text)


def test_a_nickname_resolves_through_to_a_channel(sysfs):
    write(sysfs.nicknames, f'stlink {STLINK}\n')
    assert usbman.resolve_channel('stlink') == 1  # the same channel the serial resolves to


def test_a_nickname_works_for_a_device_which_is_off(sysfs):
    """The pairing that matters: a name you chose, for a board you cannot see."""
    write(sysfs.nicknames, 'numaker NUMAKER123\n')
    write(sysfs.snapshot, '3 NUMAKER123 # Numaker M5531\n')
    assert usbman.resolve_channel('numaker') == 3


def test_a_nickname_switches_the_right_channel(sysfs, hub):
    write(sysfs.nicknames, 'numaker NUMAKER123\n')
    write(sysfs.snapshot, '3 NUMAKER123\n')
    usbman.cli.run(['switch', '--on', 'numaker'], device_path='/dev/fake', setup_logging=lambda level: None)
    assert hub.state == 0b100


def test_nicknames_mix_with_channel_numbers(sysfs, hub):
    write(sysfs.nicknames, f'stlink {STLINK}\n')
    usbman.cli.run(['only', 'stlink', '5'], device_path='/dev/fake', setup_logging=lambda level: None)
    assert hub.state == 0b10001  # channel 1 for the ST-LINK, and channel 5


@pytest.mark.parametrize(
    ('text', 'expected'),
    [
        ('', {}),
        ('# only a comment\n', {}),
        (f'stlink {STLINK}\n', {'stlink': STLINK}),
        (f'stlink   {STLINK}   # my debugger\n', {'stlink': STLINK}),
        (f'\n\nstlink {STLINK}\npico {PICO}\n', {'stlink': STLINK, 'pico': PICO}),
        (f'rubbish\nstlink {STLINK}\n', {'stlink': STLINK}),
        (f'two fields too many here\nstlink {STLINK}\n', {'stlink': STLINK}),
        # several names for one device are fine, they are just aliases
        (f'stlink {STLINK}\ndebugger {STLINK}\n', {'stlink': STLINK, 'debugger': STLINK}),
    ],
)
def test_the_format_is_forgiving(sysfs, text, expected):
    write(sysfs.nicknames, text)
    assert usbman.read_nicknames() == expected


def test_one_nickname_for_two_devices_is_refused(sysfs):
    write(sysfs.nicknames, f'board {STLINK}\nboard {PICO}\n')
    with pytest.raises(RuntimeError, match='nickname'):
        usbman.read_nicknames()


@pytest.mark.parametrize('nickname', ['3', 'all', '/dev/ttyACM0', '42'])
def test_a_nickname_which_could_never_be_used_is_called_out(sysfs, caplog, nickname):
    """Those shapes are read as a channel, `all` or a path long before nicknames are consulted."""
    write(sysfs.nicknames, f'{nickname} {STLINK}\n')
    assert usbman.read_nicknames() == {}
    assert 'never be read as a nickname' in caplog.text


def test_a_long_digit_nickname_is_allowed(sysfs):
    """Four digits or more is read as a serial, so it can be a nickname too."""
    write(sysfs.nicknames, f'1234 {STLINK}\n')
    assert usbman.read_nicknames() == {'1234': STLINK}


def test_an_unknown_nickname_names_itself_and_the_serial(sysfs):
    write(sysfs.nicknames, 'ghost NOSUCHSERIAL\n')
    with pytest.raises(usbman.DeviceNotFoundError, match=r"serial number 'NOSUCHSERIAL'.*nickname 'ghost'"):
        usbman.resolve_channel('ghost')


def test_without_a_nicknames_file_everything_still_works(sysfs):
    assert usbman.read_nicknames() == {}
    assert usbman.resolve_channel(STLINK) == 1


def test_the_first_alphabetically_is_shown_for_a_device_with_several(sysfs):
    write(sysfs.nicknames, f'zeta {STLINK}\nalpha {STLINK}\n')
    assert usbman.serial_nicknames()[STLINK] == 'alpha'


def test_list_shows_the_nickname(sysfs, capsys):
    write(sysfs.nicknames, f'stlink {STLINK}\n')
    usbman.cli.run(['list'], device_path='/dev/fake', setup_logging=lambda level: None)
    out = capsys.readouterr().out
    assert 'nickname' in out.splitlines()[0]
    assert any('stlink' in line and STLINK in line for line in out.splitlines())


def test_list_shows_a_dash_where_there_is_no_nickname(sysfs, capsys):
    usbman.cli.run(['list'], device_path='/dev/fake', setup_logging=lambda level: None)
    out = capsys.readouterr().out
    assert any(STLINK in line and ' - ' in line for line in out.splitlines())


@pytest.fixture
def xdg(tmp_path, monkeypatch):
    """Two separate XDG directories, so the search order can be exercised for real."""
    config = tmp_path / 'config'
    state = tmp_path / 'state'
    (config / 'usbman').mkdir(parents=True)
    (state / 'usbman').mkdir(parents=True)
    monkeypatch.delenv(usbman.USBMAN_DIR_ENV, raising=False)
    monkeypatch.setenv('XDG_CONFIG_HOME', str(config))
    monkeypatch.setenv('XDG_STATE_HOME', str(state))
    return types.SimpleNamespace(config=str(config / 'usbman' / 'nicknames'), state=str(state / 'usbman' / 'nicknames'))


def test_the_config_directory_is_looked_at_first(xdg):
    write(xdg.config, f'fromconfig {STLINK}\n')
    assert usbman.read_nicknames() == {'fromconfig': STLINK}


def test_beside_the_snapshot_also_works(xdg):
    """For anyone who would rather keep both usbman files in one place."""
    write(xdg.state, f'fromstate {STLINK}\n')
    assert usbman.read_nicknames() == {'fromstate': STLINK}


def test_the_config_one_wins_and_the_other_is_called_out(xdg, caplog):
    write(xdg.config, f'fromconfig {STLINK}\n')
    write(xdg.state, f'fromstate {STLINK}\n')
    assert usbman.read_nicknames() == {'fromconfig': STLINK}
    assert 'ignoring' in caplog.text
    assert xdg.state in caplog.text


def test_with_neither_the_config_one_is_the_one_to_create(xdg):
    assert usbman.read_nicknames() == {}
    assert usbman.nicknames_path() == xdg.config


def test_usbman_dir_replaces_both(tmp_path, monkeypatch):
    monkeypatch.setenv(usbman.USBMAN_DIR_ENV, str(tmp_path))
    assert usbman.nicknames_paths() == [str(tmp_path / 'nicknames')]
    assert usbman.snapshot_path() == str(tmp_path / 'snapshot')


def test_the_snapshot_is_never_looked_for_in_the_config_directory(xdg, tmp_path):
    """Only the nicknames are searched for: usbman writes the snapshot, so it has one home."""
    assert usbman.snapshot_path() == str(tmp_path / 'state' / 'usbman' / 'snapshot')
