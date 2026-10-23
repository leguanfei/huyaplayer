# 虎牙播放器 · HuyaPlayer

基于 PySide6 + 内嵌 mpv 的虎牙直播桌面播放器，自带弹幕侧栏，可打包成单文件 exe。

## 为什么用它？

虎牙网页端播放器是个很重的壳，本项目换成原生播放内核：

- 画面交给 mpv 硬解，资源占用低，老机器也能流畅看高清
- 弹幕走 TARS 协议直连，停靠侧栏 / 全屏浮层两种形态，不上网页
- 无边框窗口、浮层控制条、亮暗主题、系统托盘
- 取流内核也保留为 CLI 和 HTTP 代理，可单独使用

## 与上游的关系

取流协议（`huya.py` / `huya_wup/` / `tars/` / `huya_danmaku.py`）来自
[justwezzz/huya_live](https://github.com/justwezzz/huya_live)；
桌面播放器、弹幕侧栏、主题系统与打包流程是在其基础上的二次开发。

## 下载

Windows 用户直接从 [Releases](https://github.com/leguanfei/huyaplayer/releases) 下载
`HuyaLive.exe`，双击即用，无需安装 Python 或 mpv。

## 安装

### 依赖

- Python 3.9+
- [mpv](https://mpv.io/) 播放器（用于播放）
- PySide6（桌面播放器界面，`pip install -r requirements.txt` 会带上 Essentials 子集）

### 安装步骤

```bash
# 克隆仓库
git clone https://github.com/leguanfei/huyaplayer.git
cd huyaplayer

# 安装 Python 依赖
pip install -r requirements.txt
```

### 安装 mpv

**Ubuntu/Debian:**
```bash
sudo apt install mpv
```

**Arch Linux:**
```bash
sudo pacman -S mpv
```

**macOS:**
```bash
brew install mpv
```

**Windows:**
从 [mpv 官网](https://mpv.io/installation/) 下载安装。

## 使用（桌面播放器）

`app.py` 是一个内嵌 mpv 的桌面播放器，无需安装 Python 即可使用打包后的单文件。

### 直接运行

```bash
python app.py            # 打开播放器
python app.py 988        # 打开并自动播放 988 房间
```

界面操作：

- 待机页输入房间号（支持 `988` 或完整虎牙链接），回车或点「观看」；起流后待机页淡出
- 播放控件收在画面底部的**浮层控制条**里：播放/停止、音量滑杆、清晰度、线路、全屏；
  鼠标静止 2 秒自动淡出，移到画面上重新浮现
- 标题栏 `◐` 切换亮/暗主题（只换外壳，画面区始终为黑）；关闭按钮默认进系统托盘，
  托盘菜单里才是真正的退出
- 断流会自动重连（2/4/8/16/30 秒退避），浮层状态文字会显示「连接中断，自动重连中…」
- 按 `F1` 打开快捷键面板

### 弹幕侧栏

- 拖动画面与侧栏之间的**握把条**即可改宽度；双击握把复位到 320px
- `Ctrl+←` / `Ctrl+→` 以 40px 步进调整栏宽，`Ctrl+D` 开关侧栏
- **全屏时侧栏自动变成半透明浮层**贴在画面右缘，不压缩画面；退出全屏回到停靠态
- 新弹幕以滑入 + 淡入入场；往上翻看历史时不会被新弹幕顶走，底部出现
  「↓ 新消息 N 条」，点击回到最新即恢复跟随
- `Ctrl+滚轮` 或右键菜单调整弹幕字号（10–13 档）；右键菜单还可复制全部 / 清屏 /
  复位栏宽 / 隐藏侧栏。栏宽、字号、开关状态都会记住
- 侧栏顶部的圆点表示弹幕连接状态，断线与重连会作为分隔行写入消息流

弹幕通过 `wss://cdnws.api.huya.com` 的 TARS 协议实现（见 `huya_danmaku.py`），无需虎牙开发者账号，断线会自动重连。

### 打包为单文件 exe

```powershell
# 首次会自动下载 mpv 播放器并安装依赖
pwsh -File build.ps1
```

产物位于 `dist\HuyaLive.exe`，无需安装 Python 或 mpv，双击即可使用。

发布版本不需要本地打包：推一个 `v*` tag 会触发
[release workflow](.github/workflows/release.yml)，在 `windows-latest` 上跑同一套
`build.ps1`，把 exe 挂到 Release。

```bash
git tag v1.0.0
git push origin v1.0.0
```

## 命令行用法（可选）

播放器之外，`huya.py` 也可以单独当取流工具用：

```bash
python huya.py <房间号>               # 打印直播流 URL
python huya.py <房间号> --play        # 交给系统 mpv 播放
python huya.py <房间号> --play --quality 2000   # 高清
python huya.py <房间号> --play --quality 4000   # 超清
python huya.py <房间号> --list-cdn    # 列出所有可用 CDN
python huya.py <房间号> --cdn tx --play         # 指定线路（tx / al 通常较稳）
```

房间号支持数字（`660002`）或主播昵称（`Maybe111`，会自动解析）。

## 技术原理

虎牙直播采用动态 Token 机制防止第三方取流，本工具通过以下步骤获取播放地址：

1. **获取房间信息**：从移动端页面解析直播流基础信息
2. **Tars 协议调用**：通过腾讯 Tars 协议调用 `getCdnTokenInfoEx` 接口获取动态 Token
3. **签名算法**：实现虎牙的签名算法，包括：
   - UID 旋转加密 (rotl64)
   - MD5 签名
   - 时间戳和序列号生成
4. **构建播放 URL**：组装最终的 FLV 流地址

## 项目结构

```
huyaplayer/
├── huya.py              # 取流核心（房间信息 / WUP 动态 Token / 签名），也是 CLI 入口
├── app.py               # 桌面播放器组装（PySide6 无边框窗口 + 内嵌 mpv）
├── theme.py             # 设计令牌与 QSS 生成（亮/暗两套，纯数据可单测）
├── mpv_embed.py         # mpv 进程 / JSON IPC / 断流指数退避重连（可注入单测）
├── chat_model.py        # 弹幕列表模型（裁剪、斑马、入场动画窗口）
├── chat_panel.py        # 弹幕侧栏容器：自绘 delegate / 拖拽把手 / 右键菜单
├── chat_layout.py       # 侧栏布局数学（栏宽边界、字号档位）
├── huya_danmaku.py      # 弹幕客户端（wss + Tars）
├── api.py               # FastAPI 代理，把动态流地址固定成一条 URL
├── requirements.txt     # Python 依赖
├── tests/               # 57 项单测 + Qt offscreen 冒烟，无需显示器
├── tars/                # Tars 协议实现
│   ├── __tars.py        # Tars 编解码核心
│   ├── __packet.py      # 包结构
│   └── ...
└── huya_wup/            # 虎牙 WUP 协议
    ├── wup.py           # WUP 协议封装
    ├── packet/          # 请求/响应结构
    └── ...
```

## 测试

```bash
python -m unittest discover -s tests
```

Qt 相关测试跑在 `QT_QPA_PLATFORM=offscreen` 下，无图形环境也能执行；
取流与弹幕协议模块（`huya.py` / `huya_danmaku.py`）不在测试范围内。

## 致谢

本项目的实现参考了以下开源项目：

- [dart_simple_live](https://github.com/xiaoyaocz/dart_simple_live) - Dart 实现的直播源获取
- [DanmakuRender](https://github.com/SmallPeaches/DanmakuRender) - Python 实现的直播录制工具

## Proxy API 模式

通过 FastAPI Web 服务将虎牙直播流地址映射为固定 URL，适合在 nxmp 等播放器中使用。

### 快速部署（Docker）

```bash
# 修改 docker-compose.yml 中的 HUYA_API_KEY
docker compose up -d
```

### 手动运行

```bash
pip install -r requirements.txt
HUYA_API_KEY=your_secret uvicorn api:app --host 0.0.0.0 --port 9898
```

### API 端点

| 端点 | 说明 |
|------|------|
| `GET /huya/{room_id}?key=xxx` | 302 重定向到真实 FLV 地址 |
| `GET /huya/{room_id}/info?key=xxx` | 返回房间信息 JSON |

### 参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `key` | 必填 | API Key（环境变量 HUYA_API_KEY） |
| `quality` | 0 | 清晰度: 0=原画, 2000=高清, 4000=超清 |
| `cdn` | 自动 | CDN 线路: tx/ali/hw 等 |

### NS 端使用

在 SD 卡创建 `.strm` 文件：

```
http://服务器IP:9898/huya/123456?key=your_secret
```

或创建 `.m3u` 播放列表：

```
#EXTM3U
#EXTINF:-1,虎牙-房间123456
http://服务器IP:9898/huya/123456?key=your_secret
```

## 许可证

本项目以 MIT 许可证发布，全文见 [LICENSE](LICENSE)；上游 `huya_live` 同样声明为 MIT。

## 免责声明

本项目仅供学习交流使用，请勿用于商业用途。使用本工具观看直播时，请遵守虎牙直播的用户协议。
