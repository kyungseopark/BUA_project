import asyncio
from browser_use import BrowserSession, BrowserProfile
import os
from dotenv import load_dotenv
from browser_use import Agent, Browser, Controller, ChatOpenAI, ChatBrowserUse, ChatGoogle
from logged_agent import LoggedAgent

load_dotenv()

CNU_ID = os.getenv("CNU_ID")
CNU_PW = os.getenv("CNU_PW")

BASE_CONTEXT = (
    "통합정보시스템 버튼을 클릭하면 새 탭이 열릴 거야. "
    "반드시 새로 열린 탭(cnuit.cnu.ac.kr)으로 전환한 후 "
    "그 탭 안에서만 다음을 수행해줘. "
    "핍압 창이 뜬다면 전부(여러개가 있을수도 있음) 지우고 진행해줘."
    "통합정보시스템은 iframe 구조라 옆에 메뉴도 있다는 것을 인지해야해."
    "학사행정 메뉴에 거의 다 있을거야."
    "portal.cnu.ac.kr 페이지는 절대 사용하지 마: "
)
TASKS = [
    "저번 학기에 내가 들었던 수업이 뭐가 있었는지 알려줘.",
    # 태스크 추가하기
]


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
        # 비번 입력창 포커스 후 엔터
        await bu_page.press("Enter")
        print("✅ 아이디/비번 입력 완료")

    except Exception as e:
        print(f"⚠️ 자동 입력 실패: {e}")

    print("\n인증코드 입력 후 로그인 완료되면 Enter를 눌러주세요...")
    await asyncio.get_event_loop().run_in_executor(None, input)
    print("✅ 로그인 완료")

async def run_task(task: str, task_index: int, browser_session: BrowserSession):
    print(f"\n[{task_index+1}/{len(TASKS)}] 태스크 시작: {task}")

    full_task = f"{BASE_CONTEXT}{task}"

    agent = LoggedAgent(
        task=full_task,
        llm=ChatOpenAI(model="gpt-4o"),
        log_path="./data/training_data.jsonl",
        browser=browser_session,
        save_conversation_path=f"./data/conversations/task_{task_index}.json",
    )

    try:
        history = await agent.run(max_steps=20)
        agent.flush_logs(success=history.is_successful())
        print(f"완료: {history.final_result()}")

        screenshots = history.screenshot_paths()
        print(f"스크린샷 {len([s for s in screenshots if s])}장 저장됨")
    except Exception as e:
        agent.flush_logs(success=False)
        print(f"에러 발생: {e}")


async def main():
    os.makedirs("./data", exist_ok=True)
    os.makedirs("./data/conversations", exist_ok=True)

    browser_session = BrowserSession(
        browser_profile=BrowserProfile(headless=False),
    )
    await browser_session.start()

    await auto_login(browser_session)

    for i, task in enumerate(TASKS):
        await run_task(task, i, browser_session)
        await asyncio.sleep(2)

    await browser_session.stop()


if __name__ == "__main__":
    asyncio.run(main())