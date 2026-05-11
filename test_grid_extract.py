# test_grid_extract.py
import asyncio
import os
import json
from datetime import datetime
from browser_use import BrowserSession, BrowserProfile, ChatBrowserUse
from logged_agent import LoggedAgent
from dotenv import load_dotenv

load_dotenv()
CNU_ID = os.getenv("CNU_ID")
CNU_PW = os.getenv("CNU_PW")


EXTRACT_JS = """
() => {
    const grids = document.querySelectorAll('[role="grid"]');
    const results = [];
    
    grids.forEach((grid, idx) => {
        const cells = grid.querySelectorAll('[role="gridcell"]');
        const rows = {};
        const headers = {};
        
        const colHeaders = grid.querySelectorAll('[role="columnheader"]');
        colHeaders.forEach((h, i) => {
            headers[i+1] = h.innerText.trim();
        });
        
        cells.forEach(cell => {
            const label = cell.getAttribute('aria-label') || '';
            const m = label.match(/(\\d+)행 (\\d+)열 (.*)/);
            if (m) {
                const row = m[1];
                const col = m[2];
                const val = m[3];
                if (!rows[row]) rows[row] = {};
                const colName = headers[col] || ('col_' + col);
                rows[row][colName] = val;
            }
        });
        
        let context = '';
        try {
            const parent = grid.parentElement;
            if (parent) {
                context = parent.innerText.substring(0, 100).replace(/\\n/g, ' ');
            }
        } catch(e) {}
        
        results.push({
            grid_idx: idx,
            grid_id: grid.id,
            context: context,
            total_cells: cells.length,
            total_rows: Object.keys(rows).length,
            total_headers: Object.keys(headers).length,
            headers: Object.values(headers),
            data: Object.values(rows)
        });
    });
    
    return JSON.stringify(results);
}
"""


COUNT_VISIBILITY_JS = """
() => {
    const grids = document.querySelectorAll('[role="grid"]');
    const stats = [];
    
    grids.forEach((grid, idx) => {
        const cells = grid.querySelectorAll('[role="gridcell"]');
        let visible = 0;
        let invisible = 0;
        let totalRows = new Set();
        
        cells.forEach(cell => {
            const rect = cell.getBoundingClientRect();
            const style = window.getComputedStyle(cell);
            const isVisible = rect.width > 0 && rect.height > 0 && 
                              style.display !== 'none' && 
                              style.visibility !== 'hidden';
            if (isVisible) visible++;
            else invisible++;
            
            const label = cell.getAttribute('aria-label') || '';
            const m = label.match(/(\\d+)행/);
            if (m) totalRows.add(m[1]);
        });
        
        stats.push({
            grid_idx: idx,
            grid_id: grid.id,
            total_cells: cells.length,
            visible_cells: visible,
            invisible_cells: invisible,
            unique_rows_in_dom: totalRows.size
        });
    });
    
    return JSON.stringify(stats);
}
"""


async def safe_evaluate(page, js_code):
    """evaluate 호출 후 결과를 파싱해서 반환"""
    try:
        result = await page.evaluate(js_code)
        
        # 결과 디버깅
        print(f"   [DEBUG] evaluate 결과 타입: {type(result).__name__}")
        
        # 다양한 형태 처리
        if isinstance(result, str):
            # JSON 문자열인 경우
            return json.loads(result)
        elif isinstance(result, list):
            # 이미 list인 경우
            return result
        elif isinstance(result, dict):
            # dict 형태로 wrapper에 감싸진 경우
            print(f"   [DEBUG] dict 키: {list(result.keys())[:10]}")
            # 흔한 패턴: {'value': [...]} 또는 {'result': [...]}
            for key in ['value', 'result', 'data', 'return']:
                if key in result:
                    val = result[key]
                    if isinstance(val, str):
                        return json.loads(val)
                    return val
            # dict 자체가 결과면 list로 감싸기
            return [result]
        else:
            print(f"   [DEBUG] 알 수 없는 타입, 원본 반환: {result}")
            return result
    except Exception as e:
        print(f"   [DEBUG] safe_evaluate 예외: {type(e).__name__}: {e}")
        raise


async def get_page_url(page):
    """페이지 URL을 안전하게 가져오기"""
    try:
        url = page.url
        if url:
            return url
    except:
        pass
    
    try:
        url = page._page.url
        if url:
            return url
    except:
        pass
    
    try:
        # evaluate는 dict로 올 수 있으니 JSON.stringify 사용
        result = await page.evaluate("() => JSON.stringify({url: window.location.href})")
        if isinstance(result, str):
            data = json.loads(result)
            return data.get('url')
        elif isinstance(result, dict):
            return result.get('value', {}).get('url') or result.get('url')
    except:
        pass
    
    return "unknown"


async def safe_bring_to_front(page):
    """bring_to_front 안전하게 호출"""
    # 방법 1: 직접 호출
    try:
        await page.bring_to_front()
        return True
    except:
        pass
    
    # 방법 2: 내부 _page 객체
    try:
        await page._page.bring_to_front()
        return True
    except:
        pass
    
    # 방법 3: focus_tab 같은 다른 메서드
    try:
        if hasattr(page, 'focus'):
            await page.focus()
            return True
    except:
        pass
    
    print(f"   [DEBUG] bring_to_front 실패, 메서드 없음")
    return False


TEST_MENUS = [
    {
        "label": "전체성적조회",
        "navigation_task": (
            "통합정보시스템 버튼을 클릭해서 새 탭으로 이동해. "
            "팝업이 뜨면 모두 닫아. "
            "그 다음 좌측 메뉴에서 학사행정 > 성적정보 > 전체성적조회 메뉴를 찾아서 클릭해. "
            "데이터 그리드가 화면에 표시되면 done을 호출해. "
            "전체 44건이 추출되어야 해"
        )
    },
    {
        "label": "신상정보",
        "navigation_task": (
            "현재 통합정보시스템 탭에 있어. "
            "팝업이 뜨면 모두 닫아. "
            "좌측 메뉴에서 학사행정 > 신상정보 > 신상정보/개인설정 메뉴를 찾아서 클릭해. "
            "도움말 팝업이 뜨면 닫아. "
            "기타 정보 탭으로 이동해서 환불 계좌가 어떻게 조회되는지 확인해. "
            "데이터가 화면에 표시되면 done을 호출해."
        )
    },
    {
        "label": "수강편람조회",
        "navigation_task": (
            "현재 통합정보시스템 탭에 있어. "
            "팝업이 뜨면 모두 닫아. "
            "좌측 메뉴에서 학사행정 > 일반교육과정 > 수강편람조회 메뉴를 클릭해. "
            "과목명 검색창에 '논리회로'를 입력하고 검색 버튼을 눌러. "
            "검색 결과가 그리드에 표시되면 done을 호출해."
        )
    },
]


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


async def find_cnuit_page(browser_session):
    """현재 활성 페이지가 cnuit인지 확인"""
    try:
        page = await browser_session.get_current_page()
        url = await get_page_url(page)
        print(f"   [DEBUG] 현재 활성 페이지 URL: {url}")
        
        if url and "cnuit.cnu.ac.kr" in url:
            return page
        
        # 모든 탭 탐색
        pages = None
        for attr_name in ['pages', 'get_pages', 'browser_context']:
            if hasattr(browser_session, attr_name):
                attr = getattr(browser_session, attr_name)
                try:
                    if callable(attr):
                        pages = await attr() if asyncio.iscoroutinefunction(attr) else attr()
                    elif hasattr(attr, 'pages'):
                        pages = attr.pages
                    else:
                        pages = attr
                    if pages:
                        break
                except:
                    continue
        
        if pages:
            print(f"   [DEBUG] 모든 탭 탐색: {len(pages)}개")
            for i, p in enumerate(pages):
                p_url = await get_page_url(p)
                print(f"   [DEBUG] 탭 {i}: {p_url}")
                if p_url and "cnuit.cnu.ac.kr" in p_url:
                    return p
        
        # cnuit 못 찾으면 현재 페이지 반환
        print(f"   [DEBUG] cnuit URL 못 찾음, 현재 활성 페이지로 시도")
        return page
    except Exception as e:
        print(f"   [DEBUG] find_cnuit_page 예외: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        return None


async def navigate_with_agent(browser_session, navigation_task: str, label: str, task_index: int):
    """browser-use 에이전트로 메뉴까지 이동"""
    print(f"\n🤖 에이전트가 '{label}' 페이지로 이동 중...")
    
    save_dir = "./data/grid_extract_test/conversations"
    os.makedirs(save_dir, exist_ok=True)
    
    agent = None
    nav_result = {
        "success": False,
        "final_result": None,
        "steps": 0,
        "error": None,
    }
    
    try:
        agent = LoggedAgent(
            task=navigation_task,
            llm=ChatBrowserUse(),
            use_vision=True,
            calculate_cost=False,
            log_path=f"./data/grid_extract_test/nav_log.jsonl",
            task_index=task_index,
            browser=browser_session,
            save_conversation_path=f"{save_dir}/nav_{label}.json",
        )
        
        history = await agent.run(max_steps=15)
        success = history.is_successful()
        agent.flush_logs(success=success)
        
        nav_result["success"] = success
        nav_result["final_result"] = history.final_result()
        nav_result["steps"] = history.number_of_steps()
        
        print(f"   {'✅' if success else '⚠️'} 이동 결과: {success}")
        
        del agent
        agent = None
        
    except Exception as e:
        print(f"   ❌ 이동 실패: {type(e).__name__}: {e}")
        nav_result["error"] = f"{type(e).__name__}: {e}"
        if agent:
            try:
                agent.flush_logs(success=False)
            except:
                pass
    
    return nav_result


async def extract_grid_data(cnuit_page, label: str):
    """그리드 데이터 추출"""
    extraction_result = {
        "label": label,
        "url": None,
        "visibility_stats": [],
        "extraction_result": [],
        "errors": [],
    }
    
    print(f"\n{'='*60}")
    print(f"📊 [{label}] 그리드 추출 시작")
    print('='*60)
    
    # URL
    try:
        extraction_result["url"] = await get_page_url(cnuit_page)
        print(f"   [DEBUG] 페이지 URL: {extraction_result['url']}")
    except Exception as e:
        extraction_result["errors"].append(f"URL 가져오기 실패: {e}")
    
    # 1. 가시성 분석
    print("\n1. 셀 가시성 분석...")
    try:
        visibility = await safe_evaluate(cnuit_page, COUNT_VISIBILITY_JS)
        if not isinstance(visibility, list):
            print(f"   ⚠️ visibility가 list 아님: {type(visibility)}")
            visibility = []
        
        extraction_result["visibility_stats"] = visibility
        print(f"   ✅ 발견된 그리드: {len(visibility)}개")
        for v in visibility:
            if isinstance(v, dict):
                print(f"   [Grid {v.get('grid_idx')}] 전체셀 {v.get('total_cells')}, "
                      f"보임 {v.get('visible_cells')}, "
                      f"숨김 {v.get('invisible_cells')}, "
                      f"DOM행 {v.get('unique_rows_in_dom')}")
    except Exception as e:
        err_msg = f"가시성 분석 실패: {type(e).__name__}: {e}"
        print(f"   ❌ {err_msg}")
        extraction_result["errors"].append(err_msg)
        import traceback
        traceback.print_exc()
    
    # 2. 데이터 추출
    print("\n2. 그리드 데이터 추출...")
    try:
        result = await safe_evaluate(cnuit_page, EXTRACT_JS)
        if not isinstance(result, list):
            print(f"   ⚠️ result가 list 아님: {type(result)}")
            result = []
        
        extraction_result["extraction_result"] = result
        print(f"   ✅ 추출 성공: {len(result)}개 그리드")
    except Exception as e:
        err_msg = f"추출 실패: {type(e).__name__}: {e}"
        print(f"   ❌ {err_msg}")
        extraction_result["errors"].append(err_msg)
        import traceback
        traceback.print_exc()
    
    # 3. 결과 출력
    if extraction_result["extraction_result"]:
        print(f"\n3. 추출 결과 요약:")
        for r in extraction_result["extraction_result"]:
            if not isinstance(r, dict):
                print(f"   ⚠️ 그리드 데이터 형식 이상: {type(r)}")
                continue
            print(f"\n   [Grid {r.get('grid_idx', '?')}] id={str(r.get('grid_id', ''))[:30]}...")
            print(f"     셀 수: {r.get('total_cells', 0)}")
            print(f"     행 수: {r.get('total_rows', 0)}")
            print(f"     헤더 수: {r.get('total_headers', 0)}")
            print(f"     컨텍스트: {r.get('context', '')[:50]}")
            if r.get('headers'):
                print(f"     헤더: {r['headers'][:10]}")
            if r.get('data'):
                print(f"     첫 행: {r['data'][0]}")
                if len(r['data']) > 1:
                    print(f"     마지막 행: {r['data'][-1]}")
    
    return extraction_result


def save_result(label: str, save_dir: str, nav_result: dict, extraction_result: dict):
    """모든 결과를 통합해서 저장"""
    timestamp = datetime.now().strftime("%H%M%S")
    safe_label = label.replace(" ", "_").replace("/", "_")
    filepath = os.path.join(save_dir, f"{safe_label}_{timestamp}.json")
    
    full_result = {
        "label": label,
        "timestamp": datetime.now().isoformat(),
        "navigation": nav_result,
        "url": extraction_result.get("url"),
        "visibility_stats": extraction_result.get("visibility_stats", []),
        "extraction_result": extraction_result.get("extraction_result", []),
        "errors": extraction_result.get("errors", []),
    }
    
    try:
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(full_result, f, ensure_ascii=False, indent=2)
        
        if os.path.exists(filepath):
            size = os.path.getsize(filepath)
            print(f"\n💾 저장 성공: {filepath} ({size} bytes)")
            return filepath
        else:
            print(f"\n❌ 저장 후 파일이 존재하지 않음")
            return None
    except Exception as e:
        print(f"\n❌ 저장 실패: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        return None


async def process_menu(browser_session, menu: dict, task_index: int, save_dir: str):
    """하나의 메뉴를 처리"""
    label = menu['label']
    
    # 1. 네비게이션
    nav_result = await navigate_with_agent(
        browser_session,
        menu['navigation_task'],
        label,
        task_index=task_index
    )
    
    print(f"\n[DEBUG] navigate 완료, success={nav_result['success']}")
    
    extraction_result = {
        "label": label,
        "url": None,
        "visibility_stats": [],
        "extraction_result": [],
        "errors": [],
    }
    
    if nav_result["success"]:
        await asyncio.sleep(2)
        
        try:
            cnuit_page = await find_cnuit_page(browser_session)
        except Exception as e:
            print(f"❌ find_cnuit_page 예외: {type(e).__name__}: {e}")
            cnuit_page = None
            extraction_result["errors"].append(f"find_cnuit_page 실패: {e}")
        
        if cnuit_page:
            await safe_bring_to_front(cnuit_page)
            await asyncio.sleep(1)
            
            try:
                extraction_result = await extract_grid_data(cnuit_page, label)
            except Exception as e:
                print(f"❌ extract 예외: {type(e).__name__}: {e}")
                extraction_result["errors"].append(f"extract 예외: {e}")
                import traceback
                traceback.print_exc()
        else:
            print(f"❌ {label} cnuit 탭 없음")
            extraction_result["errors"].append("cnuit 탭 못 찾음")
    else:
        print(f"⚠️ {label} 네비게이션 실패, 추출 건너뜀")
        extraction_result["errors"].append("네비게이션 실패로 추출 건너뜀")
    
    save_result(label, save_dir, nav_result, extraction_result)


async def main():
    print(f"\n{'='*80}")
    print(f"🔍 그리드 추출 검증 스크립트")
    print(f"{'='*80}\n")
    
    save_dir = "./data/grid_extract_test"
    os.makedirs(save_dir, exist_ok=True)
    
    browser_session = BrowserSession(
        browser_profile=BrowserProfile(headless=False),
        keep_alive=True,
    )
    await browser_session.start()
    await auto_login(browser_session)
    
    print(f"\n총 {len(TEST_MENUS)}개 메뉴 자동 검증 시작\n")
    
    for i, menu in enumerate(TEST_MENUS):
        print(f"\n{'#'*80}")
        print(f"# [{i+1}/{len(TEST_MENUS)}] {menu['label']} 시작")
        print(f"{'#'*80}")
        
        try:
            await process_menu(browser_session, menu, i, save_dir)
        except Exception as e:
            print(f"❌ process_menu 최상위 예외: {type(e).__name__}: {e}")
            import traceback
            traceback.print_exc()
            
            save_result(
                menu['label'], 
                save_dir,
                nav_result={"success": False, "error": f"{type(e).__name__}: {e}"},
                extraction_result={"errors": [f"최상위 예외: {e}"]}
            )
        
        print(f"\n[DEBUG] {menu['label']} 완료, 3초 대기 후 다음 메뉴...")
        await asyncio.sleep(3)
    
    print(f"\n{'='*80}")
    print(f"✅ 모든 검증 완료. 결과 폴더: {save_dir}")
    print(f"{'='*80}")
    
    print(f"\n📁 저장된 결과 파일:")
    if os.path.exists(save_dir):
        files = sorted(os.listdir(save_dir))
        for f in files:
            if f.endswith('.json'):
                full_path = os.path.join(save_dir, f)
                size = os.path.getsize(full_path)
                print(f"   - {f} ({size} bytes)")
    
    print("\n결과 확인 후 Enter:")
    await asyncio.get_event_loop().run_in_executor(None, input)
    
    await browser_session.stop()


if __name__ == "__main__":
    asyncio.run(main())