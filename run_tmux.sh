#!/bin/bash
# 사용법:
#   ./run_tmux.sh                          # qwen_bua, 전체
#   ./run_tmux.sh qwen_base 0 50           # qwen_base, 0~49
#   ./run_tmux.sh qwen_bua 50 100 :2       # 디스플레이 :2 사용

MODEL=${1:-qwen_bua}
START=${2:-0}
END=${3:-}
DISPLAY_NUM=${4:-:1}
SESSION="bua_${MODEL}_${START}"

# 이미 같은 이름 세션이 있으면 종료 여부 확인
if tmux has-session -t "$SESSION" 2>/dev/null; then
    echo "⚠️  세션 '$SESSION' 이 이미 존재합니다."
    read -rp "종료하고 새로 시작할까요? [y/N] " ans
    if [[ "$ans" =~ ^[Yy]$ ]]; then
        tmux kill-session -t "$SESSION"
    else
        echo "기존 세션에 attach: tmux attach -t $SESSION"
        exit 0
    fi
fi

mkdir -p ./data/logs

tmux new-session -d -s "$SESSION"
tmux send-keys -t "$SESSION" "cd $(pwd) && DISPLAY=$DISPLAY_NUM python test.py $MODEL $START $END 2>&1 | tee ./data/logs/${SESSION}.log" Enter

echo "✅ tmux 세션 '$SESSION' 시작됨 (DISPLAY=$DISPLAY_NUM)"
echo ""
echo "  접속:    tmux attach -t $SESSION"
echo "  분리:    Ctrl+B, D"
echo "  로그:    tail -f ./data/logs/${SESSION}.log"
echo "  종료:    tmux kill-session -t $SESSION"
