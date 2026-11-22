# 碧蓝航线 · 壁纸生成器

搜索碧蓝航线 Dynamic Skin Viewer 网站上的皮肤，一键下载模型、台词语音、背景和 BGM，生成可直接导入 **Wallpaper Engine** 的网页壁纸。

## 运行

- **推荐：** 双击 `dist\碧蓝航线壁纸生成器.exe`。单文件、约 11 MB，无需安装 Python。
  - 第一次启动会在 exe 旁边生成 `cache\`（皮肤列表缓存）和 `output\`（生成结果）。
- 源码运行：双击 `启动壁纸生成器.bat`（需要 Python 3.12，路径 `D:\Program Files\Python312\`），或 `python wallpaper_maker.py`。源码运行只使用标准库。

## 重新打包 exe

```
"D:\Program Files\Python312\python.exe" -m PyInstaller --noconsole --onefile --clean --noconfirm --name "碧蓝航线壁纸生成器" --add-data "template;template" wallpaper_maker.py
```

需要先安装 PyInstaller（`pip install pyinstaller`）。产物在 `dist\`。

## 使用

1. 启动后自动读取皮肤列表（缓存 24 小时，可点“刷新皮肤列表”）。
2. 皮肤以带缩略图的卡片网格显示（按舰船英文名排序，卡片上方是舰船名，下方是皮肤名，左上角标出有无背景 / BGM）。缩略图只在滚动到可见区域时才下载，并缓存到 `cache\thumbs\`，首次浏览会稍慢。
3. 在搜索框输入中文名、英文名、日文名、编号或素材名过滤；顶部可切换名称语言（中文 / English / 日本語）。
4. 点击卡片，右侧显示大图预览和信息。确认是否下载语音、是否打包 zip。
5. 点“生成壁纸”，结果保存在输出目录（默认 `output\`）下的 `<皮肤名>_<编号>\` 文件夹中。
6. 在 Wallpaper Engine 中创建网页壁纸，选择该文件夹中的 `index.html`。

## 生成的壁纸功能

- 角色 Spine 动画循环，表情 1–8 与台词按网站数据对应。
- 台词字幕（可在 WE 中关闭）、语音（可关闭）、BGM（可关闭）。
- 光斑粒子特效（可关闭）。
- 点击头部播放头部触碰台词，点击身体随机播放一句。
- 属性：缩放、速度、帧率、对齐、位置、表情、音量、显示互动框（调试用）。

## 注意

- 点击热区是按骨骼包围盒的比例估算的，并非每个皮肤的精确热区。可以在 WE 里打开“显示互动框”查看并调整。
- 目前只支持网站上的 `spine` 类型皮肤，不支持 `spinePlus`。
- 个别皮肤没有中文台词，会自动改用英文，并给出提示。
- 下载的素材版权归游戏官方所有，仅限个人使用，请勿公开上传或商用。
