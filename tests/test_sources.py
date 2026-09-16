"""Kiểm thử phần gom nguồn: ZIP trên máy và ZIP/ảnh tải từ Google Drive.

Drive được giả lập bằng một module ``gdown`` giả: "tải" nghĩa là chép file có
sẵn vào thư mục output, đúng cách gdown thật đặt tên file theo Content-Disposition.
"""

import shutil
import sys
import tempfile
import types
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from sparkle_cleaner.sources import Collector, parse_drive_link

FILE_ID = "1AbCdEfGhIjKlMnOpQrStUvWxYz0123456"  # 33 ký tự, dạng ID Drive thật
FOLDER_ID = "1ZXEhzbLRLU1giKKRJkjm8N04cO_JoYE2"


def _fake_png() -> bytes:
    # Collector không mở ảnh, chỉ cần đuôi hợp lệ; vài byte là đủ.
    return b"\x89PNG\r\n\x1a\n" + b"\x00" * 16


def _make_zip(path: Path, names) -> Path:
    with zipfile.ZipFile(path, "w") as zf:
        for n in names:
            zf.writestr(n, _fake_png())
    return path


class FakeGdown(types.ModuleType):
    """gdown giả: chép các file trong ``payload`` vào thư mục output."""

    def __init__(self, payload: dict):
        super().__init__("gdown")
        self.payload = payload  # tên file trên Drive -> file nguồn trên máy
        self.calls = []

    def download(self, id=None, output=None, quiet=False, use_cookies=True):
        self.calls.append(("download", id, output))
        out_dir = Path(output)
        out_dir.mkdir(parents=True, exist_ok=True)
        name, src = next(iter(self.payload.items()))
        dst = out_dir / name
        shutil.copy(src, dst)
        return str(dst)

    def download_folder(self, id=None, output=None, quiet=False, use_cookies=True):
        self.calls.append(("download_folder", id, output))
        root = Path(output) / "Thu muc Drive"
        root.mkdir(parents=True, exist_ok=True)
        got = []
        for name, src in self.payload.items():
            dst = root / name
            shutil.copy(src, dst)
            got.append(str(dst))
        return got


class ParseDriveLinkTests(unittest.TestCase):
    def test_folder_links(self):
        for url in (
            f"https://drive.google.com/drive/folders/{FOLDER_ID}",
            f"https://drive.google.com/drive/folders/{FOLDER_ID}?usp=sharing",
            f"https://drive.google.com/drive/u/0/folders/{FOLDER_ID}",
            f"https://drive.google.com/folderview?id={FOLDER_ID}",
        ):
            self.assertEqual(parse_drive_link(url), ("folder", FOLDER_ID), url)

    def test_file_links(self):
        for url in (
            f"https://drive.google.com/file/d/{FILE_ID}/view?usp=sharing",
            f"https://drive.google.com/file/d/{FILE_ID}/view?usp=drive_link",
            f"https://drive.google.com/file/d/{FILE_ID}",  # thiếu /view
            f"https://drive.google.com/file/u/1/d/{FILE_ID}/view",
            f"https://drive.google.com/open?id={FILE_ID}",
            f"https://drive.google.com/uc?export=download&id={FILE_ID}",
            f"  https://drive.google.com/uc?id={FILE_ID}  ",
        ):
            self.assertEqual(parse_drive_link(url), ("file", FILE_ID), url)

    def test_links_without_id(self):
        for url in (
            "https://drive.google.com/drive/my-drive",
            "https://drive.google.com/",
            "https://drive.google.com/file/d/short/view",
        ):
            self.assertIsNone(parse_drive_link(url), url)


class CollectorTests(unittest.TestCase):
    def setUp(self):
        self.work = Path(tempfile.mkdtemp(prefix="sc-test-"))
        self.logs = []
        self.collector = Collector(log=lambda m, lv="info": self.logs.append((lv, m)))

    def tearDown(self):
        self.collector.cleanup()
        self.assertFalse(self.collector._tmp.exists(), "cleanup phải xoá thư mục tạm")
        shutil.rmtree(self.work, ignore_errors=True)

    def _errors(self):
        return [m for lv, m in self.logs if lv == "error"]

    # -- ZIP trên máy (hồi quy sau khi tách _extract_zip) -------------------
    def test_local_zip_extracts_only_images(self):
        archive = _make_zip(
            self.work / "anh.zip",
            ["a.png", "sub/b.jpg", "__MACOSX/._a.png", "ghi-chu.txt", "sub/.DS_Store"],
        )
        items = self.collector.collect([str(archive)])
        self.assertEqual(sorted(str(i.rel) for i in items), ["a.png", "sub/b.jpg"])
        for it in items:
            self.assertTrue(it.ephemeral)
            self.assertTrue(it.path.is_file())
            self.assertTrue(it.origin.startswith("anh.zip:"), it.origin)

    def test_two_local_zips_with_same_name_do_not_collide(self):
        (self.work / "x").mkdir()
        (self.work / "y").mkdir()
        z1 = _make_zip(self.work / "x" / "anh.zip", ["1.png"])
        z2 = _make_zip(self.work / "y" / "anh.zip", ["1.png"])
        items = self.collector.collect([str(z1), str(z2)])
        self.assertEqual(len(items), 2)
        self.assertNotEqual(items[0].path, items[1].path)

    # -- Drive: link FILE trỏ tới ZIP ---------------------------------------
    def test_drive_file_link_to_zip_is_downloaded_and_extracted(self):
        archive = _make_zip(
            self.work / "src.zip", ["a.png", "sub/b.jpg", "__MACOSX/._a.png", "note.txt"]
        )
        fake = FakeGdown({"Ảnh Gemini.zip": archive})
        url = f"https://drive.google.com/file/d/{FILE_ID}/view?usp=sharing"
        with patch.dict(sys.modules, {"gdown": fake}):
            items = self.collector.collect([url])

        self.assertEqual(fake.calls[0][0], "download")
        self.assertEqual(fake.calls[0][1], FILE_ID, "phải truyền id đã rút, không truyền URL")
        self.assertTrue(fake.calls[0][2].endswith("/"), "output phải là thư mục để giữ tên file gốc")

        self.assertEqual(sorted(str(i.rel) for i in items), ["a.png", "sub/b.jpg"])
        for it in items:
            self.assertTrue(it.ephemeral)
            self.assertTrue(it.path.is_file())
            self.assertTrue(it.origin.startswith("Drive/Ảnh Gemini.zip:"), it.origin)
        self.assertEqual(self._errors(), [])
        self.assertTrue(any("giải nén 2 ảnh" in m for _, m in self.logs), self.logs)

    def test_drive_file_link_to_single_image(self):
        img = self.work / "one.jpg"
        img.write_bytes(_fake_png())
        fake = FakeGdown({"one.jpg": img})
        with patch.dict(sys.modules, {"gdown": fake}):
            items = self.collector.collect([f"https://drive.google.com/open?id={FILE_ID}"])
        self.assertEqual(len(items), 1)
        self.assertEqual(str(items[0].rel), "one.jpg")
        self.assertEqual(items[0].origin, "Drive/one.jpg")

    # -- Drive: link THƯ MỤC chứa cả ảnh lẻ lẫn ZIP ---------------------------
    def test_drive_folder_with_images_and_zip(self):
        img = self.work / "x.png"
        img.write_bytes(_fake_png())
        archive = _make_zip(self.work / "y.zip", ["p/1.png", "p/2.png", "readme.md"])
        fake = FakeGdown({"x.png": img, "y.zip": archive})
        url = f"https://drive.google.com/drive/u/0/folders/{FOLDER_ID}"
        with patch.dict(sys.modules, {"gdown": fake}):
            items = self.collector.collect([url])

        self.assertEqual(fake.calls[0][:2], ("download_folder", FOLDER_ID))
        self.assertEqual(len(items), 3)
        origins = sorted(i.origin for i in items)
        self.assertEqual(origins[0], "Drive/Thu muc Drive/x.png")
        self.assertTrue(origins[1].startswith("Drive/Thu muc Drive/y.zip:"))
        self.assertEqual(self._errors(), [])

    # -- Drive: các trường hợp lỗi -------------------------------------------
    def test_drive_link_without_id_is_rejected_before_download(self):
        fake = FakeGdown({})
        with patch.dict(sys.modules, {"gdown": fake}):
            items = self.collector.collect(["https://drive.google.com/drive/my-drive"])
        self.assertEqual(items, [])
        self.assertEqual(fake.calls, [])
        self.assertTrue(any("Không nhận ra ID" in m for m in self._errors()), self.logs)

    def test_drive_html_page_named_zip_logs_clear_error(self):
        # Drive chưa chia sẻ công khai thường trả về trang HTML thay vì file.
        html = self.work / "page.html"
        html.write_text("<html>Bạn cần quyền truy cập</html>", encoding="utf-8")
        fake = FakeGdown({"anh.zip": html})
        with patch.dict(sys.modules, {"gdown": fake}):
            items = self.collector.collect([f"https://drive.google.com/file/d/{FILE_ID}/view"])
        self.assertEqual(items, [])
        self.assertTrue(any("không phải file ZIP hợp lệ" in m for m in self._errors()), self.logs)

    def test_drive_download_failure_is_logged_not_raised(self):
        class Boom(FakeGdown):
            def download(self, id=None, output=None, quiet=False, use_cookies=True):
                raise RuntimeError("Cannot retrieve the public link of the file")

        fake = Boom({})
        with patch.dict(sys.modules, {"gdown": fake}):
            items = self.collector.collect([f"https://drive.google.com/file/d/{FILE_ID}/view"])
        self.assertEqual(items, [])
        self.assertTrue(any("Tải Drive thất bại" in m for m in self._errors()), self.logs)


if __name__ == "__main__":
    unittest.main()
