# -*- coding: utf-8 -*-
"""口播封面生成：自动选最佳帧 + 3:4/9:16 裁切 + 标题文字排版

流程：
1. 在指定时间窗内均匀抽样帧，按「清晰度(Laplacian方差) + 人脸大小 + 眼睛睁开」打分选帧
   ——封面大忌是闭眼帧/模糊帧，选帧逻辑内置排除
2. 按目标比例居中裁切（默认 3:4 = 1080x1440 抖音封面规格，可选 9:16）
3. PIL 叠加标题：大字标题（白字黑描边）+ 可选副标题 + 可选底部色条强调

用法：
python gen_cover.py --video 素材.mp4 --out cover.png \
    --title "越饿越容易反弹" --subtitle "别再饿肚子减肥了" \
    --window 2 40 --ratio 3:4
"""
import argparse, os, sys, subprocess
import numpy as np
import cv2

WIN_FONT = 'C:/Windows/Fonts/msyhbd.ttc'   # 微软雅黑 Bold
WIN_FONT_REG = 'C:/Windows/Fonts/msyh.ttc'


def load_font(size, bold=True):
    from PIL import ImageFont
    path = WIN_FONT if bold and os.path.exists(WIN_FONT) else WIN_FONT_REG
    if not os.path.exists(path):
        path = 'C:/Windows/Fonts/simhei.ttf'  # 兜底黑体
    return ImageFont.truetype(path, size)


def pick_best_frame(video, t0, t1, n=14):
    """抽样帧 → 清晰度+人脸大小打分，返回 (时间, 帧)"""
    cap = cv2.VideoCapture(video)
    fps = cap.get(cv2.CAP_PROP_FPS) or 30
    dur = cap.get(cv2.CAP_PROP_FRAME_COUNT) / fps
    t0 = max(0, t0); t1 = min(dur - 0.1, t1)
    ts = list(np.linspace(t0, t1, n))
    face_cascade = cv2.CascadeClassifier(
        os.path.join(cv2.data.haarcascades, 'haarcascade_frontalface_default.xml'))
    eye_cascade = cv2.CascadeClassifier(
        os.path.join(cv2.data.haarcascades, 'haarcascade_eye.xml'))
    best = None  # (score, t, frame)
    for t in ts:
        cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
        ok, frame = cap.read()
        if not ok:
            continue
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        sharp = cv2.Laplacian(gray, cv2.CV_64F).var()
        h, w = frame.shape[:2]
        faces = face_cascade.detectMultiScale(gray, 1.1, 4, minSize=(w//8, w//8))
        face_area = 0.0
        eyes_open = True
        if len(faces):
            fx, fy, fw, fh = max(faces, key=lambda f: f[2] * f[3])
            face_area = (fw * fh) / (w * h)
            roi = gray[fy:fy + fh, fx:fx + fw]
            eyes = eye_cascade.detectMultiScale(roi, 1.1, 4)
            eyes_open = len(eyes) >= 1  # 检到眼=睁眼；闭眼帧检出眼数少
        # 清晰度为主，人脸占比加分，闭眼/无人脸扣分
        score = sharp / 50.0 + face_area * 20 + (3 if (eyes_open and face_area > 0.02) else -4)
        if best is None or score > best[0]:
            best = (score, t, frame)
    cap.release()
    if best is None:
        raise RuntimeError('时间窗内抽帧失败')
    return best[1], best[2]


def crop_ratio(frame, ratio):
    """按目标比例居中裁切并放大到标准宽度"""
    h, w = frame.shape[:2]
    if ratio == '9:16':
        tw, th = 1080, 1920
    else:  # 3:4
        tw, th = 1080, 1440
    target = tw / th
    cur = w / h
    if cur > target:   # 太宽 → 裁左右
        nw = int(h * target)
        x0 = (w - nw) // 2
        frame = frame[:, x0:x0 + nw]
    else:              # 太高 → 裁下（顶部锚定：人脸在上方，且胸口位的成片字幕被裁出画外）
        nh = int(w / target)
        frame = frame[0:nh]
    return cv2.resize(frame, (tw, th), interpolation=cv2.INTER_LANCZOS4)


def split_balanced(title, max_per_line=7):
    """均衡断行：尽量把字符均分到各行，避免孤字行"""
    if len(title) <= max_per_line:
        return [title]
    n_lines = -(-len(title) // max_per_line)
    base = len(title) // n_lines
    extra = len(title) % n_lines
    lines, i = [], 0
    for k in range(n_lines):
        take = base + (1 if k < extra else 0)
        lines.append(title[i:i + take])
        i += take
    return lines


def bottom_mask(img, frac=0.16):
    """底部渐变暗条：盖住源视频自带字幕，避免与封面标题打架（柔和渐变，不做成黑块）"""
    h = img.shape[0]
    y0 = int(h * (1 - frac))
    t = (np.arange(y0, h, dtype=np.float32) - y0) / (h - y0)
    alpha = (185 * t ** 2.5 / 255.0)[:, None, None]   # 底缘最多 ~73% 压暗（盖源字幕），向上快速变透明
    band = img[y0:h].astype(np.float32)
    dark = np.array([8, 6, 4], dtype=np.float32)
    img[y0:h] = (band * (1 - alpha) + dark * alpha).astype(np.uint8)
    return img


def draw_text(img_bgr, title, subtitle):
    """标题白字黑描边大字，副标题小一号；超宽自动缩字号防裁切；返回 PIL 图"""
    from PIL import Image, ImageDraw
    img = Image.fromarray(cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB))
    d = ImageDraw.Draw(img)
    W, H = img.size
    lines = split_balanced(title)
    # 字号自适应：任一行超过画布 92% 宽就缩小字号，直到全部放下（最低 40）
    size = 96
    while size > 40:
        stroke = max(3, size // 14)
        font = load_font(size)
        if all((d.textbbox((0, 0), ln, font=font, stroke_width=stroke)[2]
                - d.textbbox((0, 0), ln, font=font, stroke_width=stroke)[0])
               <= W * 0.92 for ln in lines):
            break
        size -= 4
    font = load_font(size)
    y = int(H * 0.60)
    stroke = max(3, size // 14)
    for ln in lines:
        bbox = d.textbbox((0, 0), ln, font=font, stroke_width=stroke)
        tw = bbox[2] - bbox[0]
        d.text(((W - tw) // 2 - bbox[0], y), ln, font=font, fill=(255, 255, 255, 255),
               stroke_width=stroke, stroke_fill=(20, 12, 8, 255))
        y += int(size * 1.22)
    if subtitle:
        f2 = load_font(int(size * 0.42), bold=False)
        bbox = d.textbbox((0, 0), subtitle, font=f2, stroke_width=2)
        tw = bbox[2] - bbox[0]
        d.text(((W - tw) // 2 - bbox[0], y + 18), subtitle, font=f2,
               fill=(255, 240, 200, 255), stroke_width=2, stroke_fill=(20, 12, 8, 255))
    return cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--video', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--title', required=True)
    ap.add_argument('--subtitle', default='')
    ap.add_argument('--window', nargs=2, type=float, default=[1.0, 40.0],
                    help='选帧时间窗（秒），默认 1-40s')
    ap.add_argument('--ratio', default='3:4', choices=['3:4', '9:16'])
    ap.add_argument('--at', type=float, default=None, help='手动指定帧时间，跳过自动选帧')
    args = ap.parse_args()

    if args.at is not None:
        cap = cv2.VideoCapture(args.video)
        cap.set(cv2.CAP_PROP_POS_MSEC, args.at * 1000)
        ok, frame = cap.read()
        cap.release()
        if not ok:
            sys.exit('指定时间抽帧失败')
        t = args.at
    else:
        t, frame = pick_best_frame(args.video, args.window[0], args.window[1])
        print(f'自动选帧 t={t:.2f}s')

    frame = crop_ratio(frame, args.ratio)
    frame = bottom_mask(frame)
    frame = draw_text(frame, args.title, args.subtitle)
    os.makedirs(os.path.dirname(args.out) or '.', exist_ok=True)
    ok, buf = cv2.imencode('.png', frame, [cv2.IMWRITE_PNG_COMPRESSION, 6])
    if not ok:
        sys.exit('PNG 编码失败（中文路径请用 imencode，本脚本已内置）')
    buf.tofile(args.out)
    print(f'COVER_OK: {args.out}  {frame.shape[1]}x{frame.shape[0]}')


if __name__ == '__main__':
    main()
