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
├── huya.py              # 主程序入口
├── requirements.txt     # Python 依赖
├── tars/                # Tars 协议实现
│   ├── __tars.py        # Tars 编解码核心
│   ├── __packet.py      # 包结构
│   └── ...
└── huya_wup/            # 虎牙 WUP 协议
    ├── wup.py           # WUP 协议封装
    ├── packet/          # 请求/响应结构
    └── ...
```

## 致谢

本项目的实现参考了以下开源项目：

- [dart_simple_live](https://github.com/xiaoyaocz/dart_simple_live) - Dart 实现的直播源获取
- [DanmakuRender](https://github.com/SmallPeaches/DanmakuRender) - Python 实现的直播录制工具

## 许可证

MIT License

## 免责声明

本项目仅供学习交流使用，请勿用于商业用途。使用本工具观看直播时，请遵守虎牙直播的用户协议。
