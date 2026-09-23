"""
实验总入口: 对样本仓库跑 (变体 x 模型 x 重复) 矩阵。

用法(先小规模试):
    python -m src.run_experiment --sample data/sample_repos.csv \
        --variants v0_baseline v1_minimal \
        --models anthropic/claude-sonnet-4.5 \
        --repeats 1 --limit 5
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import pandas as pd
import yaml

from .agent_runner import run_one
from .clone import cleanup, fetch_repo, parse_github_url

ROOT = Path(__file__).resolve().parent.parent


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", default=str(ROOT / "data" / "sample_repos.csv"))
    ap.add_argument("--variants", nargs="+", default=["v0_baseline"])
    ap.add_argument("--models", nargs="+", default=["anthropic/claude-sonnet-4.5"])
    ap.add_argument("--repeats", type=int, default=1)
    ap.add_argument("--limit", type=int, default=None, help="只跑前 N 个仓库")
    args = ap.parse_args()

    cfg = yaml.safe_load((ROOT / "config" / "experiment.yaml").read_text())
    df = pd.read_csv(args.sample)
    df = df[df["clone_status"] == "success"] if "clone_status" in df.columns else df
    if args.limit:
        df = df.head(args.limit)

    total = len(df) * len(args.variants) * len(args.models) * args.repeats
    print(f"计划运行 {total} 次 ({len(df)} 仓库 x {len(args.variants)} 变体 "
          f"x {len(args.models)} 模型 x {args.repeats} 次重复)\n")

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
            for model in args.models:
                for r in range(args.repeats):
                    done += 1
                    print(f"[{done}/{total}] {repo} | {variant} | {model} | run {r+1}")
                    try:
                        rec = run_one(repo_path, variant, model, cfg)
                        print(f"    tokens={rec['tokens']['total']} "
                              f"calls={rec['tool_call_count_actual']} "
                              f"blocked_writes={len(rec['blocked_write_attempts_actual'])} "
                              f"verdict={(rec['agent_parsed_json'] or {}).get('overall_verdict')}")
                    except Exception as e:
                        print(f"    [失败] {e}")
                    time.sleep(1)

        cleanup(dest)  # 测完即删,不囤积

    print("\n完成。跑 python -m src.analyze 看汇总。")


if __name__ == "__main__":
    main()
