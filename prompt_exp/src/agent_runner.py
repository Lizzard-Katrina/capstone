"""
Agent 主循环: 调 OpenRouter,让模型用工具诊断一个仓库,记录每一轮的 token。

用法:
    python -m src.agent_runner --repo workdir/owner_repo \
        --variant v0_baseline --model anthropic/claude-sonnet-4.5
"""
from __future__ import annotations

import argparse
import json
import os
import re
import time
import uuid
from pathlib import Path

import requests
import yaml
from dotenv import load_dotenv

from .sandbox import create_venv, destroy_venv, detect_gpu
from .tools import TOOL_SCHEMAS, Sandbox

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"


def load_prompt(variant: str, max_tool_calls: int) -> str:
    """组装 prompt: 变体模板 + 共用约束 + 输出 schema。"""
    pdir = ROOT / "prompts"
    template = (pdir / f"{variant}.md").read_text(encoding="utf-8")
    shared = (pdir / "_shared_constraints.md").read_text(encoding="utf-8")
    schema = (pdir / "_output_schema.md").read_text(encoding="utf-8")

    out = template.replace("{SHARED_CONSTRAINTS}", shared)
    out = out.replace("{OUTPUT_SCHEMA}", schema)
    out = out.replace("{MAX_TOOL_CALLS}", str(max_tool_calls))
    return out


def extract_json(text: str) -> dict | None:
    """从模型最后的自然语言里抠出 JSON。"""
    if not text:
        return None
    # 优先找 ```json ``` 代码块
    blocks = re.findall(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    for b in reversed(blocks):
        try:
            return json.loads(b)
        except json.JSONDecodeError:
            continue
    # 退而求其次: 最后一个看起来像对象的片段
    start = text.rfind("{")
    while start != -1:
        try:
            return json.loads(text[start:])
        except json.JSONDecodeError:
            start = text.rfind("{", 0, start)
    return None


def run_one(repo_path: Path, variant: str, model: str, cfg: dict,
            run_id: str | None = None) -> dict:
    """对一个仓库跑一次完整的 agent 诊断。"""
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        raise RuntimeError("没有找到 OPENROUTER_API_KEY,检查 .env")

    run_id = run_id or uuid.uuid4().hex[:8]
    repo_path = Path(repo_path)
    tag = f"{variant}__{model.replace('/', '-')}__{repo_path.name}__{run_id}"

    venv_path = ROOT / "workdir" / f"venv_{run_id}"
    log_path = ROOT / "logs" / f"{tag}.jsonl"

    venv_info = create_venv(venv_path, cfg.get("python_version", "3.11"))

    sandbox = Sandbox(
        repo_path=repo_path,
        venv_path=venv_path,
        log_path=log_path,
        default_timeout=cfg.get("command_timeout_sec", 120),
    )

    system_prompt = load_prompt(variant, cfg.get("max_tool_calls", 30))
    user_msg = (
        f"请诊断这个仓库: {repo_path.name}\n"
        f"仓库根目录就是你的工作目录。venv 已创建,python/pip 已在 PATH 中。\n"
        f"开始吧。"
    )

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_msg},
    ]

    total_in = total_out = 0
    tool_calls_made = 0
    hit_limit = False
    max_calls = cfg.get("max_tool_calls", 30)
    t_start = time.time()
    final_text = ""

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    while True:
        payload = {
            "model": model,
            "messages": messages,
            "tools": TOOL_SCHEMAS,
            "temperature": cfg.get("temperature", 0),
        }
        data = None
        last_err = None
        for attempt in range(3):
            try:
                resp = requests.post(OPENROUTER_URL, headers=headers,
                                     json=payload, timeout=600)
                resp.raise_for_status()
                data = resp.json()
                break
            except Exception as e:
                last_err = e
                print(f"    [重试 {attempt+1}/3] {type(e).__name__}")
                time.sleep(5 * (attempt + 1))
        if data is None:
            final_text = f"[API 调用失败,重试3次] {last_err}"
            break

        usage = data.get("usage", {}) or {}
        total_in += usage.get("prompt_tokens", 0)
        total_out += usage.get("completion_tokens", 0)

        choice = (data.get("choices") or [{}])[0]
        msg = choice.get("message", {}) or {}
        messages.append(msg)

        tcs = msg.get("tool_calls") or []
        if not tcs:
            final_text = msg.get("content") or ""
            break

        for tc in tcs:
            if tool_calls_made >= max_calls:
                hit_limit = True
                break
            fn = tc.get("function", {}) or {}
            name = fn.get("name")
            try:
                fargs = json.loads(fn.get("arguments") or "{}")
            except json.JSONDecodeError:
                fargs = {}

            result = sandbox.dispatch(name, fargs)
            tool_calls_made += 1

            messages.append({
                "role": "tool",
                "tool_call_id": tc.get("id"),
                "content": json.dumps(result, ensure_ascii=False)[:8000],
            })

        if hit_limit:
            messages.append({
                "role": "user",
                "content": f"已达到 {max_calls} 次工具调用上限。请立即停止执行,"
                           f"输出目前已得到的结果,并将 hit_iteration_limit 置为 true。",
            })
            # 再让它说最后一轮总结
            payload["messages"] = messages
            try:
                resp = requests.post(OPENROUTER_URL, headers=headers,
                                     json=payload, timeout=600)
                data = resp.json()
                usage = data.get("usage", {}) or {}
                total_in += usage.get("prompt_tokens", 0)
                total_out += usage.get("completion_tokens", 0)
                final_text = ((data.get("choices") or [{}])[0]
                              .get("message", {}) or {}).get("content") or ""
            except Exception as e:
                final_text = f"[收尾调用失败] {e}"
            break

    elapsed = time.time() - t_start
    gpu = detect_gpu(venv_path)
    parsed = extract_json(final_text)

    record = {
        "run_id": run_id,
        "repo": repo_path.name,
        "variant": variant,
        "model": model,
        "tokens": {
            "input": total_in,
            "output": total_out,
            "total": total_in + total_out,
        },
        "tool_call_count_actual": tool_calls_made,   # 我们数的,不是 agent 自己说的
        "hit_iteration_limit_actual": hit_limit,
        "blocked_write_attempts_actual": sandbox.blocked_writes,
        "elapsed_sec": round(elapsed, 1),
        "venv": venv_info,
        "gpu_probe": gpu,
        "agent_final_text": final_text,
        "agent_parsed_json": parsed,
        "trace_log": str(log_path),
    }

    out_dir = ROOT / "results" / f"{variant}__{model.replace('/', '-')}"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{repo_path.name}__{run_id}.json").write_text(
        json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    destroy_venv(venv_path)
    return record


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--variant", default="v0_baseline")
    ap.add_argument("--model", default="anthropic/claude-sonnet-4.5")
    args = ap.parse_args()

    cfg = yaml.safe_load((ROOT / "config" / "experiment.yaml").read_text())
    rec = run_one(Path(args.repo), args.variant, args.model, cfg)

    print(json.dumps({
        "repo": rec["repo"],
        "variant": rec["variant"],
        "model": rec["model"],
        "tokens": rec["tokens"],
        "tool_calls": rec["tool_call_count_actual"],
        "blocked_writes": len(rec["blocked_write_attempts_actual"]),
        "elapsed_sec": rec["elapsed_sec"],
        "verdict": (rec["agent_parsed_json"] or {}).get("overall_verdict"),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
