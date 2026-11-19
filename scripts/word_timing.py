# -*- coding: utf-8 -*-
"""词级时间戳：定位重复词与词缝空档"""
import os, json
os.environ.setdefault("HF_HOME", r"E:/workbuddy_models/hf_home")
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
os.environ.setdefault("OMP_NUM_THREADS", "4")
from faster_whisper import WhisperModel

SRC = r"E:/剪映/素材1/11月13日.mp4"
m = WhisperModel("medium", device="cpu", compute_type="int8",
                 download_root=r"E:/workbuddy_models/hf_home/hub")
segs, info = m.transcribe(SRC, language="zh", vad_filter=True,
                          word_timestamps=True, beam_size=5,
                          initial_prompt="以下是普通话口播，内容为美妆眼影推荐。")

words = []
for s in segs:
    for w in (s.words or []):
        words.append({"w": w.word.strip(), "s": round(w.start, 2),
                      "e": round(w.end, 2), "p": round(w.probability, 2)})

json.dump(words, open(r"C:/Users/DELL/WorkBuddy/2026-11-12-20-00-52/01_工作区/perception/words.json",
                      "w", encoding="utf-8"), ensure_ascii=False, indent=1)

# 打印关注区间
ZONES = [(0, 7), (24, 32), (55, 68), (69, 84)]
for a, b in ZONES:
    print(f"\n===== {a}-{b}s =====")
    for w in words:
        if a <= w["s"] <= b:
            print(f'{w["s"]:6.2f}-{w["e"]:6.2f}  {w["w"]}   ({w["p"]:.2f})')
