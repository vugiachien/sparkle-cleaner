"""Kiểm thử cách Worker xoay xở khi chạy đa tiến trình hỏng.

Đây là kịch bản hay gặp trên Windows: mỗi tiến trình con là một pythonw.exe
chạy lại từ đầu, nên phần mềm diệt virus chặn tạo tiến trình, hoặc máy yếu hết
RAM, là cả pool chết. Khi đó app phải xử lý nốt chứ không được bỏ dở cả lượt.
"""

import unittest
from concurrent.futures import Future
from concurrent.futures.process import BrokenProcessPool
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import numpy as np
from PIL import Image
from PySide6.QtWidgets import QApplication

from sparkle_cleaner.app import Worker

app = QApplication.instance() or QApplication([])


class _PoolChetNgayLucTao:
    """Pool không tạo nổi tiến trình con nào — như khi bị diệt virus chặn."""

    def __init__(self, **kwargs):
        raise BrokenProcessPool("giả lập: không tạo được tiến trình con")


class _PoolChayTaiCho:
    """Executor giả: chạy ngay trong luồng này nhưng trả về Future thật.

    ``huy_viec_dau`` ép việc đầu tiên thành 'đã huỷ', đúng như khi người dùng
    bấm Dừng, để kiểm tra CancelledError không giết cả lượt xử lý.
    """

    def __init__(self, huy_viec_dau=False, initializer=None, **kwargs):
        if initializer is not None:
            initializer()
        self.huy_viec_dau = huy_viec_dau
        self.so_viec = 0

    def submit(self, fn, arg):
        fut = Future()
        self.so_viec += 1
        if self.huy_viec_dau and self.so_viec == 1:
            fut.cancel()
            fut.set_running_or_notify_cancel()
        else:
            fut.set_result(fn(arg))
        return fut

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _tao_anh(folder: Path, n: int) -> None:
    """Ảnh nhiễu ngẫu nhiên — chắc chắn không chứa dấu sparkle."""
    rng = np.random.default_rng(0)
    for i in range(n):
        arr = rng.integers(60, 200, (48, 64, 3), dtype=np.uint8)
        Image.fromarray(arr).save(folder / f"anh{i}.png")


class WorkerFallbackTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.src = Path(self.tmp.name) / "vao"
        self.out = Path(self.tmp.name) / "ra"
        self.src.mkdir()
        _tao_anh(self.src, 3)
        self.logs: list[tuple[str, str]] = []
        self.summary: dict = {}

    def _worker(self, workers=4) -> Worker:
        w = Worker([str(self.src)], {
            "out_dir": str(self.out), "beside_source": False, "keep_tree": False,
            "suffix": "_clean", "sensitivity": "canbang", "format": "giu",
            "quality": 96, "strip_meta": True, "restore_grain": True,
            "copy_when_clean": True, "workers": workers,
        })
        w.log.connect(lambda m, lv: self.logs.append((lv, m)))
        w.done.connect(self.summary.update)
        return w

    def test_pool_chet_thi_van_xu_ly_het_anh_theo_kieu_tuan_tu(self):
        w = self._worker()
        with patch("sparkle_cleaner.app.ProcessPoolExecutor", _PoolChetNgayLucTao):
            w.run()  # gọi thẳng, không start() — chạy đồng bộ trong test

        self.assertEqual(self.summary["total"], 3)
        self.assertEqual(self.summary["clean"], 3, "phải xử lý đủ cả 3 ảnh")
        self.assertEqual(self.summary["error"], 0)
        self.assertEqual(len(list(self.out.glob("*.png"))), 3, "phải ghi ra đủ 3 file")
        self.assertTrue(
            any("tuần tự" in m for _, m in self.logs),
            "phải nói rõ trong nhật ký là đã chuyển sang chạy tuần tự",
        )

    def test_viec_bi_huy_khong_bi_tinh_thanh_loi(self):
        w = self._worker()
        with patch("sparkle_cleaner.app.ProcessPoolExecutor",
                   lambda **kw: _PoolChayTaiCho(huy_viec_dau=True, **kw)):
            w._stop = True  # như vừa bấm nút Dừng
            w.run()

        # Trước khi sửa, mỗi việc bị huỷ rơi vào "except Exception" và bị đếm
        # thành một lỗi, dù người dùng chỉ bấm Dừng.
        self.assertEqual(self.summary["error"], 0)
        self.assertFalse(
            any("không lường trước" in m for _, m in self.logs),
            "bấm Dừng không được sinh ra lỗi không lường trước",
        )

    def test_mot_luong_thi_chay_thang_khong_dung_toi_pool(self):
        w = self._worker(workers=1)
        with patch("sparkle_cleaner.app.ProcessPoolExecutor", _PoolChetNgayLucTao):
            w.run()
        self.assertEqual(self.summary["clean"], 3)


if __name__ == "__main__":
    unittest.main()
