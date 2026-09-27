"""
T(-1): 仓库获取。纯脚本,零 LLM token。

从 manifest 读 code_url + head_commit,下载 tarball 解压到 workdir。
clone 失败的直接记录状态,不进入 agent 诊断。

用法:
    python -m src.clone --manifest ../retrival/Capstone/data/manifest/nlp_paper_code_reviewed.csv \
                        --sample data/sample_repos.csv
    python -m src.clone --single https://github.com/owner/repo --commit abc123
"""
from __future__ import annotations

import argparse
import io
import json
import os
import re
import shutil
import stat
import tarfile
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
WORKDIR = ROOT / "workdir"
RESULTS = ROOT / "results"

GITHUB_RE = re.compile(r"github\.com[/:]([^/]+)/([^/.\s]+)", re.I)


def parse_github_url(url: str):
    """从 code_url 提取 (owner, repo)。解析不了就返回 None。"""
    if not url or not isinstance(url, str):
        return None
    m = GITHUB_RE.search(url.strip())
    if not m:
        return None
    owner, repo = m.group(1), m.group(2)
    repo = repo.replace(".git", "")
    return owner, repo


def _make_readonly(path: Path):
    """递归去掉写权限。这是只读挂载的简易替代方案。

    注意: 这挡不住 root。真正的隔离应该用 Docker 的 :ro 挂载或只读文件系统,
    这里只是第一道防线。agent 自己也没有写工具(见 tools.py)。
    """
    for p in sorted(path.rglob("*"), reverse=True):
        try:
            mode = p.stat().st_mode
            p.chmod(mode & ~stat.S_IWUSR & ~stat.S_IWGRP & ~stat.S_IWOTH)
        except OSError:
            pass
    try:
        mode = path.stat().st_mode
        path.chmod(mode & ~stat.S_IWUSR & ~stat.S_IWGRP & ~stat.S_IWOTH)
    except OSError:
        pass


def _restore_writable(path: Path):
    """删除前恢复写权限,否则 rmtree 会失败。"""
    for p in path.rglob("*"):
        try:
            p.chmod(p.stat().st_mode | stat.S_IWUSR)
        except OSError:
            pass
    try:
        path.chmod(path.stat().st_mode | stat.S_IWUSR)
    except OSError:
        pass


def is_effectively_empty(path: Path) -> bool:
    """只有 README / LICENSE,没有实际代码的仓库。"""
    code_files = [
        p for p in path.rglob("*")
        if p.is_file() and p.suffix in {".py", ".sh", ".ipynb", ".yaml", ".yml", ".cfg", ".toml"}
    ]
    return len(code_files) == 0


def fetch_repo(owner: str, repo: str, commit: str | None, dest: Path,
               token: str | None = None, timeout: int = 60) -> dict:
    """
    下载并解压到 dest。返回 {'clone_status': ..., 'path': ..., ...}

    优先用 tarball(比 git clone 省空间、无 .git 历史)。
    commit 为空时退回默认分支 HEAD,并在结果里标注。
    """
    headers = {"Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    ref = commit if commit else "HEAD"
    used_default_branch = commit is None
    url = f"https://api.github.com/repos/{owner}/{repo}/tarball/{ref}"

    try:
        resp = requests.get(url, headers=headers, timeout=timeout, stream=True)
    except requests.Timeout:
        return {"clone_status": "timeout"}
    except requests.RequestException as e:
        return {"clone_status": f"network_error_{type(e).__name__}"}

    if resp.status_code == 404:
        # 仓库没了,或者这个 commit 已经不存在(被 force push 掉了)
        return {"clone_status": "not_found", "http_status": 404}
    if resp.status_code in (401, 403):
        remaining = resp.headers.get("X-RateLimit-Remaining")
        if remaining == "0":
            return {"clone_status": "rate_limited", "http_status": resp.status_code}
        return {"clone_status": "private_or_forbidden", "http_status": resp.status_code}
    if resp.status_code != 200:
        return {"clone_status": f"http_{resp.status_code}", "http_status": resp.status_code}

    dest.mkdir(parents=True, exist_ok=True)
    try:
        raw = io.BytesIO(resp.content)
        with tarfile.open(fileobj=raw, mode="r:gz") as tf:
            # tarball 顶层是 owner-repo-sha/ 这种目录,剥掉一层
            members = tf.getmembers()
            if not members:
                return {"clone_status": "empty_archive"}
            top = members[0].name.split("/")[0]
            tf.extractall(dest)
        extracted = dest / top
        if not extracted.exists():
            return {"clone_status": "extract_failed"}
    except (tarfile.TarError, OSError) as e:
        return {"clone_status": f"extract_error_{type(e).__name__}"}

    if is_effectively_empty(extracted):
        return {"clone_status": "empty_or_readme_only", "path": str(extracted)}

    size_mb = sum(f.stat().st_size for f in extracted.rglob("*") if f.is_file()) / 1e6

    _make_readonly(extracted)

    return {
        "clone_status": "success",
        "path": str(extracted),
        "size_mb": round(size_mb, 1),
        "used_default_branch": used_default_branch,
    }


def cleanup(path: Path):
    """测完即删。不囤积仓库。"""
    if path.exists():
        _restore_writable(path)
        shutil.rmtree(path, ignore_errors=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", help="nlp_paper_code_reviewed.csv 的路径")
    ap.add_argument("--sample", help="输出/读取样本列表 csv")
    ap.add_argument("--n", type=int, default=25, help="抽多少个")
    ap.add_argument("--single", help="只下载一个 url,用于调试")
    ap.add_argument("--commit", help="配合 --single")
    ap.add_argument("--keep", action="store_true", help="下载后不删除(调试用)")
    args = ap.parse_args()

    token = os.environ.get("GITHUB_TOKEN")  # 可选,提高 API 限额

    if args.single:
        parsed = parse_github_url(args.single)
        if not parsed:
            print(json.dumps({"clone_status": "bad_url"}))
            return
        owner, repo = parsed
        dest = WORKDIR / f"{owner}_{repo}"
        r = fetch_repo(owner, repo, args.commit, dest, token)
        print(json.dumps(r, ensure_ascii=False, indent=2))
        if not args.keep and "path" in r:
            cleanup(Path(r["path"]).parent)
        return

    # 批量模式: 读 manifest,抽样,逐个下载并记录 clone_status
    import pandas as pd

    df = pd.read_csv(args.manifest)
    print(f"manifest 共 {len(df)} 行")

    # 按年份分层抽样
    if "year" in df.columns and args.n < len(df):
        per_year = max(1, args.n // df["year"].nunique())
        sample = df.groupby("year", group_keys=False).apply(
            lambda g: g.sample(min(len(g), per_year), random_state=42)
        )
    else:
        sample = df.sample(min(args.n, len(df)), random_state=42)

    RESULTS.mkdir(parents=True, exist_ok=True)
    records = []
    for _, row in sample.iterrows():
        parsed = parse_github_url(row.get("code_url", ""))
        rec = {
            "paper_id": row.get("paper_id"),
            "year": row.get("year"),
            "framework": row.get("framework"),
            "code_url": row.get("code_url"),
            "head_commit": row.get("head_commit"),
            "paper_url": row.get("paper_url"),
            "arxiv_id": row.get("arxiv_id"),
            "title": row.get("title"),
        }
        if not parsed:
            rec["clone_status"] = "bad_url"
            records.append(rec)
            continue

        owner, repo = parsed
        dest = WORKDIR / f"{owner}_{repo}"
        commit = row.get("head_commit")
        if isinstance(commit, float):  # NaN
            commit = None
        r = fetch_repo(owner, repo, commit, dest, token)
        rec.update(r)
        records.append(rec)
        print(f"  {owner}/{repo}: {r['clone_status']}")

        if not args.keep and "path" in r:
            cleanup(dest)
        time.sleep(0.5)  # 对 GitHub 客气一点

    out = pd.DataFrame(records)
    if args.sample:
        Path(args.sample).parent.mkdir(parents=True, exist_ok=True)
        out.to_csv(args.sample, index=False)
        print(f"\n写入 {args.sample}")

    print("\nclone_status 分布:")
    print(out["clone_status"].value_counts())


if __name__ == "__main__":
    main()
