"""
cnu_search.py
통합정보시스템 메뉴별 탐색 + vision 필요성 분석 도구

목적:
  - 각 메뉴 페이지에서 DOM 텍스트만으로 충분한지 vs 스크린샷(vision)이 필요한지 판단
  - 결과를 JSON으로 저장해 input token 최적화 전략 수립에 활용

사용법:
  python cnu_search.py              # 전체 메뉴 탐색
  python cnu_search.py 0 5          # 0~4번 메뉴만 탐색
"""

import asyncio
import base64
import json
import os
import sys
from datetime import datetime
from pathlib import Path

from browser_use import BrowserSession, BrowserProfile, ChatOpenAI
from browser_use.agent.service import Agent
from dotenv import load_dotenv

load_dotenv()

CNU_ID = os.getenv("CNU_ID", "")
CNU_PW = os.getenv("CNU_PW", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")

OUTPUT_DIR = Path("./data/cnu_search")
MAX_STEPS_EXPLORE = 10  # 탐색용 에이전트는 짧게
SLEEP_BETWEEN = 3

# ── 탐색 대상 메뉴 목록 ──────────────────────────────────────────────────────
# (menu_id, 탐색 지시, 예상 카테고리)
EXPLORE_TARGETS = [
    # 학생정보
    {"id": "personal_info",       "category": "학생정보", "task": "학사행정 > 학생정보 메뉴로 이동해서 내 신상정보 화면을 열어줘."},
    {"id": "contact_info",        "category": "학생정보", "task": "학사행정 > 학생정보 > 연락처 화면을 열어줘."},
    # 학적관리
    {"id": "leave_of_absence",    "category": "학적관리", "task": "학사행정 > 학적관리 > 휴학신청 화면을 열어줘."},
    {"id": "major_change",        "category": "학적관리", "task": "학사행정 > 학적관리 > 전과신청 화면을 열어줘."},
    {"id": "double_major",        "category": "학적관리", "task": "학사행정 > 학적관리 > 복수전공 신청 내역 화면을 열어줘."},
    # 수강관리
    {"id": "course_list",         "category": "수강관리", "task": "학사행정 > 수강관리 > 수강편람조회 화면을 열어줘."},
    {"id": "syllabus",            "category": "수강관리", "task": "학사행정 > 수강관리 > 강의계획서 조회 화면을 열어줘."},
    {"id": "my_courses",          "category": "수강관리", "task": "학사행정 > 수강관리 > 수강신청내역 조회 화면을 열어줘."},
    {"id": "attendance",          "category": "수강관리", "task": "학사행정 > 수강관리 > 출결조회 화면을 열어줘."},
    {"id": "lecture_eval",        "category": "수강관리", "task": "학사행정 > 수강관리 > 강의평가 화면을 열어줘."},
    # 성적관리
    {"id": "grade_lookup",        "category": "성적관리", "task": "학사행정 > 성적관리 > 성적조회 화면을 열어줘."},
    {"id": "grade_transcript",    "category": "성적관리", "task": "학사행정 > 성적관리 > 성적통지표 조회 화면을 열어줘."},
    {"id": "retake_list",         "category": "성적관리", "task": "학사행정 > 성적관리 > 재이수 가능 과목 화면을 열어줘."},
    # 졸업관리
    {"id": "grad_self_check",     "category": "졸업관리", "task": "학사행정 > 졸업관리 > 졸업자가진단 화면을 열어줘."},
    {"id": "early_grad",          "category": "졸업관리", "task": "학사행정 > 졸업관리 > 조기졸업 신청 화면을 열어줘."},
    {"id": "foreign_lang",        "category": "졸업관리", "task": "학사행정 > 졸업관리 > 외국어성적 신청 화면을 열어줘."},
    # 교육과정
    {"id": "curriculum",          "category": "교육과정", "task": "학사행정 > 교육과정 > 교육과정 조회 화면을 열어줘."},
    {"id": "intensive_prog",      "category": "교육과정", "task": "학사행정 > 교육과정 > 심화과정 조회 화면을 열어줘."},
    # 장학/등록
    {"id": "scholarship",         "category": "장학/등록", "task": "학사행정 > 장학/등록 > 장학금 수혜내역 화면을 열어줘."},
    {"id": "tuition",             "category": "장학/등록", "task": "학사행정 > 장학/등록 > 등록금 납부현황 화면을 열어줘."},
    {"id": "tuition_bill",        "category": "장학/등록", "task": "학사행정 > 장학/등록 > 등록 고지서 화면을 열어줘."},
    # 취창업/비교과
    {"id": "internship",          "category": "취창업",   "task": "학사행정 > 취창업 > 백마인턴십 신청 화면을 열어줘."},
    {"id": "volunteer",           "category": "취창업",   "task": "학사행정 > 취창업 > 사회봉사활동 신청 화면을 열어줘."},
    # 국제교류
    {"id": "credit_exchange",     "category": "국제교류", "task": "학사행정 > 국제교류 > 타대학학점교류 신청 화면을 열어줘."},
    {"id": "overseas_activity",   "category": "국제교류", "task": "학사행정 > 국제교류 > 해외체험활동 신청 화면을 열어줘."},
    # 상담/기타
    {"id": "career_consult",      "category": "상담",     "task": "학사행정 > 미래설계상담 신청현황 화면을 열어줘."},
    {"id": "classroom_schedule",  "category": "기타",     "task": "학사행정 > 강의실 시간표 조회 화면을 열어줘."},
    {"id": "favorites",           "category": "기타",     "task": "통합정보시스템 메인에서 즐겨찾기 목록 화면을 열어줘."},
    {"id": "academic_calendar",   "category": "기타",     "task": "통합정보시스템에서 학사일정 화면을 열어줘."},
    {"id": "full_menu",           "category": "기타",     "task": "통합정보시스템 학사행정 전체 메뉴 목록이 보이도록 펼쳐줘."},
]

# ── GPT-4o로 vision 필요성 분석 ──────────────────────────────────────────────
ANALYSIS_SYSTEM_PROMPT = """You are an expert at analyzing web pages from CNU university's eXbuilder6-based integrated information system.
Evaluate whether a page requires visual (screenshot) understanding or if DOM text alone is sufficient for an LLM agent to complete tasks.

eXbuilder6 specifics:
- Grid/table data often rendered as visual elements → may not appear in DOM text
- Calendar widgets require visual interaction
- Complex dropdown comboboxes may need visual feedback
- Charts, diagrams, PDF viewers are fully visual
- Simple text forms, notice boards → DOM text usually sufficient

Return ONLY valid JSON, no markdown."""

ANALYSIS_USER_PROMPT = """Analyze this 통합정보시스템 page.

DOM text extracted (first 3000 chars):
{dom_text}

Screenshot attached.

Respond with JSON:
{{
  "menu_id": "{menu_id}",
  "category": "{category}",
  "page_type": "form|grid_table|list|dashboard|calendar|pdf|mixed|other",
  "vision_required": true or false,
  "confidence": "high|medium|low",
  "reason_ko": "한국어로 판단 이유 설명 (2~3문장)",
  "visual_elements": ["시각적으로만 파악 가능한 요소들"],
  "dom_extractable": ["DOM 텍스트로 충분히 추출 가능한 요소들"],
  "token_tip_ko": "이 페이지에서 토큰 절감 방법 (한국어)"
}}"""


async def analyze_with_gpt4o(menu_id: str, category: str, dom_text: str, screenshot_b64: str | None) -> dict:
    """GPT-4o로 vision 필요성 분석"""
    import openai

    client = openai.AsyncOpenAI(api_key=OPENAI_API_KEY)

    user_content = [
        {
            "type": "text",
            "text": ANALYSIS_USER_PROMPT.format(
                menu_id=menu_id,
                category=category,
                dom_text=dom_text[:3000],
            ),
        }
    ]

    if screenshot_b64:
        user_content.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/png;base64,{screenshot_b64}", "detail": "low"},
        })

    try:
        response = await client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": ANALYSIS_SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ],
            max_tokens=512,
            temperature=0.0,
        )
        raw = response.choices[0].message.content.strip()
        # JSON 파싱
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        return json.loads(raw)
    except Exception as e:
        return {
            "menu_id": menu_id,
            "category": category,
            "error": str(e),
            "vision_required": None,
        }


async def explore_menu(target: dict, browser_session: BrowserSession, gpt_llm, analysis_dir: Path) -> dict:
    """단일 메뉴 탐색 + 분석"""
    menu_id = target["id"]
    category = target["category"]
    task = target["task"]

    print(f"\n[{menu_id}] {task[:60]}...")

    BASE_CONTEXT = "통합정보시스템 버튼을 클릭하고 열리는 탭으로 전환하세요.\n"
    full_task = (
        f"{BASE_CONTEXT}"
        f"요청: {task}\n"
        "해당 화면에 도달하면 즉시 done을 호출해줘. 데이터 조회나 입력은 하지 말고, "
        "화면 진입만 확인하면 돼."
    )

    result = {
        "menu_id": menu_id,
        "category": category,
        "task": task,
        "timestamp": datetime.now().isoformat(),
        "navigation_success": False,
        "screenshot_saved": False,
        "dom_text_length": 0,
        "analysis": None,
    }

    try:
        agent = Agent(
            task=full_task,
            llm=gpt_llm,
            use_vision=True,
            browser=browser_session,
            generate_gif=False,
        )

        history = await agent.run(max_steps=MAX_STEPS_EXPLORE)
        result["navigation_success"] = history.is_successful()
        result["steps"] = history.number_of_steps()

        # 마지막 유효 스크린샷 + DOM 추출
        screenshots = history.screenshots(return_none_if_not_screenshot=True)
        last_screenshot = None
        for s in reversed(screenshots):
            if s:
                last_screenshot = s
                break

        # 마지막 state의 DOM text
        dom_text = ""
        for h in reversed(history.history):
            if h.state and h.state.dom_state:
                dom_text = getattr(h.state.dom_state, "element_tree", "") or ""
                if isinstance(dom_text, object) and not isinstance(dom_text, str):
                    dom_text = str(dom_text)
                break

        result["dom_text_length"] = len(dom_text)

        # 스크린샷 저장
        if last_screenshot:
            import base64 as b64
            img_data = b64.b64decode(last_screenshot)
            img_path = analysis_dir / f"{menu_id}.png"
            img_path.write_bytes(img_data)
            result["screenshot_saved"] = True
            result["screenshot_path"] = str(img_path)

        # GPT-4o 분석
        if OPENAI_API_KEY:
            print(f"  → GPT-4o 분석 중...")
            analysis = await analyze_with_gpt4o(menu_id, category, dom_text, last_screenshot)
            result["analysis"] = analysis
            vision_flag = analysis.get("vision_required")
            print(f"  → vision_required={vision_flag} | {analysis.get('reason_ko', '')[:60]}")
        else:
            # API 키 없으면 heuristic만
            result["analysis"] = _heuristic_analysis(menu_id, category, dom_text)

    except Exception as e:
        result["error"] = str(e)
        print(f"  ⚠️  에러: {e}")

    return result


def _heuristic_analysis(menu_id: str, category: str, dom_text: str) -> dict:
    """GPT-4o 없을 때 DOM 길이 기반 간단 휴리스틱"""
    visual_keywords = ["calendar", "chart", "graph", "image", "canvas", "pdf", "그래프", "달력"]
    has_visual = any(kw in dom_text.lower() for kw in visual_keywords)
    dom_rich = len(dom_text) > 500

    return {
        "menu_id": menu_id,
        "category": category,
        "page_type": "unknown",
        "vision_required": has_visual or not dom_rich,
        "confidence": "low",
        "reason_ko": f"휴리스틱: dom_text={len(dom_text)}자, 시각요소감지={has_visual}",
        "visual_elements": [],
        "dom_extractable": [],
        "token_tip_ko": "GPT-4o 분석 없이 휴리스틱 판단됨",
    }


def print_summary(results: list[dict]):
    vision_required = [r for r in results if r.get("analysis", {}) and r["analysis"].get("vision_required") is True]
    text_only = [r for r in results if r.get("analysis", {}) and r["analysis"].get("vision_required") is False]
    unknown = [r for r in results if r.get("analysis") is None or r["analysis"].get("vision_required") is None]

    print("\n" + "=" * 60)
    print(f"📊 분석 완료: 총 {len(results)}개 메뉴")
    print("=" * 60)
    print(f"  ✅ 텍스트만으로 충분: {len(text_only)}개")
    for r in text_only:
        print(f"     - [{r['category']}] {r['menu_id']}")

    print(f"\n  🖼️  Vision 필요:       {len(vision_required)}개")
    for r in vision_required:
        tip = r["analysis"].get("token_tip_ko", "")
        print(f"     - [{r['category']}] {r['menu_id']} → {tip[:50]}")

    print(f"\n  ❓ 판단 불가:          {len(unknown)}개")
    for r in unknown:
        print(f"     - [{r['category']}] {r['menu_id']}")


async def auto_login(browser_session: BrowserSession):
    try:
        await browser_session.navigate_to("https://portal.cnu.ac.kr/login.jsp")
        await asyncio.sleep(10)
        bu_page = await browser_session.get_current_page()
        await bu_page.evaluate(
            f"document.querySelector(\"input[name='user_id']\").value = '{CNU_ID}';"
        )
        await asyncio.sleep(0.5)
        await bu_page.evaluate(
            f"document.querySelector(\"input[name='user_password']\").value = '{CNU_PW}';"
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
    analysis_dir = OUTPUT_DIR / "screenshots"
    analysis_dir.mkdir(exist_ok=True)

    print(f"\n🔍 CNU 통합정보시스템 탐색 시작 ({len(targets)}개 메뉴)")
    print(f"   저장 경로: {OUTPUT_DIR}")

    # GPT-4o — 탐색 + 분석 모두 사용
    gpt_llm = ChatOpenAI(model="gpt-4o", api_key=OPENAI_API_KEY, temperature=0.0)

    browser_session = BrowserSession(
        browser_profile=BrowserProfile(
            headless=True,
            viewport={"width": 1920, "height": 1080},
            args=["--disable-dev-shm-usage", "--no-sandbox"],
        )
    )
    await browser_session.start()
    await auto_login(browser_session)

    all_results = []
    try:
        for target in targets:
            result = await explore_menu(target, browser_session, gpt_llm, analysis_dir)
            all_results.append(result)

            # 중간 저장
            out_path = OUTPUT_DIR / "results.json"
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(all_results, f, ensure_ascii=False, indent=2)

            await asyncio.sleep(SLEEP_BETWEEN)

    finally:
        await browser_session.stop()

    # 최종 요약 출력
    print_summary(all_results)

    # vision 필요/불필요 분리 저장
    vision_map = {
        r["menu_id"]: {
            "vision_required": r.get("analysis", {}).get("vision_required"),
            "confidence": r.get("analysis", {}).get("confidence"),
            "reason_ko": r.get("analysis", {}).get("reason_ko"),
            "token_tip_ko": r.get("analysis", {}).get("token_tip_ko"),
        }
        for r in all_results
    }
    with open(OUTPUT_DIR / "vision_map.json", "w", encoding="utf-8") as f:
        json.dump(vision_map, f, ensure_ascii=False, indent=2)

    print(f"\n📁 결과 저장:")
    print(f"   전체:      {OUTPUT_DIR}/results.json")
    print(f"   vision map: {OUTPUT_DIR}/vision_map.json")
    print(f"   스크린샷:  {analysis_dir}/")


if __name__ == "__main__":
    asyncio.run(main())
