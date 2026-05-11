import asyncio
import os
import sys
import json
import time
import glob  # 진행 상황(progress) 파일을 찾기 위해 추가됨
from datetime import datetime
from browser_use import BrowserSession, BrowserProfile, ChatBrowserUse, ChatOpenAI, ChatGoogle
from logged_agent import LoggedAgent
from dotenv import load_dotenv
from tasks.cnu_tasks import ALL_TASKS, TASK_CATEGORIES

load_dotenv()

CNU_ID = os.getenv("CNU_ID")
CNU_PW = os.getenv("CNU_PW")


BASE_CONTEXT = (
    "통합정보시스템 버튼을 클릭하면 새 탭이 열릴 거야. "
    "반드시 새로 열린 탭(cnuit.cnu.ac.kr)으로 전환한 후 "
    "그 탭 안에서만 다음을 수행해줘. "
    "팝업 창이 뜬다면 전부(여러개가 있을수도 있음) 지우고 진행해줘. "
    "통합정보시스템은 iframe 구조라 옆에 메뉴도 있다는 것을 인지해야해. "
    "학사행정 메뉴에 거의 다 있을거야. "
    "portal.cnu.ac.kr 페이지는 절대 사용하지 마: "
    "열람이 안되거나 해당 기간이 아니라고 뜨면 그대로 전달해줘. "
)

# 수집 설정
MAX_STEPS = 30
SLEEP_BETWEEN_TASKS = 3
RESET_INTERVAL = 10

# vLLM 서버 주소
VLLM_BASE_URL = "http://168.188.125.233:8000/v1"

# 모델 설정
MODELS = {
    "browser_use": ChatBrowserUse(),
    "gpt": ChatOpenAI(model="gpt-4o-mini"),
    "gemini": ChatGoogle(model='gemini-2.5-flash'),
    "qwen_base": ChatOpenAI(
        model="Qwen/Qwen2.5-32B-Instruct",
        base_url=VLLM_BASE_URL,
        api_key="dummy",
    ),
    "qwen_bua": ChatOpenAI(
        model="./output/merged_adapter_1_bua",
        base_url=VLLM_BASE_URL,
        api_key="dummy",
    ),
}

# 모델별 use_vision 설정
USE_VISION = {
    "browser_use": True,
    "gpt": True,
    "gemini": True,
    "qwen_base": False,
    "qwen_bua": False,
}


async def auto_login(browser_session: BrowserSession):
    try:
        await browser_session.navigate_to("https://portal.cnu.ac.kr/login.jsp")
        await asyncio.sleep(5)

        bu_page = await browser_session.get_current_page()

        print("아이디/비번 자동 입력 중...")
        await bu_page.evaluate(f"(...args) => {{ document.querySelector(\"input[name='user_id']\").value = '{CNU_ID}'; }}")
        await asyncio.sleep(0.5)
        await bu_page.evaluate(f"(...args) => {{ document.querySelector(\"input[name='user_password']\").value = '{CNU_PW}'; }}")
        await asyncio.sleep(0.5)
        await bu_page.press("Enter")
        print("✅ 아이디/비번 입력 완료")

    except Exception as e:
        print(f"⚠️ 자동 입력 실패: {e}")

    print("\n인증코드 입력 후 로그인 완료되면 Enter를 눌러주세요...")
    await asyncio.get_event_loop().run_in_executor(None, input)
    print("✅ 로그인 완료")


async def reset_cnuit_tab(browser_session: BrowserSession):
    """통합정보시스템 탭을 닫고 포털에서 다시 열기"""
    try:
        context = browser_session.context

        # 1. 기존 cnuit 탭 모두 닫기
        for page in context.pages:
            if "cnuit.cnu.ac.kr" in page.url:
                print("🔄 기존 통합정보시스템 탭 닫는 중...")
                await page.close()
                await asyncio.sleep(1)

        # 2. 포털 탭으로 이동
        portal_page = None
        for page in context.pages:
            if "portal.cnu.ac.kr" in page.url:
                portal_page = page
                break

        if portal_page is None:
            print("⚠️ 포털 탭 없음, 새로 열기...")
            await browser_session.navigate_to("https://portal.cnu.ac.kr")
            await asyncio.sleep(3)
            portal_page = await browser_session.get_current_page()

        # 3. 포털에서 통합정보시스템 버튼 클릭
        print("🔄 통합정보시스템 새로 열기 중...")
        await portal_page.bring_to_front()
        await asyncio.sleep(1)

        # 통합정보시스템 링크 클릭
        await portal_page.evaluate("""
            () => {
                const links = document.querySelectorAll('a');
                for (const link of links) {
                    if (link.textContent.includes('통합정보시스템') || 
                        link.href.includes('cnuit.cnu.ac.kr')) {
                        link.click();
                        return true;
                    }
                }
                return false;
            }
        """)
        await asyncio.sleep(4)

        # 4. 새로 열린 cnuit 탭 확인
        cnuit_page = None
        for page in context.pages:
            if "cnuit.cnu.ac.kr" in page.url:
                cnuit_page = page
                break

        if cnuit_page:
            await cnuit_page.bring_to_front()
            print("✅ 통합정보시스템 새 탭 열기 완료")
        else:
            print("⚠️ 통합정보시스템 탭 열기 실패")

    except Exception as e:
        print(f"⚠️ 리셋 실패: {e}")


async def reset_to_initial_state(browser_session: BrowserSession):
    try:
        context = browser_session.context

        cnuit_page = None
        for page in context.pages:
            if "cnuit.cnu.ac.kr" in page.url:
                cnuit_page = page
                break

        if cnuit_page:
            print("🔄 통합정보시스템 초기화 중...")
            await cnuit_page.goto("https://cnuit.cnu.ac.kr", wait_until="domcontentloaded")
            await asyncio.sleep(2)
            print("✅ 초기 상태로 리셋 완료")
        else:
            print("🔄 포털로 이동 중...")
            await browser_session.navigate_to("https://portal.cnu.ac.kr")
            await asyncio.sleep(2)
            print("✅ 포털로 이동 완료")

    except Exception as e:
        print(f"⚠️ 리셋 실패: {e}")


async def run_task(task_index: int, task: str, browser_session: BrowserSession, model_name: str):
    print(f"\n{'='*60}")
    print(f"[모델: {model_name}] [{task_index+1}/{len(ALL_TASKS)}] {task}")
    print('='*60)

    # 매 태스크 시작 전 통합정보시스템 탭 닫고 새로 열기
    await reset_cnuit_tab(browser_session)

    full_task = f"{BASE_CONTEXT}{task}"
    task_start_time = time.time()

    agent = LoggedAgent(
        task=full_task,
        llm=MODELS[model_name],
        use_vision=USE_VISION[model_name],
        calculate_cost=True,
        log_path=f"./data/{model_name}_temp/training_data.jsonl",
        task_index=task_index,
        browser=browser_session,
        save_conversation_path=f"./data/{model_name}_temp/conversations/task_{task_index:03d}.json",
    )

    result = {
        "model": model_name,
        "task_index": task_index,
        "task": task,
        "success": None,
        "error": None,
    }

    try:
        history = await agent.run(max_steps=MAX_STEPS)
        agent.flush_logs(success=history.is_successful())

        result["success"] = history.is_successful()
        result["final_result"] = history.final_result()
        result["steps"] = history.number_of_steps()

        try:
            if hasattr(history, 'usage') and history.usage is not None:
                result["token_usage"] = str(history.usage)
            else:
                result["token_usage"] = None
        except Exception as e:
            print(f"⚠️ 토큰 사용량 가져오기 실패: {e}")
            result["token_usage"] = None

        task_end_time = time.time()
        result["total_time_seconds"] = round(task_end_time - task_start_time, 2)

        print(f"결과: {'성공' if result['success'] else '실패'} ({result['steps']} steps)")
        print(f"소요 시간: {result['total_time_seconds']}초")

    except Exception as e:
        agent.flush_logs(success=False)
        result["success"] = False
        result["error"] = str(e)
        result["token_usage"] = None
        task_end_time = time.time()
        result["total_time_seconds"] = round(task_end_time - task_start_time, 2)
        print(f"에러: {e}")
        print(f"소요 시간: {result['total_time_seconds']}초")

    await asyncio.sleep(SLEEP_BETWEEN_TASKS)
    return result


async def main():
    if len(sys.argv) > 1:
        model_name = sys.argv[1]
    else:
        model_name = "qwen_bua"

    if model_name not in MODELS:
        print(f"❌ 에러: '{model_name}'은(는) 유효하지 않은 모델입니다.")
        print(f"사용 가능한 모델: {', '.join(MODELS.keys())}")
        print(f"\n사용법:")
        print(f"  python collect.py [모델명]")
        return

    print(f"\n{'='*80}")
    print(f"사용 모델: {model_name}")
    print(f"Vision 사용: {USE_VISION[model_name]}")
    print(f"리셋 주기: {RESET_INTERVAL}개 태스크마다")
    print(f"{'='*80}\n")

    base_dirs = [
        f"./data/{model_name}_temp",
        f"./data/{model_name}_temp/conversations",
        f"./data/{model_name}_temp/results",
        f"./data/{model_name}_temp/token_usage"
    ]
    for d in base_dirs:
        os.makedirs(d, exist_ok=True)

    start = int(os.getenv("START_TASK", "0"))
    end = int(os.getenv("END_TASK", str(len(ALL_TASKS))))

    all_results = []

    # 🔄 [1. Auto-Resume] 체크포인트 복구 로직
    progress_files = glob.glob(f"./data/{model_name}_temp/results/progress_*.json")
    if progress_files:
        latest_progress_file = max(progress_files, key=os.path.getctime)
        print(f"🔄 이전 진행 상황 발견: {latest_progress_file}")
        try:
            with open(latest_progress_file, "r", encoding="utf-8") as f:
                all_results = json.load(f)
            
            if all_results:
                last_completed_index = all_results[-1]["task_index"]
                start = last_completed_index + 1
                print(f"✅ 총 {len(all_results)}개의 이전 기록을 메모리에 불러왔습니다.")
                print(f"🚀 {start}번 태스크부터 이어서 수집을 시작합니다!\n")
        except Exception as e:
            print(f"⚠️ 진행 상황 불러오기 실패 (빈 상태로 시작합니다): {e}")
            all_results = []

    if start >= end:
        print("🎉 모든 태스크가 이미 완료되었습니다. 종료합니다.")
        return

    print(f"총 {end - start}개 태스크 수집 시작 (index {start}~{end-1})")

    download_path = os.path.abspath(f"./data/{model_name}_temp/downloads")
    os.makedirs(download_path, exist_ok=True)

    browser_session = BrowserSession(
        browser_profile=BrowserProfile(
            headless=False,
            downloads_path=download_path,
        ),
        keep_alive=True,
    )
    await browser_session.start()

    await auto_login(browser_session)

    collection_start_time = time.time()

    # 🛑 [2. Graceful Shutdown] 예외 처리를 통한 안전 종료
    try:
        for i, task in list(enumerate(ALL_TASKS))[start:end]:
            if i > start and (i - start) % RESET_INTERVAL == 0:
                print(f"\n{'='*60}")
                print(f"📊 {RESET_INTERVAL}개 태스크 완료 - 초기화 수행")
                print(f"{'='*60}")
                await reset_to_initial_state(browser_session)

            result = await run_task(i, task, browser_session, model_name)
            all_results.append(result)

            if result.get("token_usage"):
                try:
                    token_record = {
                        "model": model_name,
                        "task_index": i,
                        "task": task,
                        "timestamp": datetime.now().isoformat(),
                        "success": result["success"],
                        "steps": result.get("steps"),
                        "total_time_seconds": result.get("total_time_seconds"),
                        "token_usage": result["token_usage"]
                    }
                    with open(f"./data/{model_name}_temp/token_usage/task_{i:03d}.json", "w", encoding="utf-8") as f:
                        json.dump(token_record, f, ensure_ascii=False, indent=2)
                except Exception as e:
                    print(f"⚠️ 토큰 사용량 저장 실패: {e}")

            if len(all_results) % 10 == 0:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                with open(f"./data/{model_name}_temp/results/progress_{timestamp}.json", "w", encoding="utf-8") as f:
                    json.dump(all_results, f, ensure_ascii=False, indent=2)
                print(f"💾 진행상황 저장: 총 {len(all_results)}개 태스크 완료 (체크포인트 생성)")

    except KeyboardInterrupt:
        print("\n\n🛑 [긴급 정지] 사용자가 Ctrl+C를 눌러 실행을 중단했습니다.")
        print("💾 지금까지 수집된 데이터를 바탕으로 파이널 서머리를 안전하게 생성하고 종료합니다...\n")

    # 정상 종료이든, Ctrl+C 긴급 정지이든 무조건 아래 요약 코드가 실행됩니다.
    collection_end_time = time.time()
    total_collection_time = round(collection_end_time - collection_start_time, 2)

    await browser_session.stop()

    print(f"\n{'='*60}")
    print(f"[{model_name}] 수집 완료(또는 중단) 요약")
    print('='*60)

    success_count = sum(1 for r in all_results if r["success"])
    fail_count = sum(1 for r in all_results if not r["success"])
    total_time = sum(r.get("total_time_seconds", 0) for r in all_results)
    avg_time = total_time / len(all_results) if all_results else 0

    print(f"성공: {success_count}개")
    print(f"실패: {fail_count}개")
    print(f"성공률: {success_count/len(all_results)*100:.1f}%" if all_results else "성공률: N/A")
    # 주의: 여기서 보여주는 총 소요 시간은 "이번 실행 세션(Run)"의 구동 시간입니다.
    print(f"이번 세션 총 구동 시간: {total_collection_time}초 ({total_collection_time/60:.1f}분)")
    print(f"태스크당 평균 소요 시간: {avg_time:.2f}초")

    task_to_cat = {}
    for cat, tasks in TASK_CATEGORIES.items():
        for t in tasks:
            task_to_cat[t] = cat

    cat_stats = {}
    for r in all_results:
        cat = task_to_cat.get(r["task"], "unknown")
        if cat not in cat_stats:
            cat_stats[cat] = {"success": 0, "fail": 0, "total_time": 0, "count": 0}
        if r["success"]:
            cat_stats[cat]["success"] += 1
        else:
            cat_stats[cat]["fail"] += 1
        cat_stats[cat]["total_time"] += r.get("total_time_seconds", 0)
        cat_stats[cat]["count"] += 1

    print("\n카테고리별 통계:")
    for cat, stats in cat_stats.items():
        total = stats["success"] + stats["fail"]
        rate = stats["success"] / total * 100 if total > 0 else 0
        avg_cat_time = stats["total_time"] / stats["count"] if stats["count"] > 0 else 0
        print(f"  [{cat}] {stats['success']}/{total} ({rate:.0f}%) - 평균 {avg_cat_time:.1f}초")

    if fail_count > 0:
        print("\n실패 태스크:")
        for r in all_results:
            if not r["success"]:
                print(f"  [{r['task_index']}] {r['task']} ({r.get('total_time_seconds', 0)}초)")
                if r.get("error"):
                    print(f"       에러: {r['error'][:100]}")

    final_summary = {
        "model": model_name,
        "collection_date": datetime.now().isoformat(),
        "reset_interval": RESET_INTERVAL,
        "total_tasks_collected": len(all_results),
        "success_count": success_count,
        "fail_count": fail_count,
        "success_rate": success_count/len(all_results)*100 if all_results else 0,
        "session_run_time_seconds": total_collection_time,
        "average_task_time_seconds": avg_time,
        "category_stats": cat_stats,
        "task_results": all_results
    }

    # 최종 결과 저장
    with open(f"./data/{model_name}_temp/results/final_results.json", "w", encoding="utf-8") as f:
        json.dump(final_summary, f, ensure_ascii=False, indent=2)

    print(f"\n✅ 결과 저장 완료:")
    print(f"  - 요약 리포트: ./data/{model_name}_temp/results/final_results.json")
    print(f"  - 학습 데이터: ./data/{model_name}_temp/training_data.jsonl")
    print(f"  - 대화 기록: ./data/{model_name}_temp/conversations/")


if __name__ == "__main__":
    asyncio.run(main())