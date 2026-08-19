"""AstrBot command front end for the Genshin Impact cover-MV service."""

from __future__ import annotations

import asyncio
import json
import mimetypes
import re
import shlex
import time
import uuid
from pathlib import Path
from urllib.parse import unquote, urlparse

import aiohttp
from astrbot.api import AstrBotConfig
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.message_components import File, Plain, Record, Reply, Video
from astrbot.api.star import Context, Star, register
from astrbot.core.star.filter.command import GreedyStr
from astrbot.core.utils.astrbot_path import get_astrbot_plugin_data_path


PLUGIN_NAME = "astrbot_plugin_cover_mv"
AUDIO_EXTENSIONS = {".mp3", ".wav", ".m4a", ".flac", ".aac", ".ogg", ".opus"}
INVALID_FILENAME_CHARS = re.compile(r'[\x00-\x1f<>:"/\\|?*]+')


def _safe_filename_part(value: str, fallback: str) -> str:
    cleaned = INVALID_FILENAME_CHARS.sub("_", str(value or "")).strip(" .")
    return cleaned[:80] or fallback


def _parse_command_args(raw: str) -> tuple[str, str, str]:
    try:
        values = shlex.split(raw.strip())
    except ValueError as exc:
        raise ValueError(f"命令参数中的引号不完整：{exc}") from exc
    if len(values) != 3 or any(not value.strip() for value in values):
        raise ValueError(
            "用法：回复一个音乐文件并发送 /翻唱视频 角色名称 原唱作者 原曲名称。"
            "名称含空格时请用英文双引号包住。"
        )
    if any(len(value) > 160 for value in values):
        raise ValueError("角色名称、原唱作者或原曲名称过长。")
    return tuple(value.strip() for value in values)


def _file_name(component: File, path: str) -> str:
    name = str(component.name or "").strip()
    if name:
        return name.replace("\\", "/").rsplit("/", 1)[-1]
    if component.url:
        url_name = Path(unquote(urlparse(component.url).path)).name
        if url_name:
            return url_name
    return Path(path).name


@register(
    PLUGIN_NAME,
    "tignioj",
    "引用音乐并调用映界服务制作原神角色翻唱 MV",
    "1.0.0",
)
class CoverMvPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config
        self.service_url = str(
            config.get("service_url", "http://192.168.100.1:18787")
        ).rstrip("/")
        self.timeout_seconds = max(60, int(config.get("timeout_seconds", 7200)))
        self.poll_interval_seconds = min(
            30.0, max(2.0, float(config.get("poll_interval_seconds", 5)))
        )
        self.max_music_size_mb = min(
            300, max(1, int(config.get("max_music_size_mb", 300)))
        )
        self.data_dir = Path(get_astrbot_plugin_data_path()) / PLUGIN_NAME
        self.output_dir = self.data_dir / "outputs"
        self.output_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _quoted_components(event: AstrMessageEvent) -> list[object]:
        quoted: list[object] = []
        for component in event.get_messages():
            if isinstance(component, Reply) and component.chain:
                quoted.extend(component.chain)
        return quoted

    async def _find_quoted_audio(
        self, event: AstrMessageEvent
    ) -> tuple[str, str]:
        components = self._quoted_components(event)
        if not components:
            raise ValueError("请回复/引用一条包含音乐文件的消息后再使用此命令。")

        for component in components:
            if isinstance(component, Record):
                path = await component.convert_to_file_path()
                if not path:
                    continue
                return path, Path(path).name or "quoted-record.wav"
            if isinstance(component, File):
                path = await component.get_file()
                if not path:
                    continue
                name = _file_name(component, path)
                extension = Path(name).suffix.lower() or Path(path).suffix.lower()
                if extension not in AUDIO_EXTENSIONS:
                    continue
                return path, name

        raise ValueError(
            "引用的消息中没有受支持的音乐文件；支持 MP3、WAV、M4A、FLAC、AAC、OGG、OPUS。"
        )

    def _validate_audio(self, path: str, original_name: str) -> None:
        audio = Path(path)
        if not audio.is_file():
            raise ValueError("无法读取引用的音乐文件。")
        extension = Path(original_name).suffix.lower() or audio.suffix.lower()
        if extension not in AUDIO_EXTENSIONS:
            raise ValueError(
                "音乐格式不支持；请引用 MP3、WAV、M4A、FLAC、AAC、OGG 或 OPUS。"
            )
        limit = self.max_music_size_mb * 1024 * 1024
        if audio.stat().st_size > limit:
            raise ValueError(f"音乐文件不能超过 {self.max_music_size_mb} MB。")

    @staticmethod
    async def _error_detail(response: aiohttp.ClientResponse, operation: str) -> str:
        payload = await response.text()
        try:
            decoded = json.loads(payload)
            detail = decoded.get("detail") or decoded.get("error") or payload
        except (json.JSONDecodeError, AttributeError):
            detail = payload
        return f"{operation}返回 HTTP {response.status}：{str(detail).strip() or '未知错误'}"

    async def _create_job(
        self,
        audio_path: str,
        original_name: str,
        character: str,
        original_artist: str,
        song_name: str,
    ) -> dict:
        timeout = aiohttp.ClientTimeout(total=300, connect=30, sock_read=300)
        form = aiohttp.FormData()
        form.add_field("character", character)
        form.add_field("original_artist", original_artist)
        form.add_field("song_name", song_name)
        content_type = mimetypes.guess_type(original_name)[0] or "application/octet-stream"
        handle = await asyncio.to_thread(Path(audio_path).open, "rb")
        form.add_field(
            "music",
            handle,
            filename=original_name,
            content_type=content_type,
        )
        try:
            async with aiohttp.ClientSession(timeout=timeout, trust_env=False) as session:
                async with session.post(
                    f"{self.service_url}/api/cover-mv", data=form
                ) as response:
                    if response.status != 202:
                        raise RuntimeError(await self._error_detail(response, "创建任务失败，服务"))
                    payload = await response.json(content_type=None)
        finally:
            await asyncio.to_thread(handle.close)
        if not isinstance(payload, dict) or not payload.get("id"):
            raise RuntimeError("MV 服务没有返回有效任务 ID。")
        return payload

    async def _wait_for_job(self, event: AstrMessageEvent, job_id: str) -> dict:
        timeout = aiohttp.ClientTimeout(total=30, connect=15, sock_read=30)
        deadline = asyncio.get_running_loop().time() + self.timeout_seconds
        notified_milestone = 0
        async with aiohttp.ClientSession(timeout=timeout, trust_env=False) as session:
            while True:
                if asyncio.get_running_loop().time() >= deadline:
                    raise asyncio.TimeoutError
                async with session.get(
                    f"{self.service_url}/api/jobs/{job_id}"
                ) as response:
                    if response.status != 200:
                        raise RuntimeError(await self._error_detail(response, "查询任务失败，服务"))
                    job = await response.json(content_type=None)

                status = str(job.get("status", ""))
                if status == "completed":
                    return job
                if status == "failed":
                    raise RuntimeError(str(job.get("error") or "MV 合成失败"))

                try:
                    progress = int(float(job.get("progress", 0)))
                except (TypeError, ValueError):
                    progress = 0
                milestone = min(75, progress // 25 * 25)
                if milestone > notified_milestone:
                    notified_milestone = milestone
                    message = str(job.get("message") or "正在制作")
                    await event.send(
                        event.plain_result(f"翻唱视频进度 {progress}%：{message}")
                    )
                await asyncio.sleep(self.poll_interval_seconds)

    async def _download_result(self, job_id: str) -> Path:
        output = self.output_dir / f"cover_mv_{uuid.uuid4().hex}.mp4"
        timeout = aiohttp.ClientTimeout(total=None, connect=30, sock_read=300)
        try:
            async with aiohttp.ClientSession(timeout=timeout, trust_env=False) as session:
                async with session.get(
                    f"{self.service_url}/api/jobs/{job_id}/download"
                ) as response:
                    if response.status != 200:
                        raise RuntimeError(await self._error_detail(response, "下载成片失败，服务"))
                    with output.open("wb") as target:
                        async for chunk in response.content.iter_chunked(1024 * 1024):
                            target.write(chunk)
            if not output.is_file() or output.stat().st_size == 0:
                raise RuntimeError("MV 服务返回了空视频。")
            return output
        except Exception:
            output.unlink(missing_ok=True)
            raise

    def _cleanup_outputs(self) -> None:
        retention = max(1, int(self.config.get("output_retention_hours", 24)))
        deadline = time.time() - retention * 3600
        for output in self.output_dir.glob("cover_mv_*.mp4"):
            try:
                if output.stat().st_mtime < deadline:
                    output.unlink()
            except OSError:
                continue

    @filter.command("翻唱视频")
    async def cover_mv(self, event: AstrMessageEvent, args: GreedyStr):
        """回复音乐并制作原神角色 MV：角色 原唱 原曲。"""
        try:
            character, original_artist, song_name = _parse_command_args(str(args))
            audio_path, original_name = await self._find_quoted_audio(event)
            self._validate_audio(audio_path, original_name)
        except Exception as error:
            yield event.plain_result(str(error))
            return

        await event.send(
            event.plain_result(
                f"已接收引用的音乐，开始制作 {character} 的《{song_name}》翻唱视频。"
                "系统会自动查找同步歌词并合成 1080P MV，请耐心等待。"
            )
        )
        try:
            await asyncio.to_thread(self._cleanup_outputs)
            job = await self._create_job(
                audio_path,
                original_name,
                character,
                original_artist,
                song_name,
            )
            job_id = str(job["id"])
            await event.send(event.plain_result(f"MV 任务已创建：{job_id}"))
            completed = await self._wait_for_job(event, job_id)
            output = await self._download_result(job_id)

            subtitle_message = "已烧录同步歌词" if completed.get("has_subtitles") else "未找到可靠同步歌词，成片无字幕"
            summary = f"翻唱视频制作完成：{character}《{song_name}》（{original_artist} 原唱），{subtitle_message}。"
            if bool(self.config.get("send_as_file", False)):
                filename = (
                    f"{_safe_filename_part(character, '角色')}-"
                    f"{_safe_filename_part(song_name, '翻唱')}-MV.mp4"
                )
                yield event.chain_result(
                    [Plain(summary), File(name=filename, file=str(output))]
                )
            else:
                yield event.chain_result([Plain(summary), Video.fromFileSystem(output)])
        except asyncio.TimeoutError:
            yield event.plain_result(
                f"翻唱视频制作超时（{self.timeout_seconds} 秒），请检查 MV 服务任务状态。"
            )
        except aiohttp.ClientError as error:
            yield event.plain_result(
                f"无法连接 MV 服务 {self.service_url}：{error}"
            )
        except Exception as error:
            yield event.plain_result(f"翻唱视频制作失败：{error}")
