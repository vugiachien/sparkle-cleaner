"""Vẽ icon ứng dụng (ngôi sao 4 cánh trên nền tối) và xuất ra .icns / .ico / .png.

Chạy: .venv/bin/python tools/make_icons.py
Tạo:  assets/sparkle.png (1024px), assets/sparkle.ico (Windows),
      assets/sparkle.icns (chỉ trên macOS, cần iconutil),
      sparkle_cleaner/sparkle.png (256px, icon cửa sổ khi chạy).
"""

from __future__ import annotations

import math
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"


def astroid(cx: float, cy: float, r: float, n: int = 720) -> list[tuple[float, float]]:
    """Đường astroid x = r·cos³t, y = r·sin³t — đúng hình dấu sparkle của Gemini."""
    return [
        (cx + r * math.cos(t) ** 3, cy + r * math.sin(t) ** 3)
        for t in (2 * math.pi * i / n for i in range(n))
    ]


def draw(size: int = 1024) -> Image.Image:
    ss = 4  # vẽ to gấp 4 rồi thu nhỏ để có viền mượt
    n = size * ss
    img = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    # Nền: ô vuông bo góc kiểu macOS, chừa lề ~6% như icon hệ thống.
    m = int(n * 0.06)
    d.rounded_rectangle([m, m, n - m, n - m], radius=int(n * 0.21), fill=(27, 30, 36, 255))

    # Quầng sáng xanh mờ phía sau ngôi sao.
    glow = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    ImageDraw.Draw(glow).polygon(astroid(n / 2, n / 2, n * 0.37), fill=(111, 180, 255, 150))
    glow = glow.filter(ImageFilter.GaussianBlur(n * 0.035))
    img = Image.alpha_composite(img, glow)

    d = ImageDraw.Draw(img)
    d.polygon(astroid(n / 2, n / 2, n * 0.33), fill=(255, 255, 255, 255))
    # Sao nhỏ màu xanh lá ở góc: dấu "đã sạch".
    d.polygon(astroid(n * 0.745, n * 0.265, n * 0.075), fill=(95, 211, 141, 255))

    return img.resize((size, size), Image.LANCZOS)


def main() -> None:
    ASSETS.mkdir(exist_ok=True)
    base = draw(1024)
    base.save(ASSETS / "sparkle.png")
    base.resize((256, 256), Image.LANCZOS).save(ROOT / "sparkle_cleaner" / "sparkle.png")
    base.save(
        ASSETS / "sparkle.ico",
        sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
    )
    print(f"Đã ghi {ASSETS / 'sparkle.png'}, {ASSETS / 'sparkle.ico'}")

    if sys.platform == "darwin" and shutil.which("iconutil"):
        with tempfile.TemporaryDirectory() as td:
            iconset = Path(td) / "sparkle.iconset"
            iconset.mkdir()
            for s in (16, 32, 128, 256, 512):
                base.resize((s, s), Image.LANCZOS).save(iconset / f"icon_{s}x{s}.png")
                base.resize((2 * s, 2 * s), Image.LANCZOS).save(iconset / f"icon_{s}x{s}@2x.png")
            subprocess.run(
                ["iconutil", "-c", "icns", str(iconset), "-o", str(ASSETS / "sparkle.icns")],
                check=True,
            )
        print(f"Đã ghi {ASSETS / 'sparkle.icns'}")


if __name__ == "__main__":
    main()
