#!/bin/bash
# Dựng "Sparkle Cleaner.app" (PyInstaller, chứa sẵn Python + toàn bộ thư viện)
# rồi đóng thành file .dmg. Chạy trên Mac, trong thư mục dự án đã có .venv:
#
#     bash tools/build_macos.sh
#
# Kết quả: dist/SparkleCleaner-<phiên bản>-macOS.dmg
# App chỉ được ký ad-hoc (không có tài khoản Apple Developer), nên máy khác lần
# đầu mở phải vào System Settings → Privacy & Security → Open Anyway.
set -euo pipefail
cd "$(dirname "$0")/.."

PY=".venv/bin/python"
if [ ! -x "$PY" ]; then
  echo "Chưa có .venv — mở 'Sparkle Cleaner.command' một lần để nó tự tạo, rồi chạy lại." >&2
  exit 1
fi

VERSION=$("$PY" -c "import sparkle_cleaner; print(sparkle_cleaner.__version__)")
APP="dist/Sparkle Cleaner.app"
DMG="dist/SparkleCleaner-${VERSION}-macOS.dmg"
ARCH=$(uname -m)

echo "==> Cài PyInstaller"
"$PY" -m pip install -q --upgrade pyinstaller

echo "==> Vẽ icon"
"$PY" tools/make_icons.py

echo "==> Đóng gói .app (mất 1–3 phút)"
rm -rf build "dist/Sparkle Cleaner" "$APP" dist/dmg-stage
"$PY" -m PyInstaller --noconfirm --clean --windowed \
  --name "Sparkle Cleaner" \
  --icon assets/sparkle.icns \
  --osx-bundle-identifier com.sparklecleaner.app \
  --add-data "sparkle_cleaner/sparkle.png:sparkle_cleaner" \
  --hidden-import gdown \
  launcher.py
rm -rf "dist/Sparkle Cleaner"   # bản thư mục rời, chỉ giữ .app

PLIST="$APP/Contents/Info.plist"
set_plist() {  # set_plist <khoá> <giá trị>
  /usr/libexec/PlistBuddy -c "Set :$1 $2" "$PLIST" 2>/dev/null \
    || /usr/libexec/PlistBuddy -c "Add :$1 string $2" "$PLIST"
}
set_plist CFBundleShortVersionString "$VERSION"
set_plist CFBundleVersion "$VERSION"
set_plist CFBundleDisplayName "Sparkle Cleaner"
set_plist LSApplicationCategoryType public.app-category.graphics-design
set_plist NSHumanReadableCopyright "Sparkle Cleaner ${VERSION}"

echo "==> Ký ad-hoc"
codesign --force --deep --sign - "$APP"

echo "==> Tự kiểm tra bản đóng gói"
"$APP/Contents/MacOS/Sparkle Cleaner" --selftest

echo "==> Đóng .dmg"
STAGE="dist/dmg-stage"
mkdir -p "$STAGE"
cp -R "$APP" "$STAGE/"
ln -s /Applications "$STAGE/Applications"
cp "installer/macos/Đọc trước khi cài.txt" "$STAGE/"
rm -f "$DMG"
hdiutil create -quiet -volname "Sparkle Cleaner" -srcfolder "$STAGE" -ov -format UDZO "$DMG"
rm -rf "$STAGE"

echo
echo "Xong: $DMG  ($(du -h "$DMG" | cut -f1), kiến trúc $ARCH)"
