#!/usr/bin/env python3
"""Tải sẵn Python nhúng + thư viện bản Windows vào thư mục ``win-runtime/``.

Chạy MỘT LẦN trên máy đang có mạng (Mac, Linux hay chính Windows đều được):

    python3 tools/fetch_windows_runtime.py

Sau đó chép NGUYÊN thư mục dự án sang USB. Máy Windows chỉ cần nhấn đúp
"Sparkle Cleaner.bat" là chạy được — không cần mạng, không cần cài Python,
không cần quyền admin.

Vì sao phải có bước này: wheel của PySide6/numpy/scipy/OpenCV là bản biên dịch
riêng cho Windows, máy Mac không tự sinh ra được. Nhưng ``pip download`` tải hộ
được nhờ ``--platform win_amd64``, nên vẫn chuẩn bị trọn gói từ Mac.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RUNTIME = ROOT / "win-runtime"
WHEELS = RUNTIME / "wheels"

# Python 3.12 là bản có đủ wheel Windows cho cả sáu thư viện, và bản nhúng của
# nó đã kèm sẵn vcruntime140.dll nên máy đích không cần cài Visual C++ Redist.
PY_VERSION = "3.12.10"
PY_TAG = "312"  # phải khớp PY_VERSION — quyết định tên file pythonNNN._pth
PY_ZIP = f"python-{PY_VERSION}-embed-amd64.zip"
PY_URL = f"https://www.python.org/ftp/python/{PY_VERSION}/{PY_ZIP}"


def human(n: int) -> str:
    return f"{n / 1024 / 1024:.1f} MB"


def fetch_python(force: bool = False) -> Path:
    dest = RUNTIME / PY_ZIP
    if dest.is_file() and not force:
        print(f"  đã có sẵn {dest.name} ({human(dest.stat().st_size)})")
        return dest
    print(f"  tải {PY_URL}")
    tmp = dest.with_suffix(".part")
    with urllib.request.urlopen(PY_URL, timeout=120) as r, open(tmp, "wb") as f:
        shutil.copyfileobj(r, f)
    # Kiểm tra ngay: file hỏng mà để sang tận máy Windows mới phát hiện thì
    # người dùng cuối không có cách nào tự sửa.
    with zipfile.ZipFile(tmp) as zf:
        names = set(zf.namelist())
        for need in ("python.exe", "pythonw.exe", f"python{PY_TAG}.zip"):
            if need not in names:
                raise SystemExit(f"LỖI: bộ Python nhúng thiếu {need}")
    tmp.replace(dest)
    print(f"  xong {dest.name} ({human(dest.stat().st_size)})")
    return dest


def _pip_download(what: list[str]) -> None:
    """Tải wheel bản Windows 64-bit / CPython 3.12 về thư mục wheels."""
    cmd = [
        sys.executable, "-m", "pip", "download",
        "--only-binary=:all:",           # không lấy bản mã nguồn phải biên dịch
        "--platform", "win_amd64",       # wheel cho Windows 64-bit
        "--python-version", "3.12",
        "--implementation", "cp",
        "--dest", str(WHEELS),
        *what,
    ]
    proc = subprocess.run(cmd, text=True, capture_output=True)
    if proc.returncode != 0:
        sys.stderr.write(proc.stdout + proc.stderr)
        raise SystemExit("LỖI: pip download thất bại (xem thông báo phía trên).")


def fetch_wheels(force: bool = False) -> list[Path]:
    if force and WHEELS.is_dir():
        shutil.rmtree(WHEELS)
    WHEELS.mkdir(parents=True, exist_ok=True)
    if any(WHEELS.glob("*.whl")) and not force:
        got = sorted(WHEELS.glob("*.whl"))
        print(f"  đã có sẵn {len(got)} wheel")
        return got
    _pip_download(["-r", str(ROOT / "requirements.txt")])
    return sorted(WHEELS.glob("*.whl"))


def close_dependencies(wheels: list[Path]) -> list[Path]:
    """Tải bổ sung cho tới khi bộ wheel không còn thiếu phụ thuộc nào.

    Cần bước này vì ``pip download --platform win_amd64`` chỉ đổi cách CHỌN
    wheel, còn điều kiện kiểu ``; platform_system == "Windows"`` thì nó vẫn
    đánh giá theo máy đang chạy. Chạy trên Mac là bỏ sót — ví dụ tqdm cần
    colorama trên Windows. Vì vậy không thêm các gói đó vào requirements.txt
    (bản macOS không cần), mà dò rồi tải thêm ngay tại đây.
    """
    names: list[str] = []
    for _ in range(5):
        missing = verify_closure(wheels)
        if not missing:
            print("  đủ, không thiếu gói nào")
            return wheels
        names = sorted({m.split(" (")[0] for m in missing})
        print(f"  tải bổ sung gói chỉ dùng trên Windows: {', '.join(names)}")
        _pip_download(names)
        wheels = sorted(WHEELS.glob("*.whl"))
    raise SystemExit("LỖI: vẫn thiếu " + ", ".join(names))


def verify_closure(wheels: list[Path]) -> list[str]:
    """Kiểm tra bộ wheel đã đủ phụ thuộc chưa — trả về danh sách gói còn thiếu.

    pip download đã tự kéo phụ thuộc, nhưng nó giải theo môi trường CHẠY pip
    (macOS) chứ không phải môi trường đích, nên một gói chỉ cần trên Windows có
    thể bị bỏ sót. Thiếu gói thì mãi tới lúc người dùng cuối mở app ở máy khác
    mới lộ ra, nên kiểm ngay từ đây.
    """
    try:
        from packaging.markers import Marker
        from packaging.requirements import Requirement
        from packaging.utils import canonicalize_name
    except ImportError:
        print("  (bỏ qua kiểm tra phụ thuộc: máy này chưa có thư viện 'packaging')")
        return []

    # Môi trường đích: Windows 64-bit, CPython 3.12.
    env = {
        "sys_platform": "win32", "platform_system": "Windows",
        "os_name": "nt", "platform_machine": "AMD64",
        "python_version": "3.12", "python_full_version": PY_VERSION,
        "implementation_name": "cpython", "platform_python_implementation": "CPython",
        "extra": "",
    }

    have, requires = set(), []
    for w in wheels:
        with zipfile.ZipFile(w) as zf:
            meta = next((n for n in zf.namelist()
                         if n.endswith(".dist-info/METADATA")), None)
            if meta is None:
                continue
            text = zf.read(meta).decode("utf-8", "replace")
        for line in text.splitlines():
            if line.startswith("Name:"):
                have.add(canonicalize_name(line.split(":", 1)[1].strip()))
            elif line.startswith("Requires-Dist:"):
                requires.append((w.name, line.split(":", 1)[1].strip()))

    missing = []
    for wheel_name, raw in requires:
        try:
            req = Requirement(raw)
        except Exception:  # noqa: BLE001
            continue
        # Bỏ qua phụ thuộc tuỳ chọn (extra) và phụ thuộc của hệ điều hành khác.
        if req.marker is not None and not Marker(str(req.marker)).evaluate(env):
            continue
        if canonicalize_name(req.name) not in have:
            missing.append(f"{req.name} (cần bởi {wheel_name})")
    return sorted(set(missing))


def write_manifest(wheels: list[Path]) -> None:
    lines = [
        "Bộ chạy Windows dựng sẵn cho Sparkle Cleaner.",
        f"Python nhúng: {PY_VERSION} (amd64, tag cp{PY_TAG})",
        f"Số wheel: {len(wheels)}",
        "",
    ]
    lines += [f"{w.name}" for w in wheels]
    (RUNTIME / "manifest.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


# Chỉ những thứ này mới cần đi theo USB. Cố tình bỏ .venv, dist và build —
# đó là đồ của máy Mac, cộng lại hơn 1 GB và máy Windows không dùng tới.
STAGE_ITEMS = [
    "sparkle_cleaner", "tools", "win-runtime", "assets",
    "Sparkle Cleaner.bat", "requirements.txt",
    "HUONG DAN - Windows.txt", "README.md",
]


def stage(dest: Path) -> None:
    """Chép đúng phần cần thiết sang ``dest`` để bỏ vào USB."""
    dest.mkdir(parents=True, exist_ok=True)
    total = 0
    for name in STAGE_ITEMS:
        src = ROOT / name
        if not src.exists():
            print(f"  bỏ qua (không có): {name}")
            continue
        target = dest / name
        if src.is_dir():
            if target.exists():
                shutil.rmtree(target)
            # Bỏ __pycache__: vừa thừa, vừa là file .pyc biên dịch cho Python
            # của máy Mac nên máy Windows không dùng được.
            shutil.copytree(src, target,
                            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        else:
            shutil.copy2(src, target)
        total += sum(f.stat().st_size for f in target.rglob("*") if f.is_file()) \
            if target.is_dir() else target.stat().st_size
        print(f"  chép {name}")
    print(f"\nXong: {dest}  ({human(total)})")
    print("Chép nguyên thư mục này vào USB. Trên máy Windows, chép nó từ USB ra")
    print('Desktop rồi nhấn đúp "Sparkle Cleaner.bat".')


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--force", action="store_true",
                    help="tải lại từ đầu dù đã có sẵn")
    ap.add_argument("--stage", metavar="THU_MUC",
                    help="chép sẵn phần cần đưa sang Windows vào thư mục này "
                         "(bỏ .venv/dist/build của máy Mac)")
    args = ap.parse_args()

    RUNTIME.mkdir(parents=True, exist_ok=True)
    print(f"==> Python nhúng {PY_VERSION} cho Windows")
    py = fetch_python(args.force)
    print("==> Thư viện bản Windows (vài phút, khoảng 200 MB)")
    wheels = fetch_wheels(args.force)
    print("==> Kiểm tra bộ wheel đã đủ phụ thuộc chưa")
    wheels = close_dependencies(wheels)
    write_manifest(wheels)

    total = py.stat().st_size + sum(w.stat().st_size for w in wheels)
    print()
    print(f"Xong: {RUNTIME.relative_to(ROOT)}/ — {len(wheels)} wheel, tổng {human(total)}")
    for w in wheels:
        print(f"    {w.name}")
    print()
    if args.stage:
        print()
        print(f"==> Đóng gói phần đi Windows vào {args.stage}")
        stage(Path(args.stage).expanduser())
    else:
        print("Chép sang USB: chạy lại lệnh này kèm --stage, ví dụ")
        print("    python3 tools/fetch_windows_runtime.py --stage ~/Desktop/sparkle-win")
        print("để khỏi chép nhầm .venv/dist/build (hơn 1 GB, máy Windows không dùng).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
