# -*- coding: utf-8 -*-
"""成片回转写复核：确认重复词与空档真的被剪掉了

带切片探针，避免全片解码把残留的结巴"修顺"后误判通过。

用法:
  python verify_cut.py --input 02_成片/成片.mp4 --out 01_工作区/verify
  python verify_cut.py --input 成片.mp4 --out vf --expect "踩过:1,但是这:1,不是:1"

通过条件:
  - 短语重复 0 处
  - 实测静音 >= 阈值 的 0 处
  - 探针异常（转写被修顺，+2字以上）0 处
  - --expect 每个词实测次数 == 期望值

退出码 0 = 通过，1 = 不通过。交付前必跑。
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from word_audit import (transcribe, detect_silences, find_repeats, find_gaps,  # noqa: E402
                        find_single_repeats, suspicious_windows, probe, duration_of)


def count_occurrences(words, needle):
    return "".join(w["t"] for w in words).count(needle)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--model", default="medium")
    ap.add_argument("--lang", default="zh")
    ap.add_argument("--gap", type=float, default=0.45)
    ap.add_argument("--repeat-win", type=float, default=2.0)
    ap.add_argument("--expect", default=None, help='如 "踩过:1,但是这:1"')
    ap.add_argument("--baseline", default=None)
    ap.add_argument("--no-probe", action="store_true")
    args = ap.parse_args()

    os.makedirs(args.out, exist_ok=True)
    print(f"[1/3] 回转写成片: {args.input}", flush=True)
    words = transcribe(args.input, args.model, args.lang, None)
    if not words:
        print("FAIL: 成片未识别出语音（音轨丢失或人声被误压）", file=sys.stderr)
        return 1

    silences = detect_silences(args.input) or []
    reps = find_repeats(words, args.repeat_win)
    gaps = find_gaps(words, silences, args.gap)
    singles = find_single_repeats(words, args.repeat_win)

    probes = []
    if not args.no_probe and silences:
        total = duration_of(args.input)
        wins = suspicious_windows(words, gaps, silences, total)
        probes = probe(args.input, words, wins, args.model, args.lang,
                       os.path.join(args.out, "_probe"), args.repeat_win,
                       total=total, silences=silences)
        try:
            os.rmdir(os.path.join(args.out, "_probe"))
        except OSError:
            pass
    susp = [p for p in probes if p["repeats"]]

    json.dump({"source": os.path.abspath(args.input), "repeats": reps, "gaps": gaps,
               "single_repeats": singles, "probes": probes, "word_count": len(words)},
              open(os.path.join(args.out, "verify.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)

    # --expect 声明 ≥2 次的短语 = 正当复用（如「保住/保护感」被转写归并为同词），豁免重复拦截
    expected = {}
    if args.expect:
        for item in args.expect.split(","):
            item = item.strip()
            if not item:
                continue
            name, _, want = item.partition(":")
            expected[name] = int(want) if want else 1
    reps_ack = [r for r in reps if expected.get(r["text"], 0) >= 2]
    reps_fail = [r for r in reps if r not in reps_ack]

    print("[2/3] 复核", flush=True)
    print(f"  词数 {len(words)}")
    print(f"  短语重复 {len(reps_fail)} 处" + (f"（另有 {len(reps_ack)} 处已由 --expect 豁免）" if reps_ack else ""))
    for r in reps_fail:
        print(f"    ✗ 「{r['text']}」 {r['a_start']:.2f}-{r['a_end']:.2f} / "
              f"{r['b_start']:.2f}-{r['b_end']:.2f}（间隔 {r['gap']:.2f}s）")
    for r in reps_ack:
        print(f"    ○ 「{r['text']}」 {r['a_start']:.2f}s / {r['b_start']:.2f}s（--expect 豁免）")
    print(f"  空档（实测静音 ≥{args.gap}s）{len(gaps)} 处")
    for g in gaps:
        print(f"    ✗ {g['start']:.2f}-{g['end']:.2f}s  静音 {g['gap']:.2f}s  "
              f"{g['prev']}→{g['next']}")
    print(f"  探针异常 {len(susp)} 处")
    for p in susp:
        for r in p["repeats"]:
            print(f"    ✗ 「{r['text']}」 {r['a_start']:.2f}s / {r['b_start']:.2f}s"
                  f"（窗口 {p['start']:.2f}-{p['end']:.2f}s）")
    print(f"  单字重复 {len(singles)} 处（参考，不阻断）")

    ok = not reps_fail and not gaps and not susp

    print("[3/3] 关键词", flush=True)
    if args.expect:
        for name, want in expected.items():
            got = count_occurrences(words, name)
            if got != want:
                ok = False
            print(f"    {'✓' if got == want else '✗'} {name}: 实测 {got} / 期望 {want}")

    if args.baseline and os.path.exists(args.baseline):
        b = json.load(open(args.baseline, encoding="utf-8"))
        b_susp = sum(len(x.get("repeats", [])) for x in b.get("probes", []))
        print(f"  对比剪前：重复 {len(b.get('repeats', []))}→{len(reps)}，"
              f"空档 {len(b.get('gaps', []))}→{len(gaps)}，"
              f"探针异常 {b_susp}→{sum(len(p['repeats']) for p in susp)}")

    print("\n" + ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
