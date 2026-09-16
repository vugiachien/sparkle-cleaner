"""Giao diện Sparkle Cleaner — gỡ dấu sparkle của Gemini hàng loạt."""

from __future__ import annotations

import datetime as dt
import os
import sys
import traceback
from concurrent.futures import CancelledError, ProcessPoolExecutor, as_completed
from concurrent.futures.process import BrokenProcessPool
from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QFont, QGuiApplication, QIcon
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QFileDialog, QGroupBox,
    QHBoxLayout, QInputDialog, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QMainWindow, QMessageBox, QPlainTextEdit, QProgressBar,
    QPushButton, QRadioButton, QSpinBox, QSplitter, QVBoxLayout, QWidget,
)

from .pipeline import ensure_std_streams, process_one
from .sources import Collector, is_drive_link, is_image, parse_drive_link

COLORS = {
    "info": "#c8ccd4", "ok": "#5fd38d", "warn": "#e8b552",
    "error": "#f2726f", "step": "#6fb4ff", "muted": "#7f8794",
}


# ---------------------------------------------------------------------------
# Luồng chạy nền
# ---------------------------------------------------------------------------


class Worker(QThread):
    log = Signal(str, str)
    progress = Signal(int, int)
    done = Signal(dict)

    def __init__(self, entries, opts):
        super().__init__()
        self.entries, self.opts = entries, opts
        self._stop = False

    def stop(self):
        self._stop = True
        self.log.emit("Đã yêu cầu dừng — chờ các ảnh đang xử lý hoàn tất…", "warn")

    # ------------------------------------------------------------------
    def run(self):
        summary = {"cleaned": 0, "clean": 0, "error": 0, "total": 0}
        collector = Collector(log=lambda m, lv="info": self.log.emit(m, lv))
        try:
            self.log.emit("Đang gom danh sách ảnh…", "step")
            items = collector.collect(self.entries)
            summary["total"] = len(items)
            if not items:
                self.log.emit("Không có ảnh nào để xử lý.", "warn")
                self.done.emit(summary)
                return
            self.log.emit(f"Tổng cộng {len(items)} ảnh.", "ok")

            tasks = []
            if self.opts["beside_source"] and any(i.ephemeral for i in items):
                self.log.emit(
                    "Ảnh từ ZIP/Drive không có 'ảnh gốc' trên máy, nên sẽ được "
                    f"lưu vào {self.opts['out_dir']}.", "warn")
            for it in items:
                dst = self._destination(it)
                tasks.append({
                    "src": str(it.path), "dst": str(dst), "origin": it.origin,
                    "sensitivity": self.opts["sensitivity"],
                    "restore_grain": self.opts["restore_grain"],
                    "strip_meta": self.opts["strip_meta"],
                    "format": self.opts["format"], "quality": self.opts["quality"],
                    "copy_when_clean": self.opts["copy_when_clean"],
                })

            workers = max(1, int(self.opts["workers"]))
            self._done, self._total = 0, len(tasks)
            if workers == 1:
                self.log.emit("Bắt đầu xử lý, chạy tuần tự một ảnh một lượt.", "step")
                self._run_serial(tasks, summary)
            else:
                self.log.emit(f"Bắt đầu xử lý với {workers} tiến trình song song.", "step")
                left = self._run_pool(tasks, summary, workers)
                if left:
                    self.log.emit(
                        f"Làm nốt {len(left)} ảnh còn lại theo kiểu tuần tự "
                        "(chậm hơn nhưng chắc chắn xong).", "warn")
                    self._run_serial(left, summary)
        except Exception:  # noqa: BLE001
            self.log.emit("Lỗi không lường trước:\n" + traceback.format_exc(), "error")
        finally:
            collector.cleanup()
            self.done.emit(summary)

    # ------------------------------------------------------------------
    def _tick(self) -> None:
        self._done += 1
        self.progress.emit(self._done, self._total)

    def _run_serial(self, tasks: list[dict], summary: dict) -> None:
        """Xử lý ngay trong luồng này, không đẻ tiến trình con."""
        for t in tasks:
            if self._stop:
                break
            try:
                self._report(process_one(t), summary)
            except Exception as exc:  # noqa: BLE001
                summary["error"] += 1
                self.log.emit(f"Lỗi khi xử lý {t.get('origin', t['src'])}: {exc}", "error")
            self._tick()

    def _run_pool(self, tasks: list[dict], summary: dict, workers: int) -> list[dict]:
        """Xử lý song song; trả về những việc CHƯA xong để gọi bên ngoài làm nốt.

        Trên Windows đây là chỗ dễ hỏng nhất: không có fork, nên mỗi tiến trình
        con là một pythonw.exe chạy lại từ đầu và nạp lại numpy/OpenCV. Phần mềm
        diệt virus chặn việc tạo tiến trình con, hay máy yếu hết RAM, đều làm
        chết cả pool. Khi đó thà chạy chậm mà xong còn hơn bỏ dở nguyên lượt,
        nên phần việc còn lại được trả ra ngoài để chạy tuần tự.
        """
        pending = dict(enumerate(tasks))
        try:
            with ProcessPoolExecutor(max_workers=workers, initializer=ensure_std_streams) as pool:
                futures = {pool.submit(process_one, t): i for i, t in enumerate(tasks)}
                for fut in as_completed(futures):
                    if self._stop:
                        for f in futures:
                            f.cancel()
                    try:
                        self._report(fut.result(), summary)
                    except CancelledError:
                        # Việc bị huỷ do người dùng bấm Dừng — không phải lỗi.
                        # Phải bắt TRƯỚC "except Exception" vì CancelledError
                        # cũng là một Exception; không bắt riêng thì mỗi ảnh bị
                        # huỷ lại bị đếm thành một lỗi, nhật ký đầy dòng đỏ vô
                        # nghĩa và bảng tổng kết báo sai số lỗi.
                        pass
                    except BrokenProcessPool:
                        raise  # cả pool chết: ra ngoài để làm nốt tuần tự
                    except Exception as exc:  # noqa: BLE001
                        summary["error"] += 1
                        self.log.emit(f"Lỗi tiến trình: {exc}", "error")
                    pending.pop(futures[fut], None)
                    self._tick()
        except Exception as exc:  # noqa: BLE001
            if self._stop:
                return []
            self.log.emit(f"Chạy đa tiến trình không thành công: {exc}", "warn")
            return list(pending.values())
        return []

    def _destination(self, item) -> Path:
        suffix = self.opts["suffix"]
        name = item.rel.name
        stem, ext = os.path.splitext(name)
        new_name = f"{stem}{suffix}{ext}"

        # Nguồn ZIP/Drive nằm trong thư mục tạm sẽ bị xoá khi xong, nên không
        # thể ghi "cạnh ảnh gốc" — những ảnh đó luôn về thư mục đích.
        if self.opts["beside_source"] and item.base is not None and not item.ephemeral:
            folder = item.path.parent
        else:
            root = Path(self.opts["out_dir"])
            folder = root / item.rel.parent if self.opts["keep_tree"] else root
        return folder / new_name

    def _report(self, res: dict, summary: dict):
        st = res.get("status")
        origin = res.get("origin", res.get("src", "?"))
        if st == "cleaned":
            summary["cleaned"] += 1
            self.log.emit(f"✓ {origin} — đã gỡ dấu · {res['message']}", "ok")
        elif st == "clean":
            summary["clean"] += 1
            self.log.emit(f"– {origin} — {res['message']}", "muted")
        else:
            summary["error"] += 1
            self.log.emit(f"✗ {origin} — {res.get('message','lỗi')}", "error")


# ---------------------------------------------------------------------------
# Danh sách nguồn có hỗ trợ kéo–thả
# ---------------------------------------------------------------------------


class DropList(QListWidget):
    changed = Signal()

    def __init__(self):
        super().__init__()
        self.setAcceptDrops(True)
        self.setAlternatingRowColors(True)
        self.setSelectionMode(QListWidget.ExtendedSelection)

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls() or e.mimeData().hasText():
            e.acceptProposedAction()

    def dragMoveEvent(self, e):
        if e.mimeData().hasUrls() or e.mimeData().hasText():
            e.acceptProposedAction()

    def dropEvent(self, e):
        md = e.mimeData()
        added = []
        if md.hasUrls():
            for url in md.urls():
                if url.isLocalFile():
                    added.append(url.toLocalFile())
                else:
                    added.append(url.toString())
        elif md.hasText():
            added += [ln for ln in md.text().splitlines() if ln.strip()]
        for a in added:
            self.add_entry(a)
        e.acceptProposedAction()

    def add_entry(self, path: str):
        path = path.strip()
        if not path:
            return
        existing = {self.item(i).text() for i in range(self.count())}
        if path in existing:
            return
        p = Path(path)
        if is_drive_link(path):
            label, icon = "Link Drive", "🔗"
        elif p.is_dir():
            label, icon = "Thư mục", "📁"
        elif p.suffix.lower() == ".zip":
            label, icon = "File ZIP", "🗜"
        elif is_image(path):
            label, icon = "Ảnh", "🖼"
        else:
            label, icon = "Không hỗ trợ", "⚠️"
        it = QListWidgetItem(f"{icon}  {path}")
        it.setData(Qt.UserRole, path)
        it.setToolTip(label)
        self.addItem(it)
        self.changed.emit()

    def entries(self) -> list[str]:
        return [self.item(i).data(Qt.UserRole) for i in range(self.count())]


# ---------------------------------------------------------------------------
# Cửa sổ chính
# ---------------------------------------------------------------------------


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Sparkle Cleaner — gỡ dấu Gemini hàng loạt")
        self.resize(1080, 780)
        self.worker: Worker | None = None
        self._build()
        self._apply_style()
        self.write_log("Sẵn sàng. Kéo ảnh, thư mục hoặc file ZIP vào ô bên trên.", "step")
        self.write_log(
            "Link Google Drive: dán link thư mục, ảnh lẻ hoặc file ZIP đã bật chia sẻ "
            "'Bất kỳ ai có đường liên kết' — ZIP sẽ được tự tải về và giải nén.", "muted",
        )

    # ------------------------------------------------------------------
    def _build(self):
        root = QWidget()
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(14, 12, 14, 12)
        outer.setSpacing(10)

        splitter = QSplitter(Qt.Vertical)
        outer.addWidget(splitter, 1)

        # ---------------- nguồn ----------------
        top = QWidget()
        tl = QVBoxLayout(top)
        tl.setContentsMargins(0, 0, 0, 0)

        src_box = QGroupBox("1 · Nguồn ảnh")
        sv = QVBoxLayout(src_box)
        self.list = DropList()
        self.list.setMinimumHeight(120)
        sv.addWidget(self.list)

        row = QHBoxLayout()
        for text, slot in (
            ("Thêm ảnh…", self.add_images),
            ("Thêm thư mục…", self.add_folder),
            ("Thêm ZIP…", self.add_zip),
            ("Thêm link Drive…", self.add_drive),
        ):
            b = QPushButton(text)
            b.clicked.connect(slot)
            row.addWidget(b)
        row.addStretch(1)
        self.btn_remove = QPushButton("Xoá mục chọn")
        self.btn_remove.clicked.connect(self.remove_selected)
        self.btn_clear = QPushButton("Xoá hết")
        self.btn_clear.clicked.connect(self.list.clear)
        row.addWidget(self.btn_remove)
        row.addWidget(self.btn_clear)
        sv.addLayout(row)
        tl.addWidget(src_box)

        # ---------------- nơi lưu ----------------
        out_box = QGroupBox("2 · Nơi lưu kết quả")
        ov = QVBoxLayout(out_box)
        r1 = QHBoxLayout()
        self.rb_folder = QRadioButton("Vào thư mục tôi chọn:")
        self.rb_folder.setChecked(True)
        self.rb_folder.toggled.connect(self._toggle_out)
        r1.addWidget(self.rb_folder)
        self.out_edit = QLineEdit(str(Path.home() / "Pictures" / "sparkle-cleaned"))
        r1.addWidget(self.out_edit, 1)
        b = QPushButton("Chọn…")
        b.clicked.connect(self.pick_out)
        r1.addWidget(b)
        ov.addLayout(r1)

        r2 = QHBoxLayout()
        self.rb_beside = QRadioButton("Đặt cạnh ảnh gốc (giữ nguyên file gốc)")
        r2.addWidget(self.rb_beside)
        r2.addStretch(1)
        self.cb_tree = QCheckBox("Giữ cấu trúc thư mục con")
        self.cb_tree.setChecked(True)
        r2.addWidget(self.cb_tree)
        r2.addSpacing(22)
        r2.addWidget(QLabel("Hậu tố tên file:"))
        self.suffix_edit = QLineEdit("_clean")
        self.suffix_edit.setFixedWidth(110)
        r2.addWidget(self.suffix_edit)
        ov.addLayout(r2)
        tl.addWidget(out_box)

        # ---------------- tuỳ chọn ----------------
        opt_box = QGroupBox("3 · Tuỳ chọn xử lý")
        opt_wrap = QVBoxLayout(opt_box)
        og = QHBoxLayout()
        og.addWidget(QLabel("Độ nhạy:"))
        self.sens = QComboBox()
        self.sens.addItem("Chặt — chỉ gỡ khi rất chắc", "chat")
        self.sens.addItem("Cân bằng (khuyến nghị)", "canbang")
        self.sens.addItem("Nhạy — bắt cả dấu mờ", "nhay")
        self.sens.setCurrentIndex(1)
        og.addWidget(self.sens)

        og.addWidget(QLabel("Định dạng:"))
        self.fmt = QComboBox()
        self.fmt.addItem("Giữ như ảnh gốc", "giu")
        self.fmt.addItem("JPEG", "jpeg")
        self.fmt.addItem("PNG (không mất chất lượng)", "png")
        og.addWidget(self.fmt)

        og.addWidget(QLabel("Chất lượng JPEG:"))
        self.qual = QSpinBox()
        self.qual.setRange(70, 100)
        self.qual.setValue(96)
        og.addWidget(self.qual)

        og.addWidget(QLabel("Số luồng:"))
        self.workers = QSpinBox()
        self.workers.setRange(1, 16)
        self.workers.setValue(max(1, min(6, (os.cpu_count() or 4) - 2)))
        og.addWidget(self.workers)
        og.addStretch(1)

        opt2 = QHBoxLayout()
        self.cb_meta = QCheckBox("Xoá sạch metadata (EXIF / C2PA)")
        self.cb_meta.setChecked(True)
        self.cb_grain = QCheckBox("Bù vân hạt sau khi gỡ (nên bật)")
        self.cb_grain.setChecked(True)
        self.cb_copy = QCheckBox("Ảnh không có dấu vẫn chép sang thư mục đích")
        self.cb_copy.setChecked(True)
        for c in (self.cb_meta, self.cb_grain, self.cb_copy):
            opt2.addWidget(c)
            opt2.addSpacing(16)
        opt2.addStretch(1)

        opt_wrap.addLayout(og)
        opt_wrap.addSpacing(6)
        opt_wrap.addLayout(opt2)
        tl.addWidget(opt_box)
        splitter.addWidget(top)

        # ---------------- log ----------------
        bottom = QWidget()
        bl = QVBoxLayout(bottom)
        bl.setContentsMargins(0, 0, 0, 0)
        hdr = QHBoxLayout()
        hdr.addWidget(QLabel("Nhật ký"))
        hdr.addStretch(1)
        self.btn_savelog = QPushButton("Lưu nhật ký…")
        self.btn_savelog.clicked.connect(self.save_log)
        self.btn_clearlog = QPushButton("Xoá nhật ký")
        self.btn_clearlog.clicked.connect(lambda: self.log.clear())
        hdr.addWidget(self.btn_savelog)
        hdr.addWidget(self.btn_clearlog)
        bl.addLayout(hdr)

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(20000)
        mono = {"darwin": "Menlo", "win32": "Consolas"}.get(sys.platform, "DejaVu Sans Mono")
        f = QFont(mono)
        f.setStyleHint(QFont.Monospace)
        f.setPointSize(12 if sys.platform == "darwin" else 10)
        self.log.setFont(f)
        bl.addWidget(self.log, 1)
        splitter.addWidget(bottom)
        splitter.setSizes([440, 340])

        # ---------------- thanh chạy ----------------
        bar = QHBoxLayout()
        self.progress = QProgressBar()
        self.progress.setTextVisible(True)
        self.progress.setFormat("%v / %m ảnh")
        bar.addWidget(self.progress, 1)
        self.btn_run = QPushButton("Bắt đầu")
        self.btn_run.setObjectName("run")
        self.btn_run.setFixedWidth(150)
        self.btn_run.clicked.connect(self.start)
        self.btn_stop = QPushButton("Dừng")
        self.btn_stop.setFixedWidth(90)
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self.stop)
        bar.addWidget(self.btn_run)
        bar.addWidget(self.btn_stop)
        outer.addLayout(bar)

    def _apply_style(self):
        self.setStyleSheet("""
            QMainWindow, QWidget { background: #1b1e24; color: #dfe3ea;
                font-size: 13px; }
            QGroupBox { border: 1px solid #2f3540; border-radius: 8px;
                margin-top: 12px; padding: 12px 10px 10px 10px;
                font-weight: 600; }
            QGroupBox::title { subcontrol-origin: margin; left: 10px;
                padding: 0 5px; color: #8fa3bf; }
            QPushButton { background: #2a303a; border: 1px solid #39404d;
                border-radius: 6px; padding: 6px 12px; }
            QPushButton:hover { background: #333b47; }
            QPushButton:disabled { color: #666d78; background: #23272f; }
            QPushButton#run { background: #2f6df6; border-color: #2f6df6;
                font-weight: 600; }
            QPushButton#run:hover { background: #4680ff; }
            QPushButton#run:disabled { background: #2b3550; color: #8b93a3; }
            QLineEdit, QComboBox, QSpinBox, QListWidget, QPlainTextEdit {
                background: #14171c; border: 1px solid #2f3540;
                border-radius: 6px; padding: 5px; selection-background-color: #2f6df6; }
            QListWidget::item { padding: 3px 2px; }
            QListWidget::item:alternate { background: #181b21; }
            QProgressBar { background: #14171c; border: 1px solid #2f3540;
                border-radius: 6px; height: 26px; text-align: center; }
            QProgressBar::chunk { background: #2f6df6; border-radius: 5px; }
            QCheckBox, QRadioButton { spacing: 7px; }
            QSplitter::handle { background: #2f3540; height: 3px; }
        """)

    # ------------------------------------------------------------------
    def _toggle_out(self):
        on = self.rb_folder.isChecked()
        self.out_edit.setEnabled(on)
        self.cb_tree.setEnabled(on)

    def add_images(self):
        files, _ = QFileDialog.getOpenFileNames(
            self, "Chọn ảnh", str(Path.home()),
            "Ảnh (*.jpg *.jpeg *.png *.webp *.bmp *.tif *.tiff)",
        )
        for f in files:
            self.list.add_entry(f)

    def add_folder(self):
        d = QFileDialog.getExistingDirectory(self, "Chọn thư mục ảnh", str(Path.home()))
        if d:
            self.list.add_entry(d)

    def add_zip(self):
        files, _ = QFileDialog.getOpenFileNames(
            self, "Chọn file ZIP", str(Path.home()), "ZIP (*.zip)")
        for f in files:
            self.list.add_entry(f)

    def add_drive(self):
        text, ok = QInputDialog.getText(
            self, "Link Google Drive",
            "Dán link Drive đã bật chia sẻ công khai (thư mục, ảnh lẻ hoặc file ZIP):")
        if ok and text.strip():
            if not is_drive_link(text):
                QMessageBox.warning(self, "Link không hợp lệ",
                                    "Đó không phải link Google Drive.")
                return
            if parse_drive_link(text) is None:
                QMessageBox.warning(
                    self, "Link không hợp lệ",
                    "Không nhận ra ID file/thư mục trong link này.\n"
                    "Trên Drive hãy dùng Chia sẻ → Sao chép liên kết rồi dán lại.")
                return
            self.list.add_entry(text.strip())

    def remove_selected(self):
        for it in self.list.selectedItems():
            self.list.takeItem(self.list.row(it))

    def pick_out(self):
        d = QFileDialog.getExistingDirectory(
            self, "Chọn thư mục lưu kết quả", self.out_edit.text() or str(Path.home()))
        if d:
            self.out_edit.setText(d)

    # ------------------------------------------------------------------
    def write_log(self, msg: str, level: str = "info"):
        ts = dt.datetime.now().strftime("%H:%M:%S")
        color = COLORS.get(level, COLORS["info"])
        safe = (msg.replace("&", "&amp;").replace("<", "&lt;")
                   .replace(">", "&gt;").replace("\n", "<br>"))
        self.log.appendHtml(
            f'<span style="color:#5c6470">{ts}</span>  '
            f'<span style="color:{color}">{safe}</span>'
        )
        self.log.verticalScrollBar().setValue(self.log.verticalScrollBar().maximum())

    def save_log(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Lưu nhật ký", str(Path.home() / "sparkle-cleaner-log.txt"),
            "Văn bản (*.txt)")
        if path:
            Path(path).write_text(self.log.toPlainText(), encoding="utf-8")
            self.write_log(f"Đã lưu nhật ký vào {path}", "ok")

    # ------------------------------------------------------------------
    def start(self):
        entries = self.list.entries()
        if not entries:
            QMessageBox.information(self, "Chưa có nguồn",
                                    "Hãy thêm ảnh, thư mục, file ZIP hoặc link Drive.")
            return
        beside = self.rb_beside.isChecked()
        out_dir = self.out_edit.text().strip()
        if not out_dir:
            if not beside:
                QMessageBox.warning(self, "Thiếu thư mục",
                                    "Hãy chọn thư mục lưu kết quả.")
                return
            out_dir = str(Path.home() / "Pictures" / "sparkle-cleaned")
        try:
            Path(out_dir).mkdir(parents=True, exist_ok=True)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Không tạo được thư mục", str(exc))
            return
        suffix = self.suffix_edit.text()
        if beside and not suffix:
            QMessageBox.warning(
                self, "Cần hậu tố",
                "Khi lưu cạnh ảnh gốc phải có hậu tố, nếu không sẽ trùng tên file gốc.")
            return

        opts = {
            "out_dir": out_dir, "beside_source": beside,
            "keep_tree": self.cb_tree.isChecked(), "suffix": suffix,
            "sensitivity": self.sens.currentData(),
            "format": self.fmt.currentData(), "quality": self.qual.value(),
            "strip_meta": self.cb_meta.isChecked(),
            "restore_grain": self.cb_grain.isChecked(),
            "copy_when_clean": self.cb_copy.isChecked(),
            "workers": self.workers.value(),
        }

        self.progress.setValue(0)
        self.progress.setMaximum(1)
        self.btn_run.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.write_log("──────── bắt đầu lượt xử lý ────────", "step")

        self.worker = Worker(entries, opts)
        self.worker.log.connect(self.write_log)
        self.worker.progress.connect(self._on_progress)
        self.worker.done.connect(self._on_done)
        self.worker.finished.connect(self._on_worker_finished)
        self.worker.start()

    def stop(self):
        if self.worker:
            self.worker.stop()
            self.btn_stop.setEnabled(False)

    def _on_worker_finished(self):
        if self.worker is not None:
            self.worker.deleteLater()
            self.worker = None

    def _on_progress(self, done, total):
        self.progress.setMaximum(max(total, 1))
        self.progress.setValue(done)

    def _on_done(self, summary):
        self.btn_run.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.write_log(
            f"Xong: {summary['cleaned']} ảnh đã gỡ dấu · "
            f"{summary['clean']} ảnh không có dấu · "
            f"{summary['error']} lỗi (tổng {summary['total']}).",
            "ok" if not summary["error"] else "warn",
        )
        self.write_log("────────────────────────────────────", "step")

    def closeEvent(self, e):
        if self.worker and self.worker.isRunning():
            if QMessageBox.question(self, "Đang xử lý",
                                    "Vẫn còn ảnh đang xử lý. Thoát luôn?") \
                    != QMessageBox.Yes:
                e.ignore()
                return
            self.worker.stop()
            self.worker.wait(3000)
            self.worker.deleteLater()
            self.worker = None
        e.accept()


# ---------------------------------------------------------------------------
# Điểm vào
# ---------------------------------------------------------------------------


def _log_path() -> Path:
    """Nơi ghi lỗi không bắt được khi app chạy không có console (pythonw / .app)."""
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Logs" / "Sparkle Cleaner" / "error.log"
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home())
        return base / "Sparkle Cleaner" / "error.log"
    return Path.home() / ".sparkle-cleaner" / "error.log"


def _install_crash_log() -> None:
    """Chạy bằng pythonw hoặc trong .app thì stderr là None, lỗi sẽ mất dấu.

    Ghi vào file log để còn biết đường sửa; khi có console thì để nguyên.
    """
    if sys.stderr is not None:
        return
    log = _log_path()

    def hook(exc_type, exc, tb):
        try:
            log.parent.mkdir(parents=True, exist_ok=True)
            with open(log, "a", encoding="utf-8") as f:
                f.write(f"\n--- {dt.datetime.now():%Y-%m-%d %H:%M:%S} ---\n")
                traceback.print_exception(exc_type, exc, tb, file=f)
        except Exception:  # noqa: BLE001
            pass

    sys.excepthook = hook


def selftest() -> int:
    """Kiểm tra bản cài/bản đóng gói: nạp đủ thư viện, dò một ảnh, dựng cửa sổ.

    Script build và bộ cài Windows gọi ``--selftest``; phải in OK và thoát 0.
    Chạy ẩn (offscreen) nên không hiện cửa sổ nào.
    """
    import tempfile
    from concurrent.futures import ProcessPoolExecutor

    import cv2
    import gdown  # noqa: F401  — chỉ cần nạp được
    import numpy as np
    import PySide6
    import scipy  # noqa: F401
    from PIL import Image
    from PySide6.QtCore import QTimer

    from . import engine, pipeline

    rng = np.random.default_rng(0)
    img = rng.integers(60, 200, (360, 480, 3), dtype=np.uint8)
    if engine.detect(img) is not None:
        raise RuntimeError("ảnh nhiễu ngẫu nhiên lại bị báo là có dấu")

    with tempfile.TemporaryDirectory() as td:
        src = Path(td) / "a.png"
        Image.fromarray(img).save(src)
        task = {"src": str(src), "dst": str(Path(td) / "out" / "a_clean.png")}
        # Chạy qua tiến trình con thật để chắc multiprocessing hoạt động trong
        # bản đóng gói — đây là chỗ hay hỏng nhất với PyInstaller/pythonw.
        with ProcessPoolExecutor(max_workers=1,
                                 initializer=pipeline.ensure_std_streams) as pool:
            res = pool.submit(pipeline.process_one, task).result(timeout=180)
        if res.get("status") != "clean" or not Path(res["dst"]).is_file():
            raise RuntimeError(f"xử lý thử thất bại: {res}")

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication(sys.argv[:1])
    win = MainWindow()
    win.show()
    QTimer.singleShot(300, app.quit)
    app.exec()
    win.close()

    if sys.stdout:
        print(
            f"OK — Python {sys.version.split()[0]} · PySide6 {PySide6.__version__} · "
            f"numpy {np.__version__} · OpenCV {cv2.__version__} · "
            f"{'bản đóng gói' if getattr(sys, 'frozen', False) else 'mã nguồn'}"
        )
    return 0


def main() -> int:
    # Gọi sau _install_crash_log() (đã chạy trong entry()) chứ không trước: hàm
    # đó dựa vào sys.stderr is None để biết có console hay không.
    ensure_std_streams()
    QGuiApplication.setAttribute(Qt.AA_DontUseNativeMenuBar, False)
    if sys.platform == "win32":
        # Để Windows gom cửa sổ vào đúng nhóm trên taskbar và dùng icon của app
        # thay vì icon Python.
        try:
            import ctypes

            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("SparkleCleaner.App")
        except Exception:  # noqa: BLE001
            pass
    app = QApplication(sys.argv)
    app.setApplicationName("Sparkle Cleaner")
    icon = Path(__file__).with_name("sparkle.png")
    if icon.exists():
        app.setWindowIcon(QIcon(str(icon)))
    win = MainWindow()
    win.show()
    return app.exec()


def entry(argv: list[str] | None = None) -> int:
    """Điểm vào chung cho ``python -m sparkle_cleaner`` và bản đóng gói."""
    argv = list(sys.argv[1:] if argv is None else argv)
    _install_crash_log()
    if "--selftest" in argv:
        return selftest()
    if argv and argv[0] == "--explain":
        from .pipeline import explain

        return explain(argv[1:])
    return main()


if __name__ == "__main__":
    sys.exit(entry())
