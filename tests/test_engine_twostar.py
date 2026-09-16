"""Dấu Gemini hai sao (sao lớn + sao nhỏ chếch dưới-trái) phải được dò và gỡ cả hai.

Ảnh thử được tạo tổng hợp: nền có gradient và vân hạt nhiều tầng, phủ lớp trắng
bán trong suốt đúng theo mô hình astroid, rồi nén JPEG như ảnh thật.
"""

import unittest

import cv2
import numpy as np

from sparkle_cleaner import engine
from sparkle_cleaner.engine import ASTROID_P, _astroid  # noqa: F401 — dùng trong test màu

W, H = 1000, 620
BIG = (930.0, 545.0, 28.0)  # cx, cy, r
SMALL = (BIG[0] - 1.3 * BIG[2], BIG[1] + 1.55 * BIG[2], 0.45 * BIG[2])
ALPHA = 0.45


def _background(seed: int = 1) -> np.ndarray:
    rng = np.random.default_rng(seed)
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float64)
    base = 70 + 60 * (xx / W) + 20 * np.sin(yy / 23.0)
    tex = np.zeros((H, W))
    for sigma, amp in ((1.0, 10.0), (3.0, 12.0), (9.0, 15.0)):
        n = cv2.GaussianBlur(rng.normal(0, 1, (H, W)), (0, 0), sigma)
        tex += amp * n / (n.std() + 1e-9)
    g = np.clip(base + tex, 0, 255)
    return np.clip(np.stack([g * 0.95, g, g * 1.08], axis=2), 0, 255)


def _overlay(rgb: np.ndarray, cx: float, cy: float, r: float, alpha: float, edge: float = 0.12):
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float64)
    d = _astroid(xx, yy, cx, cy, r, r, ASTROID_P)
    a = alpha * np.clip((1.0 - d) / edge + 0.5, 0, 1)
    a = cv2.GaussianBlur(a, (0, 0), max(0.5, r * 0.02))
    return (1 - a[..., None]) * rgb + a[..., None] * 255.0


def _jpeg(rgb: np.ndarray, q: int = 90) -> np.ndarray:
    u8 = np.clip(np.rint(rgb), 0, 255).astype(np.uint8)
    ok, buf = cv2.imencode(".jpg", cv2.cvtColor(u8, cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, q])
    assert ok
    return cv2.cvtColor(cv2.imdecode(buf, cv2.IMREAD_COLOR), cv2.COLOR_BGR2RGB)


def _star_mask(cx, cy, r):
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float64)
    return _astroid(xx, yy, cx, cy, r, r, ASTROID_P) <= 1.0


def _lowpass_err(a: np.ndarray, b: np.ndarray, mask: np.ndarray) -> float:
    ga = cv2.GaussianBlur(a.mean(2), (0, 0), 2.0)
    gb = cv2.GaussianBlur(b.mean(2), (0, 0), 2.0)
    return float(np.abs(ga - gb)[mask].mean())


class TwoStarTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.clean = _jpeg(_background())
        two = _overlay(_overlay(_background(), *BIG, ALPHA), *SMALL, ALPHA)
        cls.two = _jpeg(two)
        cls.one = _jpeg(_overlay(_background(), *BIG, ALPHA))

    def test_two_star_mark_detected_with_companion(self):
        report = []
        mark = engine.detect(self.two, report=report)
        self.assertIsNotNone(mark, "\n".join(report))
        self.assertLess(abs(mark.cx - BIG[0]), 4, mark.describe())
        self.assertLess(abs(mark.cy - BIG[1]), 4, mark.describe())
        self.assertTrue(0.8 <= mark.r / BIG[2] <= 1.25, mark.describe())
        self.assertIsNotNone(mark.sub, "không thấy sao nhỏ:\n" + "\n".join(report))
        self.assertLess(abs(mark.sub.cx - SMALL[0]), 4, mark.describe())
        self.assertLess(abs(mark.sub.cy - SMALL[1]), 4, mark.describe())
        self.assertTrue(0.7 <= mark.sub.r / SMALL[2] <= 1.4, mark.describe())

    def test_two_star_mark_removed_from_both_stars(self):
        """Gỡ xong, vùng từng sao phải gần ảnh gốc sạch.

        Ngưỡng tuyệt đối 11 mức xám (trên 255) là sàn của chính phép giải ngược,
        không phải bóng ma sót lại: ảnh thử phủ lớp trắng rất đậm (độ phủ 0.45),
        nên chia cho (1 − 0.45) khuếch đại nhiễu nền và nhiễu JPEG lên 1.8 lần.
        Phép kiểm quan trọng hơn nằm ở test kế bên: gỡ dấu hai sao không được
        tệ hơn gỡ đúng sao đó khi nó đứng một mình.
        """
        mark = engine.detect(self.two)
        self.assertIsNotNone(mark)
        self.assertIsNotNone(mark.sub)
        out = engine.remove(self.two.astype(np.float64), mark, restore_grain=False)
        clean = self.clean.astype(np.float64)
        marked = self.two.astype(np.float64)
        for name, (cx, cy, r) in (("sao lớn", BIG), ("sao nhỏ", SMALL)):
            m = _star_mask(cx, cy, r)
            before = _lowpass_err(marked, clean, m)
            after = _lowpass_err(out, clean, m)
            self.assertLess(after, 11.0, f"{name}: sai số còn {after:.1f} (trước {before:.1f})")
            self.assertLess(after, 0.3 * before, f"{name}: gỡ chưa đủ ({after:.1f} vs {before:.1f})")

    def test_big_star_removed_as_well_as_when_alone(self):
        """Sao lớn trong dấu hai sao phải được gỡ sạch ngang khi nó đứng một mình.

        Đây là phép so sánh không phụ thuộc hằng số: cùng một sao, cùng nền, chỉ
        khác việc có sao nhỏ bên cạnh hay không.
        """
        clean = self.clean.astype(np.float64)
        m = _star_mask(*BIG)

        one_mark = engine.detect(self.one)
        self.assertIsNotNone(one_mark)
        err_alone = _lowpass_err(
            engine.remove(self.one.astype(np.float64), one_mark, restore_grain=False), clean, m
        )

        two_mark = engine.detect(self.two)
        self.assertIsNotNone(two_mark)
        err_pair = _lowpass_err(
            engine.remove(self.two.astype(np.float64), two_mark, restore_grain=False), clean, m
        )
        self.assertLess(
            err_pair, err_alone + 1.5,
            f"có sao nhỏ bên cạnh làm sao lớn gỡ kém đi: {err_pair:.1f} so với {err_alone:.1f}",
        )

    def test_single_star_mark_has_no_companion(self):
        report = []
        mark = engine.detect(self.one, report=report)
        self.assertIsNotNone(mark, "\n".join(report))
        self.assertLess(abs(mark.cx - BIG[0]), 4, mark.describe())
        self.assertLess(abs(mark.cy - BIG[1]), 4, mark.describe())
        self.assertIsNone(mark.sub, "nhận nhầm sao nhỏ: " + mark.describe())

    def test_clean_image_not_flagged(self):
        report = []
        mark = engine.detect(self.clean, report=report)
        self.assertIsNone(mark, "\n".join(report))

    def test_faint_blob_rejected_by_alpha_gate(self):
        """Vệt sáng rất mờ trên nền tối phải bị loại ở mức nhạy mặc định.

        Đây là dạng báo nhầm hay gặp nhất: nền tối làm phép chuẩn hoá độ phủ
        khuếch đại nhiễu, nên hình dạng có thể khớp mà độ phủ vẫn rất thấp.
        Mức "nhạy" cố tình hạ ngưỡng nên không kiểm ở đây.
        """
        rng = np.random.default_rng(5)
        yy, xx = np.mgrid[0:H, 0:W].astype(np.float64)
        dark = 26 + 14 * (xx / W) + cv2.GaussianBlur(rng.normal(0, 9, (H, W)), (0, 0), 2.0)
        rgb = np.clip(np.stack([dark * 0.97, dark, dark * 1.05], axis=2), 0, 255)
        faint = _jpeg(_overlay(rgb, *BIG, 0.07))
        self.assertIsNone(engine.detect(faint), "vệt mờ độ phủ 0.07 lại được nhận")

    def test_white_overlay_is_color_neutral_but_tinted_blob_is_not(self):
        """Lớp phủ trắng nâng đều ba kênh màu; vùng có màu thì không.

        Đây là phép thử tách bạch nhất trên ảnh thật — nó loại được ngón tay,
        mặt gỗ và ánh đèn ấm, vốn khớp hình sao rất tốt trên ảnh xám.
        """
        mark = engine.detect(self.one)
        self.assertIsNotNone(mark)
        self.assertLess(engine.color_bias(self.one, mark), 0.12)

        # Cùng vị trí, cùng hình, nhưng phủ màu da cam nhạt thay vì trắng.
        yy, xx = np.mgrid[0:H, 0:W].astype(np.float64)
        d = _astroid(xx, yy, *BIG[:2], BIG[2], BIG[2], ASTROID_P)
        a = cv2.GaussianBlur(0.45 * np.clip((1.0 - d) / 0.12 + 0.5, 0, 1), (0, 0), 1.0)
        tint = np.array([255.0, 190.0, 140.0])
        blob = _jpeg((1 - a[..., None]) * _background() + a[..., None] * tint)
        m2 = engine.detect(blob, max_color_bias=1.0)  # cố tình tắt cổng màu
        if m2 is not None:
            self.assertGreater(engine.color_bias(blob, m2), 0.12)
        self.assertIsNone(engine.detect(blob), "vùng phủ màu cam lại được nhận là dấu")

    def test_sensitivity_table_has_alpha_threshold(self):
        from sparkle_cleaner.pipeline import SENSITIVITY

        for name, values in SENSITIVITY.items():
            self.assertEqual(len(values), 4, f"{name} thiếu ngưỡng độ phủ")
        self.assertLess(SENSITIVITY["nhay"][3], SENSITIVITY["canbang"][3])
        self.assertLess(SENSITIVITY["canbang"][3], SENSITIVITY["chat"][3])


if __name__ == "__main__":
    unittest.main()
