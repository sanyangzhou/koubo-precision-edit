# -*- coding: utf-8 -*-
"""词级体检：定位重复词/短语与词缝空档

三步：
  1. 全片词级转写
  2. 实测静音（ffmpeg silencedetect）判定空档
  3. 切片探针：对「停顿前后 / 超长字 / 低置信字」重转，
     抓全片转写被"修顺"掉的结巴（关键步骤，不能省）

用法:
  python word_audit.py --input 素材.mp4 --out 01_工作区/perception
  python word_audit.py --input 素材.mp4 --out out --no-probe   # 快速模式

产出:
  words.json / word_issues.json / word_issues.md
"""
import argparse
import json
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ffmpeg_locate import get_ffmpeg  # noqa: E402

FFMPEG = get_ffmpeg()

os.environ.setdefault("HF_HOME", os.path.join(
    os.path.expanduser("~"), ".workbuddy_models", "hf_home"))
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
os.environ.setdefault("OMP_NUM_THREADS", "4")

PUNCT = "，。、？！；：,.?!;: \t\n\u3000…—-～~()（）“”\"'‘’"
STOP_SINGLE = set("的了是在一个这那就也都很又和不我你他她它吗呢吧啊着过有与及或而之其")

_MODEL = None


def norm(s: str) -> str:
    return "".join(ch for ch in s if ch not in PUNCT)


def load_model(model_name):
    global _MODEL
    if _MODEL is None:
        from faster_whisper import WhisperModel
        _MODEL = WhisperModel(model_name, device="cpu", compute_type="int8",
                              download_root=os.path.join(os.environ["HF_HOME"], "hub"))
    return _MODEL


def transcribe(src, model_name="medium", lang="zh", prompt=None,
               vad=True, words=True, offset=0.0):
    model = load_model(model_name)
    segs, _info = model.transcribe(
        src, language=lang, vad_filter=vad, word_timestamps=words,
        beam_size=5, initial_prompt=prompt or None)
    out = []
    for s in segs:
        for w in (s.words or []):
            t = norm(w.word)
            if not t:
                continue
            dur = float(w.end) - float(w.start)
            if dur < 0.02:  # 幻觉词常表现为零长度，直接丢
                continue
            out.append({"w": w.word.strip(), "t": t,
                        "s": round(offset + float(w.start), 3),
                        "e": round(offset + float(w.end), 3),
                        "p": round(float(getattr(w, "probability", 1.0)), 2)})
        if not words:
            out.append({"w": s.text.strip(), "t": norm(s.text),
                        "s": round(offset + float(s.start), 3),
                        "e": round(offset + float(s.end), 3), "p": 1.0})
    return out


def detect_silences(src, noise_db=-33, min_dur=0.15):
    cmd = [FFMPEG, "-hide_banner", "-i", src,
           "-af", f"silencedetect=noise={noise_db}dB:d={min_dur}", "-f", "null", "-"]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, errors="ignore")
    except FileNotFoundError:
        return None
    starts = [float(x) for x in re.findall(r"silence_start: (-?[\d.]+)", r.stderr)]
    ends = [float(x) for x in re.findall(r"silence_end: ([\d.]+)", r.stderr)]
    out = []
    for i, s in enumerate(starts):
        if i >= len(ends):
            break
        if ends[i] - s > 0 and ends[i] > 0:
            out.append((max(s, 0.0), ends[i]))
    return out


def duration_of(src):
    # 优先 ffprobe；没有 ffprobe（如 imageio-ffmpeg 只带 ffmpeg）则从 ffmpeg 输出解析时长
    import shutil as _sh
    ffprobe = _sh.which("ffprobe")
    if ffprobe:
        r = subprocess.run([ffprobe, "-v", "error", "-show_entries", "format=duration",
                            "-of", "default=nw=1:nk=1", src],
                           capture_output=True, text=True, errors="ignore")
        try:
            return float(r.stdout.strip())
        except ValueError:
            pass
    if FFMPEG:
        r = subprocess.run([FFMPEG, "-i", src], capture_output=True, text=True, errors="ignore")
        m = re.search(r"Duration: (\d+):(\d+):([\d.]+)", r.stderr)
        if m:
            return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
    return 0.0


def overlap(a, b, segs):
    return sum(max(0.0, min(b, e) - max(a, s)) for s, e in segs)


def find_repeats(words, win=2.0, max_n=4):
    out = []
    n_words = len(words)
    for n in range(max_n, 1, -1):
        for i in range(n_words - n + 1):
            key = tuple(w["t"] for w in words[i:i + n])
            if len("".join(key)) < 2:
                continue
            for j in range(i + n, min(n_words - n + 1, i + 60)):
                gap = words[j]["s"] - words[i + n - 1]["e"]
                if gap > win:
                    break
                if tuple(w["t"] for w in words[j:j + n]) != key:
                    continue
                out.append({"type": "repeat", "n": n, "text": "".join(key),
                            "a_start": words[i]["s"], "a_end": words[i + n - 1]["e"],
                            "b_start": words[j]["s"], "b_end": words[j + n - 1]["e"],
                            "gap": round(gap, 2)})
                break
    kept = []
    for r in sorted(out, key=lambda x: (-x["n"], x["a_start"])):
        if not any(abs(k["a_start"] - r["a_start"]) < 0.06
                   and abs(k["b_start"] - r["b_start"]) < 0.06 for k in kept):
            kept.append(r)
    kept.sort(key=lambda x: x["a_start"])
    return kept


def find_single_repeats(words, win=2.0):
    out = []
    for i in range(len(words) - 1):
        if len(words[i]["t"]) != 1 or words[i]["t"] in STOP_SINGLE:
            continue
        for j in range(i + 1, min(len(words), i + 12)):
            if words[j]["s"] - words[i]["e"] > win:
                break
            if words[j]["t"] == words[i]["t"]:
                out.append({"type": "single", "text": words[i]["t"],
                            "a_start": words[i]["s"], "b_start": words[j]["s"],
                            "gap": round(words[j]["s"] - words[i]["e"], 2)})
                break
    return out


def find_gaps(words, silences, gap_min=0.45):
    if not silences:
        return []
    out = []
    for i in range(len(words) - 1):
        a, b = words[i]["e"], words[i + 1]["s"]
        if b - a < gap_min:
            continue
        real = overlap(a, b, silences)
        if real >= gap_min:
            out.append({"type": "gap", "gap": round(real, 2), "raw_gap": round(b - a, 2),
                        "start": a, "end": b, "prev": words[i]["t"], "next": words[i + 1]["t"]})
    return out


def suspicious_windows(words, gaps, silences, total,
                       long_word=0.85, low_p=0.6, wide=3.2):
    """需要切片重转的窗口，返回 (start, end, 是否含超长字)。

    窗口宽度有两难，实测结论：
      - 太宽（≥2.2s）：whisper 认为第一遍是废起头，直接丢掉 → 看不见重复
      - 太窄（≤1.8s）：装不下两遍完整表述 → 也看不见重复
    同一段素材里两种情形同时存在，所以探针必须级联：先宽后窄。

    锚点用「异常字」和「明显停顿」，不用词缝。
    """
    wins = []

    def add(anchor_s, anchor_e):
        start = max(0.0, anchor_s - 0.7)
        end = min(total, max(anchor_e + 0.7, start + 1.4))
        wins.append((start, min(end, start + wide)))

    for w in words:
        if (w["e"] - w["s"]) >= long_word or w["p"] < low_p:
            add(w["s"], w["e"])
    for s, e in silences:
        if e - s >= 0.25:
            wins.append((max(0.0, s - 0.55), min(total, min(e + 0.55, s + wide - 0.55))))

    wins.sort()
    merged = []
    for a, b in wins:
        if b - a < 0.8:
            continue
        if merged and a < merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], b))
        else:
            merged.append((a, b))

    out = []
    for a, b in merged:
        has_long = any((w["e"] - w["s"]) >= long_word and a <= w["s"] <= b for w in words)
        out.append((a, b, has_long))
    return out


def probe(src, words, windows, model_name, lang, tmpdir, repeat_win=2.0,
          total=None, silences=None):
    """级联切片重转：窄窗(1.8s)先试，抓不到再放宽到 2.9s。

    两个宽度都需要，因为同一素材里两种情形并存：
      窄窗 → 抓「踩过 + 0.19s + 踩过无数」这种紧邻结巴
      宽窗 → 抓「但是 + 但是这盘」这种需要更多上下文才成立的重复

    **跨度只受片长限制，不受锚点语义终点限制**——这是上一版的 bug：
    被截断后两个跨度一样长，等于没放宽。

    判据不在字数差（ASR 用字差异会误报），而在「这一小段内部出现相邻重复」。
    """
    if total is None:
        total = duration_of(src)
    silences = silences or []
    os.makedirs(tmpdir, exist_ok=True)
    out = []
    for idx, item in enumerate(windows):
        a = item[0]
        spans = [(a, min(total, a + 1.8)), (a, min(total, a + 2.9))]

        reps, best_words, used, best_text = [], [], None, ""
        for k, (x, y) in enumerate(spans):
            if y - x < 1.0:
                continue
            wav = os.path.join(tmpdir, f"probe_{idx:02d}_{k}.wav")
            subprocess.run([FFMPEG, "-v", "error", "-ss", f"{x:.2f}", "-i", src,
                            "-t", f"{y - x:.2f}", "-vn", "-ac", "1", "-ar", "16000", wav, "-y"],
                           capture_output=True)
            if not os.path.exists(wav):
                continue
            got = transcribe(wav, model_name, lang, prompt=None, vad=False, offset=x)
            try:
                os.remove(wav)
            except OSError:
                pass
            if not got:
                continue
            # 落在实测静音里的词一定不是人说的，是幻觉编的
            got = [g for g in got
                   if overlap(g["s"], g["e"], silences) < 0.5 * max(g["e"] - g["s"], 0.01)]
            if not got:
                continue
            speech = sum(g["e"] - g["s"] for g in got)
            if speech / max(y - x, 0.01) < 0.35:
                continue
            found = [r for r in find_repeats(got, repeat_win)
                     if r["a_start"] >= x - 0.05 and r["b_end"] <= y + 0.05]
            if found:
                reps, best_words, used = found, got, (x, y)
                best_text = "".join(g["t"] for g in got)
                break

        if not reps:
            continue
        # 同一处重复的嵌套匹配只留最长的那条
        reps.sort(key=lambda r: -(r["b_end"] - r["a_start"]))
        keep = []
        for r in reps:
            if not any(r["a_start"] >= k["a_start"] - 0.06 and r["b_end"] <= k["b_end"] + 0.06
                       for k in keep):
                keep.append(r)
        keep.sort(key=lambda r: r["a_start"])

        full_text = "".join(w["t"] for w in words if w["s"] >= a - 0.05 and w["e"] <= a + 2.9)
        out.append({"start": round(a, 2), "end": round(used[1], 2),
                    "probe_span": [round(used[0], 2), round(used[1], 2)],
                    "probe_text": best_text, "full_text": full_text,
                    "extra_chars": len(best_text) - len(full_text),
                    "repeats": keep, "words": best_words})
    return out


def to_md(issues, src, gap_min, win):
    reps, gaps, singles, probes = (issues["repeats"], issues["gaps"],
                                   issues["single_repeats"], issues["probes"])
    suspicious = [p for p in probes if p["repeats"]]
    L = [f"# 词级体检 · {os.path.basename(src)}", "",
         f"- 探针发现（全片转写藏起来的重复）：**{sum(len(p['repeats']) for p in suspicious)}** 处"
         f"，分布在 {len(suspicious)} 个窗口",
         f"- 短语重复（全片转写层面）：**{len(reps)}** 处（同片段间隔 ≤{win}s）",
         f"- 空档（实测静音 ≥{gap_min}s）：**{len(gaps)}** 处",
         f"- 单字重复（参考，滤虚词）：{len(singles)} 处", ""]

    if suspicious:
        L += ["## 零、探针发现（优先处理，这些是全片转写藏起来的）", "",
              "| 首次 | 再次 | 重复内容 | 全片转写 | 切片重转 |",
              "| --- | --- | --- | --- | --- |"]
        for p in suspicious:
            for r in p["repeats"]:
                L.append(f"| {r['a_start']:.2f}-{r['a_end']:.2f}s "
                         f"| {r['b_start']:.2f}-{r['b_end']:.2f}s "
                         f"| 「{r['text']}」 | {p['full_text']} | **{p['probe_text']}** |")
        L += ["", "> 全片解码会把结巴合并成一句、把停顿填进某个字里。"
              "**下刀用这张表的时间码**，那是切片重转算出来的，比全片转写准。", ""]
    else:
        L += ["## 零、探针发现", "", "无。全片转写与切片重转一致，没有藏起来的重复。", ""]

    L += ["## 一、短语重复（全片层面，已被上面覆盖的可忽略）", ""]
    if not reps:
        L += ["无。", ""]
    else:
        L += ["| 首次 | 再次 | 内容 | 间隔 | 建议 |", "| --- | --- | --- | --- | --- |"]
        for r in reps:
            L.append(f"| {r['a_start']:.2f}-{r['a_end']:.2f}s | {r['b_start']:.2f}-{r['b_end']:.2f}s "
                     f"| 「{r['text']}」({r['n']}字) | {r['gap']:.2f}s | 先找原片有无更完整的一次性表述；"
                     f"没有再保后删前 |")
        L += ["", "> 删前留后是默认（人重说第二遍更顺），例外是后一次被截断时删后留前。", ""]

    L += ["## 二、空档（实测静音）", ""]
    if not gaps:
        L += ["无。", ""]
    else:
        L += ["| 区间 | 静音 | 词缝 | 前→后 | 建议 |", "| --- | --- | --- | --- | --- |"]
        for g in gaps:
            target = 0.30 if g["gap"] >= 1.0 else 0.18
            L.append(f"| {g['start']:.2f}-{g['end']:.2f}s | {g['gap']:.2f}s | {g['raw_gap']:.2f}s "
                     f"| {g['prev']}→{g['next']} | 压到 {target:.2f}s |")
        L += ["", "> 0.3-0.45s 的短间隙是人声呼吸，不动；全压成 0 会变机关枪。", ""]

    if singles:
        L += ["## 三、单字重复（仅供人听）", ""]
        L += [f"- 「{s['text']}」 {s['a_start']:.2f}s / {s['b_start']:.2f}s（间隔 {s['gap']:.2f}s）"
              for s in singles[:12]]
        L += [""]
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--model", default="medium")
    ap.add_argument("--lang", default="zh")
    ap.add_argument("--gap", type=float, default=0.45)
    ap.add_argument("--repeat-win", type=float, default=2.0)
    ap.add_argument("--noise-db", type=float, default=-33)
    ap.add_argument("--prompt", default=None)
    ap.add_argument("--no-probe", action="store_true", help="跳过切片探针（快但不准）")
    args = ap.parse_args()

    os.makedirs(args.out, exist_ok=True)
    print(f"[1/4] 全片词级转写: {args.input}", flush=True)
    words = transcribe(args.input, args.model, args.lang, args.prompt)
    if not words:
        print("未识别到语音：无人声素材，跳过词级体检", file=sys.stderr)
        json.dump({"source": args.input, "repeats": [], "gaps": [], "single_repeats": [],
                   "probes": [], "word_count": 0},
                  open(os.path.join(args.out, "word_issues.json"), "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)
        return 0

    print(f"[2/4] 实测静音：{len(words)} 词", flush=True)
    silences = detect_silences(args.input, args.noise_db)
    if silences is None:
        print("警告: 找不到 ffmpeg，空档检测跳过（pip install imageio-ffmpeg 可修复）", file=sys.stderr)
        silences = []
    reps = find_repeats(words, args.repeat_win)
    gaps = find_gaps(words, silences, args.gap) if silences else []

    probes = []
    if not args.no_probe and silences:
        total = duration_of(args.input)
        wins = suspicious_windows(words, gaps, silences, total)
        print(f"[3/4] 切片探针：{len(wins)} 个可疑窗口", flush=True)
        probes = probe(args.input, words, wins, args.model, args.lang,
                       os.path.join(args.out, "_probe"), args.repeat_win,
                       total=total, silences=silences)
        try:
            os.rmdir(os.path.join(args.out, "_probe"))
        except OSError:
            pass
    else:
        print("[3/4] 跳过探针", flush=True)

    issues = {"source": os.path.abspath(args.input), "gap_threshold": args.gap,
              "repeat_window": args.repeat_win, "word_count": len(words),
              "silence_count": len(silences), "repeats": reps, "gaps": gaps,
              "single_repeats": find_single_repeats(words, args.repeat_win),
              "probes": probes}

    json.dump(words, open(os.path.join(args.out, "words.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    json.dump(issues, open(os.path.join(args.out, "word_issues.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    open(os.path.join(args.out, "word_issues.md"), "w", encoding="utf-8").write(
        to_md(issues, args.input, args.gap, args.repeat_win))

    susp = [p for p in probes if p["repeats"]]
    print(f"[4/4] 重复 {len(reps)} / 空档 {len(gaps)} / "
          f"探针异常 {sum(len(p['repeats']) for p in susp)}（{len(susp)} 窗）", flush=True)
    print(f"      → {os.path.join(args.out, 'word_issues.md')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
