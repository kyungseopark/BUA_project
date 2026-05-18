"""
cnu_search.py
통합정보시스템 메뉴별 DOM 분석 + input token 최적화 전략 도구

목적:
  - 각 메뉴 페이지에서 LLM에 전달되는 DOM 구조 분석
  - vision(스크린샷) 없이 텍스트만으로 충분한지 판단
  - input token 절감 가능한 부분 구체적으로 제안

사용법:
  python cnu_search.py              # 전체 메뉴 탐색
  python cnu_search.py 0 5          # 0~4번 메뉴만
"""

import asyncio
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

from browser_use import BrowserSession, BrowserProfile, ChatGoogle
from dotenv import load_dotenv
from logged_agent import LoggedAgent

load_dotenv()

CNU_ID = os.getenv("CNU_ID", "")
CNU_PW = os.getenv("CNU_PW", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY", "")

OUTPUT_DIR = Path("./data/cnu_search")
MAX_STEPS = 10
SLEEP_BETWEEN = 3

BASE_CONTEXT = "통합정보시스템 버튼을 클릭하고 열리는 탭으로 전환하세요.\n"

# ── 탐색 대상 메뉴 ──────────────────────────────────────────────────────────
EXPLORE_TARGETS = [
    {"id": "personal_info",      "category": "학생정보", "task": "학사행정 > 학생정보 > 신상정보 화면을 열고, 내 전화번호를 알려줘."},
    {"id": "contact_info",       "category": "학생정보", "task": "학사행정 > 학생정보 > 연락처 화면을 열어줘."},
    {"id": "leave_of_absence",   "category": "학적관리", "task": "학사행정 > 학적관리 > 휴학신청 화면을 열어줘."},
    {"id": "double_major",       "category": "학적관리", "task": "학사행정 > 학적관리 > 복수전공 신청 내역 화면을 열어줘."},
    {"id": "course_list",        "category": "수강관리", "task": "학사행정 > 수강관리 > 수강편람조회 화면을 열어줘."},
    {"id": "syllabus",           "category": "수강관리", "task": "학사행정 > 수강관리 > 강의계획서 조회 화면을 열어줘."},
    {"id": "my_courses",         "category": "수강관리", "task": "학사행정 > 수강관리 > 수강신청내역 조회 화면을 열어줘."},
    {"id": "attendance",         "category": "수강관리", "task": "학사행정 > 수강관리 > 출결조회 화면을 열어줘."},
    {"id": "grade_lookup",       "category": "성적관리", "task": "학사행정 > 성적관리 > 성적조회 화면을 열어줘."},
    {"id": "grade_transcript",   "category": "성적관리", "task": "학사행정 > 성적관리 > 성적통지표 화면을 열어줘."},
    {"id": "grad_self_check",    "category": "졸업관리", "task": "학사행정 > 졸업관리 > 졸업자가진단 화면을 열어줘."},
    {"id": "foreign_lang",       "category": "졸업관리", "task": "학사행정 > 졸업관리 > 외국어성적 신청 화면을 열어줘."},
    {"id": "curriculum",         "category": "교육과정", "task": "학사행정 > 교육과정 조회 화면을 열어줘."},
    {"id": "scholarship",        "category": "장학/등록", "task": "학사행정 > 장학/등록 > 장학금 수혜내역 화면을 열어줘."},
    {"id": "tuition",            "category": "장학/등록", "task": "학사행정 > 장학/등록 > 등록금 납부현황 화면을 열어줘."},
    {"id": "internship",         "category": "취창업",   "task": "학사행정 > 취창업 > 백마인턴십 신청 화면을 열어줘."},
    {"id": "credit_exchange",    "category": "국제교류", "task": "학사행정 > 국제교류 > 타대학학점교류 신청 화면을 열어줘."},
    {"id": "career_consult",     "category": "상담",     "task": "학사행정 > 미래설계상담 신청현황 화면을 열어줘."},
    {"id": "academic_calendar",  "category": "기타",     "task": "통합정보시스템에서 학사일정 화면을 열어줘."},
    {"id": "full_menu",          "category": "기타",     "task": "통합정보시스템 학사행정 전체 메뉴를 펼쳐줘."},
]


# ── 대화 로그에서 DOM 분석 ──────────────────────────────────────────────────
def parse_conversation_log(jsonl_path: str) -> list[dict]:
    """LoggedAgent가 저장한 JSONL에서 스텝별 DOM/토큰 정보 추출"""
    steps = []
    if not os.path.exists(jsonl_path):
        return steps

    with open(jsonl_path, encoding="utf-8") as f:
        for line in f:
            try:
                item = json.loads(line)
                step_info = {
                    "step": item.get("step_number"),
                    "system_prompt_len": 0,
                    "dom_text_len": 0,
                    "has_screenshot": False,
                    "agent_state_len": 0,
                    "agent_history_len": 0,
                    "total_input_len": 0,
                }

                for msg in item.get("input", []):
                    role = msg.get("role", "")
                    content = msg.get("content", "")

                    if role == "system":
                        step_info["system_prompt_len"] = len(str(content))

                    elif role == "user":
                        if isinstance(content, list):
                            for part in content:
                                ptype = part.get("type", "")
                                text = str(part.get("text", ""))
                                if ptype == "text":
                                    step_info["total_input_len"] += len(text)
                                    # browser_state 섹션 (실제 DOM 요소들)
                                    if "<browser_state>" in text:
                                        s = text.find("<browser_state>")
                                        e = text.find("</browser_state>")
                                        step_info["agent_state_len"] = (e - s) if e > s else len(text) - s
                                    if "<agent_history>" in text:
                                        hist_start = text.find("<agent_history>")
                                        hist_end = text.find("</agent_history>")
                                        if hist_end > hist_start:
                                            step_info["agent_history_len"] = hist_end - hist_start
                                elif ptype == "image_url":
                                    step_info["has_screenshot"] = True
                        elif isinstance(content, str):
                            step_info["total_input_len"] += len(content)

                steps.append(step_info)
            except Exception:
                continue

    return steps


def summarize_steps(steps: list[dict]) -> dict:
    """스텝 목록에서 대표 통계 추출 (첫 번째 실제 DOM 스텝 기준)"""
    if not steps:
        return {}

    # 첫 번째 DOM이 있는 스텝 사용 (step 1은 초기화라 agent_state가 작음)
    target = steps[1] if len(steps) > 1 else steps[0]
    return {
        "total_steps": len(steps),
        "system_prompt_chars": target["system_prompt_len"],
        "agent_state_chars": target["agent_state_len"],
        "agent_history_chars": target["agent_history_len"],
        "has_screenshot": target["has_screenshot"],
        "total_input_chars": target["total_input_len"] + target["system_prompt_len"],
        # 대략적인 토큰 수 추정 (한국어 평균 ~2.5자/토큰)
        "estimated_tokens": int((target["total_input_len"] + target["system_prompt_len"]) / 2.5),
    }


# ── Gemini로 DOM 최적화 분석 ────────────────────────────────────────────────
ANALYSIS_PROMPT = """당신은 웹 에이전트의 input token을 최적화하는 전문가입니다.
아래는 충남대학교 통합정보시스템(eXbuilder6 기반)의 특정 메뉴 페이지에서 LLM 에이전트에게 전달된 실제 입력 데이터입니다.

[메뉴 정보]
- menu_id: {menu_id}
- category: {category}

[토큰 사용 현황]
- 시스템 프롬프트: {system_prompt_chars}자
- agent_state(DOM): {agent_state_chars}자
- agent_history: {agent_history_chars}자
- 스크린샷 포함: {has_screenshot}
- 총 입력 추정 토큰: {estimated_tokens}개

[실제 agent_state 내용 (처음 3000자)]
{agent_state_sample}

위 정보를 바탕으로 다음을 분석해줘:
1. vision(스크린샷) 없이 DOM 텍스트만으로 이 페이지의 전형적인 태스크를 수행할 수 있는가?
2. DOM에서 삭제하거나 압축할 수 있는 불필요한 요소는 무엇인가?
3. 토큰을 줄이기 위한 구체적인 최적화 방법은?

반드시 아래 JSON 형식으로만 답변해줘 (마크다운 코드블록 없이 순수 JSON):
{{
  "vision_required": true 또는 false,
  "vision_reason": "vision 필요/불필요 이유 (한국어 2문장)",
  "dom_issues": ["DOM에서 발견된 불필요한 요소들"],
  "optimization_tips": ["구체적인 최적화 방법들"],
  "estimated_token_reduction": "최적화 시 예상 절감률 (예: 30~40%)",
  "priority": "high|medium|low (최적화 우선순위)"
}}"""


async def analyze_with_gemini(menu_id: str, category: str, stats: dict, agent_state_sample: str) -> dict:
    import google.genai as genai
    import google.genai.types as genai_types

    client = genai.Client(api_key=GEMINI_API_KEY)
    prompt = ANALYSIS_PROMPT.format(
        menu_id=menu_id,
        category=category,
        system_prompt_chars=stats.get("system_prompt_chars", 0),
        agent_state_chars=stats.get("agent_state_chars", 0),
        agent_history_chars=stats.get("agent_history_chars", 0),
        has_screenshot=stats.get("has_screenshot", False),
        estimated_tokens=stats.get("estimated_tokens", 0),
        agent_state_sample=agent_state_sample[:3000],
    )

    try:
        response = await asyncio.to_thread(
            client.models.generate_content,
            model="gemini-2.5-flash",
            contents=prompt,
            config=genai_types.GenerateContentConfig(
                temperature=0.0,
                max_output_tokens=2048,
                thinking_config=genai_types.ThinkingConfig(thinking_budget=0),
            ),
        )
        raw = response.text.strip()
        # 마크다운 코드블록 제거
        if "```" in raw:
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.strip()
        # JSON 부분만 추출 (앞뒤 텍스트 제거)
        start = raw.find("{")
        end = raw.rfind("}") + 1
        if start >= 0 and end > start:
            raw = raw[start:end]
        return json.loads(raw)
    except Exception as e:
        return {"error": str(e), "vision_required": None}


# ── 메뉴 탐색 + 분석 ────────────────────────────────────────────────────────
async def explore_menu(target: dict, gemini_llm, output_dir: Path) -> dict:
    menu_id = target["id"]
    category = target["category"]
    task = target["task"]

    print(f"\n[{menu_id}] {task}")

    full_task = (
        f"{BASE_CONTEXT}"
        f"요청: {task}\n"
        "화면에 도달한 후 요청한 정보를 찾아서 done으로 반환해줘."
    )

    log_path = str(output_dir / f"{menu_id}.jsonl")
    if os.path.exists(log_path):
        os.remove(log_path)

    result = {
        "menu_id": menu_id,
        "category": category,
        "task": task,
        "timestamp": datetime.now().isoformat(),
        "navigation_success": False,
        "steps": 0,
        "token_stats": {},
        "analysis": None,
    }

    # test.py 패턴: 태스크마다 새 브라우저 세션 생성 + 로그인
    browser_session = BrowserSession(
        browser_profile=BrowserProfile(
            headless=False,
            viewport={"width": 1920, "height": 1080},
            args=["--disable-dev-shm-usage", "--no-sandbox"],
        )
    )

    try:
        await browser_session.start()
        await auto_login(browser_session)

        agent = LoggedAgent(
            task=full_task,
            llm=gemini_llm,
            use_vision=False,
            log_path=log_path,
            task_index=0,
            browser=browser_session,
            generate_gif=False,
        )

        history = await agent.run(max_steps=MAX_STEPS)
        agent.flush_logs(success=history.is_successful())

        result["navigation_success"] = history.is_successful()
        result["steps"] = history.number_of_steps()

        # 대화 로그 파싱
        steps_data = parse_conversation_log(log_path)
        stats = summarize_steps(steps_data)
        result["token_stats"] = stats

        # agent_state 샘플 추출 (Gemini 분석용)
        agent_state_sample = ""
        if os.path.exists(log_path):
            with open(log_path, encoding="utf-8") as f:
                lines = f.readlines()
            # DOM이 가장 풍부한 스텝 사용 (신상정보 페이지 진입 후)
            target_line = lines[min(3, len(lines)-1)]
            item = json.loads(target_line)
            for msg in item.get("input", []):
                if msg.get("role") == "user":
                    content = msg.get("content", [])
                    if isinstance(content, list):
                        for part in content:
                            if part.get("type") == "text" and "<browser_state>" in part.get("text", ""):
                                text = part["text"]
                                s = text.find("<browser_state>")
                                agent_state_sample = text[s:s+4000]
                                break

        print(f"  → 총 입력 추정 토큰: {stats.get('estimated_tokens', '?')}개 "
              f"| DOM: {stats.get('agent_state_chars', '?')}자 "
              f"| 스크린샷: {stats.get('has_screenshot', '?')}")

        # Gemini 분석
        if GEMINI_API_KEY and stats:
            print(f"  → Gemini 분석 중...")
            analysis = await analyze_with_gemini(menu_id, category, stats, agent_state_sample)
            result["analysis"] = analysis
            print(f"  → vision_required={analysis.get('vision_required')} | "
                  f"절감 예상: {analysis.get('estimated_token_reduction', '?')} | "
                  f"우선순위: {analysis.get('priority', '?')}")

    except Exception as e:
        result["error"] = str(e)
        print(f"  ⚠️  에러: {e}")

    finally:
        await browser_session.stop()

    return result


# ── 요약 출력 ────────────────────────────────────────────────────────────────
def print_summary(results: list[dict]):
    print("\n" + "=" * 65)
    print(f"{'메뉴':<22} {'토큰':>6} {'DOM':>6} {'Vision':>7} {'절감':>8} {'우선순위':>6}")
    print("-" * 65)

    for r in results:
        stats = r.get("token_stats", {})
        analysis = r.get("analysis") or {}
        tokens = stats.get("estimated_tokens", 0)
        dom = stats.get("agent_state_chars", 0)
        vision = str(analysis.get("vision_required", "?"))
        reduction = analysis.get("estimated_token_reduction", "-")
        priority = analysis.get("priority", "-")
        name = r["menu_id"][:20]
        print(f"{name:<22} {tokens:>6,} {dom:>6,} {vision:>7} {reduction:>8} {priority:>6}")

    print("=" * 65)

    vision_required = [r for r in results if (r.get("analysis") or {}).get("vision_required") is True]
    text_only = [r for r in results if (r.get("analysis") or {}).get("vision_required") is False]
    high_priority = [r for r in results if (r.get("analysis") or {}).get("priority") == "high"]

    print(f"\n✅ 텍스트만 충분: {len(text_only)}개  |  🖼️  Vision 필요: {len(vision_required)}개")
    if high_priority:
        print(f"\n🔥 최적화 우선순위 HIGH ({len(high_priority)}개):")
        for r in high_priority:
            tips = (r.get("analysis") or {}).get("optimization_tips", [])
            print(f"  [{r['category']}] {r['menu_id']}")
            for tip in tips[:2]:
                print(f"    · {tip}")


# ── 메인 ────────────────────────────────────────────────────────────────────
async def auto_login(browser_session: BrowserSession):
    try:
        await browser_session.navigate_to("https://portal.cnu.ac.kr/login.jsp")
        await asyncio.sleep(10)
        bu_page = await browser_session.get_current_page()
        await bu_page.evaluate(
            f"(...args) => {{ document.querySelector(\"input[name='user_id']\").value = '{CNU_ID}'; }}"
        )
        await asyncio.sleep(0.5)
        await bu_page.evaluate(
            f"(...args) => {{ document.querySelector(\"input[name='user_password']\").value = '{CNU_PW}'; }}"
        )
        await asyncio.sleep(1)
        await bu_page.press("Enter")
        await asyncio.sleep(5)
        print("✅ 로그인 완료")
    except Exception as e:
        print(f"⚠️ 로그인 실패: {e}")


async def main():
    start_idx = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    end_idx = int(sys.argv[2]) if len(sys.argv) > 2 else len(EXPLORE_TARGETS)
    targets = EXPLORE_TARGETS[start_idx:end_idx]

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    logs_dir = OUTPUT_DIR / "logs"
    logs_dir.mkdir(exist_ok=True)

    print(f"\n🔍 CNU 통합정보시스템 DOM 분석 시작 ({len(targets)}개 메뉴)")

    gemini_llm = ChatGoogle(model="gemini-2.5-flash", api_key=GEMINI_API_KEY, temperature=0.0)

    all_results = []
    for target in targets:
        result = await explore_menu(target, gemini_llm, logs_dir)
        all_results.append(result)

        with open(OUTPUT_DIR / "results.json", "w", encoding="utf-8") as f:
            json.dump(all_results, f, ensure_ascii=False, indent=2)

        await asyncio.sleep(SLEEP_BETWEEN)

    print_summary(all_results)

    # vision map 저장
    vision_map = {
        r["menu_id"]: {
            "category": r["category"],
            "vision_required": (r.get("analysis") or {}).get("vision_required"),
            "estimated_tokens": r.get("token_stats", {}).get("estimated_tokens"),
            "estimated_token_reduction": (r.get("analysis") or {}).get("estimated_token_reduction"),
            "priority": (r.get("analysis") or {}).get("priority"),
            "optimization_tips": (r.get("analysis") or {}).get("optimization_tips", []),
        }
        for r in all_results
    }
    with open(OUTPUT_DIR / "vision_map.json", "w", encoding="utf-8") as f:
        json.dump(vision_map, f, ensure_ascii=False, indent=2)

    print(f"\n📁 결과: {OUTPUT_DIR}/results.json")
    print(f"📁 요약: {OUTPUT_DIR}/vision_map.json")


if __name__ == "__main__":
    asyncio.run(main())
