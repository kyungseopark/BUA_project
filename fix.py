import json

def fix_deep_success_mismatch(input_path: str, output_path: str):
    results = {"total": 0, "fixed": 0, "error_skipped": 0}
    
    with open(input_path, "r", encoding="utf-8") as fin, \
         open(output_path, "w", encoding="utf-8") as fout:
        
        for line_num, line in enumerate(fin, 1):
            results["total"] += 1
            
            try:
                data = json.loads(line)
            except json.JSONDecodeError as e:
                fout.write(line)
                results["error_skipped"] += 1
                continue
            
            # 1. 최상단 success 값 확보
            top_level_success = data.get("success")
            
            if top_level_success is not None and "messages" in data:
                if len(data["messages"]) > 0 and data["messages"][-1]["role"] == "assistant":
                    assistant_msg = data["messages"][-1]
                    
                    try:
                        content_json = json.loads(assistant_msg["content"])
                        is_fixed = False
                        
                        # 2. 🚨 핵심 수정: action 배열을 순회하며 done 객체를 찾음
                        if "action" in content_json and isinstance(content_json["action"], list):
                            for action_item in content_json["action"]:
                                if "done" in action_item and isinstance(action_item["done"], dict):
                                    # done 안의 success 값이 최상단 값과 다르면 덮어쓰기
                                    if action_item["done"].get("success") != top_level_success:
                                        action_item["done"]["success"] = top_level_success
                                        is_fixed = True
                        
                        # 3. 수정이 발생했다면 다시 문자열로 덮어쓰기
                        if is_fixed:
                            assistant_msg["content"] = json.dumps(content_json, ensure_ascii=False)
                            results["fixed"] += 1
                            
                    except json.JSONDecodeError:
                        pass
            
            fout.write(json.dumps(data, ensure_ascii=False) + "\n")
            
    print(f"✅ 작업 완료: 총 {results['total']}줄 확인.")
    print(f"   - action -> done 내부 success 동기화 완료: {results['fixed']}건")
    print(f"   - 문법 깨짐으로 건너뜀: {results['error_skipped']}건")

if __name__ == "__main__":
    fix_deep_success_mismatch(
        "./data/browser_use/review_data.jsonl", 
        "./data/browser_use/review_data_fixed.jsonl"
    )