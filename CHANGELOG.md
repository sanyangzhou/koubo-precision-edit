# Changelog

## 1.2.0 - 2026-11-18

### Added
- 素材展示智能穿插（画中画 contain 安全缩放模板）
- ffmpeg 自动定位（PATH → imageio-ffmpeg）+ 缺失时智能体自动安装
- faster-whisper 原生层 segfault 降级路径（whisper.cpp 兜底 / 段级模式）
- gen_cover.py 封面标题字号自适应（超画布 92% 宽自动缩，防裁切）
- verify_sync.py 内置 349 字繁简兜底映射（opencc 缺失时生效）
- 文档：ASS 两大静默失败坑（绝对路径误解析 / 裸秒时间戳静默丢字幕）、BGM amix 音量档位、PIP contain 缩放模板

### Changed
- 能力介绍全面改版：免人工修字、表情体检、素材穿插等卖点前置
- 触发词扩充至 16 个

## 1.1.0 - 2026-11-18

### Added
- 停顿区表情体检：RMS 实测语音边界 + Haar 级联闭眼检测，区分表情动作与自然眨眼（≤0.15s 放行）
- pause_expression_scan.py 实测 8 处停顿精确命中 1 处真表情、零误杀
- cut-rules 停顿默认档 0.30s → 0.15s（用户既定呼吸偏好）
- 字幕实测校准（先变速后烧字幕 + 成片回转写模糊对齐）
- gen_cover.py 封面生成（选帧打分 + 顶部锚定 3:4 裁切 + 底部渐变暗带）

### Fixed
- verify_sync.py 繁体回转写拉低比对分数 → opencc 归一化

## 1.0.0 - 2026-11-17

- 首版：词级体检（全片词级转写 + 实测静音 silencedetect + 切片探针重转）、剪映草稿路线、
  决策单闸门、9 步流程框架
