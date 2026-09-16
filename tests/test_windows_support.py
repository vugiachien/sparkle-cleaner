"""Kiểm thử phần làm cho app chạy được trên Windows.

Chạy được trên máy Mac/Linux: các hàm liên quan đến Windows đều nhận tham số
để ép chạy nhánh Windows, nên không cần máy Windows mới kiểm thử được.
"""

import sys
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

from sparkle_cleaner.sources import Collector, safe_zip_name  # noqa: E402
from win_install_wheels import compatible  # noqa: E402


def _fake_png() -> bytes:
    return b"\x89PNG\r\n\x1a\n" + b"\x00" * 16


class SafeZipNameTests(unittest.TestCase):
    """Tên trong ZIP -> tên ghi được, nhất là khi ZIP nén từ Mac mở trên Windows."""

    def test_ten_binh_thuong_giu_nguyen_tren_moi_he_dieu_hanh(self):
        for win in (False, True):
            self.assertEqual(safe_zip_name("anh/con-meo.jpg", win), "anh/con-meo.jpg")

    def test_tieng_viet_co_dau_khong_bi_dong_vao(self):
        # Dấu tiếng Việt hợp lệ trên cả hai hệ — không được thay bậy.
        self.assertEqual(safe_zip_name("Ảnh mới/hoa đào.png", True), "Ảnh mới/hoa đào.png")

    def test_ky_tu_windows_cam_bi_thay_khi_chay_tren_windows(self):
        self.assertEqual(safe_zip_name('anh 1:2.jpg', True), "anh 1_2.jpg")
        self.assertEqual(safe_zip_name('a?b*c|d.png', True), "a_b_c_d.png")

    def test_ky_tu_do_van_giu_nguyen_tren_mac(self):
        # Không đổi hành vi sẵn có của bản macOS.
        self.assertEqual(safe_zip_name("anh 1:2.jpg", False), "anh 1:2.jpg")

    def test_ten_thiet_bi_dos_duoc_doi_di(self):
        self.assertEqual(safe_zip_name("con.jpg", True), "_con.jpg")
        self.assertEqual(safe_zip_name("NUL.png", True), "_NUL.png")
        self.assertEqual(safe_zip_name("console.jpg", True), "console.jpg")  # không phải CON

    def test_dau_cham_va_dau_cach_cuoi_ten_bi_cat(self):
        # Windows tự cắt, nên phải cắt sẵn kẻo tên ghi ra một đằng nhớ một nẻo.
        self.assertEqual(safe_zip_name("anh.jpg .", True), "anh.jpg")

    def test_chan_zip_slip_o_ca_hai_he(self):
        for win in (False, True):
            self.assertEqual(safe_zip_name("../../etc/passwd.jpg", win), "etc/passwd.jpg")
            self.assertEqual(safe_zip_name("/tmp/x.jpg", win), "tmp/x.jpg")
            self.assertIsNone(safe_zip_name("../..", win))
            self.assertIsNone(safe_zip_name("", win))

    def test_dau_gach_nguoc_duoc_coi_la_dau_phan_cach(self):
        self.assertEqual(safe_zip_name(r"thu-muc\anh.jpg", True), "thu-muc/anh.jpg")
        self.assertEqual(safe_zip_name(r"..\..\x.jpg", True), "x.jpg")


class ExtractZipTests(unittest.TestCase):
    """Giải nén thật, để chắc tên đã làm sạch cũng là tên dùng khi ghi kết quả."""

    def setUp(self):
        self.logs = []
        self.col = Collector(log=lambda m, lv="info": self.logs.append((lv, m)))
        self.addCleanup(self.col.cleanup)
        self.tmp = self.col._fresh_dir("test-")

    def test_anh_van_lay_duoc_va_rel_khop_file_that(self):
        z = self.tmp / "a.zip"
        with zipfile.ZipFile(z, "w") as zf:
            zf.writestr("thu muc/anh.jpg", _fake_png())
            zf.writestr("ghi-chu.txt", b"bo qua")
        items = self.col._extract_zip(z, self.col._fresh_dir("out-"), "a.zip")
        self.assertEqual(len(items), 1)
        it = items[0]
        self.assertTrue(it.path.is_file())
        # rel là tên dùng để đặt tên file kết quả — phải trỏ đúng file vừa ghi.
        self.assertTrue(str(it.path).endswith(str(it.rel)))

    def test_muc_vuot_ra_ngoai_thu_muc_dich_khong_duoc_ghi(self):
        z = self.tmp / "b.zip"
        with zipfile.ZipFile(z, "w") as zf:
            zf.writestr("../thoat-ra.jpg", _fake_png())
        dest = self.col._fresh_dir("out-")
        items = self.col._extract_zip(z, dest, "b.zip")
        for it in items:
            self.assertIn(str(dest.resolve()), str(it.path.resolve()))
        self.assertFalse((dest.parent / "thoat-ra.jpg").exists())


class WheelCompatibilityTests(unittest.TestCase):
    """Bộ cài offline phải từ chối wheel sai, kẻo tới lúc import mới đổ lỗi khó hiểu."""

    def test_nhan_wheel_dung(self):
        v = sys.version_info
        self.assertTrue(compatible(Path(f"numpy-2.5.3-cp{v.major}{v.minor}-"
                                        f"cp{v.major}{v.minor}-win_amd64.whl")))
        self.assertTrue(compatible(Path("gdown-6.2.0-py3-none-any.whl")))

    def test_tu_choi_wheel_sai_phien_ban_hoac_sai_nen_tang(self):
        v = sys.version_info
        for bad in (
            f"numpy-2.5.3-cp{v.major}{v.minor - 1}-cp{v.major}{v.minor - 1}-win_amd64.whl",
            f"numpy-2.5.3-cp{v.major}{v.minor}-cp{v.major}{v.minor}-win32.whl",
            f"numpy-2.5.3-cp{v.major}{v.minor}-cp{v.major}{v.minor}-macosx_11_0_arm64.whl",
        ):
            self.assertFalse(compatible(Path(bad)), bad)

    def test_abi3_cu_hon_thi_dung_duoc_con_moi_hon_thi_khong(self):
        v = sys.version_info
        self.assertTrue(compatible(Path(f"x-1-cp{v.major}{v.minor - 2}-abi3-win_amd64.whl")))
        self.assertFalse(compatible(Path(f"x-1-cp{v.major}{v.minor + 1}-abi3-win_amd64.whl")))


if __name__ == "__main__":
    unittest.main()
