import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException

from server import main as server_main
from server.main import (
    character_source,
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

    def test_manual_video_type_selection(self) -> None:
        record = {
            "name": "测试角色",
            "videos": [
                {"title": "《原神》角色演示-测试", "url": "/demo.mp4"},
                {"title": "《原神》EP - 测试", "url": "/ep.mp4"},
            ],
            "images": {"生日贺图": [{"url": "/birthday.png"}]},
        }

        selected = choose_source(record, "角色演示")

        self.assertEqual(selected["type"], "角色演示")
        self.assertEqual(selected["urls"], ["/demo.mp4"])

    def test_manual_birthday_selection_overrides_videos(self) -> None:
        record = {
            "name": "测试角色",
            "videos": [{"title": "《原神》EP - 测试", "url": "/ep.mp4"}],
            "images": {"生日贺图": [{"url": "/birthday.png"}]},
        }

        selected = choose_source(record, "生日贺图")

        self.assertEqual(selected["kind"], "images")
        self.assertEqual(selected["urls"], ["/birthday.png"])

    def test_unavailable_manual_type_is_rejected(self) -> None:
        with self.assertRaisesRegex(HTTPException, "角色 PV"):
            choose_source(
                {
                    "name": "测试角色",
                    "videos": [],
                    "images": {"生日贺图": [{"url": "/birthday.png"}]},
                },
                "角色 PV",
            )

    def test_invalid_manual_type_is_rejected(self) -> None:
        with self.assertRaisesRegex(HTTPException, "画面素材类型无效"):
            choose_source({"name": "测试角色", "videos": [], "images": {}}, "其他")

    @patch("server.main.character_record")
    def test_source_preview_endpoint_honors_manual_type(self, record) -> None:
        record.return_value = {
            "name": "测试角色",
            "videos": [
                {"title": "《原神》EP - 测试", "url": "/ep.mp4"},
                {"title": "《原神》角色演示-测试", "url": "/demo.mp4"},
            ],
            "images": {},
        }

        selected = character_source("测试角色", "角色演示")

        self.assertEqual(selected["kind"], "video")
        self.assertEqual(selected["type"], "角色演示")
        self.assertEqual(selected["urls"], ["/demo.mp4"])

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

    def test_enhanced_lrc_is_collapsed_to_one_cue_per_line(self) -> None:
        result = lrc_to_srt(
            "[00:13.11]风[00:13.44]捎[00:13.82]大梦[00:14.20]\n"
            "[00:14.57]似[00:14.97]你[00:15.44]在身侧[00:16.00]",
            20.0,
        )

        self.assertEqual(result.count(" --> "), 2)
        self.assertIn("00:00:13,110 --> 00:00:14,200", result)
        self.assertIn("00:00:14,570 --> 00:00:16,000", result)
        self.assertEqual(result.count("风捎大梦"), 1)
        self.assertEqual(result.count("似你在身侧"), 1)

    def test_standard_multi_timestamp_lrc_keeps_repeated_line(self) -> None:
        result = lrc_to_srt("[00:01.00][00:03.00]副歌", 5.0)

        self.assertEqual(result.count(" --> "), 2)
        self.assertEqual(result.count("副歌"), 2)

    def test_positive_offset_delays_lyrics(self) -> None:
        result = lrc_to_srt("[00:01.00]第一句\n[00:03.50]第二句", 10.0, 5.0)

        self.assertIn("00:00:06,000 --> 00:00:08,500", result)
        self.assertIn("00:00:08,500 --> 00:00:10,000", result)

    def test_negative_offset_advances_and_clips_lyrics(self) -> None:
        result = lrc_to_srt("[00:01.00]第一句\n[00:03.50]第二句", 10.0, -2.0)

        self.assertIn("00:00:00,000 --> 00:00:01,500", result)
        self.assertIn("00:00:01,500 --> 00:00:08,000", result)

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
