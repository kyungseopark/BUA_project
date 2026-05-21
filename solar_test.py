"""
solar_test.py — 다중 사이트 평가

사용법:
  python solar_test.py [model] [site_id] [start] [end]

  model   : gemini (기본) | solar
  site_id : cnuit | cyber | approval | library | dept | cnuwith | all

  python solar_test.py gemini cnuit        # Gemini로 통합정보시스템
  python solar_test.py solar cnuit 0 5     # Solar 모델로 0~4번 태스크
  python solar_test.py gemini all 0 3      # Gemini로 전체 사이트 0~2번

환경변수 (.env):
  CNU_ID, CNU_PW, GOOGLE_API_KEY
  VLLM_BASE_URL (기본: http://localhost:8000/v1), VLLM_MODEL
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

sys.path.insert(0, str(Path(__file__).parent))
from tasks.solar_task import SITE_TASKS

load_dotenv()

CNU_ID = os.getenv("CNU_ID", "")
CNU_PW = os.getenv("CNU_PW", "")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "")
VLLM_BASE_URL = os.getenv("VLLM_BASE_URL", "http://localhost:8000/v1")
VLLM_MODEL = os.getenv("VLLM_MODEL", "solar-pro")

MAX_STEPS = 20
SLEEP_BETWEEN_TASKS = 3
SAVE_DIR = Path(__file__).parent / "data"

KNOWN_MODELS = {"gemini", "solar"}

MODELS = {
    "gemini": lambda: (
        ChatGoogle(model="gemini-2.5-flash", api_key=GOOGLE_API_KEY, temperature=0.0),
        True,
    ),
    "solar": lambda: (
        ChatOpenAI(model=VLLM_MODEL, base_url=VLLM_BASE_URL, api_key="dummy", temperature=0.0),
        False,
    ),
}

EXTEND_SYSTEM_MESSAGE = (
    "You are an expert web agent navigating Chungnam National University services.\n"
    "ALL final answers in the `done` action MUST be in Korean.\n"
    "If an alert or popup appears, read the message and call done immediately.\n"
)


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
        status = "성공" if success else "실패"
        self._add(self._elapsed(), "task_end", f"[완료] {status} ({steps}단계)")

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
    model_name = "gemini"
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
                print(f"\n{'─'*60}")
                print(f"[{site_name}] Task {abs_idx}: {task}")

                browser_session = BrowserSession(
                    browser_profile=BrowserProfile(
                        headless=True,
                        viewport={"width": 1920, "height": 1080},
                        downloads_path=download_path,
                        proxy={"server": "socks5://localhost:8080"} if model_name == "solar" else None,
                        args=[
                            "--disable-dev-shm-usage",
                            "--no-sandbox",
                        ],
                    ),
                    keep_alive=False,
                )
                await browser_session.start()

                if start_url:
                    await browser_session.navigate_to(start_url)
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
