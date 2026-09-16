"""Gom ảnh từ nhiều loại nguồn: file lẻ, thư mục, file ZIP, link Google Drive."""

from __future__ import annotations

import dataclasses
import inspect
import os
import re
import shutil
import tempfile
import zipfile
from pathlib import Path

IMAGE_EXT = {
    ".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff", ".jfif", ".jpe",
}
ARCHIVE_EXT = {".zip"}
DRIVE_RE = re.compile(r"https?://(drive|docs)\.google\.com/\S+", re.I)

# ID của file/thư mục Drive là chuỗi chữ-số-gạch dài (thường 28–33 ký tự).
# Ba dạng link hay gặp:
#   .../drive/folders/ID          .../drive/u/0/folders/ID
#   .../file/d/ID/view?usp=...    .../file/d/ID          .../file/u/1/d/ID/view
#   .../open?id=ID                .../uc?id=ID&export=download
_DRIVE_FOLDER_ID_RE = re.compile(r"/folders/([-\w]{20,})")
_DRIVE_FILE_ID_RE = re.compile(
    r"/(?:file|document|spreadsheets|presentation)/(?:u/\d+/)?d/([-\w]{20,})"
)
_DRIVE_QUERY_ID_RE = re.compile(r"[?&]id=([-\w]{20,})")


@dataclasses.dataclass
class Item:
    """Một ảnh cần xử lý."""

    path: Path  # nơi ảnh đang nằm (có thể là thư mục tạm)
    rel: Path  # đường dẫn tương đối dùng khi ghi kết quả
    origin: str  # mô tả nguồn, để hiện trong log
    base: Path | None = None  # thư mục gốc, dùng cho chế độ ghi cạnh ảnh gốc
    ephemeral: bool = False  # nằm trong thư mục tạm (zip/Drive) — sẽ bị xoá


def is_image(path: os.PathLike | str) -> bool:
    return Path(path).suffix.lower() in IMAGE_EXT


def is_zip(path: os.PathLike | str) -> bool:
    """File ZIP theo đuôi; file không có đuôi thì kiểm tra chữ ký thật."""
    p = Path(path)
    if p.suffix.lower() in ARCHIVE_EXT:
        return True
    return not p.suffix and p.is_file() and zipfile.is_zipfile(p)


def is_drive_link(text: str) -> bool:
    return bool(DRIVE_RE.match(text.strip()))


def parse_drive_link(url: str) -> tuple[str, str] | None:
    """Rút ID từ link Drive. Trả về ("folder" | "file", id) hoặc None.

    Tự rút ID rồi đưa cho gdown thay vì đưa nguyên link, vì gdown chỉ hiểu vài
    dạng link chuẩn — link thiếu ``/view``, link có ``/u/0/`` hay link
    ``open?id=`` đều làm nó tải về một trang HTML thay vì file.
    """
    url = url.strip()
    m = _DRIVE_FOLDER_ID_RE.search(url)
    if m:
        return "folder", m.group(1)
    m = _DRIVE_FILE_ID_RE.search(url)
    if m:
        return "file", m.group(1)
    m = _DRIVE_QUERY_ID_RE.search(url)
    if m:
        kind = "folder" if "folderview" in url else "file"
        return kind, m.group(1)
    return None


# Windows cấm hẳn những ký tự này trong tên file, còn macOS/Linux thì cho. Một
# file ZIP nén trên Mac có ảnh tên "anh 1:2.jpg" là giải nén đổ lỗi ngay trên
# Windows — mà ZIP thì hay được gửi qua lại giữa hai hệ điều hành.
_WIN_BAD_CHARS = '<>:"|?*'

# Tên thiết bị có từ thời DOS: trên Windows không tạo nổi file tên "con.jpg"
# hay "nul.png", dù đuôi là gì.
_WIN_RESERVED = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


def safe_zip_name(name: str, for_windows: bool | None = None) -> str | None:
    """Đổi tên một mục trong ZIP thành đường dẫn tương đối chắc chắn ghi được.

    Trả về ``None`` nếu mục đó không nên ghi ra (tên rỗng, hoặc chỉ toàn "..").

    Làm hai việc:

    1. Cắt bỏ đường dẫn tuyệt đối và mọi thành phần ".." — chặn zip-slip ngay
       từ khâu đặt tên, chứ không chỉ kiểm tra lại sau khi đã ghép đường dẫn.
    2. Trên Windows, thay các ký tự và tên mà hệ thống cấm.

    Việc (2) chỉ chạy trên Windows để tên file kết quả trên macOS/Linux vẫn y
    hệt như trước. Tham số ``for_windows`` cho phép kiểm thử cả hai nhánh từ
    bất kỳ máy nào.
    """
    if for_windows is None:
        for_windows = os.name == "nt"
    parts: list[str] = []
    for raw in name.replace("\\", "/").split("/"):  # zip sai chuẩn hay dùng \
        part = raw
        if for_windows:
            part = "".join(
                "_" if c in _WIN_BAD_CHARS or ord(c) < 32 else c for c in part
            )
            # Windows lặng lẽ cắt dấu chấm và dấu cách ở cuối tên, thành ra file
            # ghi ra một tên mà mình lại nhớ một tên khác.
            part = part.rstrip(". ")
            if part.split(".")[0].upper() in _WIN_RESERVED:
                part = "_" + part
        part = part.strip()
        if not part or part in (".", ".."):
            continue
        parts.append(part)
    return "/".join(parts) or None


def _supported(fn, **kw):
    """gdown đổi tham số giữa các phiên bản — chỉ truyền cái nó nhận."""
    allowed = set(inspect.signature(fn).parameters)
    return {k: v for k, v in kw.items() if k in allowed}


class Collector:
    """Biến danh sách nguồn thô thành danh sách ảnh cụ thể.

    Mọi thứ phải tải hoặc giải nén đều nằm trong một thư mục tạm, dọn sạch khi
    xong bằng ``cleanup()``.
    """

    def __init__(self, log=print):
        self.log = log
        self._tmp = Path(tempfile.mkdtemp(prefix="sparkle-cleaner-"))

    def cleanup(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _fresh_dir(self, prefix: str) -> Path:
        """Thư mục con mới, tên không trùng, nằm trong thư mục tạm chung."""
        return Path(tempfile.mkdtemp(prefix=prefix, dir=self._tmp))

    # ------------------------------------------------------------------
    def collect(self, entries: list[str]) -> list[Item]:
        items: list[Item] = []
        seen: set[str] = set()
        for raw in entries:
            entry = raw.strip()
            if not entry:
                continue
            try:
                if is_drive_link(entry):
                    items += self._from_drive(entry)
                elif Path(entry).is_dir():
                    items += self._from_folder(Path(entry))
                elif Path(entry).suffix.lower() in ARCHIVE_EXT:
                    items += self._from_zip(Path(entry))
                elif is_image(entry):
                    p = Path(entry)
                    items.append(Item(p, Path(p.name), p.name, p.parent))
                else:
                    self.log(f"Bỏ qua (không phải ảnh/thư mục/zip/link): {entry}", "warn")
            except Exception as exc:  # noqa: BLE001
                self.log(f"Lỗi khi đọc nguồn {entry}: {exc}", "error")

        unique: list[Item] = []
        for it in items:
            key = str(it.path.resolve())
            if key in seen:
                continue
            seen.add(key)
            unique.append(it)
        return unique

    # ------------------------------------------------------------------
    def _from_folder(self, folder: Path) -> list[Item]:
        out = []
        for p in sorted(folder.rglob("*")):
            if p.is_file() and is_image(p):
                out.append(Item(p, p.relative_to(folder), f"{folder.name}/{p.relative_to(folder)}", folder))
        self.log(f"Thư mục {folder.name}: tìm thấy {len(out)} ảnh", "info")
        return out

    def _from_zip(self, archive: Path) -> list[Item]:
        picked = self._extract_zip(archive, self._fresh_dir("zip-"), archive.name)
        self.log(f"ZIP {archive.name}: giải nén {len(picked)} ảnh", "info")
        return picked

    def _extract_zip(self, archive: Path, dest: Path, origin: str) -> list[Item]:
        """Giải nén riêng phần ảnh trong ZIP vào ``dest``; mọi Item đều tạm.

        ``origin`` là tên hiển thị của file zip trong nhật ký — tên file với
        zip trên máy, hoặc ``Drive/ten.zip`` với zip vừa tải về.
        """
        dest.mkdir(parents=True, exist_ok=True)
        root = str(dest.resolve()) + os.sep
        picked = []
        with zipfile.ZipFile(archive) as zf:
            for info in zf.infolist():
                if info.is_dir():
                    continue
                name = info.filename
                if name.startswith("__MACOSX/") or Path(name).name.startswith("."):
                    continue
                rel = safe_zip_name(name)
                if rel is None or not is_image(rel):
                    continue
                # Chặn zip-slip lần hai: tên đã làm sạch rồi vẫn kiểm tra lại
                # đường dẫn thật, vì đây là dữ liệu từ bên ngoài.
                target = (dest / rel).resolve()
                if not str(target).startswith(root):
                    self.log(f"Bỏ qua mục đáng ngờ trong zip: {name}", "warn")
                    continue
                try:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with zf.open(info) as fsrc, open(target, "wb") as fdst:
                        shutil.copyfileobj(fsrc, fdst)
                except OSError as exc:
                    # Trên Windows đường dẫn dài quá 260 ký tự là ném lỗi ngay ở
                    # đây. Bỏ đúng file đó thôi, đừng làm hỏng cả lượt giải nén.
                    self.log(f"Không giải nén được {name}: {exc}", "warn")
                    continue
                picked.append(Item(target, Path(rel), f"{origin}:{name}", dest, True))
        return picked

    # ------------------------------------------------------------------
    def _from_drive(self, url: str) -> list[Item]:
        try:
            import gdown
        except ImportError:
            self.log("Chưa cài gdown nên không tải được từ Drive.", "error")
            return []

        parsed = parse_drive_link(url)
        if parsed is None:
            self.log(f"Không nhận ra ID file/thư mục trong link Drive: {url}", "error")
            self.log(
                "Link hợp lệ có dạng …/drive/folders/ID hoặc …/file/d/ID/view. "
                "Trên Drive hãy dùng Chia sẻ → Sao chép liên kết.", "warn",
            )
            return []
        kind, drive_id = parsed

        dest = self._fresh_dir("drive-")
        self.log(
            f"Đang tải {'thư mục' if kind == 'folder' else 'file'} từ Google Drive: {url}",
            "info",
        )
        try:
            if kind == "folder":
                gdown.download_folder(**_supported(
                    gdown.download_folder, id=drive_id, output=str(dest),
                    quiet=True, use_cookies=False, remaining_ok=True,
                ))
            else:
                # output kết thúc bằng dấu / để gdown giữ tên file gốc trên
                # Drive (lấy từ Content-Disposition) — nhờ đó biết được nó là
                # ảnh hay ZIP.
                got = gdown.download(**_supported(
                    gdown.download, id=drive_id, output=str(dest) + os.sep,
                    quiet=True, use_cookies=False,
                ))
                if not got:
                    raise RuntimeError("Drive không trả về file nào")
        except Exception as exc:  # noqa: BLE001
            self.log(f"Tải Drive thất bại: {exc}", "error")
            self.log(
                "Kiểm tra: link đã bật chia sẻ 'Bất kỳ ai có đường liên kết' "
                "chưa, và thư mục có quá nhiều file không.", "warn",
            )
            return []

        return self._pick_downloaded(dest)

    def _pick_downloaded(self, dest: Path) -> list[Item]:
        """Lọc thứ vừa tải về từ Drive: ảnh lấy thẳng, ZIP thì giải nén."""
        files = [p for p in sorted(dest.rglob("*")) if p.is_file()]
        out: list[Item] = []
        n_img = n_zip = 0
        for p in files:
            rel = p.relative_to(dest)
            if is_image(p):
                n_img += 1
                out.append(Item(p, rel, f"Drive/{rel}", dest, True))
            elif is_zip(p):
                n_zip += 1
                try:
                    got = self._extract_zip(p, self._fresh_dir("drive-zip-"), f"Drive/{rel}")
                except zipfile.BadZipFile:
                    self.log(
                        f"Drive: {rel} không phải file ZIP hợp lệ — thường do Drive "
                        "trả về trang HTML thay vì file (link chưa chia sẻ công khai, "
                        "hoặc file quá lớn bị chặn quét virus).", "error",
                    )
                    continue
                self.log(f"Drive: {rel} → giải nén {len(got)} ảnh", "info")
                out += got
            else:
                self.log(f"Drive: bỏ qua {rel} (không phải ảnh hay ZIP)", "warn")

        if not out:
            self.log("Không thấy ảnh nào trong link Drive đó.", "warn")
        else:
            parts = []
            if n_img:
                parts.append(f"{n_img} ảnh")
            if n_zip:
                parts.append(f"{n_zip} file ZIP")
            self.log(f"Drive: tải về {' và '.join(parts)} — tổng {len(out)} ảnh", "info")
        return out
