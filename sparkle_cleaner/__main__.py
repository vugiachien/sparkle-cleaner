"""Điểm vào khi chạy từ mã nguồn: python -m sparkle_cleaner [--selftest]"""

import multiprocessing
import sys

if __name__ == "__main__":
    # Bắt buộc trên macOS/Windows và trong bản đóng gói: tiến trình con dùng
    # 'spawn' sẽ nạp lại module này, nên phần khởi động giao diện phải nằm
    # trong guard.
    multiprocessing.freeze_support()
    from .app import entry

    sys.exit(entry())
