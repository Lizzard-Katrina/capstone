"""
汇总: 把所有 (变体 x 模型) 的结果拉到一张表,算 token、准确率、违规率、稳定性。

用法:
    python -m src.analyze --results results/ --gold data/gold_labels.csv
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent

# 6000 个仓库全量外推用
FULL_SCALE = 6000


def collect(results_dir: Path) -> pd.DataFrame:
    rows = []
    for sub in sorted(results_dir.iterdir()):
        if not sub.is_dir():
            continue
        verif = {}
        vf = sub / "_verification.json"
        if vf.exists():
            for r in json.loads(vf.read_text(encoding="utf-8")):
                verif[r["run_id"]] = r

        for f in sorted(sub.glob("*.json")):
            if f.name.startswith("_"):
                continue
            rec = json.loads(f.read_text(encoding="utf-8"))
            parsed = rec.get("agent_parsed_json") or {}
            v = verif.get(rec.get("run_id"), {})
            rows.append({
                "variant": rec.get("variant"),
                "model": rec.get("model"),
                "repo": rec.get("repo"),
                "run_id": rec.get("run_id"),
                "tok_in": rec["tokens"]["input"],
                "tok_out": rec["tokens"]["output"],
                "tok_total": rec["tokens"]["total"],
                "tool_calls": rec.get("tool_call_count_actual"),
                "hit_limit": rec.get("hit_iteration_limit_actual"),
                "elapsed_sec": rec.get("elapsed_sec"),
                "blocked_writes": len(rec.get("blocked_write_attempts_actual") or []),
                "verdict": parsed.get("overall_verdict"),
                "parsed_ok": bool(parsed),
                "n_issues": v.get("n_issues"),
                "trustworthy": v.get("trustworthy"),
            })
    return pd.DataFrame(rows)


def summarize(df: pd.DataFrame, gold: pd.DataFrame | None) -> pd.DataFrame:
    """每个 (变体, 模型) 一行。"""
    if gold is not None and not gold.empty:
        df = df.merge(gold[["repo", "gold_verdict"]], on="repo", how="left")
        df["correct"] = df["verdict"] == df["gold_verdict"]
    else:
        df["correct"] = pd.NA

    g = df.groupby(["variant", "model"])
    out = pd.DataFrame({
        "n_runs": g.size(),
        "tok_total_mean": g["tok_total"].mean().round(0),
        "tok_total_median": g["tok_total"].median().round(0),
        "tok_total_p90": g["tok_total"].quantile(0.9).round(0),
        "tool_calls_mean": g["tool_calls"].mean().round(1),
        "hit_limit_rate": g["hit_limit"].mean().round(3),
        "elapsed_mean": g["elapsed_sec"].mean().round(1),
        "parsed_ok_rate": g["parsed_ok"].mean().round(3),
        "trustworthy_rate": g["trustworthy"].mean().round(3),
        "blocked_write_rate": (g["blocked_writes"].apply(lambda s: (s > 0).mean())).round(3),
        "accuracy": g["correct"].mean().round(3),
    }).reset_index()

    # 外推全量成本(token 数,不含单价;单价按你选的模型另算)
    out["tok_full_scale_est"] = (out["tok_total_mean"] * FULL_SCALE).astype("Int64")
    return out


def stability(df: pd.DataFrame) -> pd.DataFrame:
    """同一 (变体,模型,仓库) 重复跑的一致性。"""
    g = df.groupby(["variant", "model", "repo"])
    rows = []
    for key, sub in g:
        if len(sub) < 2:
            continue
        rows.append({
            "variant": key[0], "model": key[1], "repo": key[2],
            "n": len(sub),
            "verdict_consistent": sub["verdict"].nunique() == 1,
            "tok_cv": round(sub["tok_total"].std() / max(sub["tok_total"].mean(), 1), 3),
        })
    if not rows:
        return pd.DataFrame()
    s = pd.DataFrame(rows)
    return s.groupby(["variant", "model"]).agg(
        repos_with_repeats=("repo", "count"),
        verdict_consistency=("verdict_consistent", "mean"),
        token_cv_mean=("tok_cv", "mean"),
    ).round(3).reset_index()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", default=str(ROOT / "results"))
    ap.add_argument("--gold", default=str(ROOT / "data" / "gold_labels.csv"))
    args = ap.parse_args()

    df = collect(Path(args.results))
    if df.empty:
        print("results/ 下没有找到结果")
        return

    gold_path = Path(args.gold)
    gold = pd.read_csv(gold_path) if gold_path.exists() else None
    if gold is None:
        print(f"[提示] 没有找到 {gold_path},准确率一列会是空的\n")

    print("=" * 70)
    print("按 (变体 x 模型) 汇总")
    print("=" * 70)
    summ = summarize(df, gold)
    print(summ.to_string(index=False))

    print("\n" + "=" * 70)
    print("稳定性(重复跑的一致性)")
    print("=" * 70)
    st = stability(df)
    print(st.to_string(index=False) if not st.empty else "(没有重复运行的数据)")

    out_dir = Path(args.results)
    summ.to_csv(out_dir / "_summary.csv", index=False)
    df.to_csv(out_dir / "_raw.csv", index=False)
    print(f"\n写入 {out_dir / '_summary.csv'} 和 _raw.csv")


if __name__ == "__main__":
    main()
