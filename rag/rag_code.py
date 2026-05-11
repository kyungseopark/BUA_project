# """
# collect.py에 RAG를 연결하는 방법
# 아래 3군데만 수정하면 됩니다.
# """

# # ──────────────────────────────────────────────────────
# # [수정 1] collect.py 상단 import에 추가
# # ──────────────────────────────────────────────────────

# from rag.retriever import retriever  # 이 줄 추가


# # ──────────────────────────────────────────────────────
# # [수정 2] run_task() 함수 내부 수정
# # full_task 만드는 부분을 아래처럼 교체
# # ──────────────────────────────────────────────────────

# async def run_task(task_index: int, task: str, browser_session, model_name: str):
#     print(f"\n{'='*60}")
#     print(f"[모델: {model_name}] [{task_index+1}/{len(ALL_TASKS)}] {task}")
#     print('='*60)

#     # ── RAG: 직접 답변 가능한지 먼저 확인 ──────────────────
#     # score 0.80 이상이면 브라우저 탐색 없이 즉시 반환
#     direct_answer = retriever.answer_directly(task)
#     if direct_answer:
#         print(f"[RAG] ✅ 직접 답변 가능 - 브라우저 탐색 생략")
#         print(f"[RAG] 답변:\n{direct_answer}")
#         return {
#             "model": model_name,
#             "task_index": task_index,
#             "task": task,
#             "success": True,
#             "rag_direct": True,         # RAG로 직접 답변했다는 플래그
#             "final_result": direct_answer,
#             "steps": 0,
#             "total_time_seconds": 0,
#             "token_usage": None,
#         }
#     # ───────────────────────────────────────────────────────

#     await reset_cnuit_tab(browser_session)

#     # ── RAG: 관련 컨텍스트를 task 앞에 주입 ─────────────────
#     rag_context = retriever.get_context(task)
#     if rag_context:
#         print(f"[RAG] 관련 사전 지식 주입됨")

#     full_task = f"{rag_context}{BASE_CONTEXT}{task}"
#     # ── 기존 코드: full_task = f"{BASE_CONTEXT}{task}" 에서 위로 교체 ──

#     # ... 나머지 기존 코드는 그대로 ...


# # ──────────────────────────────────────────────────────
# # [수정 3] main() 함수 시작 부분에 인덱스 확인 추가
# # browser_session = BrowserSession(...) 바로 위에 추가
# # ──────────────────────────────────────────────────────

#     # RAG 인덱스 사전 로드 (첫 태스크 지연 방지)
#     try:
#         retriever._lazy_load()
#         print("[RAG] ✅ 인덱스 준비 완료")
#     except FileNotFoundError as e:
#         print(e)
#         print("[RAG] ⚠️ RAG 없이 계속 진행합니다.")