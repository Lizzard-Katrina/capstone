"""
汇总: 比较不同 prompt 变体 / 模型的判定质量。

已去掉 token 统计(订阅制下不关心),改为关注:
- verdict 分布与一致性
- 核验通过率(agent 有没有谎报)
- 约束违反率
- 变体之间的分歧(这些仓库值得人工核实)

用法:
    python -m src.analyze
    python -m src.analyze --gold data/gold_labels.csv
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent


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
            issue_types = [i["type"] for i in v.get("issues", [])]
            rows.append({
                "variant": rec.get("variant"),
                "model": rec.get("model"),
                "repo": rec.get("repo"),
                "run_id": rec.get("run_id"),
                "verdict": parsed.get("overall_verdict"),
                "parsed_ok": bool(parsed),
                "tool_calls": rec.get("tool_call_count_actual"),
                "elapsed_sec": rec.get("elapsed_sec"),
                "returncode": rec.get("returncode"),
                "n_issues": v.get("n_issues"),
                "trustworthy": v.get("trustworthy"),
                "tried_to_write": any(
                    t in issue_types
                    for t in ("blocked_write_attempt", "shell_write_attempt")),
                "extra_install": "extra_package_install" in issue_types,
                "bad_entry_script": "non_python_entry_script" in issue_types,
                "install_status": (parsed.get("install") or {}).get("status"),
                "n_entry_scripts": len(parsed.get("entry_scripts") or []),
            })
    return pd.DataFrame(rows)


def summarize(df: pd.DataFrame, gold: pd.DataFrame | None) -> pd.DataFrame:
    if gold is not None and not gold.empty:
        df = df.merge(gold[["repo", "gold_verdict"]], on="repo", how="left")
        df["correct"] = df["verdict"] == df["gold_verdict"]
    else:
        df["correct"] = pd.NA

    g = df.groupby(["variant", "model"])
    return pd.DataFrame({
        "n_runs": g.size(),
        "parsed_ok_rate": g["parsed_ok"].mean().round(3),
        "trustworthy_rate": g["trustworthy"].mean().round(3),
        "tried_to_write_rate": g["tried_to_write"].mean().round(3),
        "extra_install_rate": g["extra_install"].mean().round(3),
        "bad_entry_rate": g["bad_entry_script"].mean().round(3),
        "tool_calls_mean": g["tool_calls"].mean().round(1),
        "elapsed_mean": g["elapsed_sec"].mean().round(1),
        "accuracy": g["correct"].mean().round(3),
    }).reset_index()


def stability(df: pd.DataFrame) -> pd.DataFrame:
    """同一 (变体,模型,仓库) 重复跑的结论一致性。"""
    rows = []
    for key, sub in df.groupby(["variant", "model", "repo"]):
        if len(sub) < 2:
            continue
        rows.append({
            "variant": key[0], "model": key[1], "repo": key[2],
            "n": len(sub),
            "verdict_consistent": sub["verdict"].nunique() == 1,
        })
    if not rows:
        return pd.DataFrame()
    s = pd.DataFrame(rows)
    return s.groupby(["variant", "model"]).agg(
        repos_with_repeats=("repo", "count"),
        verdict_consistency=("verdict_consistent", "mean"),
    ).round(3).reset_index()


def disagreements(df: pd.DataFrame) -> pd.DataFrame:
    """不同变体对同一仓库给出不同结论 —— 这些值得人工核实。"""
    rows = []
    for repo, sub in df.groupby("repo"):
        verdicts = sub["verdict"].dropna().unique()
        if len(verdicts) > 1:
            detail = sub.groupby("variant")["verdict"].apply(
                lambda s: "/".join(sorted(set(s.dropna())))
            ).to_dict()
            rows.append({"repo": repo, "verdicts": list(verdicts),
                         "by_variant": detail})
    return pd.DataFrame(rows)


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
        print(f"[提示] 没有 {gold_path},accuracy 一列为空\n")

    print("=" * 70)
    print("按 (变体 x 模型) 汇总")
    print("=" * 70)
    print(summarize(df, gold).to_string(index=False))

    print("\n" + "=" * 70)
    print("结论稳定性(重复跑)")
    print("=" * 70)
    st = stability(df)
    print(st.to_string(index=False) if not st.empty else "(没有重复运行)")

    print("\n" + "=" * 70)
    print("变体之间有分歧的仓库(优先人工核实这些)")
    print("=" * 70)
    dis = disagreements(df)
    if dis.empty:
        print("(没有分歧,或样本太少)")
    else:
        for _, r in dis.iterrows():
            print(f"  {r['repo']}: {r['by_variant']}")

    out_dir = Path(args.results)
    df.to_csv(out_dir / "_raw.csv", index=False)
    summarize(df, gold).to_csv(out_dir / "_summary.csv", index=False)
    print(f"\n写入 {out_dir / '_summary.csv'} 和 _raw.csv")


if __name__ == "__main__":
    main()
