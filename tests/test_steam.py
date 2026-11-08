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
    shots_dir = tmp_path / "shots"
    shots_dir.mkdir()
    (shots_dir / "my capture.png").write_bytes(b"x" * 10)  # not a Steam-style name
    dest = tmp_path / "flat"
    dest.mkdir()
    (dest / "my capture.png").write_bytes(b"a different picture")
    plan = steam.plan_import(steam.find_screenshots("", None, [str(shots_dir)]), str(dest))
    assert [Path(target).name for _, target in plan] == ["my capture_1.png"]
    assert (dest / "my capture.png").read_bytes() == b"a different picture"


def test_imported_screenshots_stay_imported_after_dating_renaming_or_moving(tmp_path):
    """Writing Date taken changes the file's size, renaming changes its name, and moving
    takes it out of the folder: none of that makes it 'new' again."""
    from photo_manager.core.templates import DEFAULT_TEMPLATES, match_any

    def date_of_name(name):
        found = match_any(DEFAULT_TEMPLATES, name)
        return found[1] if found else None

    s = make_steam(tmp_path)
    dest = tmp_path / "Pictures"
    log = tmp_path / "steam_imported.txt"
    shots = steam.find_screenshots(str(s))
    done, _ = steam.import_shots(steam.plan_import(shots, str(dest)))
    steam.add_to_log(log, {steam.shot_key(shot) for shot, _ in done})
    (dest / "20261104213012_1.jpg").write_bytes(b"a" * 10 + b"exif date written")  # dated: bigger
    (dest / "20261104213015_1.jpg").rename(dest / "11-04-2026 09-30-15 PM.jpg")       # renamed by date
    (dest / "20260101120000_1.png").unlink()                                          # moved away
    # From the log alone:
    assert steam.plan_import(shots, str(dest), steam.load_log(log)) == []
    # Without a log (imported by an older version), what's still in the folder is recognized:
    seen = steam.found_in_dest(shots, str(dest), date_of_name)
    assert seen == {"20261104213012_1", "20261104213015_1"}
    assert [Path(sh.path).name for sh, _ in steam.plan_import(shots, str(dest), seen)] == ["20260101120000_1.png"]
    # A new screenshot is still new.
    tf2 = s / "userdata" / "12345" / "760" / "remote" / "440" / "screenshots"
    (tf2 / "20261108090000_1.jpg").write_bytes(b"n" * 10)
    shots = steam.find_screenshots(str(s))
    assert [Path(sh.path).name for sh, _ in steam.plan_import(shots, str(dest), steam.load_log(log))] == [
        "20261108090000_1.jpg"]


def test_screenshots_listed_only_in_steams_index_are_found(tmp_path):
    """A game that saves screenshots itself and adds them to Steam's library: the file can
    live outside 760/remote; Steam's screenshots.vdf points at it."""
    s = make_steam(tmp_path)
    own = tmp_path / "Games" / "SomeGame" / "Screens"
    own.mkdir(parents=True)
    (own / "20261107083000_1.png").write_bytes(b"x" * 50)
    index = s / "userdata" / "12345" / "760" / "screenshots.vdf"
    index.write_text('''"Screenshots"
{
\t"620"
\t{
\t\t"0"
\t\t{
\t\t\t"type"\t\t"1"
\t\t\t"filename"\t\t"%s"
\t\t\t"imported"\t\t"1"
\t\t}
\t}
\t"440"
\t{
\t\t"0"
\t\t{
\t\t\t"filename"\t\t"440/screenshots/20261104213012_1.jpg"
\t\t}
\t}
}
''' % str(own / "20261107083000_1.png").replace("\\", "\\\\"))
    shots = steam.find_screenshots(str(s), "12345")
    names = [Path(x.path).name for x in shots]
    assert "20261107083000_1.png" in names
    found = next(x for x in shots if x.path.endswith("20261107083000_1.png"))
    assert found.game == "Portal 2: <Ed>" and found.taken == datetime(2026, 11, 7, 8, 30)
    assert names.count("20261104213012_1.jpg") == 1  # listed in the index AND in the folder: once
    assert steam.per_game(shots)[0][:2] == ("Portal 2: <Ed>", 1)  # newest game first


def test_extra_folders_and_duplicate_copies(tmp_path):
    s = make_steam(tmp_path)
    extra = tmp_path / "Uncompressed"
    (extra / "Team Fortress 2").mkdir(parents=True)
    (extra / "Team Fortress 2" / "20261104213012_1.png").write_bytes(b"p" * 500)  # bigger copy
    (extra / "Team Fortress 2" / "20261106100000_1.jxr").write_bytes(b"h" * 50)   # HDR capture
    (extra / "Team Fortress 2" / "thumbnails").mkdir()
    (extra / "Team Fortress 2" / "thumbnails" / "20261106100000_1.jpg").write_bytes(b"t")
    shots = steam.find_screenshots(str(s), "12345", [str(extra)])
    stems = sorted(Path(x.path).stem for x in shots)
    assert stems == ["20260101120000_1", "20261104213012_1", "20261104213015_1", "20261106100000_1"]
    tf2 = next(x for x in shots if Path(x.path).stem == "20261104213012_1")
    assert tf2.path.endswith(".png") and tf2.game == "Team Fortress 2"  # the better copy, once


def test_parse_vdf_nested_and_escapes():
    data = steam.parse_vdf('"a"\n{\n\t"b"\t"C:\\\\Games\\\\x"\n\t"c"\n\t{\n\t\t"d"\t"1"\n\t}\n}\n')
    assert data == {"a": {"b": "C:\\Games\\x", "c": {"d": "1"}}}


def test_synced_steam_deck_folder_uses_app_ids(tmp_path):
    """A Steam Deck's 760/remote folder synced to the PC: <app id>/screenshots/<file>."""
    s = make_steam(tmp_path)
    deck = tmp_path / "SteamDeck"
    (deck / "440" / "screenshots" / "thumbnails").mkdir(parents=True)
    (deck / "440" / "screenshots" / "20261107080000_1.jpg").write_bytes(b"d" * 10)
    (deck / "440" / "screenshots" / "thumbnails" / "20261107080000_1.jpg").write_bytes(b"t")
    (deck / "1234567" / "screenshots").mkdir(parents=True)
    (deck / "1234567" / "screenshots" / "20261107085800_1.jpg").write_bytes(b"k" * 10)
    shots = [x for x in steam.find_screenshots(str(s), "12345", [str(deck)]) if str(deck) in x.path]
    assert [(x.app_id, x.game) for x in shots] == [("440", "Team Fortress 2"), ("1234567", "App 1234567")]
    assert steam.unnamed_app_ids(shots) == ["1234567"]
    named = steam.find_screenshots("", None, [str(deck)], {"1234567": "Hello Kitty Island Adventure", "9": ""})
    assert [x.game for x in named] == ["App 440", "Hello Kitty Island Adventure"]  # no Steam folder here


def test_fetch_store_names_reads_the_store_reply(monkeypatch):
    import io
    import json as _json
    import urllib.request

    monkeypatch.undo()  # put back the real lookup (conftest replaces it with a no-network stand-in)
    replies = {"1": {"1": {"success": True, "data": {"name": "Game One"}}}, "2": {"2": {"success": False}}}

    def fake_urlopen(url, timeout):
        app = url.split("appids=")[1].split("&")[0]
        if app == "3":
            raise OSError("offline")
        return io.BytesIO(_json.dumps(replies[app]).encode())

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    assert steam.fetch_store_names(["1", "2", "3"]) == {"1": "Game One", "2": ""}  # 3 is asked again later
