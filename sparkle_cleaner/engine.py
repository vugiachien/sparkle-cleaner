"""
Tự dò và gỡ dấu sparkle (ngôi sao 4 cánh) của Gemini/Imagen khỏi ảnh.

Cách tiếp cận: dấu này KHÔNG phải logo đục đè, nó là một lớp trắng phủ bán
trong suốt (alpha ~0.25-0.60) theo hình astroid. Vì vậy thay vì vá đè
(inpaint) — vốn xoá luôn chi tiết thật nằm dưới — ta giải ngược phép trộn:

    obs = (1 - a) * goc + a * 255     ->     goc = (obs - 255a) / (1 - a)

Nhờ vậy mọi đường nét, vân bề mặt nằm dưới dấu đều được khôi phục nguyên vẹn.
Sau đó bù lại phần vân hạt mà JPEG đã làm bệt bên dưới dấu, và làm phẳng nốt
viền còn sót — có bảo vệ các đường nét dài thật trong ảnh.

Dấu Gemini đời mới gồm HAI sao: một sao lớn và một sao nhỏ (bán kính ~0.45
sao lớn) nằm chếch dưới-trái, cách tâm sao lớn ~2 lần bán kính. Bộ dò tìm sao
lớn trước, rồi tìm sao nhỏ trong vùng đó; khi thấy thì khớp lại sao lớn với
sao nhỏ đã loại khỏi nền, và gỡ cả hai cùng lúc.
"""

from __future__ import annotations

import dataclasses

import cv2
import numpy as np
from scipy.optimize import least_squares, minimize

# Số mũ của siêu-ellipse tạo hình sao 4 cánh lõm cạnh (astroid).
ASTROID_P = 2.0 / 3.0

# Sao nhỏ của dấu Gemini nằm chếch dưới-trái sao lớn: góc ~130° trong hệ toạ
# độ ảnh (x sang phải, y xuống dưới; 90° là thẳng xuống, 180° là sang trái).
COMPANION_ANGLE = (95.0, 165.0)


@dataclasses.dataclass
class Mark:
    """Tham số của dấu sparkle tìm thấy trong ảnh."""

    cx: float
    cy: float
    rx: float
    ry: float
    p: float
    alpha: float
    edge: float
    score: float
    fit_r2: float = 0.0
    sub: Mark | None = None  # sao nhỏ đi kèm (dấu Gemini hai sao), nếu có

    @property
    def r(self) -> float:
        return 0.5 * (self.rx + self.ry)

    def stars(self) -> list[Mark]:
        return [self] + ([self.sub] if self.sub is not None else [])

    def describe(self) -> str:
        s = (
            f"tâm ({self.cx:.0f}, {self.cy:.0f}) · bán kính {self.rx:.1f}×{self.ry:.1f}px "
            f"· độ phủ {self.alpha:.3f} · độ tách {self.score:.1f} "
            f"· độ khớp {self.fit_r2:.2f}"
        )
        if self.sub is not None:
            s += (
                f" · kèm sao nhỏ tại ({self.sub.cx:.0f}, {self.sub.cy:.0f}) "
                f"bán kính {self.sub.r:.1f}px độ phủ {self.sub.alpha:.3f}"
            )
        return s


# ----------------------------------------------------------------------------
# Dò tìm
# ----------------------------------------------------------------------------


def _astroid(shape_x, shape_y, cx, cy, rx, ry, p):
    return (np.abs(shape_x - cx) / max(rx, 1e-6)) ** p + (
        np.abs(shape_y - cy) / max(ry, 1e-6)
    ) ** p


def _template(r: float, p: float = ASTROID_P) -> np.ndarray:
    n = int(np.ceil(r * 1.30)) * 2 + 1
    c = n // 2
    yy, xx = np.mgrid[0:n, 0:n].astype(np.float64)
    d = _astroid(xx, yy, c, c, r, r, p)
    t = np.clip((1.0 - d) / 0.16 + 0.5, 0, 1)
    return cv2.GaussianBlur(t, (0, 0), max(0.6, r * 0.03)).astype(np.float32)


def _alpha_map(gray: np.ndarray, r: float) -> np.ndarray:
    """Ước lượng thô 'độ phủ trắng', chuẩn hoá theo độ sáng nền.

    Nhờ chia cho (255 - nền), dấu trên nền tối và trên nền sáng đều cho giá trị
    tương đương, nên một ngưỡng duy nhất dùng được cho mọi loại ảnh.
    """
    bg = cv2.GaussianBlur(gray, (0, 0), max(1.5, r * 1.8))
    return ((gray - bg) / np.clip(255.0 - bg, 1.0, None)).astype(np.float32)


def _search_region(w: int, h: int) -> tuple[int, int, int, int]:
    """Dấu của Gemini luôn nằm ở góc dưới phải; quét rộng rãi quanh đó."""
    return int(w * 0.45), int(h * 0.40), w, h


# Dấu Gemini luôn nằm sát góc dưới phải. Đo trên ảnh thật, tâm dấu cách mép
# phải chừng 2–6% chiều rộng và cách mép dưới chừng 8–16% chiều cao; ngưỡng
# dưới đây nới rộng gấp đôi mức đó. Đây là cổng chặn báo nhầm hiệu quả nhất:
# phần lớn thứ bị nhận nhầm (nếp vải, mép gỗ, bánh xe, khuy áo) nằm giữa ảnh.
MAX_MARGIN_X = 0.12
MAX_MARGIN_Y = 0.22


def _companion_zone(xx, yy, cx, cy, r, near: float, far: float) -> np.ndarray:
    """Vùng có thể chứa sao nhỏ: hình quạt dưới-trái, cách tâm từ near·r đến far·r."""
    dx, dy = xx - cx, yy - cy
    dist = np.hypot(dx, dy)
    ang = np.degrees(np.arctan2(dy, dx))
    return (
        (ang >= COMPANION_ANGLE[0])
        & (ang <= COMPANION_ANGLE[1])
        & (dist >= near * r)
        & (dist <= far * r)
    )


def _top_peaks(resp: np.ndarray, k: int, min_dist: int):
    """Lấy k đỉnh cao nhất, cách nhau tối thiểu min_dist."""
    work = resp.copy()
    out = []
    for _ in range(k):
        _, mx, _, loc = cv2.minMaxLoc(work)
        if not np.isfinite(mx):
            break
        out.append((float(mx), loc[0], loc[1]))
        x0 = max(0, loc[0] - min_dist)
        y0 = max(0, loc[1] - min_dist)
        work[y0 : loc[1] + min_dist + 1, x0 : loc[0] + min_dist + 1] = -1e9
    return out


def _quality(gray_full: np.ndarray, cx: float, cy: float, r: float):
    """Kiểm định một ứng viên: lớp phủ thật phải nổi rõ và đều so với nền.

    Trả về (độ tách, độ phủ trung bình, độ đều, độ lõm) hoặc None nếu không đánh
    giá được. Đây mới là thứ phân biệt dấu thật với một cụm nhiễu tình cờ khớp
    hình — điểm tương quan đơn thuần cho điểm cao cả trên nhiễu.
    """
    h, w = gray_full.shape
    pad = int(r * 3.0) + 6
    x0, y0 = max(0, int(cx) - pad), max(0, int(cy) - pad)
    x1, y1 = min(w, int(cx) + pad), min(h, int(cy) + pad)
    roi = gray_full[y0:y1, x0:x1]
    if roi.shape[0] < r * 2.2 or roi.shape[1] < r * 2.2:
        return None

    yy, xx = np.mgrid[0 : roi.shape[0], 0 : roi.shape[1]].astype(np.float64)
    sm = cv2.GaussianBlur(roi, (0, 0), max(0.8, r * 0.037))
    d = _astroid(xx, yy, cx - x0, cy - y0, r, r, ASTROID_P)
    bg = _inpaint_like(sm, d <= 1.5, max(5, int(r * 0.35)))
    target = (sm - bg) / np.clip(255.0 - bg, 1.0, None)

    inside, ring = d <= 0.70, (d >= 1.30) & (d <= 2.30)
    circ = np.hypot(xx - (cx - x0), yy - (cy - y0))
    # Dấu Gemini hai sao có sao nhỏ nằm chếch dưới-trái, rơi đúng vào vành "nền
    # sạch" này. Bỏ góc đó ra khỏi vành để sao nhỏ không bị tính là nhiễu nền.
    ring &= ~_companion_zone(xx, yy, cx - x0, cy - y0, r, 1.15, 3.5)
    # "Khe lõm": nằm trong đường tròn ngoại tiếp nhưng ngoài hình sao. Với dấu
    # thật, bốn khe này phải là nền sạch — đây là thứ loại được các đốm sáng
    # tròn (giọt nước, ánh kim) vốn khớp mọi phép thử khác.
    notch = (d >= 1.20) & (circ <= 0.90 * r)
    if inside.sum() < 12 or ring.sum() < 40 or notch.sum() < 8:
        return None
    a_in = float(target[inside].mean())
    noise = float(target[ring].std()) + 1e-4
    sep = (a_in - float(target[ring].mean())) / noise
    shape = (a_in - float(target[notch].mean())) / noise
    unif = float(target[inside].std()) / max(a_in, 1e-4)
    return sep, a_in, unif, shape


def detect(
    rgb: np.ndarray,
    min_sep: float = 4.5,
    min_shape: float = 3.0,
    min_alpha: float = 0.11,
    max_unif: float = 0.75,
    min_fit: float = 0.65,
    max_color_bias: float = 0.12,
    report: list[str] | None = None,
) -> Mark | None:
    """Tìm dấu sparkle. Trả về None nếu ảnh không có dấu.

    Hai tầng: tương quan đa tỉ lệ để đề cử ứng viên, rồi bốn phép kiểm định
    (vị trí góc, độ nổi, hình lõm bốn khe, độ đều) để loại nhiễu. Điểm tương
    quan cao một mình không đủ — nhiễu hạt cũng đạt 0.8.

    ``report``: truyền vào một list để nhận lời giải thích từng bước (dùng cho
    ``--explain`` khi cần biết vì sao một ảnh không được nhận).
    """

    def note(msg: str) -> None:
        if report is not None:
            report.append(msg)

    h, w = rgb.shape[:2]
    gray_full = rgb.mean(2).astype(np.float64)

    # Giai đoạn đề cử chạy trên bản thu nhỏ: dấu vẫn thừa lớn để nhận ra, mà
    # ảnh 4K không còn mất nửa phút. Toạ độ tìm được sẽ khớp lại ở độ phân
    # giải gốc nên độ chính xác không đổi.
    scale = 1.0
    if max(w, h) > 1400:
        scale = 1400.0 / max(w, h)
        small = cv2.resize(
            gray_full, (max(1, int(w * scale)), max(1, int(h * scale))),
            interpolation=cv2.INTER_AREA,
        )
    else:
        small = gray_full
    sh, sw = small.shape
    sx, sy, ex, ey = _search_region(sw, sh)
    gray = small[sy:ey, sx:ex]
    if gray.shape[0] < 24 or gray.shape[1] < 24:
        note("ảnh quá nhỏ để dò")
        return None

    base = min(sw, sh)
    radii = np.unique(
        np.clip(
            np.round(np.geomspace(max(7.0, base * 0.015), base * 0.10, 12)), 7, 150
        )
    )
    edge_x, edge_y = MAX_MARGIN_X * sw, MAX_MARGIN_Y * sh  # sát góc dưới phải

    cands = []
    for r in radii:
        r = float(r)
        tpl = _template(r)
        if tpl.shape[0] >= gray.shape[0] or tpl.shape[1] >= gray.shape[1]:
            continue
        amap = _alpha_map(gray, r)
        resp = cv2.matchTemplate(amap, tpl, cv2.TM_CCOEFF_NORMED)
        c = tpl.shape[0] // 2
        for score, px, py in _top_peaks(resp, 2, max(3, int(r))):
            cx, cy = px + c + sx, py + c + sy
            if (sw - cx) > edge_x or (sh - cy) > edge_y:
                continue
            cands.append((score, r / scale, cx / scale, cy / scale))

    cands.sort(key=lambda t: -t[0])
    note(f"ảnh {w}×{h}, tỉ lệ dò {scale:.2f}, {len(cands)} ứng viên thô")
    passing = []
    for score, r, cx, cy in cands[:16]:
        q = _quality(small, cx * scale, cy * scale, r * scale)
        if q is None:
            note(f"  ứng viên r={r:.0f} tại ({cx:.0f},{cy:.0f}) tương quan {score:.2f}: không đánh giá được")
            continue
        sep, a_in, unif, shape = q
        ok = sep >= min_sep and shape >= min_shape and a_in >= min_alpha and unif <= max_unif
        note(
            f"  ứng viên r={r:.0f} tại ({cx:.0f},{cy:.0f}) tương quan {score:.2f}: "
            f"độ tách {sep:.1f} (cần ≥{min_sep}) · độ lõm {shape:.1f} (≥{min_shape}) · "
            f"độ phủ {a_in:.3f} (≥{min_alpha}) · độ đều {unif:.2f} (≤{max_unif}) → "
            f"{'đạt' if ok else 'loại'}"
        )
        if ok:
            passing.append((min(sep, shape), score, r, cx, cy))

    if not passing:
        note("không ứng viên nào qua kiểm định")
        return None
    passing.sort(key=lambda t: -t[0])
    order = [passing[0]]
    # Dấu hai sao: ứng viên thắng có thể lại là sao nhỏ. Nếu ngay cạnh có ứng
    # viên khác cũng đạt chuẩn mà to hơn hẳn thì thử sao lớn đó trước.
    _, _, r0, cx0, cy0 = passing[0]
    for cand in passing[1:]:
        if cand[2] >= 1.4 * r0 and np.hypot(cand[3] - cx0, cand[4] - cy0) <= 3.5 * cand[2]:
            order.insert(0, cand)
            note(f"  ưu tiên sao to hơn ngay cạnh: r={cand[2]:.0f} tại ({cand[3]:.0f},{cand[4]:.0f})")
            break

    for rank, score, r0, cx0, cy0 in order:
        mark = _refine(gray_full, cx0, cy0, r0, rank)
        if mark is None:
            note("  khớp mô hình thất bại")
            continue
        sub = _find_companion(gray_full, mark)
        if sub is not None:
            # Hai sao chồng lớp phủ lên nhau ở vùng giữa, nên khớp riêng từng
            # cái vẫn lệch. Khớp đồng thời cả hai mới ra đúng bán kính và viền.
            mark, sub = _refine_pair(gray_full, mark, sub)
            mark.sub = sub
            note(f"  thấy sao nhỏ đi kèm: {sub.describe()}")
        else:
            note("  không thấy sao nhỏ đi kèm (dấu một sao)")
        note(f"  khớp: {mark.describe()} · p={mark.p:.2f} · viền={mark.edge:.2f}")

        ratio = mark.rx / max(mark.ry, 1e-6)
        if not (min_alpha <= mark.alpha <= 0.80):
            note(f"  loại: độ phủ {mark.alpha:.3f} ngoài [{min_alpha:.3f}, 0.80]")
            continue
        if mark.fit_r2 < min_fit:
            note(f"  loại: độ khớp {mark.fit_r2:.2f} < {min_fit}")
            continue
        if mark.edge > 0.42:
            note(f"  loại: viền quá mềm ({mark.edge:.2f} > 0.42)")
            continue
        # Dấu thật gần tròn và cạnh lõm rõ (số mũ quanh 0.67–0.90). Vật thể
        # tròn nhặt nhầm — khuy áo, bánh xe, giọt sáng — cho số mũ cao hơn hẳn,
        # còn nếp vải và mép cạnh cho hình dẹt.
        if not (0.65 <= ratio <= 1.55) or not (0.45 <= mark.p <= 0.90):
            note(f"  loại: hình dạng lệch (tỉ lệ {ratio:.2f}, p={mark.p:.2f})")
            continue
        if (w - mark.cx) > MAX_MARGIN_X * w or (h - mark.cy) > MAX_MARGIN_Y * h:
            note(
                f"  loại: quá xa góc dưới phải (lề {100 * (w - mark.cx) / w:.1f}% "
                f"và {100 * (h - mark.cy) / h:.1f}%)"
            )
            continue
        bias = color_bias(rgb, mark)
        if bias is not None and bias > max_color_bias:
            note(f"  loại: lớp phủ không trắng thuần (lệch màu {bias:.2f} > {max_color_bias})")
            continue
        note(f"  lệch màu {bias:.2f}" if bias is not None else "  không đo được lệch màu")
        note("  → nhận")
        return mark
    return None


def _inpaint_like(chan: np.ndarray, mask: np.ndarray, rad: int) -> np.ndarray:
    """Nội suy vùng mask từ xung quanh, giữ hướng của các đường nét đi qua."""
    lo, hi = float(chan.min()), float(chan.max())
    span = max(hi - lo, 1e-6)
    u8 = np.clip((chan - lo) / span * 255.0, 0, 255).astype(np.uint8)
    out = cv2.inpaint(u8, mask.astype(np.uint8), rad, cv2.INPAINT_TELEA)
    return out.astype(np.float64) / 255.0 * span + lo


def _tune_amp(d_in, sm_in, bg_in, amp0: float, edge0: float) -> tuple[float, float]:
    """Chỉnh độ phủ và độ mềm viền theo tiêu chí "gỡ xong phải trùng nền".

    Khớp bình phương tối thiểu trên bản đồ độ phủ cho hình dạng đúng, nhưng độ
    phủ nó chọn thường lệch vài phần trăm — đủ để ảnh sau khi giải ngược bị tối
    đi hoặc sáng lên thấy rõ. Ở đây tối ưu thẳng thứ ta thật sự cần: chênh lệch
    giữa vùng đã gỡ và nền nội suy quanh nó.
    """
    if d_in.size < 5:
        return amp0, edge0

    def cost(v):
        amp, edge = float(v[0]), float(v[1])
        if not (0.02 <= amp <= 0.9) or not (0.005 <= edge <= 0.8):
            return 1e9
        a = np.clip(amp * np.clip((1.0 - d_in) / edge + 0.5, 0, 1), 0, 0.92)
        rec = (sm_in - 255.0 * a) / (1.0 - a)
        return float(np.mean((rec - bg_in) ** 2))

    try:
        opt = minimize(
            cost,
            [amp0, edge0],
            method="Nelder-Mead",
            options={"xatol": 1e-4, "fatol": 1e-4, "maxiter": 400},
        )
        if opt.fun < 1e8 and cost(opt.x) < cost([amp0, edge0]):
            return float(opt.x[0]), float(opt.x[1])
    except Exception:  # noqa: BLE001
        pass
    return amp0, edge0


def _refine(gray_full: np.ndarray, cx0, cy0, r0, score, others=()) -> Mark | None:
    """Khớp chính xác tâm, bán kính, số mũ, độ phủ và độ mềm viền.

    ``others`` là các sao khác đã biết, dạng [(cx, cy, r), ...]: vùng của chúng
    bị loại khỏi cả phần ước lượng nền lẫn phần khớp, để sao đang xét không bị
    chúng kéo lệch.
    """
    h, w = gray_full.shape
    pad = int(r0 * 3.2) + 8
    x0, y0 = max(0, int(cx0) - pad), max(0, int(cy0) - pad)
    x1, y1 = min(w, int(cx0) + pad), min(h, int(cy0) + pad)
    roi = gray_full[y0:y1, x0:x1]
    if roi.shape[0] < 12 or roi.shape[1] < 12:
        return None

    yy, xx = np.mgrid[0 : roi.shape[0], 0 : roi.shape[1]].astype(np.float64)
    cx, cy = cx0 - x0, cy0 - y0
    sm = cv2.GaussianBlur(roi, (0, 0), max(0.8, r0 * 0.037))

    other = np.zeros(roi.shape, bool)
    for ocx, ocy, orr in others:
        other |= _astroid(xx, yy, ocx - x0, ocy - y0, orr * 1.6, orr * 1.6, ASTROID_P) <= 1.0

    guard = (_astroid(xx, yy, cx, cy, r0 * 1.45, r0 * 1.45, ASTROID_P) <= 1.0) | other
    bg = _inpaint_like(sm, guard, max(5, int(r0 * 0.35)))
    target = np.clip((sm - bg) / np.clip(255.0 - bg, 1.0, None), 0, 1)

    fit = (_astroid(xx, yy, cx, cy, r0 * 1.7, r0 * 1.7, ASTROID_P) <= 1.0) & ~other
    # Với ảnh lớn, lấy mẫu thưa: 7 tham số không cần hàng trăm nghìn điểm, và
    # nhờ vậy thời gian khớp gần như không đổi theo độ phân giải.
    step = max(1, int(round(r0 / 24.0)))
    thin = None
    if step > 1:
        thin = np.zeros_like(fit)
        thin[::step, ::step] = True
        fit = fit & thin
    if fit.sum() < 20:
        return None
    X, Y, T = xx[fit], yy[fit], target[fit]

    def model(prm, X, Y):
        pcx, pcy, prx, pry, pw, amp, edge = prm
        d = _astroid(X, Y, pcx, pcy, prx, pry, pw)
        return amp * np.clip((1.0 - d) / max(edge, 1e-3) + 0.5, 0, 1)

    p0 = [cx, cy, r0, r0, ASTROID_P, max(target.max(), 0.15), 0.12]
    lo = [cx - r0 * 0.35, cy - r0 * 0.35, r0 * 0.55, r0 * 0.55, 0.30, 0.04, 0.01]
    hi = [cx + r0 * 0.35, cy + r0 * 0.35, r0 * 1.75, r0 * 1.75, 1.60, 0.85, 0.60]
    p0 = [min(max(v, lo[i]), hi[i]) for i, v in enumerate(p0)]
    try:
        res = least_squares(
            lambda prm: model(prm, X, Y) - T,
            p0,
            loss="soft_l1",
            f_scale=0.02,
            bounds=(lo, hi),
            max_nfev=400,
        )
    except Exception:
        return None
    fx, fy, frx, fry, fp, famp, fedge = res.x

    # Tinh chỉnh biên độ + độ mềm viền sao cho sau khi giải ngược, vùng dấu
    # trùng mức sáng với nền xung quanh.
    d_full = _astroid(xx, yy, fx, fy, frx, fry, fp)
    inside = (d_full <= 1.35) & ~other
    if thin is not None:
        inside = inside & thin
    # Hiệu chỉnh trên ảnh gốc chưa làm mượt: bản đã mượt có biên bị nhoè sẵn,
    # nên nếu khớp trên đó thì viền luôn ra mềm hơn thực tế, và khi gỡ sẽ còn
    # sót một vành sáng ngay trong biên kèm một vành tối ngay ngoài biên.
    bg2 = _inpaint_like(roi, (d_full <= 1.6) | other, max(5, int(r0 * 0.35)))
    famp, fedge = _tune_amp(d_full[inside], roi[inside], bg2[inside], famp, fedge)

    # Độ khớp của mô hình astroid với dữ liệu: dấu thật khớp rất cao (>0.9),
    # còn vệt sáng tự nhiên hay nhiễu thì không — đây là cổng chặn cuối cùng.
    final = np.clip(famp * np.clip((1.0 - d_full) / fedge + 0.5, 0, 1), 0, 0.92)
    ss_res = float(np.sum((final[fit] - target[fit]) ** 2))
    ss_tot = float(np.sum((target[fit] - target[fit].mean()) ** 2))
    r2 = 1.0 - ss_res / max(ss_tot, 1e-9)

    return Mark(
        cx=fx + x0,
        cy=fy + y0,
        rx=float(frx),
        ry=float(fry),
        p=float(fp),
        alpha=float(np.clip(famp, 0, 0.9)),
        edge=float(np.clip(fedge, 0.005, 0.8)),
        score=float(score),
        fit_r2=float(r2),
    )


def color_bias(rgb: np.ndarray, mark: Mark) -> float | None:
    """Đo mức lệch màu của lớp phủ. Trả về None nếu vùng quá nhỏ để đo.

    Dấu sparkle là lớp phủ **trắng**, nên nó nâng cả ba kênh màu lên theo cùng
    một tỉ lệ so với nền: độ phủ tính riêng cho R, G, B phải xấp xỉ nhau. Vật
    thể sáng màu trong ảnh — ngón tay, mặt gỗ, da, ánh đèn ấm — thì không: kênh
    đỏ nhô lên nhiều hơn kênh lam. Trên ảnh thật đây là phép thử tách bạch nhất
    giữa dấu và thứ chỉ tình cờ giống hình sao: dấu cho dưới 0.05, còn vùng có
    màu cho 0.15 trở lên.
    """
    h, w = rgb.shape[:2]
    r = mark.r
    pad = int(r * 3.0) + 8
    x0, y0 = max(0, int(mark.cx) - pad), max(0, int(mark.cy) - pad)
    x1, y1 = min(w, int(mark.cx) + pad), min(h, int(mark.cy) + pad)
    roi = rgb[y0:y1, x0:x1].astype(np.float64)
    if roi.shape[0] < 8 or roi.shape[1] < 8:
        return None

    yy, xx = np.mgrid[0 : roi.shape[0], 0 : roi.shape[1]].astype(np.float64)
    d = _astroid(xx, yy, mark.cx - x0, mark.cy - y0, mark.rx, mark.ry, mark.p)
    core = d <= 0.65
    if core.sum() < 10:
        return None

    a = []
    for c in range(3):
        ch = cv2.GaussianBlur(roi[..., c], (0, 0), max(0.7, r * 0.03))
        bg = _inpaint_like(ch, d <= 1.5, max(5, int(r * 0.35)))
        a.append(float(np.mean((ch[core] - bg[core]) / np.clip(255.0 - bg[core], 1.0, None))))
    a = np.array(a)
    mean = a.mean()
    if mean <= 1e-6:
        return None
    return float((a.max() - a.min()) / mean)


def _refine_pair(gray_full: np.ndarray, big: Mark, sub: Mark) -> tuple[Mark, Mark]:
    """Khớp đồng thời hai sao trên cùng một vùng ảnh.

    Khớp riêng từng sao luôn lệch, vì phần lớp phủ của sao kia bị coi là nền:
    bán kính bị thu lại và viền bị kéo mềm ra, nên rìa sao gỡ không sạch. Ở đây
    độ phủ của hai sao được cộng lại đúng như lúc chúng được vẽ chồng lên ảnh.
    Nếu khớp chung không tốt hơn khớp riêng thì giữ nguyên kết quả cũ.
    """
    h, w = gray_full.shape
    pad = 1.9 * big.r + 6
    x0 = max(0, int(min(big.cx - big.r, sub.cx - sub.r) - pad))
    y0 = max(0, int(min(big.cy - big.r, sub.cy - sub.r) - pad))
    x1 = min(w, int(max(big.cx + big.r, sub.cx + sub.r) + pad))
    y1 = min(h, int(max(big.cy + big.r, sub.cy + sub.r) + pad))
    roi = gray_full[y0:y1, x0:x1]
    if roi.shape[0] < 16 or roi.shape[1] < 16:
        return big, sub

    yy, xx = np.mgrid[0 : roi.shape[0], 0 : roi.shape[1]].astype(np.float64)
    sm = cv2.GaussianBlur(roi, (0, 0), max(0.7, big.r * 0.03))
    cov = (
        _astroid(xx, yy, big.cx - x0, big.cy - y0, big.rx * 1.5, big.ry * 1.5, big.p) <= 1.0
    ) | (_astroid(xx, yy, sub.cx - x0, sub.cy - y0, sub.rx * 1.6, sub.ry * 1.6, sub.p) <= 1.0)
    bg = _inpaint_like(sm, cov, max(5, int(big.r * 0.35)))
    target = np.clip((sm - bg) / np.clip(255.0 - bg, 1.0, None), 0, 1)

    fit = (
        _astroid(xx, yy, big.cx - x0, big.cy - y0, big.r * 1.9, big.r * 1.9, ASTROID_P) <= 1.0
    ) | (_astroid(xx, yy, sub.cx - x0, sub.cy - y0, sub.r * 2.2, sub.r * 2.2, ASTROID_P) <= 1.0)
    step = max(1, int(round(big.r / 26.0)))
    if step > 1:
        thin = np.zeros_like(fit)
        thin[::step, ::step] = True
        fit &= thin
    if fit.sum() < 60:
        return big, sub
    X, Y, T = xx[fit], yy[fit], target[fit]

    def profile(X, Y, cx, cy, rx, ry, p, amp, edge):
        d = _astroid(X, Y, cx, cy, rx, ry, p)
        return amp * np.clip((1.0 - d) / max(edge, 1e-3) + 0.5, 0, 1)

    def model(prm, X, Y):
        a = profile(X, Y, prm[0], prm[1], prm[2], prm[3], prm[4], prm[5], prm[6])
        b = profile(X, Y, prm[7], prm[8], prm[9], prm[10], prm[4], prm[11], prm[12])
        return np.clip(a + b, 0, 0.95)

    p0 = [
        big.cx - x0, big.cy - y0, big.rx, big.ry, big.p, big.alpha, big.edge,
        sub.cx - x0, sub.cy - y0, sub.rx, sub.ry, sub.alpha, sub.edge,
    ]
    span_b, span_s = big.r * 0.30, sub.r * 0.45
    lo = [
        p0[0] - span_b, p0[1] - span_b, big.rx * 0.7, big.ry * 0.7, 0.45, 0.04, 0.01,
        p0[7] - span_s, p0[8] - span_s, sub.rx * 0.6, sub.ry * 0.6, 0.04, 0.01,
    ]
    hi = [
        p0[0] + span_b, p0[1] + span_b, big.rx * 1.4, big.ry * 1.4, 1.15, 0.90, 0.60,
        p0[7] + span_s, p0[8] + span_s, sub.rx * 1.9, sub.ry * 1.9, 0.90, 0.60,
    ]
    p0 = [min(max(v, lo[i]), hi[i]) for i, v in enumerate(p0)]
    try:
        res = least_squares(
            lambda prm: model(prm, X, Y) - T,
            p0,
            loss="soft_l1",
            f_scale=0.02,
            bounds=(lo, hi),
            max_nfev=600,
        )
    except Exception:
        return big, sub

    ss_tot = float(np.sum((T - T.mean()) ** 2))
    r2_new = 1.0 - float(np.sum((model(res.x, X, Y) - T) ** 2)) / max(ss_tot, 1e-9)
    r2_old = 1.0 - float(np.sum((model(p0, X, Y) - T) ** 2)) / max(ss_tot, 1e-9)
    if r2_new <= r2_old:
        return big, sub

    v = res.x
    # Khớp chung cho hình dạng đúng, nhưng độ phủ vẫn phải chỉnh lại theo tiêu
    # chí "gỡ xong trùng nền" cho từng sao, với sao kia đã loại khỏi vùng xét.
    d_a = _astroid(xx, yy, v[0], v[1], v[2], v[3], v[4])
    d_b = _astroid(xx, yy, v[7], v[8], v[9], v[10], v[4])
    bg2 = _inpaint_like(sm, (d_a <= 1.6) | (d_b <= 1.6), max(5, int(big.r * 0.35)))
    in_a = (d_a <= 1.35) & (d_b > 1.6)
    in_b = (d_b <= 1.35) & (d_a > 1.6)
    amp_a, edge_a = _tune_amp(d_a[in_a], sm[in_a], bg2[in_a], float(v[5]), float(v[6]))
    amp_b, edge_b = _tune_amp(d_b[in_b], sm[in_b], bg2[in_b], float(v[11]), float(v[12]))

    new_big = dataclasses.replace(
        big, cx=v[0] + x0, cy=v[1] + y0, rx=float(v[2]), ry=float(v[3]),
        p=float(v[4]), alpha=float(np.clip(amp_a, 0, 0.9)), edge=float(np.clip(edge_a, 0.005, 0.8)),
        fit_r2=float(r2_new), sub=None,
    )
    new_sub = dataclasses.replace(
        sub, cx=v[7] + x0, cy=v[8] + y0, rx=float(v[9]), ry=float(v[10]),
        p=float(v[4]), alpha=float(np.clip(amp_b, 0, 0.9)), edge=float(np.clip(edge_b, 0.005, 0.8)),
        fit_r2=float(r2_new), sub=None,
    )
    return new_big, new_sub


def _find_companion(gray_full: np.ndarray, big: Mark) -> Mark | None:
    """Tìm sao nhỏ của dấu Gemini hai sao, nằm chếch dưới-trái sao lớn ``big``.

    Cả vùng quạt dưới-trái được nội suy thành nền, rồi dò astroid nhỏ trên phần
    dôi ra so với nền đó. Sao nhỏ phải sáng cỡ sao lớn (cùng một lớp phủ), nổi
    rõ so với quanh nó, khớp mô hình, và đúng vị trí tương đối — thiếu một điều
    là coi như không có, quay về dấu một sao.
    """
    h, w = gray_full.shape
    r = big.r
    pad = int(r * 3.8) + 8
    x0, y0 = max(0, int(big.cx) - pad), max(0, int(big.cy) - pad)
    x1, y1 = min(w, int(big.cx) + pad), min(h, int(big.cy) + pad)
    roi = gray_full[y0:y1, x0:x1]
    if roi.shape[0] < r * 2 or roi.shape[1] < r * 2:
        return None

    yy, xx = np.mgrid[0 : roi.shape[0], 0 : roi.shape[1]].astype(np.float64)
    cx, cy = big.cx - x0, big.cy - y0
    zone = _companion_zone(xx, yy, cx, cy, r, 1.1, 3.3)
    if zone.sum() < 40:
        return None

    sm = cv2.GaussianBlur(roi, (0, 0), max(0.7, r * 0.02))
    d_big = _astroid(xx, yy, cx, cy, big.rx, big.ry, big.p)
    bg = _inpaint_like(sm, (d_big <= 1.5) | zone, max(5, int(r * 0.35)))
    target = np.clip((sm - bg) / np.clip(255.0 - bg, 1.0, None), 0, 1).astype(np.float32)

    cands = []
    for r2 in np.geomspace(0.28 * r, 0.70 * r, 6):
        if r2 < 3.5:
            continue
        tpl = _template(r2)
        if tpl.shape[0] >= target.shape[0] or tpl.shape[1] >= target.shape[1]:
            continue
        resp = cv2.matchTemplate(target, tpl, cv2.TM_CCOEFF_NORMED)
        c = tpl.shape[0] // 2
        zc = zone[c : c + resp.shape[0], c : c + resp.shape[1]]
        resp = np.where(zc, resp, -1.0)
        _, mx, _, loc = cv2.minMaxLoc(resp)
        if mx >= 0.30:
            cands.append((float(mx), loc[0] + c, loc[1] + c, float(r2)))
    if not cands:
        return None

    # Điểm tương quan luôn thiên vị mẫu to nhất (mẫu lớn trùm cả sao lẫn nền
    # quanh nó), nên không chọn theo điểm thô. Khớp mô hình cho vài ứng viên
    # hàng đầu rồi lấy cái khớp tốt nhất — đó mới là thước đo đúng bán kính.
    cands.sort(key=lambda t: -t[0])
    best = None
    for score2, px, py, r2 in cands[:4]:
        d2 = _astroid(xx, yy, px, py, r2, r2, ASTROID_P)
        inside = d2 <= 0.7
        ring = (d2 >= 1.3) & (d2 <= 2.3) & (d_big > 1.4)
        if inside.sum() < 6 or ring.sum() < 20:
            continue
        a2 = float(target[inside].mean())
        noise = float(target[ring].std()) + 1e-4
        sep2 = (a2 - float(target[ring].mean())) / noise
        if a2 < max(0.035, 0.4 * big.alpha) or sep2 < 3.0:
            continue

        sub = _refine(gray_full, px + x0, py + y0, r2, sep2, others=((big.cx, big.cy, r),))
        if sub is None:
            continue
        if not (0.03 <= sub.alpha <= 0.85) or sub.fit_r2 < 0.62:
            continue
        # Hai sao là cùng một lớp phủ nên độ phủ phải xấp xỉ nhau; một đốm sáng
        # tình cờ thì không. Hình cũng phải còn ra astroid, không được méo.
        if not (0.55 * big.alpha <= sub.alpha <= 1.9 * big.alpha):
            continue
        if not (0.45 <= sub.p <= 1.15):
            continue
        if not (0.6 <= sub.rx / max(sub.ry, 1e-6) <= 1.7):
            continue
        # Sao nhỏ chỉ vài chục pixel, nên độ mờ do JPEG chiếm tỉ lệ lớn hơn hẳn
        # so với sao lớn. Quy viền về đơn vị pixel rồi mới so ngưỡng, thay vì
        # dùng thẳng ngưỡng của sao lớn — nếu không, sao nhỏ luôn bị loại oan.
        edge_px = sub.edge * sub.r / max(sub.p, 0.3)
        if edge_px > 0.62 * r:
            continue
        if not (0.22 <= sub.r / max(r, 1e-6) <= 0.80):
            continue
        ddx, ddy = sub.cx - big.cx, sub.cy - big.cy
        ang = float(np.degrees(np.arctan2(ddy, ddx)))
        dist = float(np.hypot(ddx, ddy))
        if not (COMPANION_ANGLE[0] - 5 <= ang <= COMPANION_ANGLE[1] + 5):
            continue
        if not (1.0 * r <= dist <= 3.4 * r):
            continue
        if best is None or sub.fit_r2 > best.fit_r2:
            best = sub
    return best


# ----------------------------------------------------------------------------
# Gỡ dấu
# ----------------------------------------------------------------------------


def _find_donor(rgb: np.ndarray, avoid: tuple[int, int, int, int], size: int) -> np.ndarray:
    """Tìm một mảng nền sạch gần đó để mượn vân hạt (không dùng nhiễu trắng).

    ``avoid`` = (x0, y0, x1, y1) là hộp bao quanh dấu; không lấy vân từ đó.
    Vân hạt vay từ chính bức ảnh khớp với nhiễu cảm biến và nhiễu nén của nó,
    nên vùng vá không lộ ra như khi rắc nhiễu trắng tổng hợp.
    """
    h, w = rgb.shape[:2]
    size = int(np.clip(size, 16, max(16, min(h, w) - 2)))
    if h <= size or w <= size:
        return np.zeros((size, size, 3), np.float64)

    gray = rgb.mean(2).astype(np.float32)
    hf = gray - cv2.GaussianBlur(gray, (0, 0), 1.3)
    sm = cv2.GaussianBlur(gray, (0, 0), 3.0)
    gx = cv2.Sobel(sm, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(sm, cv2.CV_32F, 0, 1, ksize=3)
    grad = cv2.magnitude(gx, gy) * 0.25

    k = (size, size)
    m1 = cv2.boxFilter(hf, -1, k, normalize=True)
    m2 = cv2.boxFilter(hf * hf, -1, k, normalize=True)
    std = np.sqrt(np.maximum(m2 - m1 * m1, 0))
    gmean = cv2.boxFilter(grad, -1, k, normalize=True)
    cost = np.abs(std - 12.0) + 2.2 * gmean  # phẳng, nhiều hạt, không có cạnh

    # Chỉ xét các tâm mà ô vuông nằm trọn trong ảnh và không đè lên chính dấu.
    ax0, ay0, ax1, ay1 = avoid
    acx, acy = 0.5 * (ax0 + ax1), 0.5 * (ay0 + ay1)
    half = size // 2
    valid = np.zeros(gray.shape, bool)
    valid[half : h - (size - half), half : w - (size - half)] = True
    yy, xx = np.mgrid[0:h, 0:w]
    margin = size * 0.6
    near = (
        (xx > ax0 - margin) & (xx < ax1 + margin) & (yy > ay0 - margin) & (yy < ay1 + margin)
    )
    reach = (np.abs(xx - acx) < size * 7) & (np.abs(yy - acy) < size * 7)
    valid &= ~near & reach
    if not valid.any():
        valid = np.zeros(gray.shape, bool)
        valid[half : h - (size - half), half : w - (size - half)] = True
        valid &= ~near
    if not valid.any():
        return np.zeros((size, size, 3), np.float64)

    cost = np.where(valid, cost, np.inf)
    cy, cx = np.unravel_index(np.argmin(cost), cost.shape)
    by, bx = int(cy) - half, int(cx) - half
    return rgb[by : by + size, bx : bx + size].astype(np.float64)


def remove(rgb: np.ndarray, mark: Mark, restore_grain: bool = True) -> np.ndarray:
    """Trả về ảnh mới (float64 RGB) đã gỡ dấu — cả sao lớn lẫn sao nhỏ nếu có."""
    img = rgb.astype(np.float64)
    h, w = img.shape[:2]
    stars = mark.stars()
    r = mark.r
    # Vùng làm việc phủ hết mọi sao, chừa lề 2.6 lần bán kính của từng sao.
    x0 = max(0, min(int(s.cx - s.r * 2.6) - 10 for s in stars))
    y0 = max(0, min(int(s.cy - s.r * 2.6) - 10 for s in stars))
    x1 = min(w, max(int(s.cx + s.r * 2.6) + 10 for s in stars))
    y1 = min(h, max(int(s.cy + s.r * 2.6) + 10 for s in stars))
    if x1 <= x0 or y1 <= y0:
        return img
    roi = img[y0:y1, x0:x1].copy()

    yy, xx = np.mgrid[0 : roi.shape[0], 0 : roi.shape[1]].astype(np.float64)
    # d: "khoảng cách astroid" tới sao gần nhất (≤1 là trong sao); a: tổng độ phủ.
    a = np.zeros(roi.shape[:2])
    d = np.full(roi.shape[:2], np.inf)
    for s in stars:
        ds = _astroid(xx, yy, s.cx - x0, s.cy - y0, s.rx, s.ry, s.p)
        a_s = np.clip(s.alpha * np.clip((1.0 - ds) / s.edge + 0.5, 0, 1), 0, 0.92)
        a += cv2.GaussianBlur(a_s, (0, 0), max(0.4, s.r * 0.019))
        d = np.minimum(d, ds)
    a = np.clip(a, 0, 0.92)

    # --- 1. giải ngược lớp phủ bán trong suốt -------------------------------
    out = np.clip((roi - 255.0 * a[..., None]) / (1.0 - a[..., None]), 0, 255)

    # --- 2. bảo vệ các đường nét dài thật (mạch vữa, khe gạch, dây...) ------
    gg = cv2.GaussianBlur(out.mean(2), (0, 0), 1.0)
    dark = (gg < np.percentile(gg, 14)).astype(np.uint8)
    dark = cv2.morphologyEx(dark, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    n, lab, stats, _ = cv2.connectedComponentsWithStats(dark, 8)
    keep = np.zeros_like(dark)
    for i in range(1, n):
        bw, bh = stats[i, cv2.CC_STAT_WIDTH], stats[i, cv2.CC_STAT_HEIGHT]
        if np.hypot(bw, bh) > r * 2.0:
            keep[lab == i] = 1
    prot = np.clip(
        cv2.GaussianBlur(
            cv2.dilate(keep, np.ones((3, 3), np.uint8)).astype(np.float64),
            (0, 0),
            max(0.8, r * 0.066),
        )
        * 2.0,
        0,
        1,
    )

    # --- 3. làm phẳng phần bóng ma còn lại, chừa các đường nét -------------
    region = cv2.GaussianBlur(
        np.clip((1.32 - d) / 0.38, 0, 1), (0, 0), max(1.0, r * 0.093)
    ) * (1.0 - prot)
    mask = (d <= 1.34).astype(np.uint8)
    # Tầng cuối (bán kính rất nhỏ) nhắm đúng vành viền còn sót ngay tại biên
    # hình sao: nó chỉ rộng một hai pixel nên các tầng thô ở trên không bắt được,
    # mà trên nền phẳng thì lại lộ ra thành đường viền hình sao mờ.
    for mul, cap in ((0.148, 7), (0.089, 6), (0.063, 5), (0.038, 4)):
        sigma = max(0.9, r * mul)
        for c in range(3):
            lf = cv2.GaussianBlur(out[..., c], (0, 0), sigma)
            ref = _inpaint_like(lf, mask, max(6, int(sigma * 3)))
            out[..., c] -= np.clip(lf - ref, -cap, cap) * region
        out = np.clip(out, 0, 255)

    # --- 4. trả lại vân hạt mà JPEG đã làm bệt bên dưới dấu ----------------
    if restore_grain:
        size = int(np.clip(r * 2.4, 24, 160))
        donor = _find_donor(img, (x0, y0, x1, y1), size)
        donor = np.pad(
            donor,
            (
                (0, max(0, roi.shape[0] - donor.shape[0])),
                (0, max(0, roi.shape[1] - donor.shape[1])),
                (0, 0),
            ),
            mode="reflect",
        )[: roi.shape[0], : roi.shape[1]]
        dhf = donor - cv2.GaussianBlur(donor, (0, 0), 1.3)
        dg = dhf.mean(2).std()
        if dg > 0.5:
            soft = cv2.GaussianBlur(
                np.clip((1.15 - d) / 0.35, 0, 1), (0, 0), max(0.8, r * 0.074)
            )
            core, ref_zone = d < 0.8, (d > 1.5) & (d < 3.2)
            if ref_zone.sum() > 40:
                rng = np.random.default_rng(7)
                for _ in range(6):
                    g = out.mean(2)
                    hf = g - cv2.GaussianBlur(g, (0, 0), 1.3)
                    have, want = hf[core].std(), hf[ref_zone].std()
                    if have >= want * 0.94:
                        break
                    k = 0.72 * np.sqrt(max(want**2 - have**2, 0)) / dg
                    sh = (int(rng.integers(-40, 40)), int(rng.integers(-40, 40)))
                    out = np.clip(
                        out + np.roll(dhf, sh, (0, 1)) * (k * soft)[..., None], 0, 255
                    )

    img[y0:y1, x0:x1] = out
    return img


def clean(rgb: np.ndarray, min_sep: float = 4.0, restore_grain: bool = True):
    """Dò rồi gỡ. Trả về (ảnh_uint8, mark_hoặc_None)."""
    mark = detect(rgb, min_sep=min_sep)
    if mark is None:
        return rgb.astype(np.uint8), None
    out = remove(rgb, mark, restore_grain=restore_grain)
    return np.clip(np.rint(out), 0, 255).astype(np.uint8), mark
