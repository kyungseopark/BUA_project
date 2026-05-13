import asyncio
import os
import sys
import time
import glob
import json
from datetime import datetime
from browser_use import BrowserSession, BrowserProfile, ChatBrowserUse, ChatOpenAI, ChatGoogle
from logged_agent import LoggedAgent
from dotenv import load_dotenv


def _sec_to_srt(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int((seconds % 1) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


class SubtitleLogger:
    def __init__(self, task_index: int, task: str, start_time: float):
        self.task_index = task_index
        self.task = task
        self.start_time = start_time
        self.events: list[dict] = []
        self._add(0.0, "task_start", f"[Task {task_index}] {task}")

    def _elapsed(self) -> float:
        return time.time() - self.start_time

    def _add(self, elapsed: float, event_type: str, text: str, **extra):
        self.events.append({"time": round(elapsed, 3), "type": event_type, "text": text, **extra})

    def log_step(self, step: int, text: str):
        self._add(self._elapsed(), "step", f"[Step {step}] {text}", step=step)

    def log_done(self, success: bool, steps: int):
        status = "성공" if success else "실패"
        self._add(self._elapsed(), "task_end", f"[완료] {status} ({steps}단계)")

    def _build_srt_from_events(self) -> str:
        lines: list[str] = []
        for i, ev in enumerate(self.events):
            t_start = ev["time"]
            t_end = self.events[i + 1]["time"] if i + 1 < len(self.events) else t_start + 5.0
            lines += [str(i + 1), f"{_sec_to_srt(t_start)} --> {_sec_to_srt(t_end)}", ev["text"], ""]
        return "\n".join(lines)

    def save(self, json_path: str, srt_path: str, total_duration: float = 0.0):
        data = {"task_index": self.task_index, "task": self.task,
                "events": self.events, "total_duration": round(total_duration, 3)}
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        with open(srt_path, "w", encoding="utf-8") as f:
            f.write(self._build_srt_from_events())

# ==========================================
# 1. 시스템 프롬프트 (숏컷 및 HINT 완벽 제거)
# ==========================================
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
    "- The moment an alert is detected, STOP all further actions instantly.\n"
    "- Read the exact alert message text and immediately call:\n"
    "  {\"action\": \"done\", \"text\": \"[시스템 알림] <exact alert message>\", \"success\": true}\n"
    "- Alerts override every other instruction in this prompt.\n"
)
BASE_CONTEXT = "통합정보시스템을 클릭하고 열리는 탭으로 전환하세요.\n"

# ==========================================
# 2. 로컬 API 및 평가 환경 설정
# ==========================================
MAX_STEPS = 20 # 평가 시 너무 무한루프 돌지 않게 20으로 단축
SLEEP_BETWEEN_TASKS = 3
VLLM_BASE_URL = "http://localhost:8000/v1"
SAVE_DIR_NAME = "eval_run" # 평가 로그 저장 폴더명

CNU_ID = os.getenv("CNU_ID", "본인학번")
CNU_PW = os.getenv("CNU_PW", "본인비번")

# 💡 안전한 조회 위주의 평가 태스크 리스트 (논문 데이터용 20개)
EVAL_TASKS = [
    "내 신상정보를 조회해줘",
    "신상정보에서 연락처(전화번호)를 확인해줘",
    "신상정보에서 주소 정보를 확인해줘",
    "전공 이수 내역 확인해줘",
    "전과 신청 선발 이력 조회해줘.",
    "부전공 신청 최종적으로 어떻게 되었는지 확인해줘",
    "국제학생증신청 링크 알려줘",
    "일반 휴학 가능한지 확인해줘",
    "미래설계상담 신청 현황을 조회해줘",
    "미래설계상담 내가 상담했던 교수님 성함을 알려줘.",
    "미래설계상담 교수님이 뭐라고 입력하셨는지 알려줘",
    "일반 복수 신청 내역 확인해줘",
    "교직 복수 신청 취소 내역 확인해줘",
    "교직 복수 신청 내역 확인해줘",
    "컴퓨터융합학부 교육과정 조회해줘",
    "나 23년도 입학인데, 컴퓨터융합학부 핵심 교양 리스트 뽑아줘",
    "나 24학번 컴퓨터공학과 네트워크 및 보안 대학원생인데 교육 과정 리스트로 제공해줘",
    "작년 논리회로 수업 수강 인원이 몇명이었는지 알려줘.",
    "경제의 이해 강의는 보통 제한 인원이 어떻게 돼?",
    "이번학기 종합설계1 강의 계획서 조회해줘",
    "'탁구' 강의 계획 조회해서 알려줘",
    "데이터통신 수업이 전공 기초인지 심화인지 찾아서 알려줘",
    "이번학기 취업과 창업 들으려고 하는데 안기돈 교수님 수업으로 리스트 뽑아줘",
    "작년에 '기계학습' 어느 교수님이 더 수강자가 많았는지 확인해줘.",
    "충남대학교 심화과정교육 목표 알려줘",
    "컴퓨터공학과심화 과정 학습 성과 알려줘.",
    "나 토목공학과의 심화교육과정이 궁금해",
    "심화과정졸업기준이 궁금해",
    "이번 학기 수강신청한 과목들의 강의실 위치를 한꺼번에 정리해줘",
    "이번 학기 수강신청 내역을 조회해줘",
    "나 24학년도 1학기에 무슨 수업을 수강했는지 알려줘",
    "저번 학기에 내가 들었던 수업이 뭐가 있었는지 알려줘",
    "전체 평점 4.0을 넘기기 위해 이번 학기에 최소 몇 점을 받아야 하는지 계산해줘",
    "이수구분변경 가능한지 확인해줘",
    "폐지 재이수가 뭐하는거야?",
    "지금 수강 취소 기간아야?",
    "나 이번학기 이영석 교수님과 약속을 잡아야 하는데 교수님이 시간표 보고 되는 시간으로 알려줘",
    "공5호관 415 강의실 사용 가능한 시간들이 언제인지 알려줘",
    "내가 다음주에 종합설계1을 대외 활동으로 결석을 해서 출석 인정 처리를 해야 할 것 같아. 어떻게 해야 하는지 찾아서 알려줘.",
    "수강편람조회에서 컴퓨터공학과 전공 과목 목록을 조회해줘",
    "강의계획서 조회에서 운영체제 과목의 강의계획서를 확인해줘",
    "나 지금까지 들은 교양 중에서 '계절학기'로 들은 것만 따로 리스트 뽑아줘.",
    "지금까지 이수한 총 학점이 몇점인지 조회하고, 얼마나 남았는지 알려줘.",
    "내가 들은 수업 중에 원격 강의들만 알려줘.",
    "지금 핵심역량진단이 가능해?",
    "지금 수강과목 강의 평가 가능해?",
    "나 저번학기에 수강한 중국테마기행 공개강의평가 최종 결과가 어떻게 나왔는지 궁금해",
    "지금 내 당학기 성적 조회해줘. 나온 학점이 있으면 알려줘.",
    "나 저번학기 성적 통지표 PDF로 출력해줘",
    "나 가장 성적을 잘 받은 학기의 성적 통지표 PDF로 출력해줘",
    "내가 지금까지 수강한 과목들 학점 높은 순으로 쭉 알려줘.",
    "재이수 가능한 성적(C+ 이하)인 과목 리스트만 뽑아줘",
    "나 현재 학점이랑 백분위 알려줘",
    "나 졸업 자가진단에서 불합격인것들이 뭐뭐가 있는지 알려줘",
    "나 외국어성적신청하려고 하는데 어떤 문서들이 필요해?",
    "나 외국어 성적 신청하려고 하는데 우리 인정 기준 점수가 몇점이야?",
    "나 외국어 성적 신청을 한적이 있나 확인해줘",
    "졸업자가진단을 조회해줘",
    "졸업자가진단에서 주전공 이수현황을 확인해줘",
    "졸업자가진단에서 교양 이수현황을 확인해줘",
    "교직활동신청 현황을 조회해줘",
    "교직 실습 신청 가능해?",
    "작년에 우리 학교가 아닌 한양대학교 교류교과목 신청해서 수강을 했는데 최종 승인 된거 맞는지 확인해줘",
    "작년 제주대학교 학점교류 신청서 출력해줘",
    "타대학학점교류 신청하려고 해. 제주대학교고 6/30~7/21이고, 신청할 때 뭐뭐 작성해야 하는지 알려줘.",
    "내가 이번에 아메리칸 유니벌시티를 글로벌인재양성 프로그램으로 6/30~8/20 가는데 학점은 인정이 돼. 이거 신청해줘.",
    "아메리칸 유니벌시티 타대하학점교류 신청서 출력해줘",
    "아메리칸 유니벌시티 타대학학점교류 신청 취소해줘",
    "사회봉사활동들 중에 지금 신청 가능한 봉사들만 뽑아서 알려줘",
    "해외 체험활동 신청 가능해?",
    "해외 파견 프로그래밍 신청하려면 뭐뭐 작성해야해?",
    "나 조기졸업 신청해줘",
    "조기졸업 신청한거 취소해줘",
    "조기졸업 신청서 출력해줘",
    "장학금 수혜 내역을 조회해줘",
    "등록금 납부 현황을 확인해줘",
    "장학/등록 메뉴에서 등록 고지서를 조회해줘",
    "분할 납부 신청 가능해?",
    "이번학기 등록금 납부확인서 출력해줘",
    "계절학기 고지서 출력 가능해?",
    "통합정보시스템에 등록된 참여 대회나, 자격증, 어학시험성적이 있어?",
    "내가 지금까지 받은 장학금 총액이 얼마인지 합산해줘.",
    "통합정보에 등록된 내 자격증 리스트와 취득 일자를 보여줘.",
    "이번 학기에 내가 받은 장학금이 있는지, 있다면 장학금 명칭이 뭔지 알려줘.",
    "백마 인턴십 신청하려고 하는데 통합정보시스템에 어떤 정보나 자료가 필요한지 알려줘",
    "백마인턴십 신청 내역 조회해줘",
    "지금 백마인턴십 기관 리스트 뭐뭐 있는지 확인해줘",
    "작년 1학기에 수강한 실전코딩 수업에서 결석한 날이 언제인지 확인해줘.",
    "작년 1학기에 수강한 논리회로 수업 출결 상태가 어땟는지 알려줘.",
    "24학년도 1학기에 수강한 컴퓨터프로그래밍3 수업에서 내가 병결 낸 날이 어제인지 알려줘",
    "즐겨찾기에 졸업자가진단 메뉴를 추가해줘",
    "메뉴 검색창에서 성적을 검색해줘",
    "학사행정 전체 메뉴 구조를 탐색해줘",
    "나 지금 통합정보시스템에 사진 등록되어 있어?",
    "도움말(Manual) 버튼을 눌러서 시스템 사용 설명서 팝업을 띄워줘",
    "로그인 연장해줘.",
    "즐겨찾기 목록 알려줘",
    "학사 일정 알려줘.",
]

MODELS = {
    "qwen_base": ChatOpenAI(
        model="Qwen/Qwen2.5-32B-Instruct",
        base_url=VLLM_BASE_URL,
        api_key="dummy",
        temperature=0.0
    ),
    "qwen_bua": ChatOpenAI(
        model="cnu-agent-vision",
        base_url=VLLM_BASE_URL,
        api_key="dummy",
        temperature=0.0
    ),
}

# 💡 치명적 수정: 로컬 VLM도 반드시 Vision을 True로 설정해야 화면을 읽습니다!
USE_VISION = {
    "qwen_base": True, 
    "qwen_bua": True,
}

async def auto_login(browser_session: BrowserSession):
    # 기존 코드 동일 유지 (안정성 검증됨)
    try:
        await browser_session.navigate_to("https://portal.cnu.ac.kr/login.jsp")
        await asyncio.sleep(10)
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
    task_log_path = f"./data/{SAVE_DIR_NAME}/training_data/task_{task_index:03d}.jsonl"
    if os.path.exists(task_log_path):
        os.remove(task_log_path)

    gif_path = f"./data/{SAVE_DIR_NAME}/gifs/task_{task_index:03d}.gif"
    srt_path = f"./data/{SAVE_DIR_NAME}/subtitles/task_{task_index:03d}.srt"
    events_path = f"./data/{SAVE_DIR_NAME}/subtitles/task_{task_index:03d}_events.json"

    # 💡 숏컷 주입 로직 전면 삭제. 오직 프롬프트와 화면에만 의존하여 추론 (Method Acting)
    extend_msg = EXTEND_SYSTEM_MESSAGE
    full_task = f"{BASE_CONTEXT}\n요청사항: {task}"
    task_start_time = time.time()
    sub_logger = SubtitleLogger(task_index, task, task_start_time)

    agent = LoggedAgent(
        task=full_task,
        llm=MODELS[model_name],
        use_vision=USE_VISION[model_name],
        extend_system_message=extend_msg,
        calculate_cost=False,
        log_path=task_log_path,
        task_index=task_index,
        browser=browser_session,
        save_conversation_path=f"./data/{SAVE_DIR_NAME}/conversations/task_{task_index:03d}.json",
        generate_gif=gif_path,
        sub_logger=sub_logger,
    )

    result = {"model": model_name, "task_index": task_index, "task": task, "success": None}

    try:
        history = await agent.run(max_steps=MAX_STEPS)
        agent.flush_logs(success=history.is_successful())

        result["success"] = history.is_successful()
        result["steps"] = history.number_of_steps()
        result["final_answer"] = history.final_result() # 💡 논문 기록을 위해 최종 반환값 추가
        result["total_time_seconds"] = round(time.time() - task_start_time, 2)
        sub_logger.log_done(result["success"], result["steps"])
        print(f"결과: {'성공' if result['success'] else '실패'} ({result['steps']} steps)")
        if os.path.exists(gif_path):
            print(f"🎞️  GIF 저장: {gif_path}")

    except Exception as e:
        agent.flush_logs(success=False)
        result["success"] = False
        result["error"] = str(e)
        result["total_time_seconds"] = round(time.time() - task_start_time, 2)
        sub_logger.log_done(False, 0)
        print(f"에러: {e}")

    finally:
        duration = round(time.time() - task_start_time, 1)
        sub_logger.save(json_path=events_path, srt_path=srt_path, total_duration=duration)
        print(f"자막: {srt_path} ({duration}s)")

    return result

async def main():
    # 터미널에서 `python eval_e2e_live.py qwen_bua` 형태로 실행
    model_name = sys.argv[1] if len(sys.argv) > 1 else "qwen_bua"
    
    base_dirs = [
        f"./data/{SAVE_DIR_NAME}/conversations",
        f"./data/{SAVE_DIR_NAME}/results",
        f"./data/{SAVE_DIR_NAME}/training_data",
        f"./data/{SAVE_DIR_NAME}/gifs",
        f"./data/{SAVE_DIR_NAME}/subtitles",
    ]
    for d in base_dirs: os.makedirs(d, exist_ok=True)

    start = int(sys.argv[2]) if len(sys.argv) > 2 else 0
    end = int(sys.argv[3]) if len(sys.argv) > 3 else start + 1
    all_results = []
    download_path = os.path.abspath(f"./data/{SAVE_DIR_NAME}/downloads")
    os.makedirs(download_path, exist_ok=True)

    print(f"\n🚀 [{model_name}] 모델 논문 평가 라이브 수집 시작 (총 {end}개)...\n")

    try:
        for i, task in enumerate(EVAL_TASKS):
            print(f"▶️ 평가 중: Task {i} - {task}")
            
            browser_session = BrowserSession(
                browser_profile=BrowserProfile(headless=True, downloads_path=download_path),
                keep_alive=False,
            )
            await browser_session.start()
            await auto_login(browser_session)
            
            result = await run_task(i, task, browser_session, model_name)
            all_results.append(result)
            
            await browser_session.stop() 
            await asyncio.sleep(SLEEP_BETWEEN_TASKS)

            # 매 태스크마다 안전하게 진행상황 저장 (마감 직전 데이터 유실 방지)
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            with open(f"./data/{SAVE_DIR_NAME}/results/progress_latest.json", "w", encoding="utf-8") as f:
                json.dump(all_results, f, ensure_ascii=False, indent=2)

    except KeyboardInterrupt:
        print("\n🛑 사용자에 의해 강제 종료됨")
    except Exception as e:
        print(f"\n❌ 실행 중 치명적 에러 발생: {e}")

    final_path = f"./data/{SAVE_DIR_NAME}/results/final_eval_results_{model_name}.json"
    with open(final_path, "w", encoding="utf-8") as f:
        json.dump(all_results, f, ensure_ascii=False, indent=2)
    print(f"✅ 평가 세션 종료. 최종 데이터(Task Success Rate 산출용): {final_path}")

if __name__ == "__main__":
    asyncio.run(main())