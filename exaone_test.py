"""
exaone_test.py — 전자결재·통합정보시스템·통합시나리오 평가 (Exaone 모델)

사용법:
  python exaone_test.py [model] [site_id] [start] [end]

  model   : exaone (기본) | gemini
  site_id : approval | cnuit | scenario | all

  python exaone_test.py exaone approval        # Exaone으로 전자결재
  python exaone_test.py exaone cnuit 0 5       # Exaone으로 통합정보시스템 0~4번
  python exaone_test.py gemini scenario        # Gemini로 통합시나리오

환경변수 (.env):
  CNU_ID, CNU_PW, TEST_CNU_ID, TEST_CNU_PW, GOOGLE_API_KEY
  VLLM_BASE_URL (기본: http://localhost:8000/v1), EXAONE_MODEL (기본: exaone)
"""

import asyncio
import json
import os
import sys
import time
from pathlib import Path

from browser_use import BrowserSession, BrowserProfile, ChatOpenAI, ChatGoogle
from logged_agent import LoggedAgent
from dotenv import load_dotenv

load_dotenv()

CNU_ID = os.getenv("CNU_ID", "")
CNU_PW = os.getenv("CNU_PW", "")
TEST_CNU_ID = os.getenv("TEST_CNU_ID", "")
TEST_CNU_PW = os.getenv("TEST_CNU_PW", "")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "")
VLLM_BASE_URL = os.getenv("VLLM_BASE_URL", "http://localhost:8003/v1")
EXAONE_MODEL = os.getenv("EXAONE_MODEL", "exaone-32b")
USE_PROXY = os.getenv("USE_PROXY", "false").lower() == "true"

MAX_STEPS = 30
SLEEP_BETWEEN_TASKS = 3
SAVE_DIR = Path(__file__).parent / "data" / "exaone"

KNOWN_MODELS = {"exaone", "gemini"}

MODELS = {
    "exaone": lambda: (
        ChatOpenAI(model=EXAONE_MODEL, base_url=VLLM_BASE_URL, api_key="dummy", temperature=0.0, max_completion_tokens=4096, timeout=100.0),
        False,
    ),
    "gemini": lambda: (
        ChatGoogle(model="gemini-2.5-flash", api_key=GOOGLE_API_KEY, temperature=0.0),
        False,
    ),
}

EXTEND_SYSTEM_MESSAGE = (
    "You are an expert web agent navigating Chungnam National University services.\n"
    "ALL final answers in the `done` action MUST be in Korean.\n"
    "If an alert or popup appears, read the message and call done immediately.\n"
)

SITE_TASKS = [
    {
        "site_id": "approval",
        "site_name": "전자결재",
        "start_url": "https://cnu.korus.ac.kr/",
        "base_context": (
            "충남대학교 전자결재 시스템에 접속되어 있습니다.\n"
            "로그인이 필요하면 아이디 {{cnu_tid}}, 비밀번호 {{cnu_tpw}}로 로그인하세요.\n"
        ),
        "tasks": [
            "비전자 일괄결재 검토",
            "결재대기함 비전자문서 일괄로 검토 부탁해",
            "결재함 확인해줘",
            "대기 중인 결재 문서 검토해줘",
            "전자문서 결재대기함에서 받은 결재 건들 본문이랑 첨부파일 확인 부탁해",
            "결재 문서 미리 확인",
            "대기 중인 결재 문서 내용 요약해줘",
            "이수증 등록해줘",
            "출장 신청 좀 해줘",
            "받은 공문 첨부 일괄 다운",
            "받은 공문 확인해줘",
            "수신 공문함 열어서 보여줘",
            "오늘 들어온 공문 리스트 보여주세요",
            "전자문서 받은문서함에 새 공문 들어온 거 있나 확인하고 싶은데, 제목이랑 발신처 날짜 다 보여줘",
            "출장 문서 찾아줘",
            "진행문서함에서 연구비 신청 문서 검색해줘",
            "이번 달에 기안된 장비 구매 관련 문서 찾아주세요",
            "완료문서함에서 '학생 지도' 키워드로 제목 검색하고, 2026년 4월 이후 기안된 건만 보여줘",
            "완료 문서 보여줘",
            "결재 완료된 문서들 목록 좀 확인하고 싶어",
        ],
    },
    {
        "site_id": "cnuit",
        "site_name": "통합정보시스템",
        "start_url": "https://portal.cnu.ac.kr",
        "base_context": (
            "포털(portal.cnu.ac.kr) 로그인 페이지입니다. "
            "아이디 {{cnu_id}}, 비밀번호 {{cnu_pw}}로 로그인 후 "
            "통합정보시스템을 클릭하고 열리는 탭으로 전환하세요.\n"
        ),
        "tasks": [
            "미래설계상담 신청해줘",
            "현재 수강중인 종합설계 수강 인원 알려줘",
            "이번 학기 취업과 창업 들으려고 하는데 안기돈 교수님 수업으로 리스트 뽑아줘",
            "이번학기 수강하는 과목들의 강의실 위치 정리해줘.",
            "나 지금 졸업하려면 어떤거 더 채워야해?",
            "전체 평점 4.0을 넘으려면 계획을 어떻게 세우면 될까?",
            "이번주 이영석 교수님과 미팅을 해야하는데 교수님 시간표 보고 되는 시간으로 알려줘.",
            "공5호관 415 강의실 사용 가능한 시간들이 언제인지 알려줘",
            "지금까지 이수한 총 학점이 몇점이고, 얼마나 남았는지 알려줘.",
            "저번주에 나 컴퓨터프로그래밍3 과목을 결석했는데 출석 인정 처리 해줘.",
            "재이수 가능한 과목 리스트만 뽑아서 재수강 계획 세워줘.",
            "현재 학점이랑 백분위 알려줘.",
            "제주대학교로 학점교류 신청해줘. 6/30~7/21이고, 수강 과목 이름은 '자바의 기초', 00분반이야. 일반 선택으로 신청하면 돼. 다 하고 신청서 출력해줘.",
            "사회봉사활동 중에서 신청 가능한 것들만 리스트 뽑아줘.",
            "등록금 고지서 출력해줘.",
            "나 이번학기에 장학금 받은거 있으면 알려줘.",
            "백마인턴십 신청 내역 확인해줘.",
            "나에게 맞는 백마인턴십 추천해줘.",
            "전공 심화 리스트만 뽑아줘.",
            "핵심 교양 리스트만 뽑아줘.",
            "졸업자가진단 내용 정리해서 알려줘.",
            "운영체제 과목의 강의계획서 확인하고 나에게 정리해서 알려줘.",
            "졸업자가진단에서 불합격인것들 정리해서 알려줘.",
        ],
    },
    {
        "site_id": "scenario",
        "site_name": "통합시나리오",
        "start_url": "https://portal.cnu.ac.kr",
        "base_context": (
            "충남대학교 포털(portal.cnu.ac.kr)에서 시작합니다. "
            "포털 로그인이 필요하면 아이디 {{cnu_id}}, 비밀번호 {{cnu_pw}}로 로그인하세요. "
            "통합정보시스템 접근 시 포털에서 통합정보시스템 메뉴를 클릭하고 열리는 탭으로 전환하세요. "
            "사이버캠퍼스(https://dcs-lcms.cnu.ac.kr/)와 "
            "도서관(https://library.cnu.ac.kr/) 접속도 필요할 수 있습니다.\n"
        ),
        "tasks": [
            "포털에서 오늘 내가 듣는 수업 확인해주고 사이버캠퍼스에서 그 수업 최근 공지사항 뭐 올라왔는지 확인해줘",
            "포털에서 신착도서 확인해주고 가장 앞에 있는 도서를 도서관에서 검색해줘",
            "통합정보시스템 수강정보에서 26년 1학기 과목 확인해주고, AI 관련된 과목이 있으면 그 과목의 강의계획서를 조회하고, 사용 교재의 참고 문헌이 있으면 그 교재 도서관에서 검색해줘",
            "통합정보시스템에서 졸업자가진단 들어가주고 전공 분야에서 C+ 이하의 학점을 맞은 과목이 있으면 그 과목의 강의계획서를 조회해줘. 그리고 사용 교재의 참고 문헌이 있으면 그 교재를 도서관에서 검색해줘",
        ],
    },
]


# ── SRT 자막 유틸 ─────────────────────────────────────────────────

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
        status = "Success" if success else "Failed"
        self._add(self._elapsed(), "task_end", f"[Done] {status} ({steps} steps)")

    def _build_srt(self) -> str:
        lines: list[str] = []
        for i, ev in enumerate(self.events):
            t_start = ev["time"]
            t_end = self.events[i + 1]["time"] if i + 1 < len(self.events) else t_start + 5.0
            lines += [str(i + 1), f"{_sec_to_srt(t_start)} --> {_sec_to_srt(t_end)}", ev["text"], ""]
        return "\n".join(lines)

    def save(self, json_path: str, srt_path: str, total_duration: float = 0.0):
        data = {
            "task_index": self.task_index,
            "task": self.task,
            "events": self.events,
            "total_duration": round(total_duration, 3),
        }
        Path(json_path).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        Path(srt_path).write_text(self._build_srt(), encoding="utf-8")


# ── 태스크 실행 ───────────────────────────────────────────────────

async def run_task(
    site_id: str,
    task_index: int,
    task: str,
    base_context: str,
    browser_session: BrowserSession,
    llm,
    use_vision: bool,
) -> dict:
    site_dir = SAVE_DIR / site_id
    for sub in ("training_data", "gifs", "subtitles", "conversations"):
        (site_dir / sub).mkdir(parents=True, exist_ok=True)

    log_path = str(site_dir / "training_data" / f"task_{task_index:03d}.jsonl")
    gif_path = str(site_dir / "gifs" / f"task_{task_index:03d}.gif")
    srt_path = str(site_dir / "subtitles" / f"task_{task_index:03d}.srt")
    events_path = str(site_dir / "subtitles" / f"task_{task_index:03d}_events.json")
    conv_path = str(site_dir / "conversations" / f"task_{task_index:03d}.json")

    if os.path.exists(log_path):
        os.remove(log_path)

    full_task = f"{base_context}\n요청사항: {task}"
    task_start = time.time()
    sub_logger = SubtitleLogger(task_index, task, task_start)

    agent = LoggedAgent(
        task=full_task,
        llm=llm,
        use_vision=use_vision,
        extend_system_message=EXTEND_SYSTEM_MESSAGE,
        calculate_cost=False,
        log_path=log_path,
        task_index=task_index,
        browser=browser_session,
        save_conversation_path=conv_path,
        generate_gif=gif_path,
        sub_logger=sub_logger,
        llm_timeout=100,
    )

    result = {
        "site_id": site_id,
        "task_index": task_index,
        "task": task,
        "success": False,
        "steps": 0,
        "final_answer": "",
        "elapsed_sec": 0.0,
    }

    try:
        history = await agent.run(max_steps=MAX_STEPS)
        agent.flush_logs(success=history.is_successful())

        elapsed = round(time.time() - task_start, 2)
        steps = history.number_of_steps()
        result.update({
            "success": history.is_successful(),
            "steps": steps,
            "final_answer": history.final_result() or "",
            "elapsed_sec": elapsed,
        })
        sub_logger.log_done(result["success"], steps)
        status = "✅" if result["success"] else "❌"
        print(f"  {status} {steps}스텝 | {elapsed}s")
        if os.path.exists(gif_path):
            print(f"  🎞️  GIF: {gif_path}")

    except Exception as e:
        agent.flush_logs(success=False)
        result["elapsed_sec"] = round(time.time() - task_start, 2)
        sub_logger.log_done(False, 0)
        print(f"  ❌ 에러: {e}")

    finally:
        duration = round(time.time() - task_start, 1)
        sub_logger.save(json_path=events_path, srt_path=srt_path, total_duration=duration)

    return result


# ── 진행상황 저장 ─────────────────────────────────────────────────

def save_progress(results: list[dict], site_id: str):
    out = SAVE_DIR / site_id / "results" / "progress_latest.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".tmp")
    tmp.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(out)


# ── 메인 ─────────────────────────────────────────────────────────

async def main():
    args = list(sys.argv[1:])

    # 인자 파싱: [model] [site_id] [start] [end]
    model_name = "exaone"
    if args and args[0] in KNOWN_MODELS:
        model_name = args.pop(0)

    filter_site = None
    task_start = 0
    task_end = None

    if args and args[0] not in ("all",):
        filter_site = args[0]
    if len(args) >= 2:
        task_start = int(args[1])
    if len(args) >= 3:
        task_end = int(args[2])

    llm, use_vision = MODELS[model_name]()
    print(f"\n🚀 모델: {model_name} | vision: {use_vision}")

    sites = SITE_TASKS
    if filter_site:
        sites = [s for s in SITE_TASKS if s["site_id"] == filter_site]
        if not sites:
            print(f"❌ 사이트 '{filter_site}'를 찾을 수 없습니다.")
            print(f"   사용 가능: {[s['site_id'] for s in SITE_TASKS]}")
            return

    total_sites = len(sites)
    print(f"사이트: {total_sites}개\n")

    download_path = str(SAVE_DIR / "downloads")
    os.makedirs(download_path, exist_ok=True)

    for site in sites:
        site_id = site["site_id"]
        site_name = site["site_name"]
        base_context = (
            site["base_context"]
            .replace("{{cnu_id}}", CNU_ID)
            .replace("{{cnu_pw}}", CNU_PW)
            .replace("{{cnu_tid}}", TEST_CNU_ID)
            .replace("{{cnu_tpw}}", TEST_CNU_PW)
        )
        tasks = site["tasks"]

        end = task_end if task_end is not None else len(tasks)
        target_tasks = tasks[task_start:end]

        if not target_tasks:
            print(f"\n[{site_name}] 태스크 없음 — 건너뜀\n")
            continue

        print(f"\n{'='*60}")
        print(f"[{site_name}] ({site_id}) — {len(target_tasks)}개 태스크")
        print(f"{'='*60}")

        progress_path = SAVE_DIR / site_id / "results" / "progress_latest.json"
        all_results: list[dict] = []
        if progress_path.exists():
            try:
                all_results = json.loads(progress_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, ValueError):
                all_results = []

        start_url = site.get("start_url", "")

        try:
            for rel_idx, task in enumerate(target_tasks):
                abs_idx = task_start + rel_idx
                log_path_check = SAVE_DIR / site_id / "training_data" / f"task_{abs_idx:03d}.jsonl"
                if log_path_check.exists():
                    print(f"\n[{site_name}] Task {abs_idx}: 이미 완료 — 건너뜀")
                    continue

                print(f"\n{'─'*60}")
                print(f"[{site_name}] Task {abs_idx}: {task}")

                browser_session = BrowserSession(
                    browser_profile=BrowserProfile(
                        headless=True,
                        viewport={"width": 1920, "height": 1080},
                        accept_downloads=False,
                        proxy={"server": "socks5://localhost:8080"} if USE_PROXY else None,
                        args=[
                            "--disable-dev-shm-usage",
                            "--no-sandbox",
                        ],
                    ),
                    keep_alive=False,
                )
                await browser_session.start()

                if start_url:
                    try:
                        await browser_session.navigate_to(start_url)
                    except Exception:
                        pass
                    await asyncio.sleep(3)

                result = await run_task(
                    site_id=site_id,
                    task_index=abs_idx,
                    task=task,
                    base_context=base_context,
                    browser_session=browser_session,
                    llm=llm,
                    use_vision=use_vision,
                )

                await browser_session.stop()
                await asyncio.sleep(SLEEP_BETWEEN_TASKS)

                all_results = [r for r in all_results if not (
                    r.get("site_id") == site_id and r.get("task_index") == abs_idx
                )]
                all_results.append(result)
                save_progress(all_results, site_id)

        except KeyboardInterrupt:
            print(f"\n🛑 [{site_name}] 강제 종료")
            break

        # 사이트별 최종 결과 저장
        final_path = SAVE_DIR / site_id / "results" / "final_results.json"
        final_path.parent.mkdir(parents=True, exist_ok=True)
        final_path.write_text(json.dumps(all_results, ensure_ascii=False, indent=2), encoding="utf-8")

        done = [r for r in all_results if task_start <= r.get("task_index", -1) < end]
        success_count = sum(1 for r in done if r.get("success"))
        print(f"\n[{site_name}] 완료: {success_count}/{len(done)} 성공")

    print(f"\n{'='*60}")
    print("전체 평가 종료")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    asyncio.run(main())
