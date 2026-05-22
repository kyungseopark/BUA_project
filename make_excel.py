"""
make_excel.py — 사이트별 results 폴더의 JSON을 합쳐 Excel로 저장

사용법:
  python make_excel.py                  # data/ 하위 전체 사이트 자동 탐색
  python make_excel.py --sites dept cyber cnuit   # 특정 사이트만
  python make_excel.py --out results.xlsx         # 출력 파일명 지정
"""

import argparse
import json
from pathlib import Path

try:
    import pandas as pd
except ImportError:
    raise SystemExit("pandas가 없습니다. `pip install pandas openpyxl` 로 설치하세요.")

DATA_DIR = Path(__file__).parent / "data"
SITES = ["dept", "cnuwith", "library", "cnuit", "cyber", "approval"]


def load_site(site_id: str) -> list[dict]:
    base = DATA_DIR / site_id / "results"
    for name in ("final_results.json", "progress_latest.json"):
        path = base / name
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(data, list) and data:
                    return data
            except (json.JSONDecodeError, ValueError):
                continue
    return []


def build_df(sites: list[str]) -> pd.DataFrame:
    rows = []
    for site_id in sites:
        records = load_site(site_id)
        if not records:
            print(f"  [skip] {site_id}: results 없음")
            continue
        print(f"  [ok]   {site_id}: {len(records)}개 태스크")
        rows.extend(records)

    if not rows:
        raise SystemExit("데이터가 없습니다.")

    df = pd.DataFrame(rows)

    col_order = ["site_id", "task_index", "task", "success", "steps", "elapsed_sec", "final_answer"]
    existing = [c for c in col_order if c in df.columns]
    extra = [c for c in df.columns if c not in col_order]
    df = df[existing + extra]

    df = df.sort_values(["site_id", "task_index"]).reset_index(drop=True)
    return df


def save_excel(df: pd.DataFrame, out_path: Path):
    with pd.ExcelWriter(out_path, engine="openpyxl") as writer:
        # 전체 시트
        df.to_excel(writer, sheet_name="전체", index=False)
        _autofit(writer.sheets["전체"], df)

        # 사이트별 시트
        for site_id, group in df.groupby("site_id", sort=False):
            group = group.reset_index(drop=True)
            group.to_excel(writer, sheet_name=str(site_id), index=False)
            _autofit(writer.sheets[str(site_id)], group)

        # 요약 시트
        summary = (
            df.groupby("site_id")
            .agg(
                태스크수=("task_index", "count"),
                성공수=("success", "sum"),
                성공률=("success", lambda x: f"{x.mean()*100:.1f}%"),
                평균스텝=("steps", lambda x: round(x.mean(), 1)),
                평균시간_sec=("elapsed_sec", lambda x: round(x.mean(), 1)),
            )
            .reset_index()
        )
        summary.to_excel(writer, sheet_name="요약", index=False)
        _autofit(writer.sheets["요약"], summary)

    print(f"\n저장 완료: {out_path}")


def _autofit(ws, df: pd.DataFrame, max_width: int = 60):
    for i, col in enumerate(df.columns, start=1):
        col_len = max(
            len(str(col)),
            df[col].astype(str).str.len().max() if len(df) > 0 else 0,
        )
        ws.column_dimensions[ws.cell(1, i).column_letter].width = min(col_len + 2, max_width)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--sites", nargs="+", default=None)
    parser.add_argument("--out", default="results_combined.xlsx")
    args = parser.parse_args()

    sites = args.sites or SITES
    out_path = Path(args.out)
    if not out_path.is_absolute():
        out_path = Path(__file__).parent / out_path

    print(f"대상 사이트: {sites}")
    df = build_df(sites)
    save_excel(df, out_path)

    # 간단한 통계 출력
    total = len(df)
    success = df["success"].sum()
    print(f"전체: {success}/{total} 성공 ({success/total*100:.1f}%)")


if __name__ == "__main__":
    main()
