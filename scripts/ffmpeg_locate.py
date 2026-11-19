# -*- coding: utf-8 -*-
"""ffmpeg 定位器：所有脚本统一从这里拿 ffmpeg 可执行文件路径

查找顺序：
  1. PATH 里的 ffmpeg（标准安装）
  2. imageio-ffmpeg 自带的二进制（pip install imageio-ffmpeg，免管理员）
  3. 都没有 → 抛出带安装指引的 RuntimeError

用法：
  from ffmpeg_locate import get_ffmpeg, ensure_ffmpeg
  FFMPEG = get_ffmpeg()          # 拿路径（找不到直接报错）
  ensure_ffmpeg()                 # 找不到时打印友好指引再退出
"""
import shutil
import sys


def get_ffmpeg():
    """返回 ffmpeg 可执行文件路径；找不到返回 None"""
    # 1. PATH 里直接找
    p = shutil.which("ffmpeg")
    if p:
        return p
    # 2. imageio-ffmpeg 自带二进制（pip 安装，无需管理员）
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError:
        pass
    except Exception:
        pass
    return None


def ensure_ffmpeg():
    """找不到 ffmpeg 时打印三条安装路径并退出（供脚本入口调用）"""
    p = get_ffmpeg()
    if p:
        return p
    sys.stderr.write(
        "错误: 未找到 ffmpeg，本脚本无法运行。\n"
        "三条免管理员安装路径（任选其一）：\n"
        "  1. pip install imageio-ffmpeg        （最快，推荐）\n"
        "  2. winget install ffmpeg             （Windows）\n"
        "  3. brew install ffmpeg               （macOS）\n"
    )
    sys.exit(1)


if __name__ == "__main__":
    p = get_ffmpeg()
    print(p if p else "未找到 ffmpeg，请按 SKILL.md 第 0 步安装")
