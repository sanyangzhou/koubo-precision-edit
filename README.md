<div align="center">

# koubo-precision-edit · 口播词级精剪

**Talking-Head Word-Level Precision Editor**

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Version](https://img.shields.io/badge/version-1.2.0-blue.svg)](CHANGELOG.md)
[![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey.svg)]()

一条流水线，把口播素材剪到「一次交付直接进精修」：
词级下刀 · 表情体检 · 字幕实测校准 · 成片回转写质检闸门

GitHub：https://github.com/sanyangzhou/koubo-precision-edit
Gitee 镜像（国内访问更快）：https://gitee.com/sanyangzhou/koubo-precision-edit

</div>

---

## 为什么需要它

全片 ASR 只能给你段级时间轴——**口误、重复、隐藏结巴在段级时间轴上根本不存在**，
停顿区的撇眼/闭眼更是只有看帧才能发现。这个技能把这些问题全部机械化解决，
审美判断（节奏、构图、调色、包装）保留给用户拍板。

| 能力 | 说明 |
| --- | --- |
| 词级体检 | word-level 时间戳 + 实测静音（非 ASR 词边界差）+ 切片探针重转，抓出全片转写「修顺」掉的口误与重复 |
| 停顿区表情体检 | RMS 实测语音真实边界 → 停顿窗口逐帧抽帧 → 人脸/眼部级联检测，撇眼/闭眼帧自动标注，建议切点避开表情帧 |
| 字幕实测校准 | 先变速后烧字幕；成片回转写 + 滑动窗口模糊对齐，字幕轴逐帧对齐语音 |
| 素材智能穿插 | 按台词语义把图片/视频素材排进合适的时间位置（画中画 contain 等比缩放，不拉伸不溢出） |
| 网感封面 | 选帧（清晰度+人脸+睁眼打分）→ 3:4 竖版封面，标题超宽自动缩字号 |
| 质检闸门 | 成片回转写逐条复核字幕区间实听内容，不 PASS 不交付 |
| 决策单 | 所有剪切点以决策单形式给用户确认，未经确认绝不动刀 |

## 安装

### WorkBuddy（推荐）

在 WorkBuddy 技能市场搜索「口播词级精剪」直接安装，环境依赖由智能体自动补齐。

### Claude Code / 任意支持 Agent Skills 的环境

```bash
# 方式一：clone 到 skills 目录
git clone https://github.com/sanyangzhou/koubo-precision-edit.git ~/.claude/skills/koubo-precision-edit

# 国内网络下载慢，用 Gitee 镜像或代理直链：
# git clone https://gitee.com/sanyangzhou/koubo-precision-edit.git ~/.claude/skills/koubo-precision-edit
# https://gh-proxy.com/https://github.com/sanyangzhou/koubo-precision-edit/archive/refs/heads/main.zip
```

### 依赖说明（缺什么都能干活，能力边界如实告知）

| 级别 | 依赖 | 缺失时 |
| --- | --- | --- |
| L0 必须 | ffmpeg | 脚本自动定位 PATH / imageio-ffmpeg；都没有则一条 `pip install imageio-ffmpeg` 补齐 |
| L1 词级 | faster-whisper | 部分机器 ctranslate2 原生层会 segfault → 自动降级 whisper.cpp / 段级模式 |
| L1 表情 | opencv-python==4.10.0.84 | 5.x 移除了人脸级联，必须钉版本；装不上跳过表情体检 |
| L2 对齐 | opencc-python-reimplemented | 装不上则用内置 349 字繁简兜底映射 |

## 用法

把素材丢给智能体，一句话触发：

```
按口播词级精剪流程处理 @素材.mp4
用口播词级精剪剪这条口播，1.15 倍速、加基础字幕，出 1080x1920 竖版
帮我把这条视频的口误、长停顿清掉，出剪映草稿就行，不用渲染成片
```

智能体会走 9 步流程：环境自检 → 参数问询 → 素材盘点 → 转写打轴 → 词级+表情体检
→ **决策单（用户确认闸门）** → 执行剪辑 → 回转写复核 → QA 交付。

## 五条铁律

1. 未经确认的剪辑清单绝不动刀
2. 源素材只读，产物全部写工作区
3. 机械活自动化，审美活给选项不替用户定
4. 边界如实说：转写错字率 2%-5% 压不到零，写进交付说明
5. 成片必须回转写复核，不 PASS 不交付

## Roadmap

- [x] 词级体检 + 切片探针
- [x] 停顿区表情体检（一次性过）
- [x] 字幕实测校准 + 回转写质检
- [x] ffmpeg 自动定位与自动安装
- [ ] Pro：素材穿插自动化、封面多风格、BGM 卡点、多平台规格批量输出

## License

[MIT](LICENSE) — 自由使用、修改、分发。学思路不抄代码，抄了记得改错别字。
