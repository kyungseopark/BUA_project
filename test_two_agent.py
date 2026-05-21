"""
두 에이전트 순차 실행 테스트
- Agent 1 (vision=True): 목표 페이지까지 탐색
- Agent 2 (vision=False): 데이터 추출
"""
import asyncio
import os
from browser_use import BrowserSession, BrowserProfile, ChatGoogle
from logged_agent import LoggedAgent
from dotenv import load_dotenv

load_dotenv()

CNU_ID = os.getenv("CNU_ID", "")
CNU_PW = os.getenv("CNU_PW", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY", "")

BASE_CONTEXT = "통합정보시스템 버튼을 클릭하고 열리는 탭으로 전환하세요.\n"

NAV_TASK = (
    f"{BASE_CONTEXT}"
    "학사행정 > 학생정보 > 신상정보 화면을 열어줘. "
    "해당 화면이 완전히 로드되면 즉시 done을 호출해줘."
)

EXTRACT_TASK = (
    "현재 화면에서 내 전화번호를 찾아서 알려줘. "
    "다른 페이지로 이동하지 말고 지금 보이는 화면에서만 찾아줘."
)


async def auto_login(browser_session: BrowserSession):
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


async def main():
    llm = ChatGoogle(model="gemini-2.5-flash", api_key=GEMINI_API_KEY, temperature=0.0)

    browser_session = BrowserSession(
        browser_profile=BrowserProfile(
            headless=False,
            viewport={"width": 1920, "height": 1080},
            args=["--disable-dev-shm-usage", "--no-sandbox"],
        ),
        keep_alive=True,
    )
    await browser_session.start()
    await auto_login(browser_session)

    # ── Agent 1: vision=True, 탐색만 ──────────────────────────────
    print("\n[Agent 1] vision=True → 신상정보 페이지 탐색 중...")
    agent1 = LoggedAgent(
        task=NAV_TASK,
        llm=llm,
        use_vision=True,
        log_path="./data/cnu_search/two_agent_nav.jsonl",
        task_index=0,
        browser=browser_session,
        generate_gif=False,
    )
    history1 = await agent1.run(max_steps=10)
    agent1.flush_logs(success=history1.is_successful())

    print(f"[Agent 1] 결과: {'✅ 성공' if history1.is_successful() else '❌ 실패'} "
          f"({history1.number_of_steps()} steps)")

    if not history1.is_successful():
        print("❌ 탐색 실패 — 중단")
        await browser_session.stop()
        return

    # ── Agent 2: vision=False, 추출만 ─────────────────────────────
    print("\n[Agent 2] vision=False → 전화번호 추출 중...")
    agent2 = LoggedAgent(
        task=EXTRACT_TASK,
        llm=llm,
        use_vision=False,
        log_path="./data/cnu_search/two_agent_extract.jsonl",
        task_index=1,
        browser=browser_session,
        generate_gif=False,
    )
    history2 = await agent2.run(max_steps=5)
    agent2.flush_logs(success=history2.is_successful())

    print(f"\n[Agent 2] 결과: {'✅ 성공' if history2.is_successful() else '❌ 실패'} "
          f"({history2.number_of_steps()} steps)")
    print(f"[Agent 2] 추출값: {history2.final_result()}")

    await browser_session.stop()


if __name__ == "__main__":
    asyncio.run(main())
