"""Douyin video and image album extractor."""

from __future__ import annotations

import logging
import os
import re
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qs, quote, unquote, urlencode, urlparse

import sys
from pathlib import Path
import requests

from .abogus import ABogus
from .websign import sign as web_sign

logger = logging.getLogger(__name__)

USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36"

RE_MODAL_ID = re.compile(r"modal_id=(\d{19})")
RE_PATH_ID = re.compile(r"/(?:video|note|slides)/(\d{19})")
RE_BARE_ID = re.compile(r"\b(\d{19})\b")
RE_SHORT_URL = re.compile(r"https?://v\.douyin\.com/[A-Za-z0-9_-]+/?")


def is_douyin_url(url: str) -> bool:
    if not url:
        return False
    lower = url.lower()
    return "douyin.com" in lower or "iesdouyin.com" in lower


def extract_aweme_id(url: str) -> Optional[str]:
    if not url:
        return None

    # Handle short link redirect
    short_match = RE_SHORT_URL.search(url)
    target_url = url
    if short_match:
        try:
            short_url = short_match.group(0)
            headers = {"User-Agent": USER_AGENT}
            resp = requests.head(short_url, headers=headers, allow_redirects=True, timeout=10)
            target_url = resp.url
        except Exception as e:
            logger.warning(f"[DOUYIN] 短链接重定向解析失败: {e}")

    # 1. Match modal_id=...
    m = RE_MODAL_ID.search(target_url)
    if m:
        return m.group(1)

    # 2. Match /video/123456789... or /note/...
    m = RE_PATH_ID.search(target_url)
    if m:
        return m.group(1)

    # 3. Match bare 19-digit id
    m = RE_BARE_ID.search(target_url)
    if m:
        return m.group(1)

    return None


def get_douyin_cookies(cookie_file: Optional[str]) -> Dict[str, str]:
    cookies: Dict[str, str] = {}
    candidate_files: list[str] = []
    if cookie_file and os.path.exists(cookie_file):
        candidate_files.append(cookie_file)

    # 自动搜索常见目录（exe 目录、向上查找所有父目录直至根目录、当前工作目录等），确保用户将 cookies.txt 放入任一位置均可被识别
    search_dirs: list[str] = []

    def _add_with_parents(path_str: Optional[str]):
        if not path_str:
            return
        try:
            p = Path(path_str).resolve()
            for _ in range(5):
                search_dirs.append(str(p))
                if p.parent == p:
                    break
                p = p.parent
        except Exception:
            pass

    _add_with_parents(os.getcwd())
    if sys.argv and sys.argv[0]:
        _add_with_parents(os.path.dirname(os.path.abspath(sys.argv[0])))
    if getattr(sys, 'frozen', False):
        _add_with_parents(os.path.dirname(os.path.abspath(sys.executable)))
    try:
        from pathlib import Path
        _add_with_parents(str(Path(__file__).resolve().parent))
    except Exception:
        pass

    for sd in search_dirs:
        if not sd or not os.path.exists(sd):
            continue
        for name in ('cookies_douyin.txt', 'cookies-douyin.txt', 'douyin.cookies.txt', 'cookies.txt'):
            p = os.path.join(sd, name)
            if p not in candidate_files and os.path.exists(p):
                candidate_files.append(p)

    for cfile in candidate_files:
        try:
            with open(cfile, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    if not line or line.startswith("#"):
                        continue
                    parts = line.strip().split("\t")
                    if len(parts) >= 7:
                        domain = parts[0].lower()
                        if "douyin.com" in domain:
                            cookies[parts[5]] = parts[6]
            if cookies:
                logger.info(f"[DOUYIN] 成功从 {cfile} 加载了 {len(cookies)} 个抖音 Cookies")
                break
        except Exception as e:
            logger.warning(f"[DOUYIN] 读取 cookies 失败: {e}")

    return cookies


def get_guest_ttwid() -> str:
    try:
        payload = {
            "region": "cn",
            "aid": 1768,
            "needFid": False,
            "service": "www.ixigua.com",
            "migrate_info": {"ticket": "", "src_ticket": ""},
            "cbUrlProtocol": "https",
            "union": True,
        }
        resp = requests.post(
            "https://ttwid.bytedance.com/ttwid/union/register/",
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=5,
        )
        return resp.cookies.get("ttwid", "")
    except Exception as e:
        logger.warning(f"[DOUYIN] 获取访客 ttwid 失败: {e}")
        return ""


def fetch_douyin_detail(aweme_id: str, cookie_file: Optional[str] = None) -> Dict[str, Any]:
    cookies = get_douyin_cookies(cookie_file)
    if not cookies.get("ttwid"):
        guest_ttwid = get_guest_ttwid()
        if guest_ttwid:
            cookies["ttwid"] = guest_ttwid

    uifid = cookies.get("UIFID_TEMP") or cookies.get("UIFID") or ""

    params_dict = {
        "device_platform": "webapp",
        "aid": "6383",
        "channel": "channel_pc_web",
        "aweme_id": aweme_id,
        "update_version_code": "170400",
        "pc_client_type": "1",
        "pc_libra_divert": "Mac",
        "support_h265": "1",
        "support_dash": "1",
        "version_code": "190500",
        "version_name": "19.5.0",
        "cookie_enabled": "true",
        "screen_width": "1536",
        "screen_height": "864",
        "browser_language": "zh-CN",
        "browser_platform": "MacIntel",
        "browser_name": "Chrome",
        "browser_version": "146.0.0.0",
        "browser_online": "true",
        "engine_name": "Blink",
        "engine_version": "146.0.0.0",
        "os_name": "Mac OS",
        "os_version": "10.15.7",
        "cpu_core_num": "16",
        "device_memory": "8",
        "platform": "PC",
        "downlink": "10",
        "effective_type": "4g",
        "round_trip_time": "200",
    }
    if uifid:
        params_dict["uifid"] = uifid

    query = urlencode(params_dict)
    a_bogus = ABogus(USER_AGENT).get_value(query)
    signed_query = f"{query}&a_bogus={quote(a_bogus, safe='')}"

    if uifid:
        final_query, _ = web_sign(signed_query, uifid)
    else:
        final_query = signed_query

    api_url = f"https://www.douyin.com/aweme/v1/web/aweme/detail/?{final_query}"
    cookie_str = "; ".join(f"{k}={v}" for k, v in cookies.items())
    headers = {
        "User-Agent": USER_AGENT,
        "Referer": f"https://www.douyin.com/video/{aweme_id}",
        "Cookie": cookie_str,
        "x-secsdk-web-expire": "0",
    }

    resp = requests.get(api_url, headers=headers, timeout=15)
    if resp.status_code == 403 or "Blocked by ArgusSecurityPlugin" in resp.text:
        raise ValueError(
            "抖音安全风控拦截（Uifid Not Found）。请将浏览器导出的包含抖音登录/访客状态的 cookies.txt 放入程序目录后重试。"
        )

    if resp.status_code != 200:
        raise ValueError(f"抖音详情接口返回异常状态码: {resp.status_code}")

    try:
        data = resp.json()
    except Exception as e:
        raise ValueError(f"抖音详情响应无法解析为 JSON: {e}，内容: {resp.text[:100]}")

    detail = data.get("aweme_detail")
    if not detail:
        filter_detail = data.get("filter_detail", {})
        notice = filter_detail.get("notice") or "作品不存在或已被作者设为私密"
        raise ValueError(f"获取抖音作品详情失败: {notice}")

    return detail


def parse_douyin_info(url: str, cookie_file: Optional[str] = None) -> Dict[str, Any]:
    aweme_id = extract_aweme_id(url)
    if not aweme_id:
        raise ValueError(f"无法从输入中提取抖音作品 ID: {url}")

    detail = fetch_douyin_detail(aweme_id, cookie_file)

    raw_title = detail.get("desc") or ""
    title = re.sub(r'[\r\n\t\x00-\x1f\x7f-\x9f]+', ' ', raw_title).strip()
    title = re.sub(r'\s+', ' ', title)
    if not title:
        title = f"抖音作品_{aweme_id}"

    author = detail.get("author", {})
    uploader = author.get("nickname") or "抖音用户"
    uploader_id = author.get("unique_id") or author.get("short_id") or ""

    video = detail.get("video", {})
    images = detail.get("images") or []

    # Thumbnail
    thumbnail = ""
    cover_urls = video.get("cover", {}).get("url_list", [])
    if cover_urls:
        thumbnail = cover_urls[0]
    elif images:
        img_urls = images[0].get("url_list", [])
        if img_urls:
            thumbnail = img_urls[0]

    duration = float(video.get("duration", 0)) / 1000.0 if video.get("duration") else 0.0
    height = video.get("height", 1080) or 1080
    width = video.get("width", 1920) or 1920

    is_gallery = bool(images and not video.get("play_addr"))

    formats: List[Dict[str, Any]] = []
    quality_pairs: Dict[str, Dict[str, str]] = {}

    if not is_gallery:
        play_addrs = video.get("play_addr", {}).get("url_list", [])
        play_url = play_addrs[0] if play_addrs else ""
        h_str = str(height)

        formats.append({
            "format_id": "best",
            "format_note": f"{height}p 无水印原画",
            "ext": "mp4",
            "height": height,
            "width": width,
            "vcodec": "h264",
            "acodec": "aac",
            "url": play_url,
            "http_headers": {
                "User-Agent": USER_AGENT,
                "Referer": "https://www.douyin.com/",
            },
        })

        quality_pairs[h_str] = {
            "video": "best",
            "audio": "best",
        }
        max_height = height
    else:
        # Gallery images
        max_height = 1080
        formats.append({
            "format_id": "gallery",
            "format_note": f"图集 ({len(images)} 张图片)",
            "ext": "zip",
            "height": 1080,
            "width": 1080,
            "vcodec": "none",
            "acodec": "none",
        })
        quality_pairs["1080"] = {
            "video": "gallery",
            "audio": "gallery",
        }

    return {
        "id": aweme_id,
        "title": title,
        "description": detail.get("desc", ""),
        "uploader": uploader,
        "uploader_id": uploader_id,
        "thumbnail": thumbnail,
        "duration": duration,
        "webpage_url": f"https://www.douyin.com/video/{aweme_id}",
        "extractor": "douyin",
        "extractor_key": "Douyin",
        "formats": formats,
        "quality_pairs": quality_pairs,
        "max_height": max_height,
        "_douyin_detail": detail,
    }
