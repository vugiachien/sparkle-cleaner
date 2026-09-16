"""Chế độ --selftest phải chạy được từ mã nguồn — script build dựa vào nó."""

import os
import unittest

from sparkle_cleaner.app import entry


class SelftestTests(unittest.TestCase):
    def test_selftest_passes(self):
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
        self.assertEqual(entry(["--selftest"]), 0)


if __name__ == "__main__":
    unittest.main()
