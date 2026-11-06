"""
实验总入口: 对样本仓库跑 (变体 x 模型 x 重复) 矩阵。Claude Code 版。

用法:
    python -m src.run_experiment --variants v5_refined --repeats 1 --limit 3
    python -m src.run_experiment --variants v5_refined v0_baseline --repeats 3
"""
from __future__ import annotations

import argparse
import json
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
    ap.add_argument("--skip-done", action="store_true",
                    help="结果目录里已有同一 commit 的结果就跳过(中断后续跑用)")
    ap.add_argument("--deadline-hours", type=float, default=None,
                    help="超过这么多小时就不再开始新仓库(正在跑的会跑完)")
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

    t_start = time.time()
    auth_fail_streak = 0
    done = 0
    for _, row in df.iterrows():
        if args.deadline_hours and time.time() - t_start > args.deadline_hours * 3600:
            print(f"\n已到 {args.deadline_hours} 小时,不再开始新仓库。")
            break
        parsed = parse_github_url(row["code_url"])
        if not parsed:
            continue
        owner, repo = parsed
        dest = ROOT / "workdir" / f"{owner}_{repo}"

        commit = row.get("head_commit")
        if isinstance(commit, float):
            commit = None

        # 结果文件名是 <owner>-<repo>-<commit 前 7 位>__<run_id>.json,仓库改名时 owner/repo 会变,所以只按 commit 匹配
        if args.skip_done and commit:
            done_files = [f for v in args.variants
                          for f in (ROOT / "results" / f"{v}__default").glob(f"*-{commit[:7]}__*.json")]
            if done_files:
                print(f"[已有结果,跳过] {owner}/{repo}")
                continue

        info = fetch_repo(owner, repo, commit, dest)
        if info["clone_status"] != "success":
            print(f"[跳过] {owner}/{repo}: {info['clone_status']}")
            # L0(仓库拿不到)也是结果,要记下来
            for variant in args.variants:
                fail_log = ROOT / "results" / f"{variant}__default" / "_clone_failures.jsonl"
                fail_log.parent.mkdir(parents=True, exist_ok=True)
                with open(fail_log, "a", encoding="utf-8") as f:
                    f.write(json.dumps({"paper_id": row.get("paper_id"), "code_url": row["code_url"],
                                        "head_commit": commit, **info}, ensure_ascii=False, default=str) + "\n")
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
                        pj = rec["agent_parsed_json"] or {}
                        v = pj.get("smoke_verdict") or pj.get("repro_verdict") or pj.get("overall_verdict")
                        print(f"    calls={rec['tool_call_count_actual']} "
                              f"denials={len(rec.get('permission_denials') or [])} "
                              f"{rec['elapsed_sec']}s verdict={v}", flush=True)
                        # 登录 token 中途失效(403 / Not logged in)时,后面每个仓库都会秒失败,白白消耗样本
                        blob = f"{rec.get('agent_final_text')} {rec.get('stderr_tail')}"
                        if (rec.get("api_error_status") in (401, 403)
                                or "Not logged in" in blob or "Request not allowed" in blob):
                            auth_fail_streak += 1
                        else:
                            auth_fail_streak = 0
                        if auth_fail_streak >= 2:
                            print("\n连续 2 次登录 / 认证错误,停止。先 `claude -p ok` 检查登录,再加 --skip-done 续跑。")
                            if not args.keep:
                                cleanup(dest)
                            return
                    except Exception as e:
                        print(f"    [失败] {type(e).__name__}: {e}")
                    time.sleep(2)

        if not args.keep:
            cleanup(dest)

    print("\n完成。接下来跑 src.verify 和 src.analyze。")


if __name__ == "__main__":
    main()
