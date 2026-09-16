"""Cài thư viện từ các wheel tải sẵn vào bộ Python nhúng — không mạng, không pip.

Chạy trên Windows bằng chính python.exe của bộ nhúng:

    python.exe tools\\win_install_wheels.py <thu-muc-win-runtime> <thu-muc-python>

Vì sao không dùng pip: bản Python nhúng không kèm pip, mà hai cách bơm pip vào
nó (``get-pip.py`` hoặc chạy pip từ bên trong file .whl) đều dựa vào việc Python
tự thêm thư mục script vào ``sys.path`` — đúng cái mà chế độ ``._pth`` của bản
nhúng tắt đi. Trong khi đó wheel vốn chỉ là file zip: giải nén thẳng vào
``Lib\\site-packages`` cho ra đúng kết quả pip tạo, mà chỉ cần thư viện chuẩn.

Script này cũng ghi luôn file ``pythonNNN._pth`` — làm ở đây thay vì trong file
.bat vì logic ghi file bằng ``echo`` của cmd.exe rất dễ lẫn dấu cách thừa.
"""

import sys
import zipfile
from pathlib import Path

# In được tiếng Việt ra console mà không bao giờ ném UnicodeEncodeError.
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

PY_TAG = f"cp{sys.version_info.major}{sys.version_info.minor}"
STAMP = "da-cai.txt"


def compatible(wheel: Path) -> bool:
    """Wheel này có chạy được với Python đang chạy script không? (PEP 425 rút gọn)

    Chặn sớm ở đây để nếu ai đó tải nhầm bộ wheel (sai phiên bản Python, sai
    32/64-bit) thì báo rõ ngay, thay vì để tới lúc ``import`` mới đổ lỗi khó hiểu.
    """
    parts = wheel.stem.split("-")
    if len(parts) < 4:
        return False
    py_tags, abi_tags, plat_tags = parts[-3], parts[-2], parts[-1]
    if not any(p in ("any", "win_amd64") for p in plat_tags.split(".")):
        return False
    minor = sys.version_info.minor
    for abi in abi_tags.split("."):
        for py in py_tags.split("."):
            if abi == "none" and py in ("py3", f"py{sys.version_info.major}{minor}"):
                return True
            # abi3 = ABI ổn định: wheel dựng cho cp310 chạy được trên cp312.
            if abi == "abi3" and py.startswith("cp3") and py[3:].isdigit():
                if int(py[3:]) <= minor:
                    return True
            if abi == PY_TAG and py == PY_TAG:
                return True
    return False


def unpack(wheel: Path, site: Path) -> int:
    """Giải nén một wheel vào site-packages. Trả về số file đã ghi."""
    root = site.resolve()
    written = 0
    with zipfile.ZipFile(wheel) as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            name = info.filename
            parts = name.split("/")
            # scipy 1.18 lỡ đóng gói một mục 0 byte trùng tên chính file wheel.
            if len(parts) == 1 and name.endswith(".whl"):
                continue
            if parts[0].endswith(".data"):
                # purelib/platlib đổ thẳng vào site-packages; scripts/headers
                # /data chỉ dùng cho dòng lệnh, app này không cần.
                if len(parts) > 2 and parts[1] in ("purelib", "platlib"):
                    parts = parts[2:]
                else:
                    continue
            target = (site / Path(*parts)).resolve()
            if root not in target.parents and target != root:
                raise SystemExit(f"LỖI: wheel {wheel.name} chứa đường dẫn đáng ngờ: {name}")
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info) as fsrc, open(target, "wb") as fdst:
                while chunk := fsrc.read(1 << 20):
                    fdst.write(chunk)
            written += 1
    return written


def write_pth(pydir: Path) -> None:
    """Cho bộ Python nhúng thấy site-packages và thư mục chứa gói sparkle_cleaner.

    Đường dẫn trong ._pth tính tương đối so với chỗ đặt python.exe, nên ".."
    chính là thư mục dự án — nơi có gói ``sparkle_cleaner``.

    Cố ý KHÔNG ghi "import site": không wheel nào trong bộ này cần file .pth,
    mà bật site lên thì Python còn quét cả site-packages riêng của người dùng
    (%APPDATA%\\Python) — trên máy đã cài sẵn Python khác, nó sẽ nhặt nhầm
    numpy/PySide6 phiên bản khác và hỏng theo kiểu rất khó đoán.
    """
    pth = pydir / f"python{sys.version_info.major}{sys.version_info.minor}._pth"
    pth.write_text(
        "\n".join([
            f"python{sys.version_info.major}{sys.version_info.minor}.zip",
            ".",
            "..",
            "Lib\\site-packages",
            "",
        ]),
        encoding="ascii",
    )


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__)
        return 2
    runtime, pydir = Path(argv[0]), Path(argv[1])
    wheels = sorted((runtime / "wheels").glob("*.whl"))
    if not wheels:
        print(f"LỖI: không thấy file .whl nào trong {runtime / 'wheels'}")
        print("Thư mục win-runtime chưa được tải. Trên máy Mac/Linux chạy:")
        print("    python3 tools/fetch_windows_runtime.py")
        return 1

    site = pydir / "Lib" / "site-packages"
    stamp = site / STAMP
    want = "\n".join(w.name for w in wheels)
    if stamp.is_file() and stamp.read_text(encoding="utf-8") == want:
        print(f"Thư viện đã cài đủ ({len(wheels)} gói) — bỏ qua.")
        write_pth(pydir)
        return 0

    bad = [w.name for w in wheels if not compatible(w)]
    if bad:
        print(f"LỖI: {len(bad)} wheel không hợp với Python {sys.version.split()[0]} "
              f"({PY_TAG}, 64-bit):")
        for b in bad:
            print(f"    {b}")
        print("Tải lại bộ thư viện: python3 tools/fetch_windows_runtime.py --force")
        return 1

    site.mkdir(parents=True, exist_ok=True)
    total = 0
    for i, w in enumerate(wheels, 1):
        size = w.stat().st_size / 1024 / 1024
        print(f"  [{i}/{len(wheels)}] {w.name}  ({size:.1f} MB)", flush=True)
        try:
            total += unpack(w, site)
        except zipfile.BadZipFile:
            print(f"LỖI: file {w.name} bị hỏng — nhiều khả năng lúc chép USB bị lỗi.")
            print("Hãy chép lại cả thư mục từ nguồn rồi chạy lại.")
            return 1
        except OSError as exc:
            print(f"LỖI khi ghi file: {exc}")
            print("Kiểm tra ổ đĩa còn trống chỗ và thư mục không bị khoá chỉ-đọc.")
            return 1

    write_pth(pydir)
    stamp.write_text(want, encoding="utf-8")
    print(f"Đã cài {len(wheels)} gói, {total} file.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
