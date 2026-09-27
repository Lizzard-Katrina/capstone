"""
用 Claude Code CLI 跑一个仓库的 smoke test。

用法:
    python -m src.cc_runner --repo workdir/xxx/yyy --variant v5_refined
    python -m src.cc_runner --repo workdir/xxx/yyy --variant v0_baseline --model opus
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import time
import uuid
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent

# 只给这些工具。没有 Edit / Write —— 只读约束的第一道防线。
ALLOWED_TOOLS = "Bash,Read,Glob,Grep"
DISALLOWED_TOOLS = "Edit"


def load_prompt(variant: str, max_tool_calls: int) -> str:
    """组装 system prompt: 变体模板 + 共用约束 + 输出 schema。"""
    pdir = ROOT / "prompts"
    template = (pdir / f"{variant}.md").read_text(encoding="utf-8")
    shared = (pdir / "_shared_constraints.md").read_text(encoding="utf-8")
    schema = (pdir / "_output_schema.md").read_text(encoding="utf-8")

    out = template.replace("{SHARED_CONSTRAINTS}", shared)
    out = out.replace("{OUTPUT_SCHEMA}", schema)
    out = out.replace("{MAX_TOOL_CALLS}", str(max_tool_calls))
    return out


def extract_json(text: str) -> dict | None:
    """从最终文本里抠出 JSON。"""
    if not text:
        return None
    blocks = re.findall(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    for b in reversed(blocks):
        try:
            return json.loads(b)
        except json.JSONDecodeError:
            continue
    start = text.rfind("{")
    while start != -1:
        try:
            return json.loads(text[start:])
        except json.JSONDecodeError:
            start = text.rfind("{", 0, start)
    return None


def run_one(repo_path: Path, variant: str, cfg: dict,
            model: str | None = None, run_id: str | None = None,paper_url: str | None = None) -> dict:
    """对一个仓库跑一次 Claude Code 诊断。"""
    run_id = run_id or uuid.uuid4().hex[:8]
    repo_path = Path(repo_path).resolve()
    model_tag = (model or "default").replace("/", "-")
    tag = f"{variant}__{model_tag}__{repo_path.name}__{run_id}"

    log_path = ROOT / "logs" / f"{tag}.jsonl"
    log_path.parent.mkdir(parents=True, exist_ok=True)

    system_prompt = load_prompt(variant, cfg.get("max_tool_calls", 40))
    user_prompt = (
        f"请诊断当前目录这个仓库: {repo_path.name}\n"
        f"当前工作目录就是仓库根目录。开始吧。"
    )
    if paper_url:
        user_prompt += f"对应的论文地址: {paper_url}\n"
    user_prompt += "开始吧。"

    if variant.startswith(("v6", "v8", "v9","v10","v11")):
        tools = "Bash,Read,Glob,Grep,WebFetch,WebSearch"
    else:
        tools = ALLOWED_TOOLS

    cmd = [
        "claude", "-p", user_prompt,
        "--system-prompt", system_prompt,
        "--tools", ALLOWED_TOOLS,
        "--disallowedTools", DISALLOWED_TOOLS,
        "--output-format", "stream-json",
        "--verbose",    
        "--permission-mode", "bypassPermissions",  
        "--settings", str(ROOT / ".claude" / "settings.json"),             
        "--no-session-persistence",
    ]
    if model:
        cmd += ["--model", model]

    t0 = time.time()
    events: list[dict] = []
    final_text = ""
    result_meta: dict = {}
    stderr_tail = ""
    proc = None

    try:
        proc = subprocess.Popen(
            cmd, cwd=repo_path,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, bufsize=1,
        )
        with open(log_path, "w", encoding="utf-8") as lf:
            for line in proc.stdout:
                line = line.strip()
                if not line:
                    continue
                lf.write(line + "\n")
                lf.flush()
                try:
                    ev = json.loads(line)
                except json.JSONDecodeError:
                    continue
                events.append(ev)

                if ev.get("type") == "result":
                    final_text = ev.get("result") or final_text
                    result_meta = {
                        "num_turns": ev.get("num_turns"),
                        "total_cost_usd": ev.get("total_cost_usd"),
                        "permission_denials": ev.get("permission_denials") or [],
                        "terminal_reason": ev.get("terminal_reason"),
                        "is_error": ev.get("is_error"),
                        "subtype": ev.get("subtype"),
                        "api_error_status": ev.get("api_error_status"),
                        "duration_ms": ev.get("duration_ms"),
                    }
                elif ev.get("type") == "assistant":
                    for blk in (ev.get("message", {}) or {}).get("content", []) or []:
                        if blk.get("type") == "text" and blk.get("text"):
                            final_text = blk["text"]

        proc.wait(timeout=cfg.get("session_timeout_sec", 2400))
        stderr_tail = (proc.stderr.read() or "")[-2000:]
        returncode = proc.returncode
    except subprocess.TimeoutExpired:
        if proc:
            proc.kill()
        returncode = None
        stderr_tail = "[会话超时,进程已终止]"
    except FileNotFoundError:
        raise RuntimeError("找不到 claude 命令,确认 Claude Code 已安装且在 PATH 里")

    elapsed = time.time() - t0

    # 从事件流里取出所有工具调用
    tool_uses = []
    for ev in events:
        if ev.get("type") == "assistant":
            for blk in (ev.get("message", {}) or {}).get("content", []) or []:
                if blk.get("type") == "tool_use":
                    tool_uses.append({
                        "name": blk.get("name"),
                        "input": blk.get("input", {}),
                    })

    # 出错的 tool_result,用于诊断
    error_results = []
    for ev in events:
        if ev.get("type") == "user":
            for blk in (ev.get("message", {}) or {}).get("content", []) or []:
                if blk.get("type") == "tool_result" and blk.get("is_error"):
                    error_results.append(str(blk.get("content", ""))[:300])

    # 限流信息
    rate_limit = None
    for ev in events:
        if ev.get("type") == "rate_limit_event":
            rate_limit = ev.get("rate_limit_info")

    parsed = extract_json(final_text)

    record = {
        "run_id": run_id,
        "repo": repo_path.name,
        "variant": variant,
        "model": model or "default",
        "returncode": returncode,
        "elapsed_sec": round(elapsed, 1),
        "n_events": len(events),
        "tool_call_count_actual": len(tool_uses),
        "num_turns": result_meta.get("num_turns"),
        "total_cost_usd": result_meta.get("total_cost_usd"),
        "terminal_reason": result_meta.get("terminal_reason"),
        "session_is_error": result_meta.get("is_error"),
        "api_error_status": result_meta.get("api_error_status"),
        "tool_uses": tool_uses,
        # 用 Claude Code 自己报的 permission_denials,比猜关键词可靠
        "permission_denials": result_meta.get("permission_denials", []),
        "error_tool_results": error_results,
        "rate_limit": rate_limit,
        "agent_final_text": final_text,
        "agent_parsed_json": parsed,
        "stderr_tail": stderr_tail,
        "trace_log": str(log_path),
    }

    out_dir = ROOT / "results" / f"{variant}__{model_tag}"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{repo_path.name}__{run_id}.json").write_text(
        json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return record


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--variant", default="v5_refined")
    ap.add_argument("--model", default=None, help="sonnet / opus / 具体模型名,留空用默认")
    args = ap.parse_args()

    cfg = yaml.safe_load((ROOT / "config" / "experiment.yaml").read_text())
    rec = run_one(Path(args.repo), args.variant, cfg, model=args.model)

    print(json.dumps({
        "repo": rec["repo"],
        "variant": rec["variant"],
        "model": rec["model"],
        "returncode": rec["returncode"],
        "num_turns": rec["num_turns"],
        "tool_calls": rec["tool_call_count_actual"],
        "permission_denials": len(rec["permission_denials"]),
        "cost_usd": rec["total_cost_usd"],
        "elapsed_sec": rec["elapsed_sec"],
        "terminal_reason": rec["terminal_reason"],
        "verdict": (rec["agent_parsed_json"] or {}).get("overall_verdict"),
        "log": rec["trace_log"],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()