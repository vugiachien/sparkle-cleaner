#!/bin/bash
# Nhấn đúp file này để mở Sparkle Cleaner.
# Lần đầu sẽ mất 1-3 phút để tự cài thư viện, các lần sau mở ngay.
set -e
cd "$(dirname "$0")"

PY=""
for c in python3.12 python3.11 python3.10 python3; do
  if command -v "$c" >/dev/null 2>&1; then
    v=$("$c" -c 'import sys;print(sys.version_info>=(3,10))' 2>/dev/null || echo False)
    [ "$v" = "True" ] && PY="$c" && break
  fi
done

if [ -z "$PY" ]; then
  osascript -e 'display alert "Thiếu Python" message "Máy chưa có Python 3.10 trở lên.\n\nMở Terminal và chạy:  xcode-select --install\nHoặc cài Python từ python.org rồi mở lại file này." as critical' >/dev/null 2>&1
  echo "Khong tim thay Python 3.10+."; read -r -p "Nhan Enter de dong."; exit 1
fi

if [ ! -d ".venv" ]; then
  echo "Lan dau chay — dang tao moi truong (1-3 phut, can mang)..."
  "$PY" -m venv .venv
fi
source .venv/bin/activate

if [ ! -f ".venv/.deps-ok" ] || [ requirements.txt -nt ".venv/.deps-ok" ]; then
  echo "Dang cai thu vien..."
  python -m pip install --upgrade pip >/dev/null
  python -m pip install -r requirements.txt
  touch ".venv/.deps-ok"
fi

echo "Dang mo Sparkle Cleaner..."
exec python -m sparkle_cleaner
