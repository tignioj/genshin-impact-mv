"use client";

/* Wiki assets come from a configurable local origin, so native images are intentional. */
/* eslint-disable @next/next/no-img-element */
/* Generated MV subtitles are burned into the video frames. */
/* eslint-disable jsx-a11y/media-has-caption */

import { ChangeEvent, FormEvent, useEffect, useMemo, useRef, useState } from "react";

type Character = {
  id: string;
  name: string;
  title?: string;
  element?: string;
  portrait?: string | null;
  video_count?: number;
};

type Job = {
  id: string;
  status: "queued" | "processing" | "completed" | "failed";
  progress: number;
  message: string;
  character: string;
  source_type?: string;
  source_title?: string;
  duration?: number;
  original_artist?: string;
  song_name?: string;
  lyric_offset_seconds?: number;
  has_subtitles?: boolean;
  lyrics_status?: "pending" | "searching" | "found" | "not_found" | "invalid" | "error" | "manual";
  lyrics_message?: string;
  preview_url?: string;
  download_url?: string;
  error?: string;
};

type SourcePreview = {
  character: string;
  kind: "video" | "images";
  type: string;
  title: string;
  urls: string[];
};

const SOURCE_TYPES = ["EP 视频", "角色预告", "角色 PV", "角色演示", "生日贺图"] as const;
type SourceType = typeof SOURCE_TYPES[number];

const API_ROOT = process.env.NEXT_PUBLIC_MV_API_URL || "http://127.0.0.1:8787";
const WIKI_ROOT = process.env.NEXT_PUBLIC_GI_WIKI_URL || "http://127.0.0.1:8765";

function assetUrl(url?: string | null) {
  if (!url) return "";
  if (/^https?:\/\//.test(url)) return url;
  return `${WIKI_ROOT}${url}`;
}

function formatSize(size: number) {
  if (size < 1024 * 1024) return `${Math.max(1, Math.round(size / 1024))} KB`;
  return `${(size / 1024 / 1024).toFixed(1)} MB`;
}

function formatLyricOffset(seconds: number) {
  const value = String(Number(seconds.toFixed(3)));
  if (seconds > 0) return `+${value} 秒（延后）`;
  if (seconds < 0) return `${value} 秒（提前）`;
  return "0 秒（不偏移）";
}

function FileDrop({
  kind,
  title,
  description,
  accept,
  file,
  onChange,
}: {
  kind: "music" | "subtitle";
  title: string;
  description: string;
  accept: string;
  file: File | null;
  onChange: (file: File | null) => void;
}) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);

  const pick = (event: ChangeEvent<HTMLInputElement>) => {
    onChange(event.target.files?.[0] || null);
  };

  return (
    <button
      className={`drop-zone ${dragging ? "is-dragging" : ""} ${file ? "has-file" : ""}`}
      type="button"
      onClick={() => inputRef.current?.click()}
      onDragOver={(event) => {
        event.preventDefault();
        setDragging(true);
      }}
      onDragLeave={() => setDragging(false)}
      onDrop={(event) => {
        event.preventDefault();
        setDragging(false);
        onChange(event.dataTransfer.files?.[0] || null);
      }}
    >
      <input ref={inputRef} hidden type="file" accept={accept} onChange={pick} />
      <span className={`file-glyph ${kind}`}>{kind === "music" ? "♫" : "字"}</span>
      <span className="drop-copy">
        <strong>{file ? file.name : title}</strong>
        <small>{file ? formatSize(file.size) : description}</small>
      </span>
      <span className="file-action">{file ? "更换" : "选择"}</span>
    </button>
  );
}

export default function Home() {
  const [query, setQuery] = useState("");
  const [characters, setCharacters] = useState<Character[]>([]);
  const [selected, setSelected] = useState<Character | null>(null);
  const [music, setMusic] = useState<File | null>(null);
  const [subtitle, setSubtitle] = useState<File | null>(null);
  const [originalArtist, setOriginalArtist] = useState("");
  const [songName, setSongName] = useState("");
  const [lyricOffsetSeconds, setLyricOffsetSeconds] = useState(0);
  const [sourceType, setSourceType] = useState<SourceType | "">("");
  const [sourcePreview, setSourcePreview] = useState<SourcePreview | null>(null);
  const [sourcePreviewError, setSourcePreviewError] = useState("");
  const [loadingSourcePreview, setLoadingSourcePreview] = useState(false);
  const [previewImageIndex, setPreviewImageIndex] = useState(0);
  const [job, setJob] = useState<Job | null>(null);
  const [loadingCharacters, setLoadingCharacters] = useState(false);
  const [error, setError] = useState("");

  const resetSourcePreview = (loading: boolean) => {
    setSourcePreview(null);
    setSourcePreviewError("");
    setPreviewImageIndex(0);
    setLoadingSourcePreview(loading);
  };

  useEffect(() => {
    if (selected && query === selected.name) return;
    const controller = new AbortController();
    const timer = window.setTimeout(async () => {
      setLoadingCharacters(true);
      try {
        const response = await fetch(`${API_ROOT}/api/characters?q=${encodeURIComponent(query)}&limit=8`, {
          signal: controller.signal,
        });
        if (!response.ok) throw new Error("角色资料服务暂不可用");
        const data = await response.json();
        setCharacters(data.items || []);
      } catch (reason) {
        if ((reason as Error).name !== "AbortError") setCharacters([]);
      } finally {
        setLoadingCharacters(false);
      }
    }, 220);
    return () => {
      controller.abort();
      window.clearTimeout(timer);
    };
  }, [query, selected]);

  useEffect(() => {
    if (!selected) return;

    const controller = new AbortController();
    const params = sourceType ? `?source_type=${encodeURIComponent(sourceType)}` : "";
    void (async () => {
      try {
        const response = await fetch(
          `${API_ROOT}/api/characters/${encodeURIComponent(selected.name)}/source${params}`,
          { signal: controller.signal },
        );
        const data = await response.json();
        if (!response.ok) throw new Error(data.detail || "无法加载该类型素材");
        setSourcePreview(data);
      } catch (reason) {
        if ((reason as Error).name !== "AbortError") {
          setSourcePreviewError(reason instanceof Error ? reason.message : "无法加载该类型素材");
        }
      } finally {
        if (!controller.signal.aborted) setLoadingSourcePreview(false);
      }
    })();
    return () => controller.abort();
  }, [selected, sourceType]);

  useEffect(() => {
    if (!job || !["queued", "processing"].includes(job.status)) return;
    const timer = window.setInterval(async () => {
      try {
        const response = await fetch(`${API_ROOT}/api/jobs/${job.id}`);
        if (response.ok) setJob(await response.json());
      } catch {
        // Keep the last known state; the next poll may recover.
      }
    }, 1200);
    return () => window.clearInterval(timer);
  }, [job]);

  const ready = Boolean(
    selected && music && originalArtist.trim() && songName.trim()
    && (!job || !["queued", "processing"].includes(job.status)),
  );
  const showSuggestions = query.length > 0 && query !== selected?.name;
  const progress = job?.progress || 0;
  const statusLabel = useMemo(() => {
    if (!job) return "等待创建";
    if (job.status === "completed") return "成片已就绪";
    if (job.status === "failed") return "合成未完成";
    return job.message || "正在处理";
  }, [job]);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!selected || !music) return;
    setError("");
    setJob(null);
    const form = new FormData();
    form.append("character", selected.name);
    form.append("music", music);
    form.append("original_artist", originalArtist.trim());
    form.append("song_name", songName.trim());
    form.append("lyric_offset_seconds", String(lyricOffsetSeconds));
    if (sourceType) form.append("source_type", sourceType);
    if (subtitle) form.append("subtitles", subtitle);
    try {
      const response = await fetch(`${API_ROOT}/api/cover-mv`, { method: "POST", body: form });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || data.error || "创建任务失败");
      setJob(data);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "创建任务失败");
    }
  };

  return (
    <main>
      <div className="ambient ambient-one" />
      <div className="ambient ambient-two" />

      <header className="site-header">
        <a className="brand" href="#top" aria-label="原神 MV 工坊首页">
          <span className="brand-mark"><i>原</i></span>
          <span><strong>映界</strong><small>GENSHIN MV STUDIO</small></span>
        </a>
        <div className="header-note"><span /> 本地创作模式</div>
      </header>

      <section className="hero" id="top">
        <div className="eyebrow"><span>✦</span> 一首歌，一段属于角色的旅程</div>
        <h1>让旋律驶入<br /><em>提瓦特的画面</em></h1>
        <p>选择角色并上传翻唱音乐。系统会自动寻找原曲同步歌词，画面素材既可自动择优，也可手动指定类型。</p>
        <div className="priority-line" aria-label="素材选择优先级">
          <span>EP 视频</span><b>›</b><span>角色预告</span><b>›</b><span>角色 PV</span><b>›</b><span>角色演示</span><b>›</b><span>生日贺图</span>
        </div>
      </section>

      <form className="studio" onSubmit={submit}>
        <section className="form-panel">
          <div className="section-heading">
            <span className="step-number">01</span>
            <div><h2>选择主角</h2><p>输入角色名，从本地 Wiki 素材库中查找</p></div>
          </div>

          <div className="character-picker">
            <span className="search-icon">⌕</span>
            <input
              value={query}
              placeholder="例如：优菈、雷电将军、芙宁娜"
              aria-label="原神角色名称"
              autoComplete="off"
              onChange={(event) => {
                setQuery(event.target.value);
                setSelected(null);
                resetSourcePreview(false);
              }}
            />
            {loadingCharacters && <span className="tiny-loader" />}
            {showSuggestions && (
              <div className="suggestions">
                {characters.length ? characters.map((character) => (
                  <button key={character.id} type="button" onClick={() => {
                    setSelected(character);
                    setQuery(character.name);
                    setCharacters([]);
                    resetSourcePreview(true);
                  }}>
                    <span className="avatar-mini">
                      {character.portrait ? <img src={assetUrl(character.portrait)} alt="" /> : character.name.slice(0, 1)}
                    </span>
                    <span><strong>{character.name}</strong><small>{character.title || character.element || "原神角色"}</small></span>
                    <i>{character.video_count ? `${character.video_count} 段视频` : "贺图模式"}</i>
                  </button>
                )) : <div className="empty-suggestion">未找到匹配角色，或 Wiki 服务尚未启动</div>}
              </div>
            )}
          </div>

          {selected && (
            <div className="selected-character">
              <span className="portrait-frame">
                {selected.portrait ? <img src={assetUrl(selected.portrait)} alt={`${selected.name} 立绘`} /> : selected.name.slice(0, 1)}
              </span>
              <div><small>本次 MV 主角</small><strong>{selected.name}</strong><span>{selected.title || `${selected.element || "未知"}元素角色`}</span></div>
              <b>✓ 已选择</b>
            </div>
          )}

          <div className="divider" />

          <div className="section-heading compact">
            <span className="step-number">02</span>
            <div><h2>选择画面素材</h2><p>自动择优，或手动指定一种角色素材类型</p></div>
          </div>

          <fieldset className="source-picker">
            <legend>画面素材类型</legend>
            <label className={!sourceType ? "is-selected" : ""}>
              <input
                type="radio"
                name="source-type"
                value=""
                checked={!sourceType}
                onChange={() => {
                  setSourceType("");
                  resetSourcePreview(Boolean(selected));
                }}
              />
              <strong>自动择优</strong>
              <small>按下方优先级自动选取</small>
            </label>
            {SOURCE_TYPES.map((type) => (
              <label key={type} className={sourceType === type ? "is-selected" : ""}>
                <input
                  type="radio"
                  name="source-type"
                  value={type}
                  checked={sourceType === type}
                  onChange={() => {
                    setSourceType(type);
                    resetSourcePreview(Boolean(selected));
                  }}
                />
                <strong>{type}</strong>
              </label>
            ))}
          </fieldset>

          <div className={`source-preview ${sourcePreview?.kind === "images" ? "is-images" : ""}`}>
            {loadingSourcePreview ? (
              <div className="source-preview-state"><span className="tiny-loader" /> 正在加载素材预览</div>
            ) : sourcePreviewError ? (
              <div className="source-preview-state is-error">{sourcePreviewError}</div>
            ) : sourcePreview?.kind === "video" ? (
              <>
                <div className="source-preview-heading">
                  <span>{sourcePreview.type}</span><strong title={sourcePreview.title}>{sourcePreview.title}</strong>
                </div>
                <video
                  key={`${selected?.name}-${sourceType}-${sourcePreview.urls[0]}`}
                  controls
                  playsInline
                  preload="metadata"
                  src={assetUrl(sourcePreview.urls[0])}
                  aria-label={`${sourcePreview.title}素材预览`}
                >
                  当前浏览器不支持视频预览。
                </video>
              </>
            ) : sourcePreview?.kind === "images" ? (
              <>
                <div className="source-preview-heading">
                  <span>{sourcePreview.type}</span><strong title={sourcePreview.title}>{sourcePreview.title}</strong>
                </div>
                <div className="source-image-stage">
                  <img
                    key={sourcePreview.urls[previewImageIndex]}
                    src={assetUrl(sourcePreview.urls[previewImageIndex])}
                    alt={`${selected?.name || "角色"}生日贺图 ${previewImageIndex + 1}`}
                  />
                  {sourcePreview.urls.length > 1 && (
                    <div className="source-image-nav">
                      <button
                        type="button"
                        aria-label="查看上一张贺图"
                        onClick={() => setPreviewImageIndex((index) => (index - 1 + sourcePreview.urls.length) % sourcePreview.urls.length)}
                      >‹</button>
                      <span>{previewImageIndex + 1} / {sourcePreview.urls.length}</span>
                      <button
                        type="button"
                        aria-label="查看下一张贺图"
                        onClick={() => setPreviewImageIndex((index) => (index + 1) % sourcePreview.urls.length)}
                      >›</button>
                    </div>
                  )}
                </div>
              </>
            ) : (
              <div className="source-preview-state">选择角色后可在这里预览对应素材</div>
            )}
          </div>

          <div className="divider" />

          <div className="section-heading compact">
            <span className="step-number">03</span>
            <div><h2>加入翻唱与原曲信息</h2><p>原唱歌手和歌曲名称用于自动查找同步歌词</p></div>
          </div>

          <div className="song-meta-grid">
            <label>
              <span>原唱歌手</span>
              <input
                value={originalArtist}
                onChange={(event) => setOriginalArtist(event.target.value)}
                placeholder="例如：周杰伦"
                maxLength={160}
                required
              />
            </label>
            <label>
              <span>歌曲名称</span>
              <input
                value={songName}
                onChange={(event) => setSongName(event.target.value)}
                placeholder="例如：晴天"
                maxLength={160}
                required
              />
            </label>
          </div>

          <div className="lyric-offset-field">
            <div className="offset-copy">
              <span>歌词时间偏移</span>
              <small>正数让歌词延后，负数让歌词提前；默认不偏移</small>
            </div>
            <div className="offset-control">
              <button
                type="button"
                aria-label="歌词提前 1 秒"
                onClick={() => setLyricOffsetSeconds((value) => Math.max(-600, value - 1))}
              >−1</button>
              <label>
                <input
                  type="number"
                  min={-600}
                  max={600}
                  step={0.1}
                  value={lyricOffsetSeconds}
                  aria-label="歌词时间偏移秒数"
                  onChange={(event) => {
                    const value = Number(event.target.value);
                    setLyricOffsetSeconds(Number.isFinite(value) ? Math.min(600, Math.max(-600, value)) : 0);
                  }}
                />
                <span>秒</span>
              </label>
              <button
                type="button"
                aria-label="歌词延后 1 秒"
                onClick={() => setLyricOffsetSeconds((value) => Math.min(600, value + 1))}
              >+1</button>
            </div>
          </div>

          <div className="file-grid">
            <FileDrop kind="music" title="上传翻唱音乐" description="MP3 · WAV · M4A · FLAC" accept="audio/*,.mp3,.wav,.m4a,.flac,.aac,.ogg" file={music} onChange={setMusic} />
            <FileDrop kind="subtitle" title="手动字幕（可选）" description="SRT · LRC；上传后优先使用" accept=".srt,.lrc,text/plain" file={subtitle} onChange={setSubtitle} />
          </div>

          {error && <div className="error-message">{error}</div>}

          <button className="create-button" type="submit" disabled={!ready}>
            <span>{job?.status === "completed" ? "重新制作" : "开始制作 MV"}</span><b>→</b>
          </button>
          <p className="consent">未上传字幕时会自动查找同步歌词；查找失败仍会生成无字幕 MV</p>
        </section>

        <aside className="preview-panel">
          <div className="preview-topline"><span>成片预览</span><small>16:9 · 1080P</small></div>
          <div className={`preview-screen ${selected ? "has-character" : ""}`}>
            {job?.status === "completed" && job.preview_url ? (
              <video
                key={job.id}
                className="preview-video"
                controls
                playsInline
                preload="metadata"
                poster={selected?.portrait ? assetUrl(selected.portrait) : undefined}
                src={`${API_ROOT}${job.preview_url}`}
              >
                当前浏览器不支持视频预览，请下载成片后播放。
              </video>
            ) : (
              <>
                {selected?.portrait && <img src={assetUrl(selected.portrait)} alt="" />}
                <div className="preview-shade" />
                <div className="constellation">✦</div>
                <div className="preview-copy">
                  <small>{selected ? selected.title || "角色印象 MV" : "CHARACTER FILM"}</small>
                  <strong>{selected?.name || "等待选择角色"}</strong>
                  <span>{music?.name || "上传音乐后开始创作"}</span>
                </div>
              </>
            )}
          </div>

          <div className="status-block">
            <div className="status-title"><span>{statusLabel}</span><b>{job ? `${Math.round(progress)}%` : "—"}</b></div>
            <div className="progress-track"><i style={{ width: `${progress}%` }} /></div>
            <div className="status-meta">
              <span><small>画面来源</small><strong>{job?.source_type || sourceType || "自动择优"}</strong></span>
              <span><small>成片时长</small><strong>{job?.duration ? `${Math.floor(job.duration / 60)}:${String(Math.round(job.duration % 60)).padStart(2, "0")}` : "随音乐"}</strong></span>
            </div>
            <p className="offset-state"><small>歌词偏移</small><strong>{formatLyricOffset(job?.lyric_offset_seconds ?? lyricOffsetSeconds)}</strong></p>
            {job?.lyrics_message && <p className={`lyrics-state is-${job.lyrics_status || "pending"}`}>{job.lyrics_message}</p>}
          </div>

          {job?.status === "completed" && job.download_url && (
            <a className="download-button" href={`${API_ROOT}${job.download_url}`}>下载成片 <span>↓</span></a>
          )}
          {job?.status === "failed" && <div className="job-failed">{job.error || job.message}</div>}

          <div className="guardrail"><span>◈</span><p><strong>长度保护</strong>音乐超过 10 分钟将不会进入处理，避免意外生成超长文件。</p></div>
        </aside>
      </form>

      <footer><span>映界 · 原神角色 MV 自动创作工具</span><span>素材由本地 GI Wiki 提供</span></footer>
    </main>
  );
}
