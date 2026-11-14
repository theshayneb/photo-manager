import os
from pathlib import Path

from photo_manager.core import folder_import as fi


def make_share(root: Path) -> Path:
    share = root / "NAS" / "Videos"
    (share / "2025" / "Summer").mkdir(parents=True)
    (share / "2026").mkdir()
    (share / "@eaDir" / "clip.mp4").mkdir(parents=True)  # Synology's thumbnail folder
    (share / "top.mp4").write_bytes(b"t" * 10)
    (share / "2025" / "Summer" / "beach.MOV").write_bytes(b"b" * 20)
    (share / "2025" / "Summer" / "beach.jpg").write_bytes(b"photo")  # not a video
    (share / "2026" / "party.mkv").write_bytes(b"p" * 30)
    (share / "@eaDir" / "clip.mp4" / "SYNOVIDEO_VIDEO_SCREENSHOT.mp4").write_bytes(b"x")
    for n, f in enumerate(["top.mp4", "2025/Summer/beach.MOV", "2026/party.mkv"]):
        os.utime(share / f, (1_700_000_000 + n, 1_700_000_000 + n))
    return share


def test_finds_videos_in_all_subfolders(tmp_path):
    share = make_share(tmp_path)
    found = fi.find_videos([str(share)])
    assert [Path(f.path).name for f in found] == ["top.mp4", "beach.MOV", "party.mkv"]  # oldest first


def test_import_flat_then_only_new_ones(tmp_path):
    share = make_share(tmp_path)
    dest = tmp_path / "Camera Roll"
    log = tmp_path / "video_imported.txt"
    plan = fi.plan_import(fi.find_videos([str(share)]), str(dest), fi.load_log(log))
    done, failures = fi.import_files(plan)
    fi.add_to_log(log, {fi.file_key(os.path.basename(v.path), v.size) for v, _ in done})
    assert not failures and sorted(p.name for p in dest.iterdir()) == ["beach.MOV", "party.mkv", "top.mp4"]
    assert (share / "top.mp4").exists()  # copied, not moved
    # Renamed and moved away afterwards: still not offered again. A new video is.
    (dest / "top.mp4").rename(dest / "11-14-2026 09-00-00 AM.mp4")
    (dest / "party.mkv").unlink()
    (share / "2026" / "new.mp4").write_bytes(b"n" * 5)
    plan = fi.plan_import(fi.find_videos([str(share)]), str(dest), fi.load_log(log))
    assert [Path(v.path).name for v, _ in plan] == ["new.mp4"]


def test_same_name_different_video_gets_a_suffix_and_move_removes_originals(tmp_path):
    share = make_share(tmp_path)
    (share / "2026" / "top.mp4").write_bytes(b"other" * 9)  # a different top.mp4 in a subfolder
    dest = tmp_path / "out"
    plan = fi.plan_import(fi.find_videos([str(share)]), str(dest))
    assert sorted(Path(t).name for _, t in plan) == ["beach.MOV", "party.mkv", "top.mp4", "top_1.mp4"]
    done, _ = fi.import_files(plan, move=True)
    assert len(done) == 4 and not (share / "top.mp4").exists() and not (share / "2026" / "top.mp4").exists()


def test_destination_inside_the_source_is_left_out(tmp_path):
    share = make_share(tmp_path)
    dest = share / "Imported"
    dest.mkdir()
    (dest / "already.mp4").write_bytes(b"a")
    assert "already.mp4" not in [Path(f.path).name for f in fi.find_videos([str(share)], str(dest))]


def test_cancel_stops_between_files(tmp_path):
    share = make_share(tmp_path)
    plan = fi.plan_import(fi.find_videos([str(share)]), str(tmp_path / "out"))
    done, _ = fi.import_files(plan, cancelled=lambda: True)
    assert done == []


def test_movie_names_are_tidied():
    cases = {
        "Title.of.Movie.2019.1080p.BluRay.x264-GROUP.mkv": "Title of Movie (2019).mkv",
        "The_Big_Lebowski_1998_720p.avi": "The Big Lebowski (1998).avi",
        "[YTS.MX] The Matrix (1999) [1080p].mp4": "The Matrix (1999).mp4",
        "Movie Name - 2015 - 720p.mkv": "Movie Name (2015).mkv",
        "Ocean's.Eleven.2001.DVDRip.avi": "Ocean's Eleven (2001).avi",
        "Spider-Man.No.Way.Home.2021.1080p.mkv": "Spider-Man No Way Home (2021).mkv",
        # Titles that are or contain numbers:
        "1917.2019.1080p.WEB.mp4": "1917 (2019).mp4",
        "2001.A.Space.Odyssey.1968.REMASTERED.2160p.mkv": "2001 A Space Odyssey (1968).mkv",
        "Blade.Runner.2049.2017.1080p.mkv": "Blade Runner 2049 (2017).mkv",  # 2049 is in the future
        "Wonder.Woman.1984.2020.1080p.mkv": "Wonder Woman 1984 (2020).mkv",
        "Title.2019.Directors.Cut.2020.Remaster.mkv": "Title (2019).mkv",
    }
    for name, tidy in cases.items():
        assert fi.movie_name(name, this_year=2026) == tidy, name
    for name in ("Holiday Video.mp4", "Show.S01E02.720p.mkv", "2019.mp4"):  # no title + year: untouched
        assert fi.movie_name(name, this_year=2026) is None, name


def test_import_with_tidy_names(tmp_path):
    share = tmp_path / "Movies"
    (share / "New").mkdir(parents=True)
    (share / "New" / "Title.of.Movie.2019.1080p.BluRay.x264-GRP.mkv").write_bytes(b"m" * 10)
    (share / "Home video.mp4").write_bytes(b"h" * 5)
    dest = tmp_path / "out"
    plan = fi.plan_import(fi.find_videos([str(share)]), str(dest), tidy_names=True)
    assert sorted(Path(t).name for _, t in plan) == ["Home video.mp4", "Title of Movie (2019).mkv"]
    fi.import_files(plan)
    # Already there under its tidy name: not imported again, even without the log.
    assert fi.plan_import(fi.find_videos([str(share)]), str(dest), tidy_names=True) == []
