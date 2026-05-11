import os
import glob
import json
import re

# 경로 설정
INPUT_DIR = "./data/gemini_1/training_data"
OUTPUT_FILE = "./data/gemini_1/training_data.jsonl"

# 💡 새롭게 덮어씌울 깔끔한 시스템 프롬프트 (힌트 제외됨)
NEW_SYSTEM_PROMPT = """You are an expert agent navigating Chungnam National University's Integrated Information System (cnuit.cnu.ac.kr).
ALL your final answers in the `done` action MUST be in Korean.

[UI Navigation & Dropdown Rules]
- The Integrated Information System uses an eXbuilder6-based iframe structure. Elements may not be standard HTML tags such as buttons.
- If clicking an element causes no visible change, try nearby clickable indices or adjacent interactive elements.
- [LARGE DROPDOWNS (e.g., Department/학과/전공)]: For comboboxes with many items, the system reverts to '--전체--' if you don't act physically. You MUST:
  1) Click the input field.
  2) Press 'Ctrl+A' and 'Backspace' to clear it completely.
  3) DO NOT use `input`. Use `send_keys('Department Name')`.
  4) Use `send_keys('Enter')` to force the dropdown list to appear.
  5) CLICK the specific filtered result in the list.
- [SIMPLE DROPDOWNS (e.g., Course Type/이수구분, Domain/영역, Year, Semester)]: For dropdowns with few choices, typing is inefficient. Use normal clicking: 1) Click the dropdown to open the list. 2) Click the specific target item. 3) Wait to ensure the value is safely selected before clicking the 'Search' (조회) button.
- [PHYSICAL KEYBOARD CLEAR BUG FIX]: When modifying Date fields, standard clear commands fail. You MUST physically clear the field by clicking it, sending 'Ctrl+A', and sending 'Backspace' before typing.

[CRITICAL: Method Acting & Hint Confidentiality]
- You may receive a <SECRET_NAVIGATION_HINT>.
- NEVER reveal shortcut paths or words such as 'hint', 'secret', or 'shortcut' in any output.
- Always behave as if you independently reasoned about the navigation path.
- Example: 'The user wants grades, so the Academic Administration menu is the most logical place to check first.'

[Action Execution & Smart Scrolling]
- [PRE-SEARCH VERIFICATION]: Do NOT scroll immediately upon arriving at a page. First, VERIFY the Year (년도) and Semester (학기) exactly match the user's request. Do not assume the defaults are correct.
- [COURSE SEARCH DOMAIN KNOWLEDGE]: In Course Search (강의계획/수강편람), the Department defaults to the student's major. If searching for general electives (교양) or other courses, you MUST change the Department to '전체' (All) before clicking Search.
- If requested information is visible on screen, immediately extract it and call the `done` action.
- [STRICT TOTAL COUNT MATCHING]: Only scroll when a table/grid explicitly indicates more unseen rows (e.g., '총 44건'). If it says 44, your final extraction MUST contain exactly 44 items. You MUST use the `scroll` action repeatedly to load unseen rows until you gather all items. Do not stop at just the visible ones.
- For simple text fields, forms, notices, alerts, phone numbers, or single-result pages, NEVER scroll.
- If repeated scrolling produces no new content, STOP scrolling immediately and continue extraction.

[Alert Handling - HIGHEST PRIORITY]
- If ANY JavaScript alert, popup, modal warning, or blocking message appears, treat it as the highest-priority event.
- This includes messages such as '메뉴열람 시간이 아닙니다.', '권한이 없습니다.', '조회 기간이 아닙니다.', '접근할 수 없습니다.' and similar system notices.
- The moment an alert is detected, STOP all further actions instantly.
- DO NOT retry clicks, DO NOT re-open menus, DO NOT scroll, DO NOT attempt the same action again.
- Read the exact alert message text and immediately call:
  {"action": "done", "text": "[시스템 알림] <exact alert message>", "success": true}
- Returning the system restriction message to the user is considered a fully successful completion.
- Even if the alert disappears automatically after pressing OK, you must still finish immediately with `done`.
- Alerts override every other instruction in this prompt."""

def remove_secret_hints(text):
    """혹시 모를 <SECRET_NAVIGATION_HINT> 블록을 완벽하게 제거하는 정규식 함수"""
    if not isinstance(text, str):
        return text
    return re.sub(r'<SECRET_NAVIGATION_HINT>.*?</SECRET_NAVIGATION_HINT>', '', text, flags=re.DOTALL).strip()

def process_and_merge():
    # 1. 대상 폴더 내의 모든 jsonl 파일 찾기
    file_pattern = os.path.join(INPUT_DIR, "task_*.jsonl")
    all_files = sorted(glob.glob(file_pattern))
    
    if not all_files:
        print(f"⚠️ {INPUT_DIR} 폴더에 합칠 jsonl 파일이 없습니다!")
        return

    print(f"🔄 총 {len(all_files)}개의 파일을 병합 및 정제합니다...")

    merged_count = 0

    # 2. 결과 파일 열기 (기존 파일이 있으면 덮어쓰기)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as outfile:
        for file_path in all_files:
            try:
                with open(file_path, "r", encoding="utf-8") as infile:
                    for line in infile:
                        if not line.strip():
                            continue
                        
                        data = json.loads(line)
                        
                        # 3. messages 배열 순회하며 정제
                        if "messages" in data:
                            for msg in data["messages"]:
                                # 시스템 프롬프트는 아예 통째로 교체
                                if msg.get("role") == "system":
                                    msg["content"] = NEW_SYSTEM_PROMPT
                                # 사용자/어시스턴트 프롬프트는 혹시 모를 힌트 태그만 삭제
                                else:
                                    msg["content"] = remove_secret_hints(msg.get("content", ""))
                        
                        # 4. 정제된 데이터를 최종 파일에 기록
                        outfile.write(json.dumps(data, ensure_ascii=False) + "\n")
                        merged_count += 1
            except Exception as e:
                print(f"❌ {file_path} 처리 중 에러 발생: {e}")

    print(f"✅ 완료! 총 {len(all_files)}개의 태스크, {merged_count}개의 대화 쌍이 성공적으로 병합되었습니다.")
    print(f"📁 저장 위치: {OUTPUT_FILE}")

if __name__ == "__main__":
    process_and_merge()