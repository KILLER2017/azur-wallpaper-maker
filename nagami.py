# -*- coding: utf-8 -*-
"""
碧蓝航线皮肤数据源（Azur Lane Dynamic Skin Viewer 使用的公开数据）。

- data.nagami.moe：皮肤索引、模型、表情、台词、BGM 的 JSON
- azlassets.nagami.moe：skel / atlas / png、台词语音、背景图、BGM 文件

直接请求会被 403 拦截，需要带浏览器 UA 与 Referer。
"""

import json
import os
import time
import urllib.error
import urllib.request

DATA_BASE = "https://data.nagami.moe"
ASSET_BASE = "https://azlassets.nagami.moe"

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/130.0 Safari/537.36",
    "Referer": "https://azurlane.nagami.moe/",
    "Origin": "https://azurlane.nagami.moe",
    "Accept": "*/*",
}

INDEX_MAX_AGE = 24 * 3600


class SourceError(RuntimeError):
    pass


def http_get(url: str, timeout: int = 60, retries: int = 2) -> bytes:
    last = None
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers=_HEADERS)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except urllib.error.HTTPError as e:
            if e.code == 404:
                raise SourceError("资源不存在（404）：" + url)
            last = e
        except Exception as e:  # noqa: BLE001
            last = e
        time.sleep(1.5 * (attempt + 1))
    raise SourceError("请求失败：%s（%s）" % (url, last))


def get_json(url: str):
    return json.loads(http_get(url).decode("utf-8"))


def try_get_json(url: str):
    try:
        return get_json(url)
    except SourceError:
        return None


def download(url: str, dest: str) -> bool:
    """下载到 dest。文件不存在（404）时返回 False，其它错误抛出。"""
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    try:
        data = http_get(url, timeout=120)
    except SourceError as e:
        if "404" in str(e):
            return False
        raise
    with open(dest, "wb") as f:
        f.write(data)
    return True


def load_spine_index(cache_dir: str, refresh: bool = False) -> list:
    """返回可用的 spine 皮肤列表（type == spine），结果本地缓存 24 小时。"""
    cache = os.path.join(cache_dir, "spine_index.json")
    fresh = os.path.exists(cache) and (time.time() - os.path.getmtime(cache)) < INDEX_MAX_AGE
    if refresh or not fresh:
        raw = http_get(DATA_BASE + "/spine/index.json", timeout=120)
        os.makedirs(cache_dir, exist_ok=True)
        with open(cache, "wb") as f:
            f.write(raw)
    with open(cache, "r", encoding="utf-8") as f:
        index = json.load(f)
    return [s for s in index.get("skins", []) if s.get("type") == "spine"]


def _pick(names, lang: str) -> str:
    """从 {CN, EN, JP} 里取指定语言，缺失时依次回退；忽略未解析的占位符（含 { ）。"""
    names = names or {}
    for key in (lang, "CN", "EN", "JP"):
        v = names.get(key) or ""
        if v and "{" not in v:
            return v
    return ""


def ship_name(entry: dict, lang: str = "CN") -> str:
    return _pick(entry.get("shipName"), lang) or entry.get("asset", "")


def skin_name(entry: dict, lang: str = "CN") -> str:
    return _pick(entry.get("skinName"), lang)


def skin_title(entry: dict, lang: str = "CN") -> str:
    """显示为 “琉·璃昂 — 在夜晚的酒馆中”；名字异常时回退到舰船名或素材名。"""
    title = _pick(entry.get("displayName"), lang)
    if not title:
        ship = ship_name(entry, lang)
        skin = skin_name(entry, lang)
        title = ("%s — %s" % (ship, skin)) if skin and ship != entry.get("asset") else ship
    return title or entry.get("asset", entry.get("id", ""))


def thumb_url(asset: str) -> str:
    return "%s/EN/shipyardicon/%s.png" % (ASSET_BASE, asset)


def fetch_thumb(thumb_dir: str, asset: str):
    """下载缩略图（216x288 PNG）到本地缓存，返回路径；站点没有该图返回 None。"""
    path = os.path.join(thumb_dir, asset + ".png")
    if os.path.exists(path) and os.path.getsize(path) > 0:
        return path
    if os.path.exists(path + ".none"):
        return None
    os.makedirs(thumb_dir, exist_ok=True)
    tmp = path + ".part"
    try:
        ok = download(thumb_url(asset), tmp)
    except SourceError:
        return None            # 网络问题：不留标记，下次还会重试
    if not ok:
        open(path + ".none", "w").close()
        return None
    os.replace(tmp, path)
    return path

class SkinBundle:
    """一个皮肤的全部在线数据（尚未下载文件）。"""

    def __init__(self, entry: dict, lang: str = "CN"):
        self.entry = entry
        self.id = str(entry["id"])
        self.asset = entry["asset"]
        self.title = skin_title(entry, lang)
        self.skin = None        # spine/<server>/skins/<id>.json
        self.model = None       # spine/EN/models/<asset>.json
        self.voices = {}        # event -> {text, cue}
        self.voice_server = "CN"
        self.bgm = None         # bgm name, e.g. "danmachi-az-story"
        self.warnings = []


def load_bundle(entry: dict, log=print, lang: str = "CN") -> SkinBundle:
    b = SkinBundle(entry, lang)
    b.skin = try_get_json("%s/spine/CN/skins/%s.json" % (DATA_BASE, b.id)) or \
             try_get_json("%s/spine/EN/skins/%s.json" % (DATA_BASE, b.id))
    if not b.skin:
        raise SourceError("找不到皮肤数据：" + b.id)

    b.model = get_json("%s/spine/EN/models/%s.json" % (DATA_BASE, b.asset))

    voices = try_get_json("%s/voices/CN/%s.json" % (DATA_BASE, b.id))
    if not voices:
        voices = try_get_json("%s/voices/EN/%s.json" % (DATA_BASE, b.id)) or {}
        b.voice_server = "EN"
        if voices:
            b.warnings.append("没有中文台词，台词改用英文。")
    b.voices = voices

    bgm_map = try_get_json("%s/skin-bgm/EN/bgm.json" % DATA_BASE) or {}
    b.bgm = bgm_map.get(b.id)
    if not b.bgm:
        b.warnings.append("没有找到该皮肤的 BGM，壁纸将不播放背景音乐。")

    layers = b.model.get("layers") or []
    if len(layers) > 1:
        b.warnings.append("模型有 %d 个图层，目前只使用主图层。" % len(layers))
    if not layers:
        raise SourceError("模型缺少图层数据：" + b.asset)
    return b


def asset_url(server: str, relative: str) -> str:
    return "%s/%s/%s" % (ASSET_BASE, server, relative)


def background_url(bundle: SkinBundle):
    bg = str(bundle.skin.get("background") or "").strip()
    if not bg:
        return None
    return asset_url("EN", "bg/star_level_bg_%s.png" % bg)


def bgm_url(bundle: SkinBundle):
    if not bundle.bgm:
        return None
    return asset_url("EN", "bgm/bgm-%s.ogg" % bundle.bgm)
