#!/bin/bash
MODEL=${1:-solar}
SITES=(approval)

for SITE in "${SITES[@]}"; do
    echo "=========================================="
    echo "[$SITE] 태스크 0번 테스트 (model: $MODEL)"
    echo "=========================================="
    DISPLAY=:1 python solar_test.py "$MODEL" "$SITE"
    echo ""
done
