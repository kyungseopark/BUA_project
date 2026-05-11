"""
RAG 검색 엔진 (Retriever)

collect.py의 run_task()에서 호출됨:
    rag_context = retriever.get_context(task)
    full_task = f"{rag_context}{BASE_CONTEXT}{task}"
"""

import os
import pickle
import json
import numpy as np
import faiss
from sentence_transformers import SentenceTransformer
from typing import Optional

INDEX_DIR = os.path.join(os.path.dirname(__file__), "index")

# 유사도 임계값: 이 값 이상일 때만 RAG 결과를 사용
# 왜 0.55인가: 너무 낮으면 관련없는 청크가 주입됨, 너무 높으면 아무것도 못 찾음
# cosine similarity 기준 0.55~0.65가 한국어 FAQ에서 실험적으로 적절한 범위
SIMILARITY_THRESHOLD = 0.55

# 최대 검색 청크 수: 너무 많으면 LLM 컨텍스트 낭비, 너무 적으면 정보 부족
TOP_K = 3


class CnuRAGRetriever:
    def __init__(self):
        self._model: Optional[SentenceTransformer] = None
        self._index = None
        self._chunks = None
        self._loaded = False

    def _lazy_load(self):
        """
        처음 검색할 때만 모델/인덱스를 로드 (lazy loading)
        왜: collect.py 시작 시 매번 모델 로드하면 부팅 시간 증가
        """
        if self._loaded:
            return

        index_path = os.path.join(INDEX_DIR, "faiss.index")
        chunks_path = os.path.join(INDEX_DIR, "chunks.pkl")
        meta_path = os.path.join(INDEX_DIR, "meta.json")

        if not os.path.exists(index_path):
            raise FileNotFoundError(
                "[RAG] ❌ 인덱스가 없습니다. 먼저 아래 명령어를 실행하세요:\n"
                "  python rag/knowledge_base.py"
            )

        with open(meta_path, "r", encoding="utf-8") as f:
            meta = json.load(f)

        print(f"[RAG] 모델 로딩: {meta['model_name']}")
        self._model = SentenceTransformer(meta["model_name"])
        self._index = faiss.read_index(index_path)

        with open(chunks_path, "rb") as f:
            self._chunks = pickle.load(f)

        self._loaded = True
        print(f"[RAG] ✅ {meta['num_chunks']}개 청크 인덱스 로드 완료")

    def search(self, query: str, top_k: int = TOP_K) -> list[dict]:
        """
        쿼리와 유사한 청크를 검색하여 반환

        반환값: [{"chunk": {...}, "score": 0.82}, ...]
        """
        self._lazy_load()

        # 쿼리 임베딩 → L2 정규화
        query_vec = self._model.encode([query], convert_to_numpy=True)
        faiss.normalize_L2(query_vec)

        scores, indices = self._index.search(query_vec, top_k)

        results = []
        for score, idx in zip(scores[0], indices[0]):
            if idx == -1:
                continue
            if score < SIMILARITY_THRESHOLD:
                # 임계값 미만 → 관련 없는 청크 → 제외
                continue
            results.append({
                "chunk": self._chunks[idx],
                "score": float(score)
            })

        return results

    def get_context(self, task: str) -> str:
        """
        collect.py의 full_task 앞에 붙일 RAG 컨텍스트 문자열 생성

        사용법:
            rag_context = retriever.get_context(task)
            full_task = f"{rag_context}{BASE_CONTEXT}{task}"
        """
        results = self.search(task)

        if not results:
            # 관련 정보 없음 → 컨텍스트 없이 그냥 진행
            return ""

        lines = [
            "=== 아래는 통합정보시스템 관련 사전 지식입니다. 이 내용을 참고하여 작업을 수행하세요 ===\n"
        ]

        for i, r in enumerate(results, 1):
            chunk = r["chunk"]
            lines.append(f"[참고 {i}] {chunk['question']}")
            lines.append(chunk["answer"])
            lines.append("")

        lines.append("=== 사전 지식 끝 ===\n\n")
        return "\n".join(lines)

    def answer_directly(self, query: str) -> Optional[str]:
        """
        RAG만으로 충분히 답변 가능한 경우 직접 답변 반환
        브라우저 자동화 없이 즉시 응답 가능한 경우에 사용

        score가 0.80 이상이면 브라우저 탐색 없이 바로 답변 가능하다고 판단
        """
        results = self.search(query, top_k=1)

        if not results:
            return None

        best = results[0]
        if best["score"] >= 0.80:
            chunk = best["chunk"]
            return (
                f"[RAG 직접 답변 - 브라우저 탐색 불필요]\n\n"
                f"**{chunk['question']}**\n\n"
                f"{chunk['answer']}"
            )

        return None


# 싱글톤 인스턴스 (모듈 임포트 시 한 번만 생성)
retriever = CnuRAGRetriever()