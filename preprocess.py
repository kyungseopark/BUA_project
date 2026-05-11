# preprocess.py
import json

def preprocess(input_path: str, output_path: str, success_only: bool = False):
    """1단계: 이미지 + 시스템 프롬프트 제거, 메타데이터 유지"""
    
    results = {"total": 0, "kept": 0, "skipped_fail": 0}
    
    with open(input_path, "r", encoding="utf-8") as fin, \
         open(output_path, "w", encoding="utf-8") as fout:
        
        for line in fin:
            results["total"] += 1
            data = json.loads(line)
            
            if success_only and not data.get("success", True):
                results["skipped_fail"] += 1
                continue
            
            messages = []
            for msg in data["input"]:
                role = msg["role"]
                content = msg.get("content", "")

                # 시스템 프롬프트 제거 ← 리뷰할 때 필요 없음
                if role == "system":
                    continue
                
                # 이미지 제거, 텍스트만 추출
                if isinstance(content, list):
                    text_parts = []
                    for part in content:
                        if isinstance(part, dict):
                            if part.get("type") == "text":
                                text_parts.append(part["text"])
                        elif isinstance(part, str):
                            text_parts.append(part)
                    content = "\n".join(text_parts)
                
                if not content.strip():
                    continue
                    
                messages.append({"role": role, "content": content})
            
            # output → assistant 응답
            output = data["output"]
            assistant_content = json.dumps(output, ensure_ascii=False)
            messages.append({"role": "assistant", "content": assistant_content})
            
            fout.write(json.dumps({
                "task_index": data.get("task_index"),
                "step_number": data.get("step_number"),
                "step_time_seconds": data.get("step_time_seconds"),
                "success": data.get("success"),
                "is_meaningful": data.get("is_meaningful"),
                "messages": messages
            }, ensure_ascii=False) + "\n")
            results["kept"] += 1
    
    print(f"전처리 완료: {results['total']}건 → {results['kept']}건")
    return results

def filter_for_finetune_fast(review_path: str, original_path: str, output_path: str):
    print("1. 공통 시스템 프롬프트 추출 중...")
    system_content = ""
    
    # 원본 파일에서 첫 번째 시스템 프롬프트 딱 한 번만 가져오기
    with open(original_path, "r", encoding="utf-8") as f:
        for line in f:
            data = json.loads(line)
            for msg in data.get("input", []):
                if msg["role"] == "system":
                    content = msg.get("content", "")
                    if isinstance(content, list):
                        text_parts = [p["text"] for p in content if isinstance(p, dict) and p.get("type") == "text"]
                        content = "\n".join(text_parts)
                    system_content = content
                    break
            if system_content:
                break # 하나 찾았으면 반복문 즉시 종료

    print(f"✅ 공통 시스템 프롬프트 추출 완료 (길이: {len(system_content)}자)")

    print("\n2. 성공(Success) 데이터 필터링 및 조립 중...")
    results = {"total": 0, "kept": 0, "skipped": 0}

    with open(review_path, "r", encoding="utf-8") as fin, \
         open(output_path, "w", encoding="utf-8") as fout:
        
        for line in fin:
            results["total"] += 1
            data = json.loads(line)
            
            # success가 True가 아니면 가차없이 버림
            if data.get("success") != True:
                results["skipped"] += 1
                continue

            # 시스템 프롬프트 도장 찍기 + 나머지 대화 이어붙이기
            final_messages = [{"role": "system", "content": system_content}]
            final_messages.extend(data["messages"])

            fout.write(json.dumps({"messages": final_messages}, ensure_ascii=False) + "\n")
            results["kept"] += 1
    
    print(f"🚀 V1.0 데이터셋 완성: 총 {results['total']}건 스캔 -> {results['kept']}건 저장 (실패/건너뜀: {results['skipped']}건)")

if __name__ == "__main__":
    # 1단계: 리뷰용 데이터 생성
    preprocess("./data/gemini_1/training_data.jsonl", "./data/gemini_1/review_data.jsonl", success_only=False)
    
    # 3단계: is_meaningful 태그 입력 후 실행
    # filter_for_finetune_fast(
    #     "./data/browser_use/review_data_fixed.jsonl",
    #     "./data/browser_use/training_data.jsonl",  # 원본 (시스템 프롬프트 가져올 곳)
    #     "./data/browser_use/ft_train.jsonl"
    # )