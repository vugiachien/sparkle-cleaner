import unittest
from unittest.mock import patch

from PySide6.QtWidgets import QApplication, QMessageBox

from sparkle_cleaner.app import MainWindow


class DummyWorker:
    def __init__(self):
        self.running = True
        self.wait_calls = 0
        self.deleted = False

    def isRunning(self):
        return self.running

    def stop(self):
        self.running = False

    def wait(self, timeout=None):
        self.wait_calls += 1
        self.running = False
        return True

    def deleteLater(self):
        self.deleted = True


class MainWindowCloseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_close_event_stops_worker_and_deletes_it(self):
        win = MainWindow()
        worker = DummyWorker()
        win.worker = worker

        class FakeEvent:
            def ignore(self):
                pass

            def accept(self):
                pass

        with patch("sparkle_cleaner.app.QMessageBox.question", return_value=QMessageBox.Yes):
            win.closeEvent(FakeEvent())

        self.assertEqual(worker.wait_calls, 1)
        self.assertTrue(worker.deleted)


if __name__ == "__main__":
    unittest.main()
