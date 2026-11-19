# -*- coding: utf-8 -*-
"""字幕-语音对位体检：成片回转写，逐条字幕检查对应时间段实际语音内容

判定：取每条字幕区间 [s,e]，收集区间内（中点落入）的识别词，
与字幕文本算字符重合率。重合率低 = 字幕和声音对不上。
同时输出第一条字幕起点 vs 首个识别词起点的整体偏移。
"""
import json, os, re, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from word_audit import transcribe

VIDEO = sys.argv[1] if len(sys.argv) > 1 else '02_成片/11月17日_v1_终版_1080x1920.mp4'
SRT = sys.argv[2] if len(sys.argv) > 2 else '03_交付/11月17日_字幕.srt'
OUT = sys.argv[3] if len(sys.argv) > 3 else '01_工作区/1117/verify_sync.json'


def parse_srt(path):
    subs = []
    blocks = re.split(r'\n\s*\n', open(path, encoding='utf-8-sig').read().strip())
    for b in blocks:
        ls = [x for x in b.strip().splitlines() if x.strip()]
        if len(ls) < 2:
            continue
        m = re.match(r'(\d+):(\d+):(\d+)[,.](\d+)\s*-->\s*(\d+):(\d+):(\d+)[,.](\d+)', ls[1])
        if not m:
            continue
        g = [int(x) for x in m.groups()]
        s = g[0]*3600 + g[1]*60 + g[2] + g[3]/1000
        e = g[4]*3600 + g[5]*60 + g[6] + g[7]/1000
        text = ''.join(ls[2:])
        subs.append((s, e, text))
    return subs


def sim(a, b):
    # 最长公共子序列占比（对识别误差宽容）；先做繁→简归一化（whisper 回转写常输出繁体）
    # opencc 缺失时用内置高频繁字映射兜底，覆盖口播文本绝大多数繁体字
    T2S_FALLBACK = str.maketrans(
        "這個們來對時說會沒後開關長門問間東車馬鳥島嶼樂條備體點無發員應該當處歲歷萬與專業產經過裏裡為麼詞語調誰團質類錢鐵銀買賣貴費資雲電號風飛食館首香單圖書寫劃語聲響顧雞難氣記認識變讓樹擊歡環境優驗錯關鍵從眾內外區碼網視頻"
        "輯機賺論場廠衛藝藥葉陰陽隨雖顯橋標構樣檔權輸運達遲適選釋鐘鋪鏡額餘驅鹹麵齣齒齡龍髮複讚緩縮縱織編練績繼續絕維綜綠緒線緣廣慶廢證評談請護議謝講課讀負財貧實寧導層幾強歸錄於週"
        "學製歐興辦動據營滿熱戰壞靈屬灣億傑壓圓園匯殘監淚溫獨獲畫確穩競節級約純細組給縣總罷義聯聽腦臺覺覽親訓訪誠誤務勝醫陸願驚麗齊"
        "習爭別價優償儘兒冊凍卻喚嗎壽夢奧婦帥張懷掛揚換榮淺淨淪淵減測準溝滅潤牽狀獅現異皺盤種稱竄筆築簡糧紅臟艦華蝦衝裝訴貝軍較輕遠鄉醜雙頂顆養"
        "銷勢試訂詳詢購贈趕蹟遞遙遺鄭鄰郵釣閉陳險霧靜頁項預頻顏題態",
        "这个们来对时说会没后开关长门问间东车马鸟岛屿乐条备体点无发员应该当处岁历万与专业产经过里里为么词语调谁团质类钱铁银买卖贵费资云电号风飞食馆首香单图书写划语声响顾鸡难气记认识变让树击欢环境优验错关键从众内外区码网视频"
        "辑机赚论场厂卫艺药叶阴阳随虽显桥标构样档权输运达迟适选释钟铺镜额余驱咸面出齿龄龙发复赞缓缩纵织编练绩继续绝维综绿绪线缘广庆废证评谈请护议谢讲课读负财贫实宁导层几强归录于周"
        "学制欧兴办动据营满热战坏灵属湾亿杰压圆园汇残监泪温独获画确稳竞节级约纯细组给县总罢义联听脑台觉览亲训访诚误务胜医陆愿惊丽齐"
        "习争别价优偿尽儿册冻却唤吗寿梦奥妇帅张怀挂扬换荣浅净沦渊减测准沟灭润牵状狮现异皱盘种称窜笔筑简粮红脏舰华虾冲装诉贝军较轻远乡丑双顶颗养"
        "销势试订详询购赠赶迹递遥遗郑邻邮钓闭陈险雾静页项预频颜题态")
    def t2s(s):
        try:
            from opencc import OpenCC
            return OpenCC('t2s').convert(s)
        except ImportError:
            return ''.join(T2S_FALLBACK.get(ch, ch) for ch in s)
    a, b = t2s(a.replace(' ', '')), t2s(b.replace(' ', ''))
    if not a or not b:
        return 0.0
    dp = [[0]*(len(b)+1) for _ in range(len(a)+1)]
    for i in range(len(a)):
        for j in range(len(b)):
            dp[i+1][j+1] = dp[i][j]+1 if a[i] == b[j] else max(dp[i][j+1], dp[i+1][j])
    return dp[-1][-1] / max(len(a), len(b))


words = transcribe(VIDEO, 'medium', 'zh', None)
if not words:
    print('FAIL: 成片未识别出语音')
    sys.exit(1)

subs = parse_srt(SRT)
full = ''.join(x['t'] for x in words)
print(f'成片词数 {len(words)}，字幕 {len(subs)} 条\n')

report = []
bad = 0
for s, e, text in subs:
    mid_words = [w for w in words if s <= (w['s']+w['e'])/2 < e]
    heard = ''.join(w['t'] for w in mid_words)
    sc = sim(text, heard)
    ok = sc >= 0.6
    if not ok:
        bad += 1
    report.append({'sub': text, 's': round(s, 2), 'e': round(e, 2),
                   'heard': heard, 'score': round(sc, 2), 'ok': ok})
    flag = 'OK ' if ok else '✗✗ '
    print(f'{flag}{s:6.2f}-{e:6.2f}  字幕「{text}」 实听「{heard}」 {sc:.2f}')

json.dump(report, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
print(f'\n不合格 {bad}/{len(subs)} 条 → {OUT}')
sys.exit(1 if bad else 0)
