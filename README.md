# 映界 · 原神角色 MV 工坊

输入原神角色名，上传一首音乐和 SRT/LRC 字幕，自动从本地 GI Wiki 选择角色素材并生成 1080P MP4 成片。

## 合成规则

素材严格按以下优先级选择：

1. EP 视频
2. 角色预告
3. 角色 PV
4. 角色演示
5. 生日贺图轮播

成片时长以用户上传的音乐为准，视频过长时裁剪、过短时循环；源视频音轨会被完全替换。音乐长度不能超过 10 分钟。字幕会直接烧录进画面，LRC 会先自动转换为 SRT 时间轴。

## 环境要求

- Windows PowerShell 7（Windows PowerShell 5.1 也可）
- Python 3.11+
- Node.js 22+
- FFmpeg 与 FFprobe 已加入 `PATH`
- 相邻目录中已有 `gi-wiki` 项目及角色资料

默认目录关系：

```text
G:\
├─ genshin-impact-mv\
└─ bilibili-download\
   └─ gi-wiki\
```

## 快速启动

首次运行安装依赖：

```powershell
.\scripts\setup.ps1
```

之后一条命令启动 Wiki、合成 API 和 Web 界面：

```powershell
.\scripts\start-dev.ps1
```

打开 <http://localhost:3000>。API 文档位于 <http://127.0.0.1:8787/docs>。

如果 GI Wiki 不在默认相邻目录，可显式指定：

```powershell
.\scripts\start-dev.ps1 -WikiPath "D:\data\gi-wiki"
```

也可以分别启动三个服务：

```powershell
# 终端 1：角色 Wiki
cd G:\bilibili-download\gi-wiki
python .\app.py

# 终端 2：合成 API
cd G:\genshin-impact-mv
.\.venv\Scripts\python.exe -m uvicorn server.main:app --host 127.0.0.1 --port 8787

# 终端 3：Web 界面
cd G:\genshin-impact-mv
npm run dev
```

## API

### 服务状态

```http
GET /api/health
```

返回 Wiki 连接状态、角色数量和 FFmpeg 可用性。

### 搜索角色

```http
GET /api/characters?q=优菈&limit=20
```

此接口代理本地 GI Wiki，供 Web 界面的角色搜索框使用。

### 预览素材选择

```http
GET /api/characters/{角色名}/source
```

返回按优先级选中的素材类型、标题和 Wiki 资源地址。

### 创建 MV

```http
POST /api/mv
Content-Type: multipart/form-data
```

表单字段：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `character` | 文本 | GI Wiki 中的完整角色名 |
| `music` | 文件 | MP3/WAV/M4A/FLAC/AAC/OGG/OPUS，最长 10 分钟 |
| `subtitles` | 文件 | SRT 或 LRC，最大 5 MB |

示例：

```powershell
curl.exe -X POST http://127.0.0.1:8787/api/mv `
  -F "character=优菈" `
  -F "music=@D:\music\song.mp3" `
  -F "subtitles=@D:\music\song.lrc"
```

接口立即返回 `202 Accepted` 和任务 ID，编码在后台执行。

### 查询进度

```http
GET /api/jobs/{任务ID}
```

任务状态为 `queued`、`processing`、`completed` 或 `failed`。完成后响应中会出现 `download_url`。

### 下载成片

```http
GET /api/jobs/{任务ID}/download
```

输出为 H.264/AAC 编码的 1920×1080 MP4 文件。

## 配置

| 环境变量 | 默认值 | 用途 |
| --- | --- | --- |
| `GI_WIKI_URL` | `http://127.0.0.1:8765` | 后端访问 GI Wiki 的地址 |
| `NEXT_PUBLIC_MV_API_URL` | `http://127.0.0.1:8787` | Web 界面访问合成 API 的地址 |
| `NEXT_PUBLIC_GI_WIKI_URL` | `http://127.0.0.1:8765` | Web 界面加载角色图片的地址 |

可复制 `.env.example` 为 `.env` 后调整。生产部署时应同时修改后端 CORS 允许来源。

## 目录

```text
app/                 Web 界面
server/main.py       FastAPI 与 FFmpeg 合成逻辑
scripts/             安装和本地启动脚本
tests/               选择规则与字幕转换测试
work/                任务临时文件（自动创建，不提交）
outputs/             MP4 成片（自动创建，不提交）
```

## 验证

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_mv_logic
npm run build
```

项目附带的 `tests/fixtures` 只用于快速验证，不参与实际生成。
