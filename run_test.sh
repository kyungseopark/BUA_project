#!/bin/bash
MODEL=${1:-qwen_bua}
START=${2:-0}
END=${3:-}

# Xvfb 설치 여부 확인 후 가상 디스플레이 설정
if command -v xvfb-run &> /dev/null; then
    xvfb-run python test.py "$MODEL" $START $END
elif command -v Xvfb &> /dev/null; then
    Xvfb :99 -screen 0 1280x720x24 &
    XVFB_PID=$!
    DISPLAY=:99 python test.py "$MODEL" $START $END
    kill $XVFB_PID
else
    DISPLAY=:0 python test.py "$MODEL" $START $END
fi
