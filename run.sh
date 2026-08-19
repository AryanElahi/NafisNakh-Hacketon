#!/usr/bin/env bash
# راه‌اندازی دستیار هوشمند مشتریان
set -e
cd "$(dirname "$0")"

if [ ! -f DATASET.xlsx ] || [ ! -f METADATA.xlsx ]; then
  echo "خطا: فایل‌های DATASET.xlsx و METADATA.xlsx را در همین پوشه قرار دهید."; exit 1
fi

python -m pip install -q -r requirements.txt

if [ ! -f cache/profiles.json ]; then
  echo "ساخت کش پروفایل‌ها (یک‌بار، حدود ۴۰ ثانیه)…"
  python store.py
fi

if [ -z "$GEMINI_API_KEY" ]; then
  echo "توجه: GEMINI_API_KEY تنظیم نشده — دستیار در حالت قطعی کار می‌کند."
fi

echo "سرور: http://127.0.0.1:${PORT:-8000}"
exec python -m uvicorn app:app --host 0.0.0.0 --port "${PORT:-8000}"
