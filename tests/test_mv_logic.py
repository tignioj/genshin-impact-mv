import unittest

from fastapi import HTTPException

from server.main import choose_source, lrc_to_srt, video_rank


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


if __name__ == "__main__":
    unittest.main()
