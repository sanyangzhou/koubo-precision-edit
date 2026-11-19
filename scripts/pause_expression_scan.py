# -*- coding: utf-8 -*-
"""停顿区表情体检：扫描每个静音停顿及其前后的眼部状态，揪出撇眼/闭眼/下瞟/眨帧

为什么必须做：口播博主常在停顿时做小表情（撇眼、眨眼、低头），而
  1) ASR 词尾 padding 可达 0.6s+（实测「蝶」35.56 收尾，词尾标 36.20）——
     按 ASR 词边界下刀会把表情起始帧留在成片里；
  2) 表情动作在段级/词级时间轴上完全不可见，只有看帧才能发现。
本脚本自动化机械部分：RMS 实测语音真实起止 → 停顿窗口 ±WIDEN 逐帧抽帧 →
人脸+眼部级联检测闭眼帧 → 自动拼接异常帧网格供人工/AI 目检确认。

产出：pause_expression_report.md（每停顿：真实语音边界、异常帧区间、建议切点）
      + frames_gap_*.png（异常帧网格，必须目检确认后再定切点）

用法：
  python pause_expression_scan.py --input 素材.mp4 --out 01_工作区/xxx/perception
参数：
  --min-gap 0.35   静音判定阈值（秒），低于呼吸间隙不扫
  --widen 0.8      停顿窗口向外扩展秒数（表情常起于语音收尾瞬间）
  --keep-frames 0.15  建议保留的呼吸停顿（秒）——用户既定偏好
"""
import argparse, json, os, subprocess, sys, glob

import numpy as np
import cv2

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ffmpeg_locate import ensure_ffmpeg  # noqa: E402

FFMPEG = ensure_ffmpeg()   # 未装 ffmpeg 时打印安装指引并退出


def rms_envelope(video, t0, t1, step=0.04):
    """返回 [(t, db)] 能量包络（40ms 步长）"""
    import av
    c = av.open(video)
    ar = float(next(s for s in c.streams if s.type == 'audio').codec_context.sample_rate)
    frames = []
    for pkt in c.demux(audio=0):
        for f in pkt.decode():
            a = f.to_ndarray()
            if a.ndim == 2:
                a = a.mean(axis=0)
            frames.append(a)
    sig = np.concatenate(frames)
    dur = len(sig) / ar
    t1 = min(t1, dur)
    w = int(step * ar)
    out = []
    for i in range(int(t0 * ar), int(t1 * ar), w):
        seg = sig[i:i + w]
        r = float(np.sqrt((seg ** 2).mean()))
        out.append((round(i / ar, 3), round(20 * np.log10(r + 1e-9), 1)))
    return out, dur


def find_silences(env, db_thr=-42.0, min_gap=0.35):
    """从包络里找连续静音区（短促呼吸波动允许 ±4dB 抖动）"""
    runs, cur = [], None
    for t, db in env:
        if db < db_thr:
            if cur is None:
                cur = [t, t]
            else:
                cur[1] = t
        else:
            if cur is not None and cur[1] - cur[0] >= min_gap:
                runs.append(tuple(cur))
            cur = None
    if cur is not None and cur[1] - cur[0] >= min_gap:
        runs.append(tuple(cur))
    # 合并间隔 <0.12s 的碎静音（呼吸起伏）
    merged = []
    for r in runs:
        if merged and r[0] - merged[-1][1] < 0.12:
            merged[-1] = (merged[-1][0], r[1])
        else:
            merged.append(r)
    return [r for r in merged if r[1] - r[0] >= min_gap]


def speech_edge(env, gap, side):
    """停顿边界处的真实语音结束/开始时刻（最后一个/第一个 ≥-38dB 的采样）"""
    thr = -38.0
    if side == 'end':      # 停顿前：语音真实结束
        ts = [t for t, db in env if db >= thr and t <= gap[0]]
        return ts[-1] if ts else gap[0]
    ts = [t for t, db in env if db >= thr and t >= gap[1]]
    return ts[0] if ts else gap[1]


def eye_state(frame, face_cascade, eye_cascade):
    """返回 (是否检出人脸, 眼睛检出数, 眼部条带图)"""
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    faces = face_cascade.detectMultiScale(gray, 1.15, 5, minSize=(60, 60))
    if len(faces) == 0:
        return False, -1, None
    x, y, w, h = max(faces, key=lambda f: f[2] * f[3])
    strip = frame[y + int(h * 0.18): y + int(h * 0.55), x:x + w]
    if strip.size == 0:
        return True, -1, None
    g = cv2.cvtColor(strip, cv2.COLOR_BGR2GRAY)
    eyes = eye_cascade.detectMultiScale(g, 1.1, 6, minSize=(int(w * 0.12), int(w * 0.08)))
    return True, len(eyes), strip


def scan_gap(video, gap, out_dir, tag, widen=0.8, fps_limit=None):
    """抽停顿窗口 ±widen 的帧，检测闭眼帧，拼网格。返回异常区间列表。"""
    w0, w1 = max(0.0, gap[0] - widen), gap[1] + widen
    tmp = os.path.join(out_dir, f'_tmp_{tag}_%03d.png')
    subprocess.run([FFMPEG, '-v', 'error', '-y', '-ss', f'{w0:.3f}',
                    '-i', video, '-t', f'{w1 - w0:.3f}',
                    '-fps_mode', 'passthrough', tmp], check=True)
    files = sorted(glob.glob(tmp.replace('%03d', '*')))
    cascade_dir = cv2.data.haarcascades
    face_cascade = cv2.CascadeClassifier(os.path.join(cascade_dir, 'haarcascade_frontalface_default.xml'))
    eye_cascade = cv2.CascadeClassifier(os.path.join(cascade_dir, 'haarcascade_eye.xml'))

    states = []   # (t, face, eyes)
    strips = {}
    for i, p in enumerate(files):
        img = cv2.imdecode(np.fromfile(p, dtype=np.uint8), 1)
        if img is None:
            continue
        t = w0 + i / 30.0
        face, n, strip = eye_state(img, face_cascade, eye_cascade)
        states.append((t, face, n))
        if strip is not None and n <= 1:
            strips[t] = strip
    for p in files:
        os.remove(p)

    # 连续闭眼/可疑帧（eyes<=1）聚成区间
    runs, cur = [], None
    for t, face, n in states:
        bad = face and n <= 1
        if bad:
            if cur is None:
                cur = [t, t]
            else:
                cur[1] = t
        else:
            if cur is not None:
                runs.append(tuple(cur))
            cur = None
    if cur is not None:
        runs.append(tuple(cur))

    # 拼网格：异常区间 ±2 帧的眼部条带
    tiles = []
    for r in runs:
        for t in np.arange(max(w0, r[0] - 0.067), min(w1, r[1] + 0.067) + 0.001, 1 / 30.0):
            key = min(strips.keys(), key=lambda k: abs(k - t))
            s = strips.get(key)
            if s is None:
                continue
            s2 = cv2.resize(s, (200, 120))
            cv2.putText(s2, f'{t:.2f}s', (3, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 2)
            tiles.append(s2)
    grid_path = None
    if tiles:
        W = 6
        rows = []
        for i in range(0, len(tiles), W):
            row = tiles[i:i + W]
            while len(row) < W:
                row.append(np.zeros_like(row[0]))
            rows.append(np.hstack(row))
        grid = np.vstack(rows)
        grid_path = os.path.join(out_dir, f'frames_gap_{tag}.png')
        ok, buf = cv2.imencode('.png', grid)
        buf.tofile(grid_path)
    return runs, grid_path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--input', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--min-gap', type=float, default=0.35)
    ap.add_argument('--widen', type=float, default=0.8)
    ap.add_argument('--keep-frames', type=float, default=0.15,
                    help='建议保留的呼吸停顿（用户既定偏好 0.15s）')
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)

    env, dur = rms_envelope(args.input, 0, 999)
    gaps = find_silences(env, min_gap=args.min_gap)
    print(f'时长 {dur:.2f}s，实测静音停顿 {len(gaps)} 处\n')

    report = ['# 停顿区表情体检 · ' + os.path.basename(args.input), '',
              f'> 判据：语音真实边界按 RMS（≥-38dB）实测，不信 ASR 词边界（padding 可达 0.6s+）；',
              f'> 异常区间为眼部级联初筛结果，**切点必须经网格图目检确认**；',
              f'> 停顿默认压至 {args.keep_frames}s（用户既定偏好）；表情动作（撇眼/闭眼/下瞟/低头）一律删除。', '']
    findings = []
    BLINK_MAX = 0.15   # ≤0.15s 的单次异常 = 自然眨眼（正常，不删）；更长的才是表情动作
    for gi, gap in enumerate(gaps):
        s_end = speech_edge(env, gap, 'end')
        s_start = speech_edge(env, gap, 'start')
        runs, grid = scan_gap(args.input, gap, args.out, f'{gi}_{gap[0]:.2f}',
                              widen=args.widen)
        blinks = [r for r in runs if r[1] - r[0] <= BLINK_MAX]
        exprs = [r for r in runs if r[1] - r[0] > BLINK_MAX]
        findings.append({'gap': gap, 'speech_end': s_end, 'speech_start': s_start,
                         'anomaly_runs': runs, 'blinks': blinks, 'expressions': exprs,
                         'grid': grid})
        status = ('表情动作 ' + str([(round(a, 2), round(b, 2)) for a, b in exprs])) if exprs \
            else ('仅自然眨眼' if blinks else '干净')
        print(f'停顿 {gap[0]:.2f}-{gap[1]:.2f}（{gap[1]-gap[0]:.2f}s）  语音真实 {s_end:.2f}→{s_start:.2f}  '
              f'{status}')
        report.append(f'## 停顿 {gi+1}：{gap[0]:.2f} – {gap[1]:.2f}s（{gap[1]-gap[0]:.2f}s）')
        report.append(f'- 语音真实边界：{s_end:.2f} → {s_start:.2f}（ASR 词边界不可信）')
        if exprs:
            report.append(f'- **表情动作（必须删）**：' + '、'.join(f'{a:.2f}–{b:.2f}s' for a, b in exprs)
                          + f'（网格图 `{os.path.basename(grid)}`，目检确认）')
            report.append(f'- **建议切点**：入点 ≤ {max(0, exprs[0][0]-0.04):.2f}（表情前最后睁眼帧），'
                          f'出点 ≥ {min(dur, exprs[-1][1]+0.04):.2f}（表情后首个睁眼帧），'
                          f'保留呼吸 {args.keep_frames}s')
        elif blinks:
            report.append(f'- 仅自然眨眼（≤{BLINK_MAX}s，正常不删）：'
                          + '、'.join(f'{a:.2f}–{b:.2f}s' for a, b in blinks)
                          + '。若切点恰好落在眨眼帧上，入/出点各避让 0.04s 即可')
        else:
            report.append('- 眼部状态正常，按标准停顿压缩处理（保留 '
                          f'{args.keep_frames}s）')
        report.append('')
    json.dump(findings, open(os.path.join(args.out, 'pause_expression.json'), 'w',
                             encoding='utf-8'), ensure_ascii=False, indent=1)
    md = os.path.join(args.out, 'pause_expression_report.md')
    open(md, 'w', encoding='utf-8').write('\n'.join(report))
    n_bad = sum(1 for f in findings if f['expressions'])
    print(f'\n{len(gaps)} 处停顿：表情动作 {n_bad} 处（须删）、纯眨眼 '
          f'{sum(1 for f in findings if f["blinks"] and not f["expressions"])} 处 → {md}')
    sys.exit(0)


if __name__ == '__main__':
    main()
