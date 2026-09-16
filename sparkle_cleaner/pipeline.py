"""Xử lý một ảnh: đọc, dò, gỡ dấu, ghi ra đúng nơi người dùng chọn.

Hàm ``process_one`` đứng ở cấp module và chỉ nhận/trả dict thuần để có thể chạy
song song bằng ProcessPoolExecutor.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import numpy as np
from PIL import Image

from . import engine

SENSITIVITY = {
    # tên: (min_sep, min_shape, min_fit, min_alpha)
    #
    # min_alpha là độ phủ tối thiểu của lớp trắng. Dấu Gemini thật nằm quanh
    # 0.27; nhiễu trên nền tối hay bị nhận nhầm lại cho độ phủ dưới 0.10, nên
    # ngưỡng này là thứ chặn báo nhầm hiệu quả nhất. Chế độ "nhạy" hạ ngưỡng
    # xuống để vẫn bắt được dấu đã mờ vì nén hoặc thu nhỏ nhiều lần.
    "chat": (5.5, 3.5, 0.72, 0.14),
    "canbang": (4.5, 3.0, 0.65, 0.11),
    "nhay": (3.8, 2.5, 0.50, 0.05),
}


def ensure_std_streams() -> None:
    """Bảo đảm ``sys.stdout``/``sys.stderr`` luôn ghi được vào đâu đó.

    Trên Windows giao diện chạy bằng ``pythonw.exe`` nên không hề có console:
    cả tiến trình cha lẫn các tiến trình con do ``ProcessPoolExecutor`` sinh ra
    đều có ``sys.stdout`` và ``sys.stderr`` bằng ``None``. Thư viện nào lỡ gọi
    ``print()`` — gdown và tqdm chẳng hạn — sẽ ném ``AttributeError: 'NoneType'
    object has no attribute 'write'`` và giết luôn tiến trình đó, mà lỗi ấy cực
    khó lần vì chẳng có chỗ nào hiện nó ra. Trỏ tạm vào devnull là hết vỡ.

    Dùng ở hai nơi: ``app.main()`` cho tiến trình giao diện, và làm
    ``initializer`` cho pool. Vì vậy hàm phải nằm ở cấp module, trong một module
    KHÔNG nạp PySide6 — để pickle sang tiến trình con mà không kéo theo cả
    giao diện.
    """
    for name in ("stdout", "stderr"):
        if getattr(sys, name, None) is None:
            try:
                setattr(sys, name, open(os.devnull, "w", encoding="utf-8"))
            except OSError:
                pass


def unique_path(path: Path) -> Path:
    """Không bao giờ đè lên file đã có: thêm hậu tố -1, -2, ..."""
    if not path.exists():
        return path
    stem, suffix, parent = path.stem, path.suffix, path.parent
    for i in range(1, 10000):
        cand = parent / f"{stem}-{i}{suffix}"
        if not cand.exists():
            return cand
    return parent / f"{stem}-{np.random.randint(1e6)}{suffix}"


def _save(img: np.ndarray, dst: Path, fmt: str, quality: int,
          strip_meta: bool, exif: bytes | None = None) -> Path:
    pil = Image.fromarray(img)
    fmt = fmt.lower()
    if fmt == "png" or (fmt == "giu" and dst.suffix.lower() == ".png"):
        dst = dst.with_suffix(".png")
        params = {"format": "PNG", "optimize": True}
    elif fmt in ("jpeg", "jpg") or (
        fmt == "giu" and dst.suffix.lower() in (".jpg", ".jpeg", ".jfif", ".jpe")
    ):
        dst = dst.with_suffix(dst.suffix if dst.suffix.lower() in (".jpg", ".jpeg") else ".jpg")
        params = {
            "format": "JPEG",
            "quality": int(quality),
            "subsampling": 0,  # 4:4:4 — không làm nhoè màu ở vùng vừa vá
            "optimize": True,
        }
    elif fmt == "giu" and dst.suffix.lower() == ".webp":
        params = {"format": "WEBP", "quality": int(quality), "method": 5}
    else:
        dst = dst.with_suffix(".png")
        params = {"format": "PNG", "optimize": True}

    dst.parent.mkdir(parents=True, exist_ok=True)
    dst = unique_path(dst)
    # Pillow chỉ ghi metadata khi được truyền vào, nên mặc định file ra đã sạch
    # EXIF/XMP/C2PA — không cần bước xoá riêng.
    if not strip_meta and exif and params["format"] in ("JPEG", "WEBP"):
        params["exif"] = exif
    pil.save(dst, **params)
    return dst


def explain(paths: list[str], sensitivity: str = "canbang") -> int:
    """In từng bước dò tìm cho các ảnh — dùng khi một ảnh không được nhận.

    Gọi qua ``python -m sparkle_cleaner --explain anh1.jpg anh2.png``.
    """
    sep, shape, fit, alpha = SENSITIVITY.get(sensitivity, SENSITIVITY["canbang"])
    code = 0
    for p in paths:
        try:
            with Image.open(p) as im:
                rgb = np.asarray(im.convert("RGB"))
        except Exception as exc:  # noqa: BLE001
            print(f"== {p}: không đọc được ảnh ({exc})")
            code = 1
            continue
        report: list[str] = []
        mark = engine.detect(
            rgb, min_sep=sep, min_shape=shape, min_fit=fit, min_alpha=alpha, report=report
        )
        print(f"== {p}  (độ nhạy: {sensitivity})")
        for line in report:
            print(line)
        print("KẾT QUẢ:", mark.describe() if mark else "không nhận dấu")
    return code


def process_one(task: dict) -> dict:
    """Xử lý một ảnh. Luôn trả về dict kết quả, không ném lỗi ra ngoài."""
    src = Path(task["src"])
    result = {"src": str(src), "origin": task.get("origin", src.name)}
    try:
        with Image.open(src) as im:
            im.load()
            exif = im.info.get("exif")
            rgb = np.asarray(im.convert("RGB"))
    except Exception as exc:  # noqa: BLE001
        result.update(status="error", message=f"không đọc được ảnh: {exc}")
        return result

    sep, shape, fit, alpha = SENSITIVITY.get(
        task.get("sensitivity", "canbang"), SENSITIVITY["canbang"]
    )
    try:
        mark = engine.detect(rgb, min_sep=sep, min_shape=shape, min_fit=fit, min_alpha=alpha)
    except Exception as exc:  # noqa: BLE001
        result.update(status="error", message=f"lỗi khi dò dấu: {exc}")
        return result

    if mark is None:
        if task.get("copy_when_clean", True):
            try:
                out = _save(
                    rgb, Path(task["dst"]), task.get("format", "giu"),
                    task.get("quality", 96), task.get("strip_meta", True), exif,
                )
                result.update(status="clean", message="không thấy dấu — chép nguyên bản", dst=str(out))
            except Exception as exc:  # noqa: BLE001
                result.update(status="error", message=f"không ghi được: {exc}")
        else:
            result.update(status="clean", message="không thấy dấu — bỏ qua")
        return result

    try:
        out_img = engine.remove(rgb, mark, restore_grain=task.get("restore_grain", True))
        out_img = np.clip(np.rint(out_img), 0, 255).astype(np.uint8)
        dst = _save(
            out_img, Path(task["dst"]), task.get("format", "giu"),
            task.get("quality", 96), task.get("strip_meta", True), exif,
        )
    except Exception as exc:  # noqa: BLE001
        result.update(status="error", message=f"lỗi khi gỡ dấu: {exc}")
        return result

    result.update(status="cleaned", message=mark.describe(), dst=str(dst))
    return result
