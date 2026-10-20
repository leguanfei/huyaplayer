# 虎牙直播取流工具

轻量级虎牙直播流获取工具，支持直接使用 mpv 播放。

## 为什么需要这个工具？

虎牙直播网页端播放器资源占用较高，本项目对于低配置机器来说：
- 资源占用极低，老机器也能流畅观看高清直播
- 支持硬件解码
- 无弹幕、无特效，纯净观看体验

## 安装

### 依赖

- Python 3.8+
- [mpv](https://mpv.io/) 播放器（用于播放）

### 安装步骤

```bash
# 克隆仓库
git clone https://github.com/yourusername/huya-live.git
cd huya-live

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

## 使用方法

### 获取直播流 URL

```bash
python huya.py <房间号>
```

示例：
```bash
python huya.py 660002
# 输出: https://tx.flv.huya.com/src/xxx.flv?wsSecret=xxx&...
```

### 直接播放

```bash
python huya.py <房间号> --play
```

### 指定清晰度

```bash
# 原画（默认）
python huya.py <房间号> --play

# 高清 (2000kbps)
python huya.py <房间号> --play --quality 2000

# 超清 (4000kbps)
python huya.py <房间号> --play --quality 4000
```

### 指定 CDN 线路

```bash
# 列出所有可用 CDN
python huya.py <房间号> --list-cdn

# 指定 CDN（通常 tx、al 线路较稳定）
python huya.py <房间号> --cdn tx --play
```

### 支持房间号格式

- 数字房间号：`660002`
- 主播昵称：`Maybe111`（会自动解析）

## 桌面播放器（图形界面）

`app.py` 是一个内嵌 mpv 的桌面播放器，无需安装 Python 即可使用打包后的单文件。

### 直接运行

```bash
python app.py            # 打开播放器
python app.py 988        # 打开并自动播放 988 房间
```

界面操作：

- 输入房间号（支持 `988` 或完整虎牙链接），按回车或点击「观看」
- 可选择清晰度（原画 / 高清 / 超清）与 CDN 线路（自动 / 腾讯 / 阿里 / 华为 / 网宿）
- 「暂停 / 静音 / 全屏」，快捷键 `F11` 或 `Ctrl+F` 切换全屏，`Esc` 退出全屏
- 播放时也可直接使用 mpv 自带快捷键（空格暂停、`m` 静音、`↑` `↓` 音量）

### 弹幕侧栏

- 拖动画面与侧栏之间的**握把条**（悬停变琥珀色）即可改宽度；双击握把复位到 320px
- `Ctrl+←` / `Ctrl+Right` 以 40px 步进调整栏宽，`Ctrl+D` 或「弹幕」按钮开关侧栏（全屏时自动隐藏）
- 栏宽始终保证画面不小于窗口 55%（且不小于 560px），窗口缩小时侧栏自动收敛、放大后自动恢复
- `Ctrl+滚轮` 或右键菜单调整弹幕字号（10–13 档），栏宽与字号会记住
- 右键菜单可复制选中 / 复制全部 / 清屏 / 复位栏宽
- 往上翻看历史时**不再被新弹幕顶走**，底部出现「↓ 新消息 N 条」，点击回到最新即恢复跟随
- 侧栏顶部的圆点表示弹幕连接状态，断线与重连会作为分隔行写入消息流

弹幕通过 `wss://cdnws.api.huya.com` 的 TARS 协议实现（见 `huya_danmaku.py`），无需虎牙开发者账号，断线会自动重连。

### 打包为单文件 exe

```powershell
# 首次会自动下载 mpv 播放器并安装依赖
pwsh -File build.ps1
```

产物位于 `dist\HuyaLive.exe`，无需安装 Python 或 mpv，双击即可使用。

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
huya_live/
├── huya.py              # 取流核心（房间信息 / WUP 动态 Token / 签名），也是 CLI 入口
├── app.py               # 桌面播放器（Tkinter + 内嵌 mpv）
├── chat_layout.py       # 弹幕侧栏的布局数学（栏宽边界、字号档位）
├── huya_danmaku.py      # 弹幕客户端（wss + Tars）
├── api.py               # FastAPI 代理，把动态流地址固定成一条 URL
├── requirements.txt     # Python 依赖
├── tests/               # 布局数学单测 + 可跳过的 Tk 面板集成测试
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

`tests/test_chat_layout.py` 是纯逻辑单测；`tests/test_chat_panel_smoke.py` 需要能创建 Tk 窗口，
无图形环境时会自动跳过。

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

MIT License

## 免责声明

本项目仅供学习交流使用，请勿用于商业用途。使用本工具观看直播时，请遵守虎牙直播的用户协议。
