#!/bin/bash
MODEL=${1:-qwen_bua}
START=${2:-0}
END=${3:-}

# TurboVNC :1 디스플레이 사용 (서버에 이미 실행 중)
DISPLAY=:1 python test.py "$MODEL" $START $END
