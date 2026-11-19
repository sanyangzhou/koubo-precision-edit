# -*- coding: utf-8 -*-
"""字幕实测校准：成片回转写词级时间戳 → 逐条模糊对齐字幕短语 → alignment.json

输出时间 = 成片（已 1.15x 变速）时间轴上的实测语音起止。
渲染脚本改为"先变速后烧字幕"，直接消费本文件，无需再做任何时间换算。
"""
import json, os, sys
from difflib import SequenceMatcher

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from word_audit import transcribe

VIDEO = '02_成片/11月17日_v1_终版_1080x1920.mp4'
OUT_JSON = '01_工作区/1117/alignment.json'

# (match_str, display_str) —— 与 render_1117.py 的 SUB_PHRASES 一致
PHRASES = [
    ('别再饿肚子减肥了', '别再饿肚子减肥了'),
    ('越饿越容易发痰', '越饿越容易发胖'),
    ('很多人减肥第一件事就是节食', '很多人减肥第一件事就是节食'),
    ('一天只吃一顿主食完全不吃', '一天只吃一顿 主食完全不吃'),
    ('短期体重看着是掉了', '短期体重看着是掉了'),
    ('掉的大多是水分和肌肉', '掉的大多是水分和肌肉'),
    ('不是脂肪', '不是脂肪'),
    ('真正健康的减脂', '真正健康的减脂'),
    ('可惜是制造温和的热量缺口', '靠的是制造温和的热量缺口'),
    ('不是把自己饿到虚脱', '不是把自己饿到虚脱'),
    ('第一主食别断', '第一 主食别断'),
    ('换种类白米饭面条减半', '换种类 白米饭面条减半'),
    ('替换成玉米红薯燕麦', '替换成玉米 红薯 燕麦'),
    ('碳水吃对才不容易暴食', '碳水吃对 才不容易暴食'),
    ('第二每餐必须要有蛋白质', '第二 每餐必须要有蛋白质'),
    ('鸡蛋鱼虾瘦肉豆腐都可以', '鸡蛋 鱼虾 瘦肉 豆腐 都可以'),
    ('蛋白质保住肌肉', '蛋白质保住肌肉'),
    ('保护感会更强', '饱腹感会更强'),
    ('第三运动不用猛练', '第三 运动不用猛练'),
    ('不用每天高强度的健身', '不用每天高强度的健身'),
    ('日常快走做家务爬楼梯', '日常快走 做家务 爬楼梯'),
    ('坚持每天活动30分钟就足够了', '坚持每天活动30分钟就足够了'),
    ('记住健康减脂速度', '记住 健康减脂速度'),
    ('一周0.5到1公斤是最合适的', '一周0.5到1公斤是最合适的'),
    ('慢慢瘦下来身体适应了', '慢慢瘦下来 身体适应了'),
    ('才不容易反弹', '才不容易反弹'),
    ('减肥改变习惯比短期拼命更重要', '减肥改变习惯 比短期拼命更重要'),
]

words = transcribe(VIDEO, 'medium', 'zh', None)
if not words:
    print('FAIL: 未识别出语音')
    sys.exit(1)
json.dump(words, open('01_工作区/1117/perception/out_words.json', 'w', encoding='utf-8'),
          ensure_ascii=False, indent=1)
print(f'成片词数 {len(words)}')

# 词展开为字符（词内等分）
chars = []
for wi, x in enumerate(words):
    t, s, e = x['t'], x['s'], x['e']
    n = len(t)
    for k in range(n):
        chars.append((t[k], s + (e - s) * k / n, s + (e - s) * (k + 1) / n))


def lcs_len(a, b):
    dp = [[0] * (len(b) + 1) for _ in range(len(a) + 1)]
    for i in range(len(a)):
        ai = a[i]
        row, nxt = dp[i], dp[i + 1]
        for j in range(len(b)):
            nxt[j + 1] = row[j] + 1 if ai == b[j] else max(row[j + 1], nxt[j])
    return dp[-1][-1]


LOOKAHEAD = 90  # 短语按序出现，起点只需在游标附近搜
result = []
cursor = 0
for match, disp in PHRASES:
    pc = ''.join(c for c in match if not c.isspace())
    n = len(pc)
    min_len = max(2, int(n * 0.6))
    max_len = int(n * 1.7) + 3
    best = None  # (score, span, -i, j) 分数优先；平局选更大窗口（保住模糊尾巴），再选更靠前
    for i in range(cursor, min(cursor + LOOKAHEAD, len(chars))):
        buf = ''
        for j in range(i, min(i + max_len, len(chars))):
            buf += chars[j][0]
            if j - i + 1 < min_len:
                continue
            score = lcs_len(buf, pc) / max(len(buf), n)
            span = j - i + 1
            cand = (score, span, -i, j + 1)
            if best is None or cand > best:
                best = cand
            if score >= 0.999:
                break
        if best and best[0] >= 0.999:
            break
    if best is None or best[0] < 0.6:
        raise RuntimeError(f'「{disp}」对齐失败（最高分 {best[0] if best else None}），游标 {cursor}')
    _, _, ni, j0 = best
    i0 = -ni
    # 用操作码裁掉窗口首尾的未匹配字符（识别差异/吞入的下句首字），时间只取匹配部分
    buf = ''.join(c[0] for c in chars[i0:j0])
    blocks = SequenceMatcher(None, buf, pc, autojunk=False).get_matching_blocks()
    blocks = [b for b in blocks if b.size > 0]
    if not blocks:
        raise RuntimeError(f'「{disp}」窗口无匹配块')
    m0, m1 = blocks[0].a, blocks[-1].a + blocks[-1].size
    start, end = chars[i0 + m0][1], chars[i0 + m1 - 1][2]
    cursor = i0 + m1  # 游标只推进到匹配部分末尾，未匹配尾巴留给下一句
    result.append({'match': match, 'display': disp,
                   's': round(start, 3), 'e': round(end, 3),
                   'score': round(best[0], 2)})
    print(f'  {start:6.2f}-{end:6.2f}  「{disp}」  score {best[0]:.2f}'
          f'  匹配「{''.join(c[0] for c in chars[i0+m0:i0+m1])}」')

json.dump(result, open(OUT_JSON, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
print(f'\nOK → {OUT_JSON}')
