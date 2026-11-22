# 碧蓝航线皮肤 → Wallpaper Engine 壁纸生成器（桌面程序）设计

状态：已确认（用户回复"你开始吧"，按我提出的方案执行）

## 目的
为自己批量制作喜欢的角色壁纸。在桌面窗口里搜索网站 Azur Lane Dynamic Skin Viewer 上的皮肤，一键下载资源并生成可导入 Wallpaper Engine 的 Web 壁纸工程。

## 方案（已选）
- 独立 Python 桌面程序（tkinter，仅标准库），不依赖 .NET 和 SpineViewerCLI。
- 数据全部来自网站公开 JSON 与文件：`data.nagami.moe` 与 `azlassets.nagami.moe`。请求需带浏览器 User-Agent 和 Referer 头，否则返回 403。
- 壁纸运行时沿用已验证的 `index1` 版本（Spine 3.8 WebGL、程序化光斑粒子、语音、BGM、台词、点击互动、暂停处理），把皮肤相关内容改为由数据生成的配置文件。

## 数据映射（已用琉·璃昂 11400021 验证）
- 皮肤列表：`data.nagami.moe/spine/index.json`，只保留 `type == spine`（spinePlus 格式不同，暂不支持）。
- 模型：`data.nagami.moe/spine/EN/models/<asset>.json` 的 `layers[0]`，给出 skel、atlas、textures，文件位于 `azlassets.nagami.moe/EN/spinepainting/<asset>/`。
- 表情：`data.nagami.moe/spine/CN/skins/<id>.json` 的 `expressions.standard`（事件名 → 表情 1–8，空字符串表示无表情）。
- 台词与语音：`data.nagami.moe/voices/CN/<id>.json`（事件名 → text、cue）。语音文件 `azlassets.nagami.moe/CN/voicelines/<cue>.ogg`。CN 不存在时回退 EN。
- 背景：皮肤的 `background` 字段 → `azlassets.nagami.moe/EN/bg/star_level_bg_<id>.png`。
- BGM：`data.nagami.moe/skin-bgm/EN/bgm.json[<id>]` → `azlassets.nagami.moe/EN/bgm/bgm-<name>.ogg`。

## 我做的决定（请过目）
1. 点击互动：头部/身体热区不再用骨骼槽位（每个皮肤槽位不同），改为按骨骼包围盒的比例区域：头部 = 顶部中间区域（触发 `headtouch`），身体 = 整个包围盒（随机触发 `touch2` 等）。这是通用近似，琉·璃昂的手工精确热区会略有差异。
2. 特效：不使用网站的 MP4 粒子（WE 中无法显示），统一使用程序化光斑粒子，与 index1 当前效果一致。
3. 预览图：直接用背景图作为 `preview.png`，不依赖 CLI 导出。
4. 表情下拉：从该皮肤 `expressions.standard` 中实际用到的表情编号生成，加上"待机"。
5. 语音：默认只下载台词里出现过的事件语音，并在 `assets/voice/` 按事件名保存。
6. 输出：每个皮肤一个文件夹，可选同时打包 zip。
7. 不使用 index1 的 `meta-effects.json` 和 `effects` 资源目录。

## 不做（YAGNI）
- 不做 Live2D、spinePlus、多层皮肤。
- 不做视频/GIF 导出。
- 不做 WE 工坊自动上传。

## 验证
- 离线：用缓存的 JSON 检查生成的 `project.json`、`js/skin.js`。
- 在线：真实下载琉·璃昂并生成工程，然后用本地 http 服务在浏览器中打开，检查渲染、台词与表情、语音、BGM 和点击。
