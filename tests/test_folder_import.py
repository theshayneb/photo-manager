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
