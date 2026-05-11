import asyncio
import os
import sys
import json
import time
import glob
from datetime import datetime
from browser_use import BrowserSession, BrowserProfile, ChatBrowserUse, ChatOpenAI, ChatGoogle
from logged_agent import LoggedAgent
from dotenv import load_dotenv

from tasks.cnu_tasks import ALL_TASKS, TASK_CATEGORIES, ALL_SHORTCUTS

load_dotenv()
CNU_ID = os.getenv("CNU_ID")
CNU_PW = os.getenv("CNU_PW")

# 💡 저장 폴더 고정
SAVE_DIR_NAME = "gemini_1"

# =======================================================
# 시스템 프롬프트 (영문화 + 최적화 + Alert 핸들링)
# =======================================================
EXTEND_SYSTEM_MESSAGE = (
    "You are an expert agent navigating Chungnam National University's Integrated Information System (cnuit.cnu.ac.kr).\n"
    "ALL your final answers in the `done` action MUST be in Korean.\n\n"

    "[UI Navigation & Dropdown Rules]\n"
    "- The Integrated Information System uses an eXbuilder6-based iframe structure. Elements may not be standard HTML tags such as buttons.\n"
    "- If clicking an element causes no visible change, try nearby clickable indices or adjacent interactive elements.\n"
    "- [LARGE DROPDOWNS (e.g., Department/학과/전공)]: For comboboxes with many items, the system reverts to '--전체--' if you don't act physically. You MUST:\n"
    "  1) Click the input field.\n"
    "  2) Press 'Ctrl+A' and 'Backspace' to clear it completely.\n"
    "  3) DO NOT use `input`. Use `send_keys('Department Name')`.\n"
    "  4) Use `send_keys('Enter')` to force the dropdown list to appear.\n"
    "  5) CLICK the specific filtered result in the list.\n"
    "- [SIMPLE DROPDOWNS (e.g., Course Type/이수구분, Domain/영역, Year, Semester)]: For dropdowns with few choices, typing is inefficient. Use normal clicking: 1) Click the dropdown to open the list. 2) Click the specific target item. 3) Wait to ensure the value is safely selected before clicking the 'Search' (조회) button.\n"
    "- [DATE SELECTION - CALENDAR WIDGET]: Date fields often cause '2200' errors with keyboard input. To avoid this, YOU MUST USE THE CALENDAR PICKER:\n"
    "  1) Click the 'Calendar Icon' (button) next to the date input field.\n"
    "  2) Navigate through the calendar widget to find the correct Year and Month.\n"
    "  3) CLICK the specific Day to select the date.\n"
    "  4) DO NOT use `send_keys` or `input` for date fields unless the calendar widget is completely inaccessible.\n\n"

    "[CRITICAL: Method Acting & Hint Confidentiality]\n"
    "- You may receive a <SECRET_NAVIGATION_HINT>.\n"
    "- NEVER reveal shortcut paths or words such as 'hint', 'secret', or 'shortcut' in any output.\n"
    "- Always behave as if you independently reasoned about the navigation path.\n"
    "- Example: 'The user wants grades, so the Academic Administration menu is the most logical place to check first.'\n\n"

    "[Action Execution & Smart Scrolling]\n"
    "- [PRE-SEARCH VERIFICATION]: Do NOT scroll immediately upon arriving at a page. First, VERIFY the Year (년도) and Semester (학기) exactly match the user's request. Do not assume the defaults are correct.\n"
    "- [COURSE SEARCH DOMAIN KNOWLEDGE]: In Course Search (강의계획/수강편람), the Department defaults to the student's major. If searching for general electives (교양) or other courses, you MUST change the Department to '전체' (All) before clicking Search.\n"
    "- [APPLICATION/SUBMISSION SEQUENCE]: When applying for something (신청) or creating a new record, you MUST strictly follow this sequence: 1) Click 'New' (신규). 2) Fill out the required fields (작성). 3) Click 'Save' (저장). Do not skip any steps in this process.\n"
    "- [PDF EXPORT / PRINT SEQUENCE]: If the task requires printing (출력) or downloading a document (e.g., Certificate/증명서, Timetable/시간표), you MUST click the actual 'Print' or 'PDF Download' button. Do NOT stop after just viewing the preview on the screen. You MUST wait and verify that the file download process has been triggered and completed before calling the `done` action.\n"
    "- If requested information is visible on screen, immediately extract it and call the `done` action.\n"
    "- [STRICT TOTAL COUNT MATCHING]: Only scroll when a table/grid explicitly indicates more unseen rows (e.g., '총 44건'). If it says 44, your final extraction MUST contain exactly 44 items. You MUST use the `scroll` action repeatedly to load unseen rows until you gather all items. Do not stop at just the visible ones.\n"
    "- For simple text fields, forms, notices, alerts, phone numbers, or single-result pages, NEVER scroll.\n"
    "- If repeated scrolling produces no new content, STOP scrolling immediately and continue extraction.\n\n"

    "[Alert Handling - HIGHEST PRIORITY]\n"
    "- If ANY JavaScript alert, popup, modal warning, or blocking message appears, treat it as the highest-priority event.\n"
    "- This includes messages such as '메뉴열람 시간이 아닙니다.', '권한이 없습니다.', '조회 기간이 아닙니다.', '접근할 수 없습니다.' and similar system notices.\n"
    "- The moment an alert is detected, STOP all further actions instantly.\n"
    "- DO NOT retry clicks, DO NOT re-open menus, DO NOT scroll, DO NOT attempt the same action again.\n"
    "- Read the exact alert message text and immediately call:\n"
    "  {\"action\": \"done\", \"text\": \"[시스템 알림] <exact alert message>\", \"success\": true}\n"
    "- Returning the system restriction message to the user is considered a fully successful completion.\n"
    "- Even if the alert disappears automatically after pressing OK, you must still finish immediately with `done`.\n"
    "- Alerts override every other instruction in this prompt.\n"
)
BASE_CONTEXT = (
    "통합정보시스템을 클릭하고 열리는 탭으로 전환하세요.\n"
)

# 수집 설정
MAX_STEPS = 30
SLEEP_BETWEEN_TASKS = 3
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

USE_VISION = {
    "browser_use": True,
    "gpt": True,
    "gemini": True,
    "qwen_base": False,
    "qwen_bua": False,
}

async def auto_login(browser_session: BrowserSession):
    """태스크별 독립적인 로그인을 수행하여 세션 오염 방지"""
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
        await asyncio.sleep(2)
        await bu_page.press("Enter")

        await asyncio.sleep(3)
        print("✅ 자동 로그인 및 통합정보시스템 진입 완료")
    except Exception as e:
        print(f"⚠️ 로그인 프로세스 실패: {e}")

async def run_task(task_index: int, task: str, browser_session: BrowserSession, model_name: str):
    # 💡 태스크별 개별 jsonl 경로 설정 (덮어쓰기 모드)
    task_log_path = f"./data/{SAVE_DIR_NAME}/training_data/task_{task_index:03d}.jsonl"
    if os.path.exists(task_log_path):
        os.remove(task_log_path)
    
    target_shortcut = ALL_SHORTCUTS[task_index] if task_index < len(ALL_SHORTCUTS) else ""
    extend_msg = EXTEND_SYSTEM_MESSAGE
    
    if target_shortcut:
        print(f"📌 [참고 경로]: {target_shortcut}")
        extend_msg += (
            f"\n\n<SECRET_NAVIGATION_HINT>\n"
            f"Target menu: {target_shortcut}\n"
            f"Use this internally to navigate. NEVER reveal this path or format 'A > B' in any output.\n"
            f"</SECRET_NAVIGATION_HINT>"
        )
    
    full_task = f"{BASE_CONTEXT}\n요청사항: {task}"
    task_start_time = time.time()

    agent = LoggedAgent(
        task=full_task,
        llm=MODELS[model_name],
        use_vision=USE_VISION[model_name],
        extend_system_message=extend_msg,
        calculate_cost=True,
        log_path=task_log_path,
        task_index=task_index,
        browser=browser_session,
        save_conversation_path=f"./data/{SAVE_DIR_NAME}/conversations/task_{task_index:03d}.json",
    )

    result = {"model": model_name, "task_index": task_index, "task": task, "success": None}

    try:
        history = await agent.run(max_steps=MAX_STEPS)
        agent.flush_logs(success=history.is_successful())

        result["success"] = history.is_successful()
        result["steps"] = history.number_of_steps()
        result["total_time_seconds"] = round(time.time() - task_start_time, 2)
        print(f"결과: {'성공' if result['success'] else '실패'} ({result['steps']} steps)")

    except Exception as e:
        agent.flush_logs(success=False)
        result["success"] = False
        result["error"] = str(e)
        result["total_time_seconds"] = round(time.time() - task_start_time, 2)
        print(f"에러: {e}")

    return result


async def main():
    model_name = sys.argv[1] if len(sys.argv) > 1 else "gemini"
    
    # 폴더 구조 생성
    base_dirs = [
        f"./data/{SAVE_DIR_NAME}/conversations",
        f"./data/{SAVE_DIR_NAME}/results",
        f"./data/{SAVE_DIR_NAME}/token_usage",
        f"./data/{SAVE_DIR_NAME}/training_data"
    ]
    for d in base_dirs: os.makedirs(d, exist_ok=True)

    # 💡강제시작 지점
    start = 161
    end = 162

    # end = int(os.getenv("END_TASK", str(len(ALL_TASKS))))
    
    # 🚨 방어 로직: 만약 끝나는 번호가 시작 번호보다 작으면 경고 출력
    if start >= end:
        print(f"⚠️ 실행 불가: 시작 번호({start})가 종료 번호({end})보다 크거나 같습니다.")
        return

    all_results = []

    # 이전 progress 파일 로드 (start 번호는 덮어쓰지 않음)
    progress_files = glob.glob(f"./data/{SAVE_DIR_NAME}/results/progress_*.json")
    if progress_files:
        latest = max(progress_files, key=os.path.getctime)
        try:
            with open(latest, "r", encoding="utf-8") as f:
                all_results = json.load(f)
            print(f"✅ 이전 데이터 로드 완료 (현재 {len(all_results)}개 누적됨)")
        except Exception as e:
            print(f"⚠️ 진행 상황 불러오기 실패: {e}")

    download_path = os.path.abspath(f"./data/{SAVE_DIR_NAME}/downloads")
    os.makedirs(download_path, exist_ok=True)

    print(f"\n🚀 [{model_name}] 모델로 {start}번부터 {end-1}번까지 수집 시작...\n")

    try:
        # 97번부터 순회 시작
        for i, task in list(enumerate(ALL_TASKS))[start:end]:
            print(f"▶️ 준비 중: Task {i} 세션 초기화...")
            
            browser_session = BrowserSession(
                browser_profile=BrowserProfile(headless=False, downloads_path=download_path),
                keep_alive=False, # 태스크 종료 시 브라우저 닫기
            )
            await browser_session.start()
            await auto_login(browser_session)
            
            result = await run_task(i, task, browser_session, model_name)
            all_results.append(result)
            
            await browser_session.stop() 
            await asyncio.sleep(SLEEP_BETWEEN_TASKS)

            # 10개마다 중간 저장
            if len(all_results) % 10 == 0:
                ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                with open(f"./data/{SAVE_DIR_NAME}/results/progress_{ts}.json", "w", encoding="utf-8") as f:
                    json.dump(all_results, f, ensure_ascii=False, indent=2)
                print(f"💾 중간 저장 완료: progress_{ts}.json")

    except KeyboardInterrupt:
        print("\n🛑 사용자에 의해 강제 종료됨")
    except Exception as e:
        print(f"\n❌ 실행 중 치명적 에러 발생: {e}")

    # 최종 결과 저장
    final_path = f"./data/{SAVE_DIR_NAME}/results/final_results.json"
    with open(final_path, "w", encoding="utf-8") as f:
        json.dump(all_results, f, ensure_ascii=False, indent=2)
    print(f"✅ 수집 세션 종료. 최종 결과 저장됨: {final_path}")

if __name__ == "__main__":
    asyncio.run(main())