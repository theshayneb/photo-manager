from datetime import datetime
from pathlib import Path

from photo_manager.core import steam


def make_steam(root: Path) -> Path:
    s = root / "Steam"
    shots = s / "userdata" / "12345" / "760" / "remote"
    tf2 = shots / "440" / "screenshots"
    (tf2 / "thumbnails").mkdir(parents=True)
    (tf2 / "20261104213012_1.jpg").write_bytes(b"a" * 10)
    (tf2 / "20261104213015_1.jpg").write_bytes(b"b" * 10)
    (tf2 / "thumbnails" / "20261104213012_1.jpg").write_bytes(b"t")
    other = shots / "999999" / "screenshots"  # a game with no manifest (e.g. non-Steam shortcut)
    other.mkdir(parents=True)
    (other / "20260101120000_1.png").write_bytes(b"c" * 10)
    (s / "userdata" / "777").mkdir()  # an account with no screenshots
    apps = s / "steamapps"
    apps.mkdir()
    (apps / "appmanifest_440.acf").write_text('"AppState"\n{\n\t"appid"\t\t"440"\n\t"name"\t\t"Team Fortress 2"\n}\n')
    lib2 = root / "Games" / "SteamLibrary"
    (lib2 / "steamapps").mkdir(parents=True)
    (lib2 / "steamapps" / "appmanifest_620.acf").write_text('"AppState"\n{\n\t"appid"\t"620"\n\t"name"\t"Portal 2: <Ed>"\n}\n')
    (apps / "libraryfolders.vdf").write_text(
        '"libraryfolders"\n{\n\t"0"\n\t{\n\t\t"path"\t\t"%s"\n\t}\n\t"1"\n\t{\n\t\t"path"\t\t"%s"\n\t}\n}\n'
        % (str(s).replace("\\", "\\\\"), str(lib2).replace("\\", "\\\\")))
    return s


def test_finds_accounts_games_and_screenshots(tmp_path):
    s = make_steam(tmp_path)
    assert steam.accounts(str(s)) == ["12345"]
    names = steam.game_names(str(s))
    assert names["440"] == "Team Fortress 2" and names["620"] == "Portal 2: <Ed>"
    shots = steam.find_screenshots(str(s), "12345")
    assert [Path(x.path).name for x in shots] == [
        "20260101120000_1.png", "20261104213012_1.jpg", "20261104213015_1.jpg"]  # oldest first, no thumbnails
    assert shots[1].game == "Team Fortress 2" and shots[1].taken == datetime(2026, 11, 4, 21, 30, 12)
    assert shots[0].game == "App 999999"


def test_import_goes_straight_into_the_chosen_folder(tmp_path):
    s = make_steam(tmp_path)
    dest = tmp_path / "Pictures" / "Steam"
    shots = steam.find_screenshots(str(s))
    plan = steam.plan_import(shots, str(dest))
    done, failures = steam.import_shots(plan)
    assert not failures and len(done) == 3
    assert sorted(p.name for p in dest.iterdir()) == [  # no subfolders
        "20260101120000_1.png", "20261104213012_1.jpg", "20261104213015_1.jpg"]
    assert (dest / "20261104213012_1.jpg").read_bytes() == b"a" * 10
    # Steam's own files are untouched, and running again finds nothing new.
    assert Path(shots[1].path).exists()
    assert steam.plan_import(steam.find_screenshots(str(s)), str(dest)) == []


def test_name_clash_gets_a_suffix_never_overwrites(tmp_path):
    s = make_steam(tmp_path)
    dest = tmp_path / "flat"
    dest.mkdir()
    (dest / "20261104213012_1.jpg").write_bytes(b"different size")
    plan = steam.plan_import(steam.find_screenshots(str(s)), str(dest))
    names = sorted(Path(target).name for _, target in plan)
    assert names == ["20260101120000_1.png", "20261104213012_1_1.jpg", "20261104213015_1.jpg"]
    assert (dest / "20261104213012_1.jpg").read_bytes() == b"different size"
