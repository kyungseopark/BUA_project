import json
import os

def create_vision_finetune_set(input_path: str, output_path: str):
    """
    성공한 데이터만 필터링하여 이미지(Vision) 정보를 포함한 
    파인튜닝용 데이터셋(JSONL)을 생성합니다.
    """
    print(f"🚀 Vision 데이터셋 생성 시작: {input_path}")
    results = {"total": 0, "kept": 0, "skipped": 0}

    with open(input_path, "r", encoding="utf-8") as fin, \
         open(output_path, "w", encoding="utf-8") as fout:
        
        for line in fin:
            results["total"] += 1
            try:
                data = json.loads(line)
                
                # 1. 실패한 태스크는 파인튜닝 데이터 오염을 막기 위해 제외
                if not data.get("success", False):
                    results["skipped"] += 1
                    continue
                
                # 2. 메시지 조립 (input 리스트를 그대로 가져와서 이미지 보존)
                messages = []
                for msg in data.get("input", []):
                    # content가 리스트(텍스트+이미지)인 경우를 그대로 유지
                    messages.append({
                        "role": msg["role"],
                        "content": msg["content"]
                    })
                
                # 3. 모델의 응답(Assistant)을 JSON 문자열 형태로 추가
                # 파인튜닝 형식에 따라 dict를 그대로 넣거나 문자열화 할 수 있습니다.
                assistant_response = data.get("output", {})
                messages.append({
                    "role": "assistant", 
                    "content": json.dumps(assistant_response, ensure_ascii=False)
                })
                
                # 4. 최종 JSONL 쓰기
                fout.write(json.dumps({"messages": messages}, ensure_ascii=False) + "\n")
                results["kept"] += 1
                
            except Exception as e:
                print(f"⚠️ 라인 처리 중 오류 발생: {e}")
                results["skipped"] += 1

    print(f"\n✨ 전처리 완료!")
    print(f"- 스캔된 총 데이터: {results['total']}건")
    print(f"- 저장된 성공 데이터(Vision 포함): {results['kept']}건")
    print(f"- 제외된 실패 데이터: {results['skipped']}건")
    print(f"📂 결과 파일: {output_path}")

if __name__ == "__main__":
    # 사용 예시
    input_file = "./data/gemini_1/training_data.jsonl"
    output_file = "./data/gemini_1/ft_vision_train.jsonl"
    
    if os.path.exists(input_file):
        create_vision_finetune_set(input_file, output_file)
    else:
        print(f"❌ 파일을 찾을 수 없습니다: {input_file}")