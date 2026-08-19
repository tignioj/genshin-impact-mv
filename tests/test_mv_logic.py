import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException

from server import main as server_main
from server.main import (
    choose_source,
    fetch_timed_lyrics,
    lrc_to_srt,
    prepare_auto_subtitle,
    video_rank,
)


class SourceSelectionTests(unittest.TestCase):
    def test_video_priority(self) -> None:
        record = {
            "name": "测试角色",
            "videos": [
                {"title": "《原神》角色演示-测试", "url": "/demo.mp4"},
                {"title": "《原神》角色PV——测试", "url": "/pv.mp4"},
                {"title": "《原神》角色预告-测试", "url": "/teaser.mp4"},
                {"title": "《原神》EP - 测试", "url": "/ep.mp4"},
            ],
            "images": {},
        }
        selected = choose_source(record)
        self.assertEqual(selected["type"], "EP 视频")
        self.assertEqual(selected["urls"], ["/ep.mp4"])

    def test_birthday_fallback(self) -> None:
        record = {
            "name": "测试角色",
            "videos": [],
            "images": {"生日贺图": [{"url": "/one.png"}, {"url": "/two.png"}]},
        }
        selected = choose_source(record)
        self.assertEqual(selected["kind"], "images")
        self.assertEqual(len(selected["urls"]), 2)

    def test_missing_source_is_rejected(self) -> None:
        with self.assertRaises(HTTPException):
            choose_source({"name": "测试角色", "videos": [], "images": {}})

    def test_rank_labels(self) -> None:
        self.assertEqual(video_rank({"title": "《原神》角色预告-测试"})[0], 1)
        self.assertEqual(video_rank({"title": "《原神》角色PV——测试"})[0], 2)
        self.assertEqual(video_rank({"title": "《原神》角色演示-测试"})[0], 3)

    def test_ep_category_is_authoritative(self) -> None:
        video = {
            "title": "《原神》珊瑚宫心海EP - 浮岳映虹之波",
            "category": "角色EP",
        }
        self.assertEqual(video_rank(video), (0, "EP 视频"))

    def test_attached_ep_title_fallback(self) -> None:
        video = {"title": "《原神》珊瑚宫心海EP - 浮岳映虹之波"}
        self.assertEqual(video_rank(video), (0, "EP 视频"))


class SubtitleTests(unittest.TestCase):
    def test_lrc_conversion(self) -> None:
        result = lrc_to_srt("[00:00.00]第一句\n[00:02.50]第二句", 5.0)
        self.assertIn("00:00:00,000 --> 00:00:02,500", result)
        self.assertIn("第二句", result)

    @patch("server.main.lyrics_agent_command", return_value=["lyrics-agent"])
    @patch("server.main.subprocess.run")
    def test_fetch_timed_lyrics_calls_agent_in_timed_mode(self, run, _command) -> None:
        payload = {
            "found": True,
            "artist": "歌手",
            "song": "歌曲",
            "timed": True,
            "lyrics": "[00:01.00]第一句",
            "sources": [],
            "message": None,
        }
        run.return_value = subprocess.CompletedProcess([], 0, json.dumps(payload), "")

        result = fetch_timed_lyrics("歌手", "歌曲")

        self.assertTrue(result["timed"])
        command = run.call_args.args[0]
        self.assertIn("--timed", command)
        self.assertEqual(command[command.index("--artist") + 1], "歌手")
        self.assertEqual(command[command.index("--song") + 1], "歌曲")

    @patch("server.main.fetch_timed_lyrics")
    def test_missing_timed_lyrics_falls_back_without_subtitles(self, fetch) -> None:
        fetch.return_value = {
            "found": False,
            "artist": "歌手",
            "song": "歌曲",
            "timed": False,
            "lyrics": None,
            "sources": [],
            "message": "未找到可靠的同步歌词",
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            job_id = "lyrics-miss"
            job = {
                "id": job_id,
                "status": "queued",
                "progress": 0,
                "message": "任务已进入队列",
                "character": "测试角色",
                "duration": 10.0,
                "original_artist": "歌手",
                "song_name": "歌曲",
                "has_subtitles": False,
                "job_dir": temp_dir,
                "created_at": server_main.utc_now(),
                "updated_at": server_main.utc_now(),
            }
            server_main.JOBS[job_id] = job
            try:
                created = prepare_auto_subtitle(job_id, job, Path(temp_dir) / "subtitle.srt")
                self.assertFalse(created)
                self.assertEqual(server_main.JOBS[job_id]["lyrics_status"], "not_found")
                self.assertFalse((Path(temp_dir) / "subtitle.srt").exists())
            finally:
                server_main.JOBS.pop(job_id, None)

    @patch("server.main.fetch_timed_lyrics")
    def test_timed_lyrics_are_converted_to_subtitles(self, fetch) -> None:
        fetch.return_value = {
            "found": True,
            "artist": "歌手",
            "song": "歌曲",
            "timed": True,
            "lyrics": "[00:01.00]第一句\n[00:03.50]第二句",
            "sources": [{"title": "歌词来源", "url": "https://example.com/lrc"}],
            "message": None,
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            job_id = "lyrics-found"
            job = {
                "id": job_id,
                "status": "queued",
                "progress": 0,
                "message": "任务已进入队列",
                "character": "测试角色",
                "duration": 10.0,
                "original_artist": "歌手",
                "song_name": "歌曲",
                "has_subtitles": False,
                "job_dir": temp_dir,
                "created_at": server_main.utc_now(),
                "updated_at": server_main.utc_now(),
            }
            server_main.JOBS[job_id] = job
            destination = Path(temp_dir) / "subtitle.srt"
            try:
                created = prepare_auto_subtitle(job_id, job, destination)
                self.assertTrue(created)
                self.assertEqual(server_main.JOBS[job_id]["lyrics_status"], "found")
                self.assertIn("第一句", destination.read_text(encoding="utf-8"))
            finally:
                server_main.JOBS.pop(job_id, None)


if __name__ == "__main__":
    unittest.main()
