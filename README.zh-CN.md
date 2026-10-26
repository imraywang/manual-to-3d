# manual-to-3d

[English](README.md)

一句话，把家具的纸质组装说明书变成可交互的 3D 分步指导。

```
"LACK coffee table 90x55"  →  找到商品和说明书  →  Claude 逐页读图
→  生成 3D 动画场景  →  对照说明书零件清单校验  →  能直接播放的网页指导
```

<img src="docs/example-thumb.png" width="420" alt="生成的茶几 3D 模型">

在线案例：[zhuanghaole.com](https://zhuanghaole.com)（6 个商品，全部由这套流程生成）。

每个指导有分步动画、每步的零件清单、语音朗读，还能用语音口令（「下一步」「上一步」「重播」）空手翻页。灵感来自 [@nutlope 的 bygga](https://x.com/nutlope/status/2113715630386077804)。

## 原理

1. **找说明书**：在 IKEA 搜索商品，下载组装说明书 PDF，从商品页读外形尺寸；也可以直接给任何品牌的 PDF。
2. **抽取**：Claude 逐页读图，照抄零件清单和每一步印的「N×」，不推测。
3. **生成场景**：Claude 看步骤页和抽取结果，写出 scene JSON（板件、五金、坐标、机位、动画）。
4. **校验 + 修复**：核对零件数、几何穿插和悬空五金、每一步新零件在镜头里是否看得见；有 error 交回 Claude 修，最多 3 轮，保留最好的一版。
5. **播放**：单文件 Three.js 播放器，正交视角、说明书风格。

跑一次约 6–12 分钟。模型调用都走本机的 `claude` 命令行（`claude -p`），不用配 API key。

## 安装

需要：已登录的 [Claude Code](https://claude.com/claude-code)、Python 3.9+、poppler，可选 Google Chrome（渲染封面图）。

```bash
brew install poppler
git clone https://github.com/imraywang/manual-to-3d ~/.claude/skills/manual-to-3d
```

## 使用

在 Claude Code 里直接说：

> 把宜家 LACK 咖啡桌的说明书做成 3D 演示

或者直接跑：

```bash
python3 ~/.claude/skills/manual-to-3d/scripts/make.py "LACK coffee table 90x55" --lang zh
```

预览：

```bash
python3 -m http.server 8931 --directory ~/manual-to-3d
```

打开 http://127.0.0.1:8931/ 看案例页，`guide.html?scene=kallax-handmade` 是手写示例。

`--lang zh` 生成中文文字和朗读（另附英文版），默认英文。其他参数：`--pick N`、`--notes "…"`、`--reuse-extraction`、`--public`。输出在 `~/manual-to-3d`，用环境变量 `MANUAL_TO_3D_HOME` 改位置。

## 公开发布

`scripts/build_public.py` 生成 `dist/`（纯静态文件，放哪都能托管），**不含任何说明书原页**。说明书版权属于厂商，不要公开 `manuals/` 目录。

## 局限

- 板式、框架类家具效果最好：柜、架、桌、凳、斗柜。
- 曲木、软包、机构多的产品效果差；3D 讲不清的步骤会退回说明书插图。
- 生成结果可能有校验发现不了的错（比如零件装反），实际组装以纸质说明书为准。

## 许可

MIT。与 IKEA 及任何家具品牌无关，产品名称归各自的商标所有者。
