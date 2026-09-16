"""Điểm vào cho bản đóng gói PyInstaller (Sparkle Cleaner.app).

PyInstaller cần một script thường chứ không chạy được ``python -m gói``, nên file
này chỉ chuyển tiếp sang ``sparkle_cleaner.app.entry``. Khi chạy từ mã nguồn
hãy dùng ``python -m sparkle_cleaner`` như cũ.
"""

import multiprocessing
import sys

if __name__ == "__main__":
    # Trong bản đóng gói, tiến trình con của ProcessPoolExecutor chính là file
    # thực thi này chạy lại; freeze_support() nhận ra và xử lý phần đó.
    multiprocessing.freeze_support()
    from sparkle_cleaner.app import entry

    sys.exit(entry())
