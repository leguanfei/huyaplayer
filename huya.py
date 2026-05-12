#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
虎牙直播取流工具
支持获取直播流 URL 和直接使用 mpv 播放

使用方法:
    python huya.py <房间号>              # 获取直播流 URL
    python huya.py <房间号> --play       # 使用 mpv 播放
    python huya.py <房间号> --quality 2000  # 指定清晰度
"""

import sys
import os
import json
import random
import re
import base64
import hashlib
import time
import subprocess
import argparse
from urllib.parse import parse_qs, unquote, quote
from enum import Enum

import requests

# 添加当前目录到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from huya_wup import Wup, DEFAULT_TICKET_NUMBER, HuyaGetCdnTokenExReq, HuyaGetCdnTokenExRsp, HuyaUserId


# 常量定义
HUYA_WEB_BASE_URL = "https://www.huya.com"
HUYA_MOBILE_BASE_URL = "https://m.huya.com"
HUYA_MP_BASE_URL = "https://mp.huya.com"
HUYA_WUP_BASE_URL = "https://wup.huya.com"
HUYA_WUP_YST_URL = "https://snmhuya.yst.aisee.tv"
HUYA_WEB_ROOM_DATA_REGEX = r"var TT_ROOM_DATA = (.*?);"

WUP_UA = "HYSDK(Windows,30000002)_APP(pc_exe&7030003&official)_SDK(trans&2.29.0.5493)"

# UID 旋转加密
rotl64 = lambda t: ((t & 0xFFFFFFFF) << 8 | (t & 0xFFFFFFFF) >> 24) & 0xFFFFFFFF | (t & ~0xFFFFFFFF)


class PLATFORM(Enum):
    """虎牙平台类型"""
    HUYA_PC_EXE = 0
    HUYA_ADR = 2
    HUYA_IOS = 3
    TV_HUYA_NFTV = 10
    HUYA_WEBH5 = 100
    HUYA_LIVE = 100
    TARS_MP = 102
    TARS_MOBILE = 103
    HUYA_LIVESHAREH5 = 104

    @classmethod
    def get_random_as_tuple(cls):
        _ = random.choice(list(cls))
        return _.name.lower(), _.value

    @classmethod
    def get_platform_id(cls, platform: str) -> int:
        return cls[platform.upper()].value if platform.upper() in cls.__members__ else 100

    @property
    def short_name(self) -> str:
        name = self.name.lower()
        idx = name.find('_')
        return name[idx + 1:] if idx != -1 else name


class UAGenerator:
    """虎牙客户端 UA 生成器"""
    HYAPP_CONFIGS = {
        PLATFORM.HUYA_ADR: {'version': '13.1.0'},
        PLATFORM.HUYA_IOS: {'version': '13.1.0'},
        PLATFORM.TV_HUYA_NFTV: {'version': '2.6.10'},
        PLATFORM.HUYA_PC_EXE: {'version': '7000000'},
    }

    @staticmethod
    def generate_hyapp_ua(platform: PLATFORM) -> str:
        config = UAGenerator.HYAPP_CONFIGS.get(platform)
        if not config:
            platform = random.choice(list(UAGenerator.HYAPP_CONFIGS.keys()))
            config = UAGenerator.HYAPP_CONFIGS[platform]

        hyapp_platform = platform.short_name
        hyapp_version = config.get("version", "0.0.0")
        hyapp_channel = config.get("channel", "official")

        if platform in {PLATFORM.HUYA_ADR, PLATFORM.TV_HUYA_NFTV}:
            hyapp_version += f".{random.randint(3000, 5000)}"

        ua = f"{hyapp_platform}&{hyapp_version}&{hyapp_channel}"

        if platform in {PLATFORM.HUYA_ADR, PLATFORM.TV_HUYA_NFTV}:
            android_api_level = random.randint(28, 36)
            ua = f"{ua}&{android_api_level}"

        return ua

    @staticmethod
    def get_random_hyapp_ua() -> str:
        random_platform = random.choice(list(PLATFORM))
        return UAGenerator.generate_hyapp_ua(random_platform)


class HuyaLive:
    """虎牙直播 API"""

    def __init__(self, room_id: str):
        self.room_id = room_id
        self.sess = requests.Session()
        self.headers = {
            'Content-Type': 'application/x-www-form-urlencoded',
            'User-Agent': 'Mozilla/5.0 (Linux; Android 5.0; SM-G900P Build/LRX21T) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/75.0.3770.100 Mobile Safari/537.36'
        }

    def __del__(self):
        self.sess.close()

    def get_room_profile(self) -> dict:
        """获取房间信息"""
        # 使用移动端页面，数据更容易解析
        resp = self.sess.get(
            f"{HUYA_MOBILE_BASE_URL}/{self.room_id}",
            headers=self.headers, timeout=10)
        resp.raise_for_status()
        text = resp.text

        for err_key in ("找不到这个主播", "该主播涉嫌违规，正在整改中"):
            if err_key in text:
                raise Exception(err_key)

        return self._extract_room_profile(text)

    def _extract_room_profile(self, data: str) -> dict:
        """从页面提取房间信息"""
        # 提取 HNF_GLOBAL_INIT JSON
        match = re.search(r'HNF_GLOBAL_INIT\s*=\s*(\{.*)', data, re.DOTALL)
        if not match:
            raise Exception("无法解析页面数据")

        content = match.group(1)
        end_idx = content.find('</script>')
        if end_idx > 0:
            content = content[:end_idx].rstrip().rstrip(';').rstrip()

        try:
            json_data = json.loads(content)
        except json.JSONDecodeError as e:
            raise Exception(f"JSON解析错误: {e}")

        room_info = json_data.get('roomInfo', {})
        live_status = room_info.get('eLiveStatus', 0)

        if live_status != 2:
            return {
                'live': False,
                'message': '未开播',
            }

        t_live_info = room_info.get('tLiveInfo', {})
        t_live_stream_info = t_live_info.get('tLiveStreamInfo', {})

        # 获取流信息
        streams_info = []
        v_stream_info = t_live_stream_info.get('vStreamInfo', {}).get('value', [])
        for stream in v_stream_info:
            streams_info.append({
                'sCdnType': stream.get('sCdnType', ''),
                'sStreamName': stream.get('sStreamName', ''),
                'sFlvUrl': stream.get('sFlvUrl', ''),
                'sFlvUrlSuffix': stream.get('sFlvUrlSuffix', 'flv'),
                'sFlvAntiCode': stream.get('sFlvAntiCode', ''),
                'sHlsUrl': stream.get('sHlsUrl', ''),
                'sHlsAntiCode': stream.get('sHlsAntiCode', ''),
                'lPresenterUid': stream.get('lPresenterUid', 0),
                'iWebPriorityRate': stream.get('iPCPriorityRate', stream.get('iWebPriorityRate', 0)),
            })

        # 获取清晰度信息
        bitrate_info = []
        v_bitrate_info = t_live_stream_info.get('vBitRateInfo', {}).get('value', [])
        for br in v_bitrate_info:
            bitrate_info.append({
                'name': br.get('sDisplayName', ''),
                'bitRate': br.get('iBitRate', 0),
            })

        return {
            'artist': t_live_info.get('sNick', ''),
            'artist_img': t_live_info.get('sAvatar180', '').replace('http://', 'https://'),
            'bitrate_info': bitrate_info,
            'gid': t_live_info.get('iGid', 0),
            'live': True,
            'live_start_time': t_live_info.get('startTime', 0),
            'max_bitrate': t_live_info.get('iBitRate', 0),
            'room_cover': t_live_info.get('sScreenshot', '').replace('http://', 'https://'),
            'room_title': t_live_info.get('sIntroduction', '') or t_live_info.get('sRoomName', ''),
            'streams_info': streams_info,
            'topSid': json_data.get('topSid', 0),
            'subSid': json_data.get('subSid', 0),
        }

    def get_cdn_token_info_ex(self, stream_name: str) -> str:
        """获取动态 Token (WUP协议)"""
        tid = HuyaUserId()
        tid.sHuYaUA = UAGenerator.get_random_hyapp_ua()

        wup_req = Wup()
        wup_req.requestid = abs(DEFAULT_TICKET_NUMBER)
        wup_req.servant = "liveui"
        wup_req.func = "getCdnTokenInfoEx"

        token_info_req = HuyaGetCdnTokenExReq()
        token_info_req.sStreamName = stream_name
        token_info_req.tId = tid

        wup_req.put(HuyaGetCdnTokenExReq, "tReq", token_info_req)
        data = wup_req.encode_v3()

        url = HUYA_WUP_BASE_URL
        if random.random() > 0.5:
            url = f"{HUYA_WUP_YST_URL}/{wup_req.servant}/{wup_req.func}"

        headers = {
            'User-Agent': WUP_UA,
            'Origin': HUYA_WEB_BASE_URL,
            'Referer': HUYA_WEB_BASE_URL,
        }

        rsp = self.sess.post(url, data=data, headers=headers, timeout=10)
        wup_rsp = Wup()
        wup_rsp.decode_v3(rsp.content)
        token_info_rsp = wup_rsp.get(HuyaGetCdnTokenExRsp, "tRsp")

        # sFlvToken 可能是 bytes 类型
        token = token_info_rsp.sFlvToken
        if isinstance(token, bytes):
            token = token.decode('utf-8')
        return token

    def build_anticode(self, stream_name: str, anti_code: str, uid: int = 0) -> str:
        """构建签名参数"""
        url_query = parse_qs(anti_code)
        if not url_query.get("fm"):
            return anti_code

        ctype = url_query.get('ctype', [])
        platform_id = url_query.get('t', [])

        if len(ctype) == 0:
            ctype, platform_id = PLATFORM.get_random_as_tuple()
        elif len(platform_id) == 0:
            ctype = ctype[0]
            platform_id = PLATFORM.get_platform_id(ctype)
        else:
            ctype = ctype[0]
            platform_id = platform_id[0]

        is_wap = int(platform_id) in {103}
        calc_start_time = time.time()

        if uid == 0:
            uid = self._generate_random_uid()

        seq_id = uid + int(calc_start_time * 1000)
        secret_hash = hashlib.md5(f"{seq_id}|{ctype}|{platform_id}".encode()).hexdigest()
        convert_uid = rotl64(uid)
        calc_uid = uid if is_wap else convert_uid

        fm = unquote(url_query['fm'][0])
        secret_prefix = base64.b64decode(fm.encode()).decode().split('_')[0]

        ws_time = url_query['wsTime'][0]
        if int(ws_time, 16) - int(calc_start_time) < (20 * 60):
            ws_time = hex(24 * 60 * 60 + int(calc_start_time))[2:]

        secret_str = f'{secret_prefix}_{calc_uid}_{stream_name}_{secret_hash}_{ws_time}'
        ws_secret = hashlib.md5(secret_str.encode()).hexdigest()

        ct = int((int(ws_time, 16) + random.random()) * 1000)
        uuid = str(int((ct % 1e10 + random.random()) * 1e3 % 0xffffffff))

        anti_code_dict = {
            "wsSecret": ws_secret,
            "wsTime": ws_time,
            "seqid": seq_id,
            "ctype": ctype,
            "ver": "1",
            "fs": url_query['fs'][0],
            "fm": quote(url_query['fm'][0], encoding='utf-8'),
            "t": platform_id,
        }

        if is_wap:
            anti_code_dict.update({"uid": uid, "uuid": uuid})
        else:
            anti_code_dict.update({"u": convert_uid})

        return '&'.join([f"{k}={v}" for k, v in anti_code_dict.items()])

    @staticmethod
    def _generate_random_uid() -> int:
        return int(f"1234{random.randint(0, 9999):04d}") \
            if random.random() > 0.5 else \
            int(f"140000{random.randint(0, 9999999):07d}")

    def get_stream_urls(self) -> list:
        """获取所有可用的直播流 URL"""
        room_profile = self.get_room_profile()
        if not room_profile.get('live'):
            raise Exception(room_profile.get('message', '直播间未开播'))

        streams_info = room_profile['streams_info']
        urls = []
        cached_anticode = ""

        for stream in streams_info:
            priority = stream['iWebPriorityRate']
            if priority < 0:
                continue

            stream_name = stream['sStreamName']
            cdn = stream['sCdnType'].lower()
            flv_url = stream['sFlvUrl'].replace('http://', 'https://')
            flv_suffix = stream['sFlvUrlSuffix']
            presenter_uid = stream.get('lPresenterUid', 0)

            if not cached_anticode:
                token = self.get_cdn_token_info_ex(stream_name)
                cached_anticode = self.build_anticode(stream_name, token, presenter_uid)
                cached_anticode = cached_anticode + "&codec=264"

            uri = f"{flv_url}/{stream_name}.{flv_suffix}?{cached_anticode}"
            urls.append({
                'cdn': cdn,
                'url': uri,
                'priority': priority
            })

        return urls

    def get_stream_url(self, cdn: str = None) -> str:
        """获取直播流 URL"""
        urls = self.get_stream_urls()
        if not urls:
            raise Exception("没有可用的直播流")

        if cdn:
            for u in urls:
                if u['cdn'] == cdn:
                    return u['url']

        # 按优先级排序，返回最高优先级的
        urls.sort(key=lambda x: x['priority'], reverse=True)
        return urls[0]['url']


def main():
    parser = argparse.ArgumentParser(description='虎牙直播取流工具')
    parser.add_argument('room_id', help='房间号')
    parser.add_argument('--play', action='store_true', help='使用 mpv 播放')
    parser.add_argument('--quality', type=int, default=0, help='清晰度 (bitrate: 0=原画, 2000=高清)')
    parser.add_argument('--cdn', type=str, help='指定 CDN 线路 (如: tx, al, bd)')
    parser.add_argument('--list-cdn', action='store_true', help='列出所有 CDN 线路')

    args = parser.parse_args()

    try:
        api = HuyaLive(args.room_id)

        if args.list_cdn:
            urls = api.get_stream_urls()
            print("可用 CDN 线路:")
            for u in urls:
                print(f"  - {u['cdn']}: 优先级 {u['priority']}")
            return

        url = api.get_stream_url(args.cdn)

        # 添加清晰度参数
        if args.quality > 0:
            url += f"&ratio={args.quality}"

        if args.play:
            print(f"正在播放房间 {args.room_id}...")
            print(f"URL: {url}")
            # 调用 mpv 播放
            subprocess.run(['mpv', f'--user-agent={WUP_UA}', url])
        else:
            print(url)

    except Exception as e:
        print(f"错误: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
