# test_rag.py
from rag.retriever import retriever

query = "휴학할 때 유의해야 하는 점 있어?"
results = retriever.search(query)

for r in results:
    print(f"[유사도: {r['score']:.2f}] {r['chunk']['question']}")
    print(r['chunk']['answer'])
    print()