import asyncio
import os
import sys
import json
import time
from datetime import datetime
from browser_use import BrowserSession, BrowserProfile, ChatBrowserUse, ChatOpenAI, ChatGoogle
from logged_agent import LoggedAgent
from dotenv import load_dotenv

# ==========================================
# 🚨 [주의] 기존 collect.py와 동시 실행 시,
# 세션 튕김을 막기 위해 반드시 다른 팀원의 학번을 사용하세요!
# ==========================================
load_dotenv()
CNU_ID = os.getenv("CNU_ID") # TEST_CNU_ID를 먼저 찾습니다.
CNU_PW = os.getenv("CNU_PW")

# 프로파일링 전용 시스템 프롬프트 (에이전트 역할 강제)
BASE_CONTEXT = (
    "당신은 충남대학교 통합정보시스템(https://cnuit.cnu.ac.kr/main.do)의 복잡한 UI 구조를 분석하고 해부하는 '구조 분석 및 프로파일링 에이전트'입니다. "
    "로그인 후 통합정보시스템 버튼을 누른 후 https://cnuit.cnu.ac.kr/main.do 이 링크 안에서 태스크를 실행하십시오."
    "당신의 핵심 목적은 사용자의 명령을 끝까지 완수하는 것이 **아니라**, 개발자들이 브라우저 자동화(Playwright) 로케이터를 짜고 LLM 파인튜닝용 텍스트 전처리(Preprocessing) 파이프라인을 구축할 수 있도록 화면의 DOM 구조, 비표준 태그, 팝업, 숨김 데이터에 대한 '분석 인사이트'를 제공하는 것입니다.\n\n"
    
    "다음의 5가지 핵심 행동 지침(Rules)을 반드시 준수하여 탐색하고 보고하십시오.\n\n"
    
    "[1. 윈도우 및 세션 제어]\n"
    "- 초기 포털(portal.cnu.ac.kr)은 절대 조작하지 마십시오. 버튼 클릭 후 열리는 '새 탭(cnuit.cnu.ac.kr)'으로 브라우저 컨텍스트를 즉시 전환하십시오.\n"
    "- 페이지 진입 직후 화면을 가리는 모든 공지사항 및 팝업창(여러 개일 수 있음)의 구조(Window vs Layer Div)와 닫기 버튼의 셀렉터를 우선적으로 분석하여 리포팅한 후 닫으십시오.\n\n"
    
    "[2. 네비게이션 및 프레임(Iframe) 구조 인지]\n"
    "- 페이지는 프레임(Iframe) 구조로 분리되어 있습니다. 좌측 네비게이션(LNB)의 '학사행정' 카테고리를 확장하여 메뉴를 탐색하되, 메뉴 이동 시 호출되는 자바스크립트 함수(onclick)나 딥링크 URL이 있다면 이를 반드시 추출하여 보고하십시오.\n\n"
    
    "[3. 비표준 DOM 상호작용 및 전처리 분석 (가장 중요)]\n"
    "- 시스템의 버튼은 <a>, <div>, <img> 태그에 role='button'이나 tabindex, onclick 이벤트가 엮인 형태일 확률이 높습니다. 클릭 전 해당 요소의 정확한 태그 패턴을 분석하십시오.\n"
    "- 데이터가 표(Table)나 그리드(Grid)로 존재할 경우, 불필요한 CSS나 style 태그를 걷어내고 순수 마크다운(Markdown)으로 변환하기 위한 기준 컨테이너(상위 div나 table 태그)의 식별자를 찾아내십시오.\n\n"
    
    "[4. 비동기 렌더링(AJAX) 대기]\n"
    "- 버튼/탭 클릭 후 데이터가 비동기로 로드될 수 있습니다. 네트워크 요청이 끝나고 실제 데이터 컨테이너가 DOM에 렌더링될 때까지 대기한 후 DOM 구조를 분석하십시오.\n\n"
    
    "[5. 예외 및 한계 상황 보고]\n"
    "- '열람이 불가합니다', '조회된 데이터가 없습니다' 등의 알럿(Alert)이 발생하거나, 데이터가 <canvas>나 타 도메인 Iframe 내부에 숨어있어 일반적인 텍스트 추출이 불가능하다고 판단되면, 즉시 탐색을 멈추고 해당 한계점(Vision 필수 사용 여부 등)을 개발자에게 상세히 리포팅하십시오."
)

# 우리가 도출한 전처리/구조 분석 전용 태스크 목록
PROFILING_TASKS = [
    # "현재 화면에서 좌측 메뉴바(LNB), 상단 헤더, 하단 푸터를 제외하고, 실제 핵심 데이터가 들어있는 '메인 프레임(Main Content)'의 가장 상위 <div>나 <iframe>의 정확한 CSS Selector(예: #main-content-wrap)를 찾아줘. 이곳만 크롤링하면 전체 DOM 대비 HTML 용량이 대략 몇 % 줄어들지 추정해줘.",
    # "메인 화면에 있는 '표(Table)' 형식의 데이터를 분석해줘. 이것이 순수 <table> 태그로 되어 있어서 파이썬의 markdownify 라이브러리로 즉시 마크다운 변환이 가능한지, 아니면 <div>와 CSS 클래스로 억지로 표처럼 보이게 만든 그리드(Grid)라서 별도의 파싱 룰을 짜야 하는지 알려줘.",
    # "현재 페이지에서 '학점', '성적', '이수 구분' 같은 핵심 데이터가 텍스트(innerText)로 온전히 렌더링되어 있는지 확인해줘. 혹시 <input value='...'> 속성에 들어있거나, 마우스를 올려야만 보이는 <span title='...'> 툴팁 형태로 숨어있는 데이터가 있다면 모두 찾아줘.",
    # "화면을 한 번 새로고침(Reload) 한 뒤, 핵심 데이터를 담고 있는 컨테이너 <div>의 ID 속성값이 아까와 다르게 난수화(예: div_123 -> div_456)되었는지 확인해줘. 만약 난수화되었다면, Playwright에서 요소를 찾을 때 ID 대신 어떤 속성(예: class, 혹은 get_by_text)을 써야 가장 안전할지 추천해줘.",
    # "화면 내에서 클릭 가능한 모든 '조회', '검색', '상세보기' 버튼들을 분석해줘. 이것들이 표준 <button> 태그인지, 아니면 <a>, <div>, 심지어 <img> 태그에 role='button'이나 tabindex 속성이 결합된 형태인지 식별해서, Playwright로 클릭하기 위한 가장 정확한 Locator(예: page.locator('a[role=\"button\"]')) 룰을 작성해줘.",
    # "페이지 내의 탭(Tab) 메뉴를 클릭했을 때, URL 주소가 바뀌는지 아니면 주소는 그대로인 상태에서 자바스크립트(AJAX)로 화면의 일부만 바뀌는지(DOM Mutation) 확인해줘. 데이터가 뜨기까지 지연 시간(네트워크 로딩)이 있다면 명시해줘.",
    # "현재 페이지의 DOM을 검사해서, 텍스트가 아닌 <canvas> 태그로 그려진 차트나 데이터가 있는지 확인해줘. 만약 있다면 이 데이터를 읽기 위해 Vision(이미지 인식) 모델 사용이 필수적인지 판단해줘.",
    # "핵심 데이터가 현재 문서(Document)가 아닌 다른 도메인의 <iframe> 안에 갇혀있거나, 크롤링을 방해하는 Shadow DOM 안에 캡슐화되어 있는지 찾아내 줘.",
    # "현재 화면에 떠 있는 팝업창이 실제 브라우저의 '새 창(window.open)'인지, 아니면 현재 DOM 위에 겹쳐진 '레이어 모달(Layer Modal, 예: <div class=\"layer_popup\"> 또는 z-index가 매우 높은 div)'인지 구조를 분석해줘.",
    # "팝업창을 닫기 위한 '닫기(Close)' 또는 'X' 버튼의 정확한 HTML 태그와 식별 가능한 속성(Class, ID, onclick 등)의 패턴을 찾아내 줘.",
    # "팝업창 내부에 '오늘 하루 보지 않기'나 '다시 보지 않음' 같은 체크박스가 존재하는지 확인하고, 만약 있다면 그 체크박스와 닫기 버튼을 순차적으로 제어하기 위한 Playwright 로케이터(Locator) 전략을 제안해줘."
    # 🔥 [신규 1] 동적 ID 난수화(Mutation) 추적 태스크
    "좌측 메뉴바(LNB)를 클릭하여 임의의 다른 메뉴들을 2~3회 왕복 이동해봐. 메뉴를 전환할 때마다 메인 콘텐츠를 감싸는 <div> 컨테이너나 표의 ID(예: div4 -> div10 등)가 동적으로 계속 변경되는지 추적해줘. 만약 ID가 난수화되어 고정되지 않는다면, Playwright에서 절대 ID를 쓰지 않고 해당 컨테이너를 안정적으로 특정할 수 있는 대체 속성(class, role, 텍스트 등) 전략을 분석해줘.",

    # 🔥 [신규 2] 졸업자가진단 정합성 검증 태스크 (비전 모델 의존도 체크)
    "학사행정 메뉴를 통해 '졸업자가진단' 페이지로 진입 후 '취득(예정)성적' 탭을 클릭해줘. 시각적 인식(Vision)에 의존하지 않고 오직 DOM 텍스트 추출만으로 화면에 있는 약 47건의 전체 행 데이터를 스크래핑 해봐. '년도, 학기, 이수구분, 과목번호, 과목명, 영역, 구분, 학점, 등급, 평점, 인증제' 열의 데이터가 단 하나의 누락이나 깨짐 없이 완벽하게 추출되는지 검증하고, 총 4개의 행의 데이터(숫자나 텍스트)가 제대로 추출되는지 확인해줘. 성공한다면 해당 데이터를 마크다운 표로 출력해줘.",

    # 🔥 [신규 3] 수강편람조회 극한의 다중 열(Column) 추출 검증 태스크
    "학사행정 > 일반교육과정 > 수강편람조회 메뉴로 이동한 뒤, 과목명 검색칸에 '논리회로'를 입력하고 검색해줘. 검색 결과(약 4건)에 대해, 화면에 가로로 매우 길게 나열된 모든 열(No, 개설학과, 학년, 과목번호, 분반, 과목명, 제한인원, 수강인원, 개설이수구분, 수업방식, 강의시간, 담당교수, 교원구분, 수강안내, 수강제한참고사항, 영어강의, 교양영역, 교육과정이수구분, 교육과정적용년도, 수업유형, 성적평가방식, 영문과목명, 교직영역, 전자출결, 국어/영어/인문/SW관련교과목) 정보가 DOM 안에 숨김없이 모두 존재하는지 파악하고, 해당하는 행들 전체를 텍스트로 추출해줘. 실제 이미지를 통해 추출한 결과와 동일한지도 확인해. 또한 전체 데이터를 마크다운 표로 완벽하게 추출해줘."
]

# 수집 설정
MAX_STEPS = 20 # 분석은 빨리 끝나므로 스텝 수를 줄임

MODELS = {
    "browser_use": ChatBrowserUse(), # 요청하신 브라우저 유즈 기본 모델
    "gpt": ChatOpenAI(model="gpt-4o-mini"),
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

async def run_profiling_task(task_index: int, task: str, browser_session: BrowserSession, model_name: str):
    print(f"\n{'='*60}")
    print(f"🔍 [프로파일링] [{task_index+1}/{len(PROFILING_TASKS)}] {task}")
    print('='*60)

    # 기존 collect.py와 완전히 분리된 저장 경로 사용
    save_dir = f"./data/profiling_results/{model_name}"
    os.makedirs(save_dir, exist_ok=True)
    os.makedirs(f"{save_dir}/conversations", exist_ok=True)

    full_task = f"{BASE_CONTEXT}\n\n[분석명령]: {task}"
    
    agent = LoggedAgent(
        task=full_task,
        llm=MODELS[model_name],
        use_vision=True, # 구조 분석이므로 Vision을 강제로 켭니다 (버튼 생김새 확인용)
        calculate_cost=False, # 분석 테스트이므로 비용 계산 생략
        log_path=f"{save_dir}/profiling_data.jsonl",
        task_index=task_index,
        browser=browser_session,
        save_conversation_path=f"{save_dir}/conversations/task_{task_index:03d}.json",
    )

    try:
        history = await agent.run(max_steps=MAX_STEPS)
        agent.flush_logs(success=history.is_successful())
        print(f"✅ 분석 완료! 결과가 {save_dir} 에 저장되었습니다.")
        
        # 에이전트가 뱉어낸 분석 리포트(Final Result)를 터미널에 바로 출력
        print(f"\n📝 [에이전트 분석 리포트]\n{history.final_result()}\n")
        
    except Exception as e:
        agent.flush_logs(success=False)
        print(f"❌ 에러 발생: {e}")

    await asyncio.sleep(3)

async def main():
    model_name = "browser_use" # 요청하신 브라우저 유즈 모델 기본 셋팅
    
    print(f"\n{'='*80}")
    print(f"🛠️ 통합정보시스템 프로파일링(구조 분석) 시작")
    print(f"사용 모델: {model_name} (Vision: True)")
    print(f"{'='*80}\n")

    browser_session = BrowserSession(
        browser_profile=BrowserProfile(headless=False),
        keep_alive=True,
    )
    await browser_session.start()
    await auto_login(browser_session)

    # 수집 모드가 아니므로 리셋 없이 연속으로 쭉 분석 지시를 내립니다.
    for i, task in enumerate(PROFILING_TASKS):
        await run_profiling_task(i, task, browser_session, model_name)

    await browser_session.stop()
    print("\n✅ 모든 프로파일링 태스크 완료. ./data/profiling_results/ 폴더를 확인하세요.")

if __name__ == "__main__":
    asyncio.run(main())