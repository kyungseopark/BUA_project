# test_gemini_no_vision.py
import asyncio
import os
import json
import time
from datetime import datetime
from browser_use import BrowserSession, BrowserProfile, ChatGoogle
from logged_agent import LoggedAgent
from dotenv import load_dotenv
from tasks.cnu_tasks import ALL_TASKS, TASK_CATEGORIES

load_dotenv()

CNU_ID = os.getenv("CNU_ID")
CNU_PW = os.getenv("CNU_PW")

TEST_TASKS = [
    "일반 휴학 가능한지 확인해줘",
    "내가 지금까지 수강한 과목들 학점 높은 순으로 쭉 알려줘.",
    "졸업자가진단을 조회해줘",
    "이번 학기 수강신청 내역을 조회해줘",
    "현재 내 학점이 어떻게 돼?",
]

BASE_CONTEXT = (
    "반드시 한국어로만 답변하세요.\n\n"

    "[통합정보시스템 구조]\n"
    "- 통합정보시스템 버튼을 클릭하면 새 탭(cnuit.cnu.ac.kr)이 열려.\n"
    "- 반드시 새로 열린 탭으로 전환한 후 그 탭 안에서만 작업해.\n"
    "- 팝업 창이 뜨면 전부 닫고 진행해줘.\n"
    "- iframe 구조라 좌측에 메뉴가 있어. 메뉴는 div role=expander로 펼쳐.\n"
    "- portal.cnu.ac.kr 페이지는 절대 사용하지 마.\n"
    "- 열람 불가 또는 기간 아님 메시지가 뜨면 그대로 전달해줘.\n\n"

    "[데이터 추출 규칙]\n"
    "- 반드시 페이지가 완전히 로드된 후 추출할 것. 로딩 중이면 wait 후 추출.\n"
    "- 그리드/표 데이터가 있으면 스크롤해서 전부 추출할 것. 보이는 것만 추출하지 말 것.\n"
    "- 스크롤 후 새 데이터가 로드되면 다시 추출. 더 이상 새 데이터가 없을 때까지 반복.\n"
    "- 조회 시 현재 학기(2026년 1학기)가 선택되어 있는지 확인할 것.\n"
    "- '조회된 데이터가 없습니다'가 뜨면 학기 필터를 현재 학기로 변경 후 재조회할 것.\n\n"

    "[메뉴 경로 숏컷]\n"
    "- 신상정보: 학사행정 > 신상정보 > 신상정보\n"
    "- 휴복학신청: 학사행정 > 휴복학 및 미래설계상담 > 휴복학신청\n"
    "- 미래설계상담: 학사행정 > 휴복학 및 미래설계상담 > 미래설계상담신청\n"
    "- 전체성적조회: 학사행정 > 성적정보 > 전체성적조회\n"
    "- 졸업자가진단: 학사행정 > 성적정보 > 졸업자가진단\n"
    "- 당학기성적조회: 학사행정 > 성적정보 > 당학기성적조회(성적발표전)\n"
    "- 강의평가: 학사행정 > 성적정보 > 수강과목강의평가\n"
    "- 수강신청내역: 학사행정 > 수강정보 > 수강신청내역/시간표\n"
    "- 수강편람조회: 학사행정 > 일반교육과정 > 수강편람조회\n"
    "- 강의계획서: 학사행정 > 일반교육과정 > 강의계획서조회\n"
    "- 장학금수혜이력: 학사행정 > 장학/등록 > 장학금수혜이력\n"
    "- 등록금납부내역: 학사행정 > 장학/등록 > 등록금납부내역\n"
    "- 출결현황: 학사행정 > 전자출결 > 출결현황\n"
    "- 백마인턴십: 학사행정 > 백마인턴십 > 인턴십신청\n\n"
)

MAX_STEPS = 25
SAVE_DIR = "./data/gemini_no_vision_test"


async def auto_login(browser_session: BrowserSession):
    try:
        await browser_session.navigate_to("https://portal.cnu.ac.kr/login.jsp")
        await asyncio.sleep(5)
        bu_page = await browser_session.get_current_page()
        print("아이디/비번 자동 입력 중...")
        await bu_page.evaluate(
            f"(...args) => {{ document.querySelector(\"input[name='user_id']\").value = '{CNU_ID}'; }}"
        )
        await asyncio.sleep(0.5)
        await bu_page.evaluate(
            f"(...args) => {{ document.querySelector(\"input[name='user_password']\").value = '{CNU_PW}'; }}"
        )
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

        for page in context.pages:
            if "cnuit.cnu.ac.kr" in page.url:
                print("🔄 기존 통합정보시스템 탭 닫는 중...")
                await page.close()
                await asyncio.sleep(1)

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

        print("🔄 통합정보시스템 새로 열기 중...")
        await portal_page.bring_to_front()
        await asyncio.sleep(1)

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


async def run_task(task_index: int, task: str, browser_session: BrowserSession):
    print(f"\n{'='*60}")
    print(f"[gemini_no_vision] [{task_index+1}/{len(TEST_TASKS)}] {task}")
    print('='*60)

    await reset_cnuit_tab(browser_session)

    agent = LoggedAgent(
        task=task,
        llm=ChatGoogle(model='gemini-2.5-flash'),
        use_vision=False,
        extend_system_message=BASE_CONTEXT,  # ← system 레벨로 전달
        calculate_cost=True,
        log_path=f"{SAVE_DIR}/training_data.jsonl",
        task_index=task_index,
        browser=browser_session,
        save_conversation_path=f"{SAVE_DIR}/conversations/task_{task_index:03d}.json",
    )

    result = {
        "task_index": task_index,
        "task": task,
        "success": None,
        "final_result": None,
        "steps": None,
        "error": None,
        "total_time_seconds": None,
    }

    task_start_time = time.time()

    try:
        history = await agent.run(max_steps=MAX_STEPS)
        agent.flush_logs(success=history.is_successful())

        result["success"] = history.is_successful()
        result["final_result"] = history.final_result()
        result["steps"] = history.number_of_steps()

        task_end_time = time.time()
        result["total_time_seconds"] = round(task_end_time - task_start_time, 2)

        print(f"결과: {'✅ 성공' if result['success'] else '❌ 실패'} ({result['steps']} steps)")
        print(f"소요 시간: {result['total_time_seconds']}초")
        print(f"결과 내용: {str(result['final_result'])[:300] if result['final_result'] else 'None'}")

    except Exception as e:
        agent.flush_logs(success=False)
        result["success"] = False
        result["error"] = str(e)
        task_end_time = time.time()
        result["total_time_seconds"] = round(task_end_time - task_start_time, 2)
        print(f"❌ 에러: {e}")

    await asyncio.sleep(3)
    return result


async def main():
    print(f"\n{'='*80}")
    print(f"🧪 Gemini 비전 OFF 테스트 v2 ({len(TEST_TASKS)}개 태스크)")
    print(f"모델: gemini-2.5-flash")
    print(f"Vision: False")
    print(f"저장 경로: {SAVE_DIR}")
    print(f"{'='*80}\n")

    os.makedirs(SAVE_DIR, exist_ok=True)
    os.makedirs(f"{SAVE_DIR}/conversations", exist_ok=True)
    os.makedirs(f"{SAVE_DIR}/results", exist_ok=True)
    os.makedirs(f"{SAVE_DIR}/downloads", exist_ok=True)

    browser_session = BrowserSession(
        browser_profile=BrowserProfile(
            headless=False,
            downloads_path=os.path.abspath(f"{SAVE_DIR}/downloads"),
        ),
        keep_alive=True,
    )
    await browser_session.start()
    await auto_login(browser_session)

    all_results = []
    start_time = time.time()

    try:
        for i, task in enumerate(TEST_TASKS):
            result = await run_task(i, task, browser_session)
            all_results.append(result)

            # 중간 저장
            with open(f"{SAVE_DIR}/results/progress.json", "w", encoding="utf-8") as f:
                json.dump(all_results, f, ensure_ascii=False, indent=2)

    except KeyboardInterrupt:
        print("\n🛑 중단됨")

    await browser_session.stop()

    total_time = round(time.time() - start_time, 2)
    success_count = sum(1 for r in all_results if r["success"])

    print(f"\n{'='*80}")
    print(f"🧪 테스트 결과 요약")
    print(f"{'='*80}")
    print(f"총 태스크: {len(all_results)}개")
    print(f"성공: {success_count}개")
    print(f"실패: {len(all_results) - success_count}개")
    print(f"성공률: {success_count/len(all_results)*100:.1f}%" if all_results else "")
    print(f"총 소요 시간: {total_time}초 ({total_time/60:.1f}분)")

    print(f"\n태스크별 결과:")
    for r in all_results:
        status = "✅" if r["success"] else "❌"
        print(f"  {status} [{r['task_index']+1}] {r['task']}")
        print(f"       {r['steps']} steps, {r['total_time_seconds']}초")
        if r['final_result']:
            print(f"       결과: {str(r['final_result'])[:150]}")
        if r['error']:
            print(f"       에러: {r['error'][:100]}")

    summary = {
        "test_name": "gemini_no_vision_test_v2",
        "timestamp": datetime.now().isoformat(),
        "model": "gemini-2.5-flash",
        "use_vision": False,
        "extend_system_message": True,
        "total_tasks": len(all_results),
        "success_count": success_count,
        "success_rate": success_count/len(all_results)*100 if all_results else 0,
        "total_time_seconds": total_time,
        "task_results": all_results
    }

    result_path = f"{SAVE_DIR}/results/test_summary_v2.json"
    with open(result_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    print(f"\n💾 결과 저장: {result_path}")

    print(f"\n{'='*80}")
    print(f"📊 판단 기준")
    print(f"{'='*80}")
    if success_count >= 4:
        print(f"✅ {success_count}/5 성공 → 텍스트 모델로 전체 학습 데이터 수집 진행!")
    elif success_count == 3:
        print(f"🟡 {success_count}/5 성공 → 텍스트 모델 유지하되 추가 개선 필요")
    else:
        print(f"❌ {success_count}/5 성공 → 비전 모델 전환 고려")


if __name__ == "__main__":
    asyncio.run(main())