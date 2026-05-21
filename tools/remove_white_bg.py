# -*- coding: utf-8 -*-
"""
将 LOGO 图的白色背景抠成透明，边缘做软羽化（线性 alpha 过渡）。
对 jpg/png 都适用，输出 PNG（带 alpha）。
"""
import sys
from pathlib import Path
from PIL import Image


def remove_white_bg(src: Path, dst: Path, hard: int = 8, soft: int = 48) -> None:
    """
    hard: 通道差 <= hard 视为纯白 → alpha=0
    soft: 通道差 在 (hard, soft] 之间 → alpha 按线性过渡 (羽化)
    通道差 > soft 时保留原 alpha
    """
    img = Image.open(src).convert("RGBA")
    w, h = img.size
    pixels = img.load()

    for y in range(h):
        for x in range(w):
            r, g, b, a = pixels[x, y]
            if a == 0:
                continue
            diff = max(255 - r, 255 - g, 255 - b)
            if diff <= hard:
                new_a = 0
            elif diff <= soft:
                new_a = int(a * (diff - hard) / (soft - hard))
            else:
                new_a = a
            pixels[x, y] = (r, g, b, new_a)

    img.save(dst, "PNG")
    print(f"Saved: {dst}  ({img.size[0]}x{img.size[1]})")


if __name__ == "__main__":
    # 基于脚本位置定位 frontend/public（跨项目通用）
    public = Path(__file__).resolve().parent.parent / "frontend" / "public"
    # 优先用原图 (.original.png 或 .jpg)
    candidates = [
        public / "airchina-corp-logo.original.png",
        public / "airchina-corp-logo.jpg",
        public / "airchina-corp-logo.png",
    ]
    src = next((p for p in candidates if p.exists()), None)
    if src is None:
        print("源 LOGO 未找到", file=sys.stderr)
        sys.exit(1)

    dst = public / "airchina-corp-logo.png"
    # 最激进：差值 30 内全抠，30-140 长羽化 → 无任何浅色残留
    remove_white_bg(src, dst, hard=30, soft=140)
