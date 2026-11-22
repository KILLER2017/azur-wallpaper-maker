# -*- coding: utf-8 -*-
"""
把一个碧蓝航线皮肤（SkinBundle）生成为 Wallpaper Engine 的 Web 壁纸工程。

产物结构：
    project.json  index.html  preview.png
    js/spine-webgl-3.8.js  js/skin.js  js/app.js
    assets/<skel> <atlas> <png...>  assets/background.<ext>
    assets/bgm/<bgm>.ogg  assets/voice/<事件名>.ogg
"""

import json
import os
import re
import shutil
import sys
import zipfile
from concurrent.futures import ThreadPoolExecutor

import nagami

# 源码运行：模板在脚本旁的 template/；PyInstaller 打包后：模板在 _MEIPASS 解压目录中。
if getattr(sys, "frozen", False):
    TEMPLATE_DIR = os.path.join(getattr(sys, "_MEIPASS", os.path.dirname(sys.executable)), "template")
else:
    TEMPLATE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "template")

# 点击身体时随机播放的台词：排除战斗语音、礼物语音和头部触碰（头部单独触发）
POOL_EXCLUDE_PREFIX = ("gift", "headtouch", "hp_warning", "lose", "skill", "win_mvp", "battle")

HEAD_REGION = [0.36, 0.26, 0.62, 0.44]   # 骨骼包围盒中上部的脸部区域，比例坐标（左上角为原点）


def safe_name(text: str) -> str:
    text = re.sub(r'[\\/:*?"<>|\r\n\t]+', "_", text).strip(" .")
    return text[:60] or "wallpaper"


def _fetch(url: str, dest: str) -> bool:
    """已存在的资源直接复用（文件名与内容由站点版本固定）；返回是否可用。"""
    if os.path.exists(dest) and os.path.getsize(dest) > 0:
        return True
    try:
        return nagami.download(url, dest)
    except nagami.SourceError:
        return False


def _cue_of(voice: dict) -> str:
    return str(voice.get("cue") or "")


def build_lines(bundle: nagami.SkinBundle):
    """事件名 → {expression, file, text}；并返回有语音的事件名列表。"""
    standard = (bundle.skin.get("expressions") or {}).get("standard") or {}
    lines = {}
    for event, voice in bundle.voices.items():
        cue = _cue_of(voice)
        if not cue:
            continue
        lines[event] = {
            "expression": str(standard.get(event) or ""),
            "file": event + ".ogg",
            "text": voice.get("text") or "",
            "cue": cue,
        }
    return lines


def choose_roles(lines: dict):
    """挑选问候、头部触碰与身体点击池。"""
    greet = "login" if "login" in lines else None
    head = None
    if "headtouch" in lines and lines["headtouch"]["expression"]:
        head = {"cue": "headtouch", "region": HEAD_REGION}
    pool = []
    for event, line in lines.items():
        if not line["expression"] or not line["text"]:
            continue
        if event.startswith(POOL_EXCLUDE_PREFIX) or "-battle" in line["cue"]:
            continue
        pool.append(event)
    return greet, head, pool


def expression_values(bundle: nagami.SkinBundle):
    standard = (bundle.skin.get("expressions") or {}).get("standard") or {}
    values = sorted({str(v) for v in standard.values() if str(v).strip()},
                    key=lambda v: int(v) if v.isdigit() else 999)
    return values


def _render_index(title: str, bg_css: str) -> str:
    with open(os.path.join(TEMPLATE_DIR, "index.html"), "r", encoding="utf-8") as f:
        text = f.read()
    return text.replace("{{TITLE}}", title).replace("{{BG}}", bg_css)


def _build_project_json(title: str, expressions: list, zoom: int = 105, x: int = 50, y: int = 46) -> dict:
    props = {
        "schemecolor": {"order": 0, "text": "ui_browse_properties_scheme_color", "type": "color",
                        "value": "0.08 0.06 0.05"},
        "zoom": {"index": 0, "max": 200, "min": 50, "order": 100, "step": 1,
                 "text": "缩放（%）", "type": "slider", "value": zoom},
        "voice": {"index": 1, "order": 101, "text": "播放语音", "type": "bool", "value": True},
        "effects": {"index": 2, "order": 102, "text": "光斑粒子特效", "type": "bool", "value": True},
        "bgm": {"index": 3, "order": 103, "text": "背景音乐", "type": "bool", "value": True},
        "bgmVolume": {"index": 4, "max": 100, "min": 0, "order": 104, "step": 1,
                      "text": "BGM 音量", "type": "slider", "value": 40},
        "voiceVolume": {"index": 5, "max": 100, "min": 0, "order": 105, "step": 1,
                        "text": "语音音量", "type": "slider", "value": 80},
        "interaction": {"index": 6, "order": 106, "text": "启用互动", "type": "bool", "value": True},
        "hints": {"index": 7, "order": 107, "text": "显示互动框", "type": "bool", "value": False},
        "greetOnStart": {"index": 8, "order": 108, "text": "启动时问候语音", "type": "bool", "value": True},
        "speed": {"fraction": True, "index": 10, "max": 2, "min": 0.2, "order": 110, "precision": 2,
                  "step": 0.05, "text": "播放速度（倍速）", "type": "slider", "value": 1},
        "fpsLimit": {"index": 11,
                     "options": [{"label": "跟随全局", "value": "0"}, {"label": "30 FPS", "value": "30"},
                                 {"label": "60 FPS", "value": "60"}, {"label": "120 FPS", "value": "120"}],
                     "order": 111, "text": "帧率限制", "type": "combo", "value": "0"},
        "alignH": {"index": 12,
                   "options": [{"label": "靠左", "value": "left"}, {"label": "居中", "value": "center"},
                               {"label": "靠右", "value": "right"}],
                   "order": 112, "text": "水平对齐", "type": "combo", "value": "center"},
        "alignV": {"index": 13,
                   "options": [{"label": "靠上", "value": "top"}, {"label": "居中", "value": "center"},
                               {"label": "靠下", "value": "bottom"}],
                   "order": 113, "text": "垂直对齐", "type": "combo", "value": "center"},
        "x": {"index": 14, "max": 100, "min": 0, "order": 114, "step": 1,
              "text": "水平位置（%）", "type": "slider", "value": x},
        "y": {"index": 15, "max": 100, "min": 0, "order": 115, "step": 1,
              "text": "垂直位置（%）", "type": "slider", "value": y},
        "showSubtitles": {"index": 16, "order": 116, "text": "显示台词", "type": "bool", "value": True},
    }
    options = [{"label": "待机", "value": "normal"}]
    options += [{"label": "表情 %s" % v, "value": v} for v in expressions]
    props["expression"] = {"index": 9, "options": options, "order": 109,
                           "text": "表情 / 姿势", "type": "combo", "value": "normal"}
    return {
        "contentrating": "Everyone",
        "description": title,
        "file": "index.html",
        "general": {"properties": props},
        "preview": "preview.png",
        "ratingsex": "none",
        "ratingviolence": "none",
        "tags": ["Anime"],
        "title": title,
        "type": "web",
        "version": 3,
    }


def build_project(bundle: nagami.SkinBundle, out_root: str, include_voice: bool = True,
                  make_zip: bool = False, log=print) -> dict:
    """
    生成壁纸工程到 out_root/<标题>_<id>/，返回 {"out_dir", "zip", "warnings"}。
    """
    warnings = list(bundle.warnings)
    title = bundle.title
    folder = os.path.join(out_root, "%s_%s" % (safe_name(title), bundle.id))
    assets = os.path.join(folder, "assets")
    os.makedirs(os.path.join(assets, "voice"), exist_ok=True)
    os.makedirs(os.path.join(folder, "js"), exist_ok=True)

    layer = bundle.model["layers"][0]
    skel_name = layer["skel"]
    atlas_name = layer["atlas"]
    textures = list(layer.get("textures") or [])
    anim = layer.get("startingAnimation") or "normal"
    skin_name = str(bundle.model.get("initialSkin") or bundle.skin.get("skeletonDefaultSkin") or "")

    # 1. 模板运行时
    shutil.copy2(os.path.join(TEMPLATE_DIR, "spine-webgl-3.8.js"),
                 os.path.join(folder, "js", "spine-webgl-3.8.js"))
    shutil.copy2(os.path.join(TEMPLATE_DIR, "app.js"), os.path.join(folder, "js", "app.js"))

    # 2. 三件套与贴图（保持原文件名）
    base = "spinepainting/%s/" % bundle.asset
    for name in [skel_name, atlas_name] + textures:
        log("· 下载 " + name)
        if not _fetch(nagami.asset_url("EN", base + name), os.path.join(assets, name)):
            raise nagami.SourceError("缺少模型文件：" + name)

    # 3. 背景
    bg_url = nagami.background_url(bundle)
    bg_css = "#14100d"
    bg_file = None
    if bg_url:
        ext = os.path.splitext(bg_url)[1] or ".png"
        bg_file = "background" + ext
        log("· 下载背景图")
        if _fetch(bg_url, os.path.join(assets, bg_file)):
            bg_css = "#14100d url(assets/%s) center/cover no-repeat" % bg_file
        else:
            warnings.append("背景图不存在，已用纯色底。")
            bg_file = None

    # 4. BGM
    bgm_rel = None
    bgm_src = nagami.bgm_url(bundle)
    if bgm_src:
        bgm_rel = "bgm/" + os.path.basename(bgm_src)
        log("· 下载 BGM")
        if not _fetch(bgm_src, os.path.join(assets, bgm_rel)):
            warnings.append("BGM 文件不存在，已关闭背景音乐。")
            bgm_rel = None

    # 5. 台词与语音
    lines = build_lines(bundle)
    if include_voice:
        jobs = [(nagami.asset_url(bundle.voice_server, "voicelines/%s.ogg" % line["cue"]),
                 os.path.join(assets, "voice", line["file"]), event)
                for event, line in sorted(lines.items())]
        log("· 下载语音 %d 条…" % len(jobs))
        with ThreadPoolExecutor(max_workers=6) as pool:
            results = list(pool.map(lambda j: (j[2], _fetch(j[0], j[1])), jobs))
        for event, ok in results:
            if not ok:
                warnings.append("语音缺失：" + event)
                lines[event]["file"] = None
    else:
        for line in lines.values():
            line["file"] = None

    greet, head, pool = choose_roles(lines)
    expressions = expression_values(bundle)

    # 6. 配置（运行时读取）
    skin_js = {
        "title": title,
        "skel": skel_name,
        "atlas": atlas_name,
        "textures": textures,
        "anim": anim,
        "skinName": skin_name or None,
        "bgm": bgm_rel,
        "lines": lines,
        "greet": greet,
        "head": head,
        "body": {"region": [0, 0, 1, 1]},
        "fallback": pool,
    }
    with open(os.path.join(folder, "js", "skin.js"), "w", encoding="utf-8") as f:
        f.write("window.SKIN = " + json.dumps(skin_js, ensure_ascii=False, indent=1) + ";\n")
    log("· 生成 js/skin.js（台词 %d 条，身体点击池 %d 条）" % (len(lines), len(pool)))

    # 7. 页面与 WE 工程
    with open(os.path.join(folder, "index.html"), "w", encoding="utf-8") as f:
        f.write(_render_index(title, bg_css))
    with open(os.path.join(folder, "project.json"), "w", encoding="utf-8") as f:
        json.dump(_build_project_json(title, expressions), f, ensure_ascii=False, indent="\t")

    # 8. 预览图：用背景图（没有背景则给出提示）
    if bg_file:
        shutil.copy2(os.path.join(assets, bg_file), os.path.join(folder, "preview.png"))
    else:
        warnings.append("没有背景图，preview.png 未生成，请在 WE 中手动设置预览图。")

    with open(os.path.join(folder, "skin_info.json"), "w", encoding="utf-8") as f:
        json.dump({"id": bundle.id, "asset": bundle.asset, "title": title,
                   "voiceServer": bundle.voice_server, "bgm": bundle.bgm,
                   "warnings": warnings}, f, ensure_ascii=False, indent=2)

    # 9. 校验
    for rel in ["project.json", "index.html", "js/app.js", "js/skin.js", "js/spine-webgl-3.8.js"]:
        if not os.path.exists(os.path.join(folder, rel)):
            raise FileNotFoundError("产物缺失：" + rel)
    with open(os.path.join(folder, "project.json"), "r", encoding="utf-8") as f:
        json.load(f)

    # 10. 可选 zip（平铺）
    zip_path = None
    if make_zip:
        zip_path = folder + ".zip"
        if os.path.exists(zip_path):
            os.remove(zip_path)
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for root, _, files in os.walk(folder):
                for name in files:
                    full = os.path.join(root, name)
                    zf.write(full, os.path.relpath(full, folder).replace("\\", "/"))
        log("· 打包：" + os.path.basename(zip_path))

    return {"out_dir": folder, "zip": zip_path, "warnings": warnings}
