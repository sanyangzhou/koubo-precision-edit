#!/usr/bin/env python
"""本地转写工具 - 口播精剪技能第 3 步用

用法:
    python transcribe_local.py <音频或视频文件> [--out 输出目录] [--model medium|small|large-v3]

产出:
    transcript.json  每段 {start, end, text, avg_logprob}
    transcript.srt   可直接用的字幕
    模型缓存于 ~/.cache/huggingface，下载走国内镜像，之后离线可用。
"""
import os
import sys
import json
import argparse

# 国内镜像必须在 import huggingface 相关模块之前设置
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
# 模型缓存固定在 E 盘，不占 C 盘（2026-11-13 已迁移）
os.environ.setdefault("HF_HOME", "E:/workbuddy_models/hf_home")
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
os.environ.setdefault("OMP_NUM_THREADS", "4")

import time
from pathlib import Path
from faster_whisper import WhisperModel


def fmt_ts(seconds: float) -> str:
    ms = int(round(seconds * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("input")
    ap.add_argument("--out", default=None)
    ap.add_argument("--model", default="medium",
                    choices=["tiny", "base", "small", "medium", "large-v3"])
    ap.add_argument("--lang", default="zh")
    args = ap.parse_args()

    src = Path(args.input)
    if not src.exists():
        sys.exit(f"ERROR: 文件不存在 {src}")
    out_dir = Path(args.out) if args.out else src.parent / (src.stem + "_transcript")
    out_dir.mkdir(parents=True, exist_ok=True)

    t0 = time.time()
    print(f"[1/3] 加载模型 {args.model}（CPU int8）...", flush=True)
    model = WhisperModel(args.model, device="cpu", compute_type="int8")

    print(f"[2/3] 转写 {src.name} ...", flush=True)
    segments, info = model.transcribe(
        str(src),
        language=args.lang,
        vad_filter=True,
        vad_parameters={"min_silence_duration_ms": 300},
        beam_size=5,
        condition_on_previous_text=False,
    )

    rows = []
    for seg in segments:
        rows.append({
            "start": round(seg.start, 3),
            "end": round(seg.end, 3),
            "text": seg.text.strip(),
            "avg_logprob": round(seg.avg_logprob, 3),
        })
        print(f"  [{seg.start:8.2f} -> {seg.end:8.2f}] {seg.text.strip()}", flush=True)

    t1 = time.time()

    # transcript.json
    data = {
        "source": str(src),
        "model": args.model,
        "language": info.language,
        "duration": round(info.duration, 2),
        "transcribe_seconds": round(t1 - t0, 1),
        "segments": rows,
    }
    (out_dir / "transcript.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    # transcript.srt
    srt_lines = []
    for i, r in enumerate(rows, 1):
        srt_lines.append(f"{i}\n{fmt_ts(r['start'])} --> {fmt_ts(r['end'])}\n{r['text']}\n")
    (out_dir / "transcript.srt").write_text("\n".join(srt_lines), encoding="utf-8")

    print(f"[3/3] 完成：{len(rows)} 段，用时 {t1 - t0:.1f}s（素材 {info.duration:.1f}s）")
    print(f"  -> {out_dir / 'transcript.json'}")
    print(f"  -> {out_dir / 'transcript.srt'}")


if __name__ == "__main__":
    main()
