"use client";

/* Wiki assets come from a configurable local origin, so native images are intentional. */
/* eslint-disable @next/next/no-img-element */

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
  download_url?: string;
  error?: string;
};

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
  const [job, setJob] = useState<Job | null>(null);
  const [loadingCharacters, setLoadingCharacters] = useState(false);
  const [error, setError] = useState("");

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

  const ready = Boolean(selected && music && subtitle && (!job || !["queued", "processing"].includes(job.status)));
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
    if (!selected || !music || !subtitle) return;
    setError("");
    setJob(null);
    const form = new FormData();
    form.append("character", selected.name);
    form.append("music", music);
    form.append("subtitles", subtitle);
    try {
      const response = await fetch(`${API_ROOT}/api/mv`, { method: "POST", body: form });
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
        <p>选择角色，上传音乐与字幕。系统会从角色 EP、预告、PV、演示或生日贺图中自动选取最佳素材，制作一支完整 MV。</p>
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
            <div><h2>加入声音与文字</h2><p>音乐决定成片长度，最长支持 10 分钟</p></div>
          </div>

          <div className="file-grid">
            <FileDrop kind="music" title="上传音乐" description="MP3 · WAV · M4A · FLAC" accept="audio/*,.mp3,.wav,.m4a,.flac,.aac,.ogg" file={music} onChange={setMusic} />
            <FileDrop kind="subtitle" title="上传字幕" description="SRT · LRC，自动烧录进画面" accept=".srt,.lrc,text/plain" file={subtitle} onChange={setSubtitle} />
          </div>

          {error && <div className="error-message">{error}</div>}

          <button className="create-button" type="submit" disabled={!ready}>
            <span>{job?.status === "completed" ? "重新制作" : "开始制作 MV"}</span><b>→</b>
          </button>
          <p className="consent">提交即表示你确认拥有所上传音乐与字幕的使用权限</p>
        </section>

        <aside className="preview-panel">
          <div className="preview-topline"><span>成片预览</span><small>16:9 · 1080P</small></div>
          <div className={`preview-screen ${selected ? "has-character" : ""}`}>
            {selected?.portrait && <img src={assetUrl(selected.portrait)} alt="" />}
            <div className="preview-shade" />
            <div className="constellation">✦</div>
            <div className="preview-copy">
              <small>{selected ? selected.title || "角色印象 MV" : "CHARACTER FILM"}</small>
              <strong>{selected?.name || "等待选择角色"}</strong>
              <span>{music?.name || "上传音乐后开始创作"}</span>
            </div>
          </div>

          <div className="status-block">
            <div className="status-title"><span>{statusLabel}</span><b>{job ? `${Math.round(progress)}%` : "—"}</b></div>
            <div className="progress-track"><i style={{ width: `${progress}%` }} /></div>
            <div className="status-meta">
              <span><small>画面来源</small><strong>{job?.source_type || "自动择优"}</strong></span>
              <span><small>成片时长</small><strong>{job?.duration ? `${Math.floor(job.duration / 60)}:${String(Math.round(job.duration % 60)).padStart(2, "0")}` : "随音乐"}</strong></span>
            </div>
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
