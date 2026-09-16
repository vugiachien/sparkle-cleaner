#!/bin/bash
# Đóng gói bộ cài Windows "SparkleCleaner-<phiên bản>-Setup.exe" bằng NSIS.
# Dựng được ngay trên macOS (brew install makensis) hoặc Linux; trên Windows
# thì cài NSIS 3 rồi mở SparkleCleaner.nsi bằng makensis.exe.
#
#     bash tools/build_windows_installer.sh
#
# Bộ cài này nhỏ (~1 MB): nó chép mã nguồn + "Sparkle Cleaner.bat", rồi file
# .bat tự tải Python nhúng và thư viện về máy người dùng lúc cài.
set -euo pipefail
cd "$(dirname "$0")/.."

if ! command -v makensis >/dev/null 2>&1; then
  echo "Thiếu makensis. Trên macOS: brew install makensis" >&2
  exit 1
fi

PY=".venv/bin/python"
[ -x "$PY" ] || PY="python3"
VERSION=$("$PY" -c "import sparkle_cleaner; print(sparkle_cleaner.__version__)")

echo "==> Vẽ icon"
"$PY" tools/make_icons.py

echo "==> Đổi file .bat sang CRLF (cmd.exe cần vậy để goto/label chạy đúng)"
perl -pi -e 's/\r?\n/\r\n/' "Sparkle Cleaner.bat"

echo "==> makensis"
mkdir -p dist
( cd installer/windows && makensis -V2 -INPUTCHARSET UTF8 -DVERSION="$VERSION" SparkleCleaner.nsi )

OUT="dist/SparkleCleaner-${VERSION}-Setup.exe"
echo
echo "Xong: $OUT  ($(du -h "$OUT" | cut -f1))"
echo "Lưu ý: file chưa được ký, Windows SmartScreen sẽ hỏi 'More info → Run anyway'."
