#!/bin/bash
# Python 캐시 정리 스크립트
# 코드 변경 후 반드시 실행!

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
echo "Cleaning Python cache in: $SCRIPT_DIR"

find "$SCRIPT_DIR" -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null
find "$SCRIPT_DIR" -name "*.pyc" -delete 2>/dev/null

echo "✓ Cache cleaned"
