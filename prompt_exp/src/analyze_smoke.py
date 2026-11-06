"""
汇总 smoke test 结果(v12_smoke_docker / v13_smoke_repro 的 smoke_verdict 输出)。

src/analyze.py 是给 v5 的 prompt 对比用的,只认 overall_verdict;这个脚本按 L0-L6 漏斗汇总。

输出:
- 每层的数量、比例和 95% Wilson 置信区间
- smoke_verdict 和 attribution 的分布
- 限时复现的结果(v13)
- 每个仓库的耗时、轮数、token、等价 API 价(token 从 logs/*.jsonl 的 result 事件取)
- 逐仓库明细写到 <结果目录>/_summary_repos.csv

用法:
    python -m src.analyze_smoke --variant v13_smoke_repro
    python -m src.analyze_smoke --variant v13_smoke_repro --sample data/sample_v13_random60.csv
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent

LAYER = {
    "blocked_code_unreleased": "L0",
    "blocked_dead_api": "L1", "blocked_restricted_api": "L1", "blocked_api_key": "L1",
    "blocked_image": "L2", "blocked_deps_removed": "L2", "blocked_deps_conflict": "L2",
    "blocked_data_licensed": "L3", "blocked_data_link_dead": "L3", "blocked_data_manual": "L3",
    "blocked_code": "L4",
    "blocked_hardware": "L5",
    "smoke_timeout": "L6",
    "smoke_passed": "passed", "smoke_passed_toy": "passed", "smoke_passed_with_entry": "passed",
}
LAYER_ORDER = ["L0", "L1", "L2", "L3", "L4", "L5", "L6", "passed", "unknown"]


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (float("nan"), float("nan"))
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, c - h), min(1.0, c + h))


def md(df: pd.DataFrame, index: bool = True) -> str:
    """不依赖 tabulate 的 markdown 表格。"""
    if index:
        df = df.reset_index()
    cols = [str(c) for c in df.columns]
    lines = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    for row in df.itertuples(index=False):
        lines.append("| " + " | ".join("" if pd.isna(v) else str(v) for v in row) + " |")
    return "\n".join(lines)


def log_stats(log_path: str) -> dict:
    """从 stream-json 日志取总 token、耗时;步数按 message.id 去重(一条回复会拆成多个事件,usage 重复)。"""
    out = {"steps": None, "duration_min": None, "in_tok": None, "out_tok": None,
           "cache_read": None, "cache_write": None, "cost_usd": None, "n_result_events": None}
    p = Path(log_path)
    if not p.exists():
        return out
    msg_ids = set()
    totals = dict.fromkeys(["duration_ms", "cost_usd", "in_tok", "out_tok", "cache_read", "cache_write"], 0)
    n_results = 0
    for line in p.open(encoding="utf-8"):
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        if ev.get("type") == "assistant":
            mid = (ev.get("message") or {}).get("id")
            if mid:
                msg_ids.add(mid)
        elif ev.get("type") == "result":
            # agent 用了后台任务时,任务结束会再触发一轮,一个会话里可能有多个 result 事件,要加起来
            u = ev.get("usage") or {}
            totals["duration_ms"] += ev.get("duration_ms") or 0
            totals["cost_usd"] += ev.get("total_cost_usd") or 0
            for k, uk in [("in_tok", "input_tokens"), ("out_tok", "output_tokens"),
                          ("cache_read", "cache_read_input_tokens"),
                          ("cache_write", "cache_creation_input_tokens")]:
                totals[k] += u.get(uk) or 0
            n_results += 1
    out["steps"] = len(msg_ids)
    if n_results:
        out.update({k: v for k, v in totals.items() if k != "duration_ms"},
                   duration_min=round(totals["duration_ms"] / 60000, 1), n_result_events=n_results)
    return out


def collect(res_dir: Path, commits: set[str] | None) -> pd.DataFrame:
    rows = []
    for f in sorted(res_dir.glob("*.json")):
        if f.name.startswith("_"):
            continue
        rec = json.loads(f.read_text(encoding="utf-8"))
        commit7 = rec["repo"].rsplit("-", 1)[-1]
        if commits is not None and commit7 not in commits:
            continue
        p = rec.get("agent_parsed_json") or {}
        verdict = p.get("smoke_verdict")
        r = p.get("repro") or {}
        e = p.get("entrypoint") or {}
        rows.append({
            "repo": rec["repo"],
            "commit7": commit7,
            "smoke_verdict": verdict or ("session_timeout" if rec.get("session_timed_out") else "parse_failed"),
            "layer": LAYER.get(verdict, "unknown"),
            "attribution": p.get("blocker_attribution"),
            "all_blockers": ";".join(b.get("verdict", "") for b in p.get("all_blockers") or []),
            "agent_wrote_entry": bool(e.get("written_by_agent")),
            "data_used": (p.get("data") or {}).get("used_for_smoke"),
            "image_used": (p.get("docker") or {}).get("image_used"),
            "repro_status": r.get("status"),
            "repro_match": r.get("match"),
            "repro_metric": r.get("metric"),
            "repro_ours": r.get("our_value"),
            "repro_paper": r.get("paper_value"),
            "tool_calls": rec.get("tool_call_count_actual"),
            "session_timed_out": rec.get("session_timed_out"),
            "verdict_reason": p.get("verdict_reason"),
            **log_stats(rec.get("trace_log", "")),
        })
    return pd.DataFrame(rows)


def collect_clone_failures(res_dir: Path, commits: set[str] | None) -> pd.DataFrame:
    f = res_dir / "_clone_failures.jsonl"
    if not f.exists():
        return pd.DataFrame()
    rows = []
    for line in f.open(encoding="utf-8"):
        d = json.loads(line)
        c7 = (d.get("head_commit") or "")[:7]
        if commits is not None and c7 not in commits:
            continue
        rows.append({"repo": d.get("code_url"), "commit7": c7,
                     "smoke_verdict": f"clone_{d.get('clone_status')}", "layer": "L0",
                     "attribution": "genuine"})
    return pd.DataFrame(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--variant", default="v13_smoke_repro")
    ap.add_argument("--model", default="default")
    ap.add_argument("--sample", default=None, help="只统计这个样本 csv 里的仓库(按 head_commit 前 7 位匹配)")
    args = ap.parse_args()

    res_dir = ROOT / "results" / f"{args.variant}__{args.model}"
    commits = None
    if args.sample:
        commits = set(pd.read_csv(args.sample)["head_commit"].dropna().str[:7])

    df = pd.concat([collect(res_dir, commits), collect_clone_failures(res_dir, commits)],
                   ignore_index=True)
    if df.empty:
        print("没有结果。")
        return
    n = len(df)
    title = args.variant + (f" / {Path(args.sample).name}" if args.sample else "")
    print(f"# {title}:{n} 个仓库\n")

    print("## 按层(95% Wilson 置信区间)\n")
    print("| 层 | 数量 | 比例 | 95% CI |\n|---|---|---|---|")
    for layer in LAYER_ORDER:
        k = int((df["layer"] == layer).sum())
        if k == 0 and layer == "unknown":
            continue
        lo, hi = wilson(k, n)
        print(f"| {layer} | {k} | {k / n:.0%} | {lo:.0%}–{hi:.0%} |")

    print("\n## smoke_verdict × attribution\n")
    ct = pd.crosstab(df["smoke_verdict"], df["attribution"].fillna("null"), margins=True, margins_name="合计")
    print(md(ct))

    if "repro_status" in df and df["repro_status"].notna().any():
        print("\n## 限时复现\n")
        print(md(df["repro_status"].value_counts(dropna=False).to_frame()))
        done = df[df["repro_status"] == "completed"]
        if not done.empty:
            print()
            print(done[["repo", "repro_metric", "repro_ours", "repro_paper", "repro_match"]]
                  .pipe(md, index=False))

    if df["agent_wrote_entry"].fillna(False).any():
        print("\n## agent 自己写了入口的仓库\n")
        print(md(df[df["agent_wrote_entry"].fillna(False)][["repo", "smoke_verdict"]], index=False))

    ran = df[df["duration_min"].notna()]
    if not ran.empty:
        print("\n## 成本(每个仓库)\n")
        print("| | 平均 | 中位数 | 最大 | 合计 |\n|---|---|---|---|---|")
        for col, name in [("duration_min", "耗时(分钟)"), ("steps", "模型轮数"),
                          ("cache_read", "缓存读 token"), ("out_tok", "输出 token"),
                          ("cost_usd", "等价 API 价 $")]:
            s = ran[col].astype(float)
            print(f"| {name} | {s.mean():,.1f} | {s.median():,.1f} | {s.max():,.1f} | {s.sum():,.1f} |")

    out = res_dir / "_summary_repos.csv"
    if args.sample:
        out = res_dir / f"_summary_repos__{Path(args.sample).stem}.csv"
    df.to_csv(out, index=False)
    print(f"\n逐仓库明细:{out}")


if __name__ == "__main__":
    main()
