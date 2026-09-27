"""
实验总入口: 对样本仓库跑 (变体 x 模型 x 重复) 矩阵。Claude Code 版。

用法:
    python -m src.run_experiment --variants v5_refined --repeats 1 --limit 3
    python -m src.run_experiment --variants v5_refined v0_baseline --repeats 3
"""
from __future__ import annotations

import argparse
import time
from pathlib import Path

import pandas as pd
import yaml

from .cc_runner import run_one
from .clone import cleanup, fetch_repo, parse_github_url

ROOT = Path(__file__).resolve().parent.parent


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", default=str(ROOT / "data" / "sample_repos.csv"))
    ap.add_argument("--variants", nargs="+", default=["v5_refined"])
    ap.add_argument("--models", nargs="+", default=[None],
                    help="留空用默认模型;也可给 sonnet opus")
    ap.add_argument("--repeats", type=int, default=1)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--keep", action="store_true", help="跑完不删仓库")
    args = ap.parse_args()

    cfg = yaml.safe_load((ROOT / "config" / "experiment.yaml").read_text())
    df = pd.read_csv(args.sample)
    if "clone_status" in df.columns:
        df = df[df["clone_status"] == "success"]
    if args.limit:
        df = df.head(args.limit)

    models = [None if m in ("none", "default", None) else m for m in args.models]
    total = len(df) * len(args.variants) * len(models) * args.repeats
    print(f"计划运行 {total} 次 ({len(df)} 仓库 x {len(args.variants)} 变体 "
          f"x {len(models)} 模型 x {args.repeats} 次重复)\n")

    done = 0
    for _, row in df.iterrows():
        parsed = parse_github_url(row["code_url"])
        if not parsed:
            continue
        owner, repo = parsed
        dest = ROOT / "workdir" / f"{owner}_{repo}"

        commit = row.get("head_commit")
        if isinstance(commit, float):
            commit = None
        info = fetch_repo(owner, repo, commit, dest)
        if info["clone_status"] != "success":
            print(f"[跳过] {owner}/{repo}: {info['clone_status']}")
            continue

        repo_path = Path(info["path"])
        for variant in args.variants:
            for model in models:
                for r in range(args.repeats):
                    done += 1
                    mtag = model or "default"
                    print(f"[{done}/{total}] {repo} | {variant} | {mtag} | run {r+1}")
                    try:
                        rec = run_one(repo_path, variant, cfg, model=model, paper_url=row.get("paper_url"))
                        v = (rec["agent_parsed_json"] or {}).get("overall_verdict")
                        print(f"    calls={rec['tool_call_count_actual']} "
                              f"denials={len(rec.get('permission_denials') or [])} "
                              f"{rec['elapsed_sec']}s verdict={v}")
                    except Exception as e:
                        print(f"    [失败] {type(e).__name__}: {e}")
                    time.sleep(2)

        if not args.keep:
            cleanup(dest)

    print("\n完成。接下来跑 src.verify 和 src.analyze。")


if __name__ == "__main__":
    main()
