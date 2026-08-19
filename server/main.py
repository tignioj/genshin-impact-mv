from __future__ import annotations

import json
import math
import os
import re
import shutil
import subprocess
import threading
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")
WORK_DIR = ROOT / "work"
OUTPUT_DIR = ROOT / "outputs"
WIKI_URL = os.environ.get("GI_WIKI_URL", "http://127.0.0.1:8765").rstrip("/")
LYRICS_AGENT_DIR = Path(
    os.environ.get("LYRICS_AGENT_PATH", ROOT.parent / "sing-song" / "lyrics-fetch-agent")
).resolve()
try:
    LYRICS_AGENT_TIMEOUT_SECONDS = float(os.environ.get("LYRICS_AGENT_TIMEOUT", "240"))
except ValueError:
    LYRICS_AGENT_TIMEOUT_SECONDS = 240.0
if LYRICS_AGENT_TIMEOUT_SECONDS <= 0:
    LYRICS_AGENT_TIMEOUT_SECONDS = 240.0
MAX_DURATION_SECONDS = 600.0
MAX_MUSIC_BYTES = 300 * 1024 * 1024
MAX_SUBTITLE_BYTES = 5 * 1024 * 1024
MUSIC_EXTENSIONS = {".mp3", ".wav", ".m4a", ".flac", ".aac", ".ogg", ".opus"}
SUBTITLE_EXTENSIONS = {".srt", ".lrc"}
VIDEO_EXTENSIONS = {".mp4", ".webm", ".mkv", ".mov"}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}
SOURCE_TYPES = ("EP 视频", "角色预告", "角色 PV", "角色演示", "生日贺图")

WORK_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(
    title="映界 · 原神 MV 合成 API",
    version="1.1.0",
    description="使用 GI Wiki 角色素材、用户音乐和自动获取的同步歌词生成 1080P 翻唱 MV。",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

JOBS: dict[str, dict[str, Any]] = {}
JOBS_LOCK = threading.RLock()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def public_job(job: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "id", "status", "progress", "message", "character", "source_type",
        "source_title", "duration", "original_artist", "song_name", "lyric_offset_seconds", "has_subtitles",
        "subtitle_source", "lyrics_status", "lyrics_message", "lyrics_sources",
        "preview_url", "download_url", "error", "created_at", "updated_at",
    )
    return {key: job[key] for key in keys if key in job}


def update_job(job_id: str, **changes: Any) -> None:
    with JOBS_LOCK:
        job = JOBS[job_id]
        job.update(changes)
        job["updated_at"] = utc_now()
        snapshot = public_job(job)
        job_dir = Path(job["job_dir"])
    try:
        (job_dir / "job.json").write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass


def wiki_json(path: str) -> dict[str, Any]:
    url = f"{WIKI_URL}{path}"
    try:
        with urllib.request.urlopen(url, timeout=12) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise HTTPException(404, "GI Wiki 中未找到该角色") from exc
        raise HTTPException(502, f"GI Wiki 返回错误：HTTP {exc.code}") from exc
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise HTTPException(503, "无法连接 GI Wiki，请先启动 gi-wiki/app.py") from exc


def character_record(name: str) -> dict[str, Any]:
    clean_name = name.strip()
    if not clean_name or len(clean_name) > 40:
        raise HTTPException(400, "角色名称无效")
    return wiki_json(f"/api/characters/{urllib.parse.quote(clean_name)}")


def video_rank(video: dict[str, Any]) -> tuple[int, str] | None:
    title = str(video.get("title", ""))
    category = re.sub(r"[\s_-]", "", str(video.get("category", ""))).upper()
    normalized = title.upper().replace("－", "-")

    # Wiki metadata already provides an authoritative category. Prefer it to
    # title heuristics because many official titles join the character name
    # directly to "EP", for example "珊瑚宫心海EP".
    if category in {"角色EP", "EP"}:
        return 0, "EP 视频"
    if category == "角色预告":
        return 1, "角色预告"
    if category == "角色PV":
        return 2, "角色 PV"
    if category == "角色演示":
        return 3, "角色演示"

    compact_title = re.sub(r"\s", "", normalized)
    if re.search(r"EP(?=$|[-—_《》「])", compact_title):
        return 0, "EP 视频"
    if "角色预告" in title:
        return 1, "角色预告"
    if "角色PV" in compact_title:
        return 2, "角色 PV"
    if "角色演示" in title:
        return 3, "角色演示"
    return None


def choose_source(record: dict[str, Any], source_type: str | None = None) -> dict[str, Any]:
    if source_type is not None and source_type not in SOURCE_TYPES:
        raise HTTPException(400, f"画面素材类型无效，可选：{'、'.join(SOURCE_TYPES)}")

    ranked: list[tuple[int, str, dict[str, Any]]] = []
    for video in record.get("videos", []):
        if not isinstance(video, dict) or not video.get("url"):
            continue
        rank = video_rank(video)
        if rank:
            ranked.append((rank[0], rank[1], video))
    if source_type and source_type != "生日贺图":
        ranked = [item for item in ranked if item[1] == source_type]

    if ranked and source_type != "生日贺图":
        _, label, video = min(ranked, key=lambda item: (item[0], str(item[2].get("title", ""))))
        return {
            "kind": "video",
            "type": label,
            "title": video.get("title") or label,
            "urls": [video["url"]],
        }

    birthday_images = record.get("images", {}).get("生日贺图", [])
    urls = [item.get("url") for item in birthday_images if isinstance(item, dict) and item.get("url")]
    if urls and source_type in (None, "生日贺图"):
        return {
            "kind": "images",
            "type": "生日贺图",
            "title": f"{record.get('name', '')}生日贺图（{len(urls)} 张）",
            "urls": urls,
        }
    if source_type:
        raise HTTPException(422, f"该角色没有可用的{source_type}素材")
    raise HTTPException(422, "该角色没有可用的 EP、预告、PV、演示或生日贺图")


def asset_absolute_url(url: str) -> str:
    if url.startswith("http://") or url.startswith("https://"):
        return url
    return f"{WIKI_URL}/{url.lstrip('/')}"


def download_asset(url: str, destination: Path) -> None:
    request = urllib.request.Request(asset_absolute_url(url), headers={"User-Agent": "YingJieMV/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=60) as response, destination.open("wb") as output:
            shutil.copyfileobj(response, output, length=1024 * 1024)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise RuntimeError(f"下载 Wiki 素材失败：{url}") from exc


def ffprobe_duration(path: Path) -> float:
    command = [
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", str(path),
    ]
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=30, check=True)
        duration = float(result.stdout.strip())
    except (FileNotFoundError, subprocess.SubprocessError, ValueError) as exc:
        raise HTTPException(400, "无法读取音乐时长，请确认文件格式有效且已安装 FFmpeg") from exc
    if duration <= 0:
        raise HTTPException(400, "音乐文件没有有效时长")
    if duration > MAX_DURATION_SECONDS + 0.05:
        raise HTTPException(400, "音乐长度不能超过 10 分钟")
    return duration


def decode_text(payload: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-16", "gb18030"):
        try:
            return payload.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise HTTPException(400, "字幕编码无法识别，请使用 UTF-8、UTF-16 或 GB18030")


def srt_timestamp(seconds: float) -> str:
    millis = max(0, round(seconds * 1000))
    hours, rest = divmod(millis, 3_600_000)
    minutes, rest = divmod(rest, 60_000)
    secs, ms = divmod(rest, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{ms:03d}"


def lrc_to_srt(text: str, duration: float, offset_seconds: float = 0.0) -> str:
    timestamps = re.compile(r"\[(\d{1,3}):(\d{2})(?:[.:](\d{1,3}))?\]")
    rows: list[tuple[float, str, float | None]] = []

    def match_seconds(match: re.Match[str]) -> float:
        fraction = match.group(3) or "0"
        return (
            int(match.group(1)) * 60
            + int(match.group(2))
            + int(fraction) / (10 ** len(fraction))
        )

    for line in text.splitlines():
        matches = list(timestamps.finditer(line))
        if not matches:
            continue
        lyric = timestamps.sub("", line).strip()
        if not lyric:
            continue

        # Enhanced LRC places timestamps between characters or words, for
        # example: [00:13.11]风[00:13.44]捎...[00:17.26].  Treating every
        # timestamp as the beginning of the complete line creates dozens of
        # overlapping identical SRT cues.  Collapse such a line into one cue;
        # a trailing timestamp is the authoritative end of that line.
        has_interleaved_lyric = any(
            line[matches[index].end():matches[index + 1].start()].strip()
            for index in range(len(matches) - 1)
        )
        if has_interleaved_lyric:
            start = match_seconds(matches[0])
            trailing_timestamp = not line[matches[-1].end():].strip()
            explicit_end = match_seconds(matches[-1]) if trailing_timestamp else None
            if explicit_end is not None and explicit_end <= start:
                explicit_end = None
            rows.append((start, lyric, explicit_end))
            continue

        # Standard LRC may put several timestamps at the beginning to reuse a
        # lyric line in multiple sections. Preserve that established meaning.
        for match in matches:
            start = match_seconds(match)
            rows.append((start, lyric, None))

    rows.sort(key=lambda row: row[0])
    if not rows:
        raise HTTPException(400, "LRC 字幕中没有可识别的时间标签")
    blocks = []
    for index, (original_start, lyric, explicit_end) in enumerate(rows):
        next_start = rows[index + 1][0] if index + 1 < len(rows) else duration
        if explicit_end is not None:
            original_end = min(explicit_end, next_start)
        else:
            original_end = min(next_start, original_start + 8.0)
        if original_end <= original_start:
            original_end = original_start + 0.8

        shifted_start = original_start + offset_seconds
        shifted_end = original_end + offset_seconds
        start = max(0.0, shifted_start)
        end = min(duration, shifted_end)
        if shifted_start >= duration or shifted_end <= 0 or end <= start:
            continue
        blocks.append(f"{len(blocks) + 1}\n{srt_timestamp(start)} --> {srt_timestamp(end)}\n{lyric}\n")
    if not blocks:
        raise HTTPException(400, "歌词偏移后没有位于音乐时长内的字幕")
    return "\n".join(blocks)


def prepare_subtitle(
    payload: bytes,
    extension: str,
    duration: float,
    destination: Path,
    offset_seconds: float = 0.0,
) -> None:
    text = decode_text(payload).replace("\r\n", "\n").replace("\r", "\n")
    if extension == ".lrc":
        text = lrc_to_srt(text, duration, offset_seconds)
    elif "-->" not in text:
        raise HTTPException(400, "SRT 字幕缺少有效时间轴")
    destination.write_text(text, encoding="utf-8")


def lyrics_agent_command() -> list[str] | None:
    """Return a command that runs the adjacent lyrics-fetch-agent project."""
    candidates = (
        LYRICS_AGENT_DIR / ".venv" / "Scripts" / "lyrics-agent.exe",
        LYRICS_AGENT_DIR / ".venv" / "bin" / "lyrics-agent",
    )
    executable = next((path for path in candidates if path.is_file()), None)
    if executable:
        return [str(executable)]
    uv = shutil.which("uv")
    if uv and (LYRICS_AGENT_DIR / "pyproject.toml").is_file():
        return [uv, "run", "--project", str(LYRICS_AGENT_DIR), "lyrics-agent"]
    return None


def fetch_timed_lyrics(original_artist: str, song_name: str) -> dict[str, Any]:
    command = lyrics_agent_command()
    if not command:
        raise RuntimeError(f"未找到 lyrics-fetch-agent：{LYRICS_AGENT_DIR}")
    result = subprocess.run(
        [
            *command,
            "--artist", original_artist,
            "--song", song_name,
            "--timed",
            "--quiet",
        ],
        cwd=LYRICS_AGENT_DIR,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=LYRICS_AGENT_TIMEOUT_SECONDS,
        check=False,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
    )
    if result.returncode != 0:
        detail = result.stderr.strip().splitlines()
        raise RuntimeError(detail[-1][:300] if detail else "lyrics-fetch-agent 执行失败")
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("lyrics-fetch-agent 未返回有效 JSON") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("lyrics-fetch-agent 返回结果格式无效")
    return payload


def prepare_auto_subtitle(job_id: str, job: dict[str, Any], destination: Path) -> bool:
    """Fetch verified LRC lyrics; any failure is a subtitle miss, not a job failure."""
    update_job(job_id, progress=2, message="正在搜索原曲同步歌词", lyrics_status="searching")
    try:
        result = fetch_timed_lyrics(job["original_artist"], job["song_name"])
        (destination.parent / "lyrics-result.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except subprocess.TimeoutExpired:
        update_job(
            job_id,
            has_subtitles=False,
            subtitle_source="none",
            lyrics_status="error",
            lyrics_message="同步歌词搜索超时，将生成无字幕 MV",
        )
        return False
    except (OSError, RuntimeError) as exc:
        update_job(
            job_id,
            has_subtitles=False,
            subtitle_source="none",
            lyrics_status="error",
            lyrics_message=f"{str(exc)[:240]}；将生成无字幕 MV",
        )
        return False

    lyrics = result.get("lyrics")
    if not result.get("found") or not result.get("timed") or not isinstance(lyrics, str):
        reason = str(result.get("message") or "未找到可靠的同步歌词")
        update_job(
            job_id,
            has_subtitles=False,
            subtitle_source="none",
            lyrics_status="not_found",
            lyrics_message=f"{reason[:240]}；将生成无字幕 MV",
            lyrics_sources=result.get("sources", []),
        )
        return False

    try:
        prepare_subtitle(
            lyrics.encode("utf-8"),
            ".lrc",
            float(job["duration"]),
            destination,
            float(job.get("lyric_offset_seconds", 0.0)),
        )
    except HTTPException as exc:
        update_job(
            job_id,
            has_subtitles=False,
            subtitle_source="none",
            lyrics_status="invalid",
            lyrics_message=f"同步歌词时间轴无效：{exc.detail}；将生成无字幕 MV",
            lyrics_sources=result.get("sources", []),
        )
        return False

    update_job(
        job_id,
        has_subtitles=True,
        subtitle_source="lyrics_agent",
        lyrics_status="found",
        lyrics_message="已获取同步歌词，成片将烧录字幕",
        lyrics_sources=result.get("sources", []),
    )
    return True


async def save_upload(upload: UploadFile, destination: Path, byte_limit: int) -> int:
    total = 0
    try:
        with destination.open("wb") as output:
            while chunk := await upload.read(1024 * 1024):
                total += len(chunk)
                if total > byte_limit:
                    raise HTTPException(413, "上传文件过大")
                output.write(chunk)
    except HTTPException:
        destination.unlink(missing_ok=True)
        raise
    finally:
        await upload.close()
    if total == 0:
        destination.unlink(missing_ok=True)
        raise HTTPException(400, "上传文件为空")
    return total


def ffmpeg_subtitle_filter() -> str:
    style = (
        "FontName=Microsoft YaHei,FontSize=20,PrimaryColour=&H00FFFFFF,"
        "OutlineColour=&H9A0A1214,BorderStyle=1,Outline=2,Shadow=0,"
        "Alignment=2,MarginV=54"
    )
    return f"subtitles=subtitle.srt:force_style='{style}'"


def run_ffmpeg(job_id: str, command: list[str], duration: float, cwd: Path) -> None:
    process = subprocess.Popen(
        command,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    log_lines: list[str] = []
    assert process.stdout is not None
    for raw_line in process.stdout:
        line = raw_line.strip()
        log_lines.append(line)
        if line.startswith("out_time_ms="):
            try:
                elapsed = int(line.split("=", 1)[1]) / 1_000_000
                progress = min(96.0, 32.0 + (elapsed / duration) * 64.0)
                update_job(job_id, progress=round(progress, 1), message="正在编码画面、字幕与音乐")
            except ValueError:
                pass
    return_code = process.wait()
    (cwd / "ffmpeg.log").write_text("\n".join(log_lines[-300:]), encoding="utf-8")
    if return_code != 0:
        useful = next((line for line in reversed(log_lines) if line), "FFmpeg 未返回详细错误")
        raise RuntimeError(f"视频编码失败：{useful[:300]}")


def create_slides_file(image_names: list[str], duration: float, destination: Path) -> None:
    per_image = max(0.25, duration / len(image_names))
    lines: list[str] = []
    for name in image_names:
        lines.append(f"file '{name}'")
        lines.append(f"duration {per_image:.6f}")
    lines.append(f"file '{image_names[-1]}'")
    destination.write_text("\n".join(lines), encoding="utf-8")


def process_job(job_id: str) -> None:
    with JOBS_LOCK:
        job = JOBS[job_id].copy()
    job_dir = Path(job["job_dir"])
    duration = float(job["duration"])
    try:
        if not job.get("has_subtitles") and job.get("original_artist") and job.get("song_name"):
            job["has_subtitles"] = prepare_auto_subtitle(
                job_id, job, job_dir / "subtitle.srt"
            )
        update_job(job_id, status="processing", progress=5, message="正在请求角色 Wiki 素材")
        record = character_record(job["character"])
        source = choose_source(record, job.get("requested_source_type"))
        update_job(
            job_id,
            progress=14,
            message="正在获取最佳画面素材",
            source_type=source["type"],
            source_title=source["title"],
        )

        music_name = job["music_name"]
        output_path = OUTPUT_DIR / f"{job_id}-{job['character']}-MV.mp4"
        common_output = [
            "-map", "0:v:0", "-map", "1:a:0", "-t", f"{duration:.6f}",
            "-c:v", "libx264", "-preset", "medium", "-crf", "20",
            "-c:a", "aac", "-b:a", "256k", "-ar", "48000",
            "-pix_fmt", "yuv420p", "-movflags", "+faststart",
            "-progress", "pipe:1", "-nostats", "-y", str(output_path),
        ]
        render_filters = [
            "scale=1920:1080:force_original_aspect_ratio=increase",
            "crop=1920:1080",
            "fps=30",
        ]
        if job.get("has_subtitles"):
            render_filters.append(ffmpeg_subtitle_filter())
        render_filter = ",".join(render_filters)

        if source["kind"] == "video":
            parsed_path = urllib.parse.urlparse(source["urls"][0]).path
            suffix = Path(urllib.parse.unquote(parsed_path)).suffix.lower()
            suffix = suffix if suffix in VIDEO_EXTENSIONS else ".mp4"
            source_name = f"source{suffix}"
            download_asset(source["urls"][0], job_dir / source_name)
            update_job(job_id, progress=30, message="正在合成视频与音乐")
            command = [
                "ffmpeg", "-hide_banner", "-loglevel", "warning",
                "-stream_loop", "-1", "-i", source_name, "-i", music_name,
                "-vf", render_filter,
            ] + common_output
        else:
            image_names: list[str] = []
            for index, url in enumerate(source["urls"]):
                parsed_path = urllib.parse.urlparse(url).path
                suffix = Path(urllib.parse.unquote(parsed_path)).suffix.lower()
                suffix = suffix if suffix in IMAGE_EXTENSIONS else ".jpg"
                image_name = f"birthday-{index:02d}{suffix}"
                download_asset(url, job_dir / image_name)
                image_names.append(image_name)
                update_job(
                    job_id,
                    progress=14 + round(((index + 1) / len(source["urls"])) * 15, 1),
                    message=f"正在获取生日贺图 {index + 1}/{len(source['urls'])}",
                )
            create_slides_file(image_names, duration, job_dir / "slides.txt")
            update_job(job_id, progress=30, message="正在制作生日贺图轮播")
            command = [
                "ffmpeg", "-hide_banner", "-loglevel", "warning",
                "-f", "concat", "-safe", "0", "-i", "slides.txt", "-i", music_name,
                "-vf", render_filter,
            ] + common_output

        run_ffmpeg(job_id, command, duration, job_dir)
        update_job(
            job_id,
            status="completed",
            progress=100,
            message="成片已就绪",
            preview_url=f"/api/jobs/{job_id}/preview",
            download_url=f"/api/jobs/{job_id}/download",
            output_path=str(output_path),
        )
    except HTTPException as exc:
        update_job(job_id, status="failed", progress=0, message="合成未完成", error=str(exc.detail))
    except Exception as exc:  # Keep background failures visible through job status.
        update_job(job_id, status="failed", progress=0, message="合成未完成", error=str(exc))


@app.get("/")
def api_index() -> dict[str, Any]:
    return {
        "name": "映界 · 原神 MV 合成 API",
        "docs": "/docs",
        "health": "/api/health",
        "cover_mv": "/api/cover-mv",
        "max_duration_seconds": int(MAX_DURATION_SECONDS),
        "source_priority": ["EP 视频", "角色预告", "角色 PV", "角色演示", "生日贺图"],
    }


@app.get("/api/health")
def health() -> dict[str, Any]:
    wiki_ok = False
    wiki_characters = 0
    try:
        payload = wiki_json("/api/health")
        wiki_ok = payload.get("status") == "ok"
        wiki_characters = int(payload.get("characters", 0))
    except HTTPException:
        pass
    return {
        "status": "ok" if wiki_ok else "degraded",
        "wiki": "connected" if wiki_ok else "unavailable",
        "wiki_characters": wiki_characters,
        "ffmpeg": shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None,
        "lyrics_agent": lyrics_agent_command() is not None,
    }


@app.get("/api/characters")
def characters(q: str = "", limit: int = 20) -> dict[str, Any]:
    safe_limit = min(max(limit, 1), 100)
    return wiki_json(f"/api/characters?q={urllib.parse.quote(q)}&limit={safe_limit}")


@app.get("/api/characters/{name}/source")
def character_source(name: str, source_type: str | None = None) -> dict[str, Any]:
    record = character_record(name)
    clean_source_type = (source_type or "").strip() or None
    return {"character": record.get("name", name), **choose_source(record, clean_source_type)}


async def create_mv_job(
    character: str = Form(...),
    music: UploadFile = File(...),
    original_artist: str | None = Form(None),
    song_name: str | None = Form(None),
    lyric_offset_seconds: float = Form(0.0),
    subtitles: UploadFile | None = File(None),
    source_type: str | None = Form(None),
) -> dict[str, Any]:
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        raise HTTPException(503, "未找到 FFmpeg，请先安装并加入 PATH")

    music_extension = Path(music.filename or "").suffix.lower()
    has_subtitles = bool(subtitles and subtitles.filename)
    subtitle_extension = Path(subtitles.filename or "").suffix.lower() if has_subtitles and subtitles else ""
    if music_extension not in MUSIC_EXTENSIONS:
        raise HTTPException(400, "音乐格式不支持，请上传 MP3、WAV、M4A、FLAC、AAC、OGG 或 OPUS")
    if has_subtitles and subtitle_extension not in SUBTITLE_EXTENSIONS:
        raise HTTPException(400, "字幕格式不支持，请上传 SRT 或 LRC")

    clean_artist = (original_artist or "").strip()
    clean_song_name = (song_name or "").strip()
    if bool(clean_artist) != bool(clean_song_name):
        raise HTTPException(400, "原唱歌手和歌曲名称必须同时填写")
    if len(clean_artist) > 160 or len(clean_song_name) > 160:
        raise HTTPException(400, "原唱歌手或歌曲名称过长")
    if not math.isfinite(lyric_offset_seconds) or abs(lyric_offset_seconds) > MAX_DURATION_SECONDS:
        raise HTTPException(400, "歌词偏移秒数必须在 -600 到 +600 之间")

    clean_source_type = (source_type or "").strip() or None
    record = character_record(character)
    source = choose_source(record, clean_source_type)

    job_id = uuid.uuid4().hex[:16]
    job_dir = WORK_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=False)
    music_name = f"music{music_extension}"
    music_path = job_dir / music_name
    await save_upload(music, music_path, MAX_MUSIC_BYTES)
    duration = ffprobe_duration(music_path)
    if has_subtitles and subtitles:
        subtitle_payload = await subtitles.read(MAX_SUBTITLE_BYTES + 1)
        await subtitles.close()
        if len(subtitle_payload) > MAX_SUBTITLE_BYTES:
            shutil.rmtree(job_dir, ignore_errors=True)
            raise HTTPException(413, "字幕文件不能超过 5 MB")
        try:
            prepare_subtitle(
                subtitle_payload,
                subtitle_extension,
                duration,
                job_dir / "subtitle.srt",
                lyric_offset_seconds,
            )
        except HTTPException:
            shutil.rmtree(job_dir, ignore_errors=True)
            raise

    job = {
        "id": job_id,
        "status": "queued",
        "progress": 0,
        "message": "任务已进入队列",
        "character": record.get("name", character.strip()),
        "source_type": source["type"],
        "source_title": source["title"],
        "duration": round(duration, 3),
        "original_artist": clean_artist or None,
        "song_name": clean_song_name or None,
        "lyric_offset_seconds": lyric_offset_seconds,
        "has_subtitles": has_subtitles,
        "subtitle_source": "upload" if has_subtitles else "pending" if clean_artist else "none",
        "lyrics_status": "manual" if has_subtitles else "pending" if clean_artist else "not_requested",
        "lyrics_message": "使用上传的字幕文件" if has_subtitles else None,
        "created_at": utc_now(),
        "updated_at": utc_now(),
        "job_dir": str(job_dir),
        "music_name": music_name,
        "requested_source_type": clean_source_type,
    }
    with JOBS_LOCK:
        JOBS[job_id] = job
    update_job(job_id)
    threading.Thread(target=process_job, args=(job_id,), daemon=True, name=f"mv-{job_id}").start()
    return public_job(job)


@app.post("/api/mv", status_code=202)
async def create_mv(
    character: str = Form(...),
    music: UploadFile = File(...),
    original_artist: str | None = Form(None),
    song_name: str | None = Form(None),
    lyric_offset_seconds: float = Form(0.0),
    subtitles: UploadFile | None = File(None),
    source_type: str | None = Form(None),
) -> dict[str, Any]:
    """Backward-compatible MV endpoint; artist/song enable automatic subtitles."""
    return await create_mv_job(
        character, music, original_artist, song_name, lyric_offset_seconds, subtitles, source_type
    )


@app.post("/api/cover-mv", status_code=202)
async def create_cover_mv(
    character: str = Form(...),
    music: UploadFile = File(...),
    original_artist: str = Form(...),
    song_name: str = Form(...),
    lyric_offset_seconds: float = Form(0.0),
    subtitles: UploadFile | None = File(None),
    source_type: str | None = Form(None),
) -> dict[str, Any]:
    """Create a cover MV and automatically fetch verified synchronized lyrics."""
    if not original_artist.strip() or not song_name.strip():
        raise HTTPException(400, "原唱歌手和歌曲名称不能为空")
    return await create_mv_job(
        character, music, original_artist, song_name, lyric_offset_seconds, subtitles, source_type
    )


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str) -> dict[str, Any]:
    with JOBS_LOCK:
        job = JOBS.get(job_id)
        if not job:
            raise HTTPException(404, "任务不存在或服务已重启")
        return public_job(job)


def completed_output(job_id: str) -> tuple[Path, str]:
    with JOBS_LOCK:
        job = JOBS.get(job_id)
        if not job:
            raise HTTPException(404, "任务不存在或服务已重启")
        if job.get("status") != "completed" or not job.get("output_path"):
            raise HTTPException(409, "成片尚未完成")
        output_path = Path(job["output_path"])
        character = job["character"]
    if not output_path.is_file():
        raise HTTPException(404, "成片文件不存在")
    return output_path, character


@app.get("/api/jobs/{job_id}/preview")
def preview_job(job_id: str) -> FileResponse:
    output_path, _ = completed_output(job_id)
    return FileResponse(
        output_path,
        media_type="video/mp4",
        headers={"Content-Disposition": "inline", "Cache-Control": "private, max-age=3600"},
    )


@app.get("/api/jobs/{job_id}/download")
def download_job(job_id: str) -> FileResponse:
    output_path, character = completed_output(job_id)
    return FileResponse(output_path, media_type="video/mp4", filename=f"{character}-MV.mp4")
