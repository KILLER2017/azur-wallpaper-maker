# -*- coding: utf-8 -*-
"""
碧蓝航线皮肤 → Wallpaper Engine 壁纸生成器（Windows 桌面程序）。

带缩略图预览的皮肤选择器 → 一键下载模型、台词语音、背景、BGM → 生成 WE 网页壁纸工程。
用 Python 3.12（带完整 Tcl/Tk）运行：python wallpaper_maker.py
"""

import os
import queue
import sys
import threading
import traceback
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import builder  # noqa: E402
import nagami  # noqa: E402

# 数据目录放在 exe（或脚本）旁边，打包后不写入临时解压目录。
if getattr(sys, "frozen", False):
    APP_DIR = os.path.dirname(os.path.abspath(sys.executable))
else:
    APP_DIR = os.path.dirname(os.path.abspath(__file__))
CACHE_DIR = os.path.join(APP_DIR, "cache")
THUMB_DIR = os.path.join(CACHE_DIR, "thumbs")
OUTPUT_DIR = os.path.join(APP_DIR, "output")

FONT = "Microsoft YaHei UI"
THUMB_W, THUMB_H = 108, 144          # 卡片内缩略图（原图 216x288 的一半）
CELL_W, CELL_H = 128, 224            # 一个卡片格子（含间距）
CARD_W = 120
PAD = 8

COL_BG = "#f1f3f6"
COL_CARD = "#ffffff"
COL_BORDER = "#d3d8e0"
COL_SELECT = "#2f7de1"
COL_HOVER = "#9bbcea"
COL_PLACE = "#e3e7ed"
COL_SHIP = "#7a8599"
COL_TEXT = "#1f2937"

LANGS = [("中文", "CN"), ("English", "EN"), ("日本語", "JP")]


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        root.title("碧蓝航线 · 壁纸生成器")
        root.geometry("1180x780")
        root.minsize(1000, 660)

        self.skins = []          # 全部 spine 皮肤（已排序）
        self.visible = []        # 当前网格中显示的皮肤
        self.bundle = None       # 当前选中皮肤的在线信息
        self.selected_id = None
        self.selected_asset = None
        self.lang = "CN"
        self.busy = False
        self.log_queue = queue.Queue()
        self.ui_queue = queue.Queue()   # 后台线程只能把界面更新放进这里，由主线程执行

        # 缩略图
        self.thumbs = {}                 # asset -> PhotoImage(小) 或 None（站点无图）
        self.thumb_pending = set()
        self.thumb_jobs = queue.LifoQueue()   # 后进先出：优先加载刚滚动到的可见卡片
        self.asset_items = {}            # asset -> 当前布局里的图片 item id
        self.card_rects = {}             # skin id -> 边框 item id
        self.card_pos = []               # 每张卡片 (x, y)
        self.cols = 0
        self.preview_img = None
        self._relayout_job = None
        self._thumb_job = None
        self._hover_id = None

        self.blank = tk.PhotoImage(width=THUMB_W, height=THUMB_H)
        self.blank.put(COL_PLACE, to=(0, 0, THUMB_W, THUMB_H))
        self.blank_big = tk.PhotoImage(width=THUMB_W * 2, height=THUMB_H * 2)
        self.blank_big.put(COL_PLACE, to=(0, 0, THUMB_W * 2, THUMB_H * 2))

        self._build_ui()
        for _ in range(12):      # 单次请求延迟约 5 秒，靠并发提速
            threading.Thread(target=self._thumb_worker, daemon=True).start()
        self._poll_log()
        self.root.after(100, self.refresh_index)

    # ------------------------------------------------------------ UI
    def _build_ui(self):
        pad = {"padx": 8, "pady": 4}

        top = ttk.Frame(self.root)
        top.pack(fill="x", **pad)
        ttk.Label(top, text="搜索").pack(side="left")
        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", lambda *_: self._schedule_relayout(True, 200))
        ttk.Entry(top, textvariable=self.search_var, width=30).pack(side="left", padx=6)

        ttk.Label(top, text="名称语言").pack(side="left", padx=(14, 4))
        self.lang_var = tk.StringVar(value="CN")
        for label, code in LANGS:
            ttk.Radiobutton(top, text=label, value=code, variable=self.lang_var,
                            command=self.on_lang_change).pack(side="left", padx=2)

        ttk.Button(top, text="刷新皮肤列表", command=lambda: self.refresh_index(True)).pack(side="left", padx=(14, 0))
        self.count_var = tk.StringVar(value="")
        ttk.Label(top, textvariable=self.count_var).pack(side="left", padx=10)

        body = ttk.Frame(self.root)
        body.pack(fill="both", expand=True, **pad)

        # ---- 左：卡片网格
        left = ttk.Frame(body)
        left.pack(side="left", fill="both", expand=True)
        self.canvas = tk.Canvas(left, bg=COL_BG, highlightthickness=1, highlightbackground=COL_BORDER)
        self.vsb = ttk.Scrollbar(left, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self._on_yscroll)
        self.vsb.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.canvas.bind("<Configure>", lambda _e: self._schedule_relayout(False, 120))
        self.canvas.bind("<Enter>", lambda _e: self.canvas.bind_all("<MouseWheel>", self._on_wheel))
        self.canvas.bind("<Leave>", lambda _e: self.canvas.unbind_all("<MouseWheel>"))
        self.canvas.bind("<Motion>", self._on_motion)

        # ---- 右：预览与输出
        right = ttk.LabelFrame(body, text="皮肤预览与输出")
        right.pack(side="left", fill="y", padx=(8, 0), ipadx=6, ipady=4)

        self.preview_label = tk.Label(right, image=self.blank_big, bg=COL_PLACE, bd=0)
        self.preview_label.pack(padx=8, pady=(8, 4))

        self.info_var = tk.StringVar(value="请在左侧选择皮肤。")
        ttk.Label(right, textvariable=self.info_var, wraplength=300, justify="left").pack(anchor="w", padx=8, pady=4)

        self.voice_var = tk.BooleanVar(value=True)
        self.zip_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(right, text="下载台词语音（约 1 MB）", variable=self.voice_var).pack(anchor="w", padx=8)
        ttk.Checkbutton(right, text="同时打包 zip", variable=self.zip_var).pack(anchor="w", padx=8)

        ttk.Label(right, text="输出目录").pack(anchor="w", padx=8, pady=(10, 0))
        row = ttk.Frame(right)
        row.pack(fill="x", padx=8)
        self.outdir_var = tk.StringVar(value=OUTPUT_DIR)
        ttk.Entry(row, textvariable=self.outdir_var, width=28).pack(side="left", fill="x", expand=True)
        ttk.Button(row, text="选择…", command=self.pick_outdir).pack(side="left", padx=4)

        self.build_btn = ttk.Button(right, text="生成壁纸", command=self.start_build, state="disabled")
        self.build_btn.pack(fill="x", padx=8, pady=14)

        log_frame = ttk.LabelFrame(self.root, text="日志")
        log_frame.pack(fill="x", **pad)
        self.log_text = tk.Text(log_frame, height=6, state="disabled", wrap="word")
        self.log_text.pack(fill="both", expand=True, padx=6, pady=4)

    # ------------------------------------------------------------ helpers
    def _log(self, msg: str):
        self.log_queue.put(msg)

    def ui(self, fn):
        """线程安全：从后台线程请求在主线程执行界面更新。"""
        self.ui_queue.put(fn)

    def _poll_log(self):
        while not self.log_queue.empty():
            msg = self.log_queue.get_nowait()
            self.log_text.configure(state="normal")
            self.log_text.insert("end", msg + "\n")
            self.log_text.see("end")
            self.log_text.configure(state="disabled")
        while not self.ui_queue.empty():
            fn = self.ui_queue.get_nowait()
            try:
                fn()
            except Exception:  # noqa: BLE001
                self._log(traceback.format_exc())
        self.root.after(100, self._poll_log)

    def _set_busy(self, busy: bool):
        self.busy = busy
        self.ui(lambda: self.build_btn.configure(
            state="disabled" if busy or not self.bundle else "normal"))

    def pick_outdir(self):
        path = filedialog.askdirectory(title="选择输出目录", initialdir=self.outdir_var.get())
        if path:
            self.outdir_var.set(path)

    # ------------------------------------------------------------ index
    def refresh_index(self, force: bool = False):
        if self.busy:
            return
        self._set_busy(True)
        self._log("· 正在读取皮肤列表…")

        def work():
            try:
                skins = nagami.load_spine_index(CACHE_DIR, refresh=force)
                skins.sort(key=lambda s: (nagami.ship_name(s, "EN").lower(), str(s.get("id", ""))))
                self.skins = skins
                self._log("· 共 %d 个可用的 spine 皮肤" % len(skins))
                self.ui(lambda: self._schedule_relayout(True, 0))
            except Exception as e:  # noqa: BLE001
                self._log("✗ 读取皮肤列表失败：" + str(e))
            finally:
                self._set_busy(False)

        threading.Thread(target=work, daemon=True).start()

    def on_lang_change(self):
        self.lang = self.lang_var.get()
        self._schedule_relayout(True, 0)

    # ------------------------------------------------------------ grid
    def _filtered(self):
        q = self.search_var.get().strip().lower()
        if not q:
            return list(self.skins)
        out = []
        for s in self.skins:
            parts = [str(s.get("id", "")), str(s.get("asset", ""))]
            for key in ("displayName", "shipName", "skinName"):
                parts.extend((s.get(key) or {}).values())
            if q in " ".join(p for p in parts if p).lower():
                out.append(s)
        return out

    def _schedule_relayout(self, refilter: bool, delay: int):
        """防抖：搜索输入、窗口缩放时合并多次重排。"""
        if self._relayout_job:
            self.root.after_cancel(self._relayout_job)
        self._relayout_job = self.root.after(delay, lambda: self.relayout(refilter))

    @staticmethod
    def _clip(text: str, limit: int) -> str:
        return text if len(text) <= limit else text[:limit - 1] + "…"

    def relayout(self, refilter: bool = False):
        self._relayout_job = None
        width = self.canvas.winfo_width()
        if width < 50:
            return
        cols = max(1, (width - PAD) // CELL_W)
        if refilter:
            self.visible = self._filtered()
            self.canvas.yview_moveto(0)
            self.count_var.set("显示 %d / %d" % (len(self.visible), len(self.skins)))
        elif cols == self.cols and self.card_pos:
            return self.request_thumbs()
        self.cols = cols

        c = self.canvas
        c.delete("all")
        self.asset_items = {}
        self.card_rects = {}
        self.card_pos = []
        lang = self.lang
        for i, s in enumerate(self.visible):
            r, col = divmod(i, cols)
            x = PAD + col * CELL_W
            y = PAD + r * CELL_H
            self.card_pos.append((x, y))
            sid = str(s.get("id"))
            tag = "card%d" % i
            c.create_text(x + 2, y, anchor="nw", text=self._clip(nagami.ship_name(s, lang), 18),
                          fill=COL_SHIP, font=(FONT, 8), tags=tag)
            top = y + 16
            rect = c.create_rectangle(x, top, x + CARD_W, y + CELL_H - 10, fill=COL_CARD,
                                      outline=COL_SELECT if sid == self.selected_id else COL_BORDER,
                                      width=2 if sid == self.selected_id else 1, tags=tag)
            self.card_rects[sid] = rect
            thumb = self.thumbs.get(s["asset"]) or self.blank
            img = c.create_image(x + (CARD_W - THUMB_W) // 2, top + 6, anchor="nw", image=thumb, tags=tag)
            self.asset_items.setdefault(s["asset"], []).append(img)
            # 标签：背景 / BGM
            bx = x + (CARD_W - THUMB_W) // 2 + 3
            for key, label in (("bg", "背景"), ("bgm", "BGM")):
                if key in (s.get("tags") or []):
                    w = 28 if key == "bg" else 32
                    c.create_rectangle(bx, top + 9, bx + w, top + 22, fill="#27303d", outline="", tags=tag)
                    c.create_text(bx + w / 2, top + 15.5, text=label, fill="white", font=(FONT, 7), tags=tag)
                    bx += w + 3
            c.create_text(x + CARD_W / 2, top + 6 + THUMB_H + 6, anchor="n", width=CARD_W - 12,
                          text=self._clip(nagami.skin_name(s, lang) or nagami.skin_title(s, lang), 30),
                          fill=COL_TEXT, font=(FONT, 9), justify="center", tags=tag)
            c.tag_bind(tag, "<Button-1>", lambda _e, idx=i: self.select(idx))

        rows = (len(self.visible) + cols - 1) // cols
        c.configure(scrollregion=(0, 0, width, PAD * 2 + rows * CELL_H))
        self.request_thumbs()

    def _on_wheel(self, event):
        self.canvas.yview_scroll(int(-event.delta / 120) * 3, "units")

    def _on_yscroll(self, first, last):
        self.vsb.set(first, last)
        if self._thumb_job:
            self.root.after_cancel(self._thumb_job)
        self._thumb_job = self.root.after(100, self.request_thumbs)

    def _on_motion(self, event):
        """悬停高亮卡片边框。"""
        if not self.card_pos:
            return
        x = self.canvas.canvasx(event.x)
        y = self.canvas.canvasy(event.y)
        col = int((x - PAD) // CELL_W)
        row = int((y - PAD) // CELL_H)
        idx = row * self.cols + col
        sid = None
        if 0 <= col < self.cols and 0 <= row and 0 <= idx < len(self.visible):
            px, py = self.card_pos[idx]
            if px <= x <= px + CARD_W and py + 16 <= y <= py + CELL_H - 10:
                sid = str(self.visible[idx].get("id"))
        if sid == self._hover_id:
            return
        if self._hover_id in self.card_rects and self._hover_id != self.selected_id:
            self.canvas.itemconfig(self.card_rects[self._hover_id], outline=COL_BORDER, width=1)
        if sid and sid != self.selected_id:
            self.canvas.itemconfig(self.card_rects[sid], outline=COL_HOVER, width=2)
        self._hover_id = sid
        self.canvas.configure(cursor="hand2" if sid else "")

    # ------------------------------------------------------------ thumbnails
    def request_thumbs(self):
        self._thumb_job = None
        if not self.card_pos:
            return
        top = self.canvas.canvasy(0)
        bottom = top + self.canvas.winfo_height()
        # 倒序入栈 + 后进先出：可见区域内从上到下依次加载
        for i in range(len(self.visible) - 1, -1, -1):
            s = self.visible[i]
            y = self.card_pos[i][1]
            if y + CELL_H < top - CELL_H or y > bottom + CELL_H:
                continue
            asset = s["asset"]
            if asset in self.thumbs or asset in self.thumb_pending:
                continue
            self.thumb_pending.add(asset)
            self.thumb_jobs.put(asset)

    def _thumb_worker(self):
        while True:
            asset = self.thumb_jobs.get()
            try:
                path = nagami.fetch_thumb(THUMB_DIR, asset)
            except Exception:  # noqa: BLE001
                path = None
            self.ui(lambda a=asset, p=path: self._on_thumb(a, p))

    def _on_thumb(self, asset, path):
        self.thumb_pending.discard(asset)
        if not path:
            return                      # 暂时没有图：保持灰色占位，下次重排还会重试网络失败的
        try:
            img = tk.PhotoImage(file=path).subsample(2, 2)
        except tk.TclError:
            return
        self.thumbs[asset] = img
        for item in self.asset_items.get(asset, []):
            self.canvas.itemconfig(item, image=img)
        if self.selected_asset == asset:
            self._show_preview(asset)

    def _show_preview(self, asset):
        path = os.path.join(THUMB_DIR, asset + ".png")
        if os.path.exists(path):
            try:
                self.preview_img = tk.PhotoImage(file=path)
                self.preview_label.configure(image=self.preview_img)
                return
            except tk.TclError:
                pass
        self.preview_label.configure(image=self.blank_big)

    # ------------------------------------------------------------ select
    def select(self, idx: int):
        if idx >= len(self.visible):
            return
        entry = self.visible[idx]
        sid = str(entry.get("id"))
        if self.selected_id in self.card_rects:
            self.canvas.itemconfig(self.card_rects[self.selected_id], outline=COL_BORDER, width=1)
        self.selected_id = sid
        self.selected_asset = entry["asset"]
        self.canvas.itemconfig(self.card_rects[sid], outline=COL_SELECT, width=2)
        self.on_select(entry)

    def on_select(self, entry):
        lang = self.lang
        self.bundle = None
        self.build_btn.configure(state="disabled")
        self.info_var.set("正在读取：" + nagami.skin_title(entry, lang) + " …")
        self._show_preview(entry["asset"])
        if entry["asset"] not in self.thumbs:
            self.thumb_pending.add(entry["asset"])
            self.thumb_jobs.put(entry["asset"])
        self._set_busy(True)

        def work():
            try:
                bundle = nagami.load_bundle(entry, lang=lang)
                if self.selected_id != str(entry.get("id")):
                    return              # 读取期间用户已选了别的皮肤
                self.bundle = bundle
                lines = builder.build_lines(bundle)
                voiced = sum(1 for v in lines.values() if v.get("cue"))
                text = "%s\n\n编号：%s\n素材：%s\n台词：%d 条（%s）\nBGM：%s\n背景：%s" % (
                    bundle.title, bundle.id, bundle.asset, voiced,
                    "中文" if bundle.voice_server == "CN" else "英文",
                    bundle.bgm or "无",
                    bundle.skin.get("background") or "无",
                )
                self.ui(lambda: self.info_var.set(text))
                for w in bundle.warnings:
                    self._log("⚠ " + w)
                self._log("· 已选择：" + bundle.title)
            except Exception as e:  # noqa: BLE001
                self.ui(lambda: self.info_var.set("读取失败：" + str(e)))
                self._log("✗ 读取皮肤信息失败：" + str(e))
            finally:
                self._set_busy(False)
                self.ui(lambda: self.build_btn.configure(
                    state="normal" if self.bundle and not self.busy else "disabled"))

        threading.Thread(target=work, daemon=True).start()

    # ------------------------------------------------------------ build
    def start_build(self):
        if self.busy or not self.bundle:
            return
        out_root = self.outdir_var.get().strip() or OUTPUT_DIR
        bundle = self.bundle
        include_voice = self.voice_var.get()
        make_zip = self.zip_var.get()
        self._set_busy(True)
        self.build_btn.configure(state="disabled")
        self._log("=== 开始生成：%s ===" % bundle.title)

        def work():
            try:
                res = builder.build_project(bundle, out_root, include_voice=include_voice,
                                            make_zip=make_zip, log=self._log)
                self._log("=== 完成 ===")
                self._log("工程目录：" + res["out_dir"])
                if res["zip"]:
                    self._log("压缩包：" + res["zip"])
                for w in res["warnings"]:
                    self._log("⚠ " + w)
                self.ui(lambda: messagebox.showinfo(
                    "完成", "壁纸工程已生成：\n" + res["out_dir"] + "\n\n在 Wallpaper Engine 中创建网页壁纸，选择其中的 index.html。"))
            except Exception as e:  # noqa: BLE001
                self._log("✗ 生成失败：" + str(e))
                self._log(traceback.format_exc())
                self.ui(lambda: messagebox.showerror("生成失败", str(e)))
            finally:
                self._set_busy(False)
                self.ui(lambda: self.build_btn.configure(
                    state="normal" if self.bundle else "disabled"))

        threading.Thread(target=work, daemon=True).start()


def main():
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
