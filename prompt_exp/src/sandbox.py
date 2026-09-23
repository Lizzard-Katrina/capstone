"""
环境准备: 为每个仓库建一个干净 venv,测完删掉。

注意: 这是最低限度的隔离,够 pilot 用。
正式跑 6000 个之前应该换成 Docker(只读挂载 + 断网执行 + 资源限制),
这一点还要跟 mentor 确认。
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


def has_uv() -> bool:
    return shutil.which("uv") is not None


def create_venv(venv_path: Path, python_version: str = "3.11") -> dict:
    """
    建 venv。优先用 uv(快,而且全局缓存能让 torch 这种大包只下一次)。
    """
    venv_path = Path(venv_path)
    if venv_path.exists():
        shutil.rmtree(venv_path, ignore_errors=True)
    venv_path.parent.mkdir(parents=True, exist_ok=True)

    if has_uv():
        cmd = ["uv", "venv", "--python", python_version, str(venv_path)]
    else:
        cmd = ["python3", "-m", "venv", str(venv_path)]

    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        return {
            "ok": proc.returncode == 0,
            "used_uv": has_uv(),
            "stderr": proc.stderr[-2000:],
        }
    except subprocess.TimeoutExpired:
        return {"ok": False, "used_uv": has_uv(), "stderr": "venv 创建超时"}


def destroy_venv(venv_path: Path):
    shutil.rmtree(Path(venv_path), ignore_errors=True)


def detect_gpu(venv_path: Path) -> dict:
    """
    硬件能力探测。写在这里而不是交给 agent,是为了保证 M/H 两次运行
    用的是同一份客观记录,不受 agent 探索路径影响。
    """
    py = Path(venv_path) / "bin" / "python"
    if not py.exists():
        py = Path("python3")
    code = (
        "import json\n"
        "try:\n"
        "    import torch\n"
        "    print(json.dumps({'torch': torch.__version__,"
        " 'cuda_available': torch.cuda.is_available()}))\n"
        "except Exception as e:\n"
        "    print(json.dumps({'torch': None, 'cuda_available': None, 'err': str(e)}))\n"
    )
    try:
        proc = subprocess.run([str(py), "-c", code], capture_output=True,
                              text=True, timeout=60)
        import json as _json
        return _json.loads(proc.stdout.strip() or "{}")
    except Exception as e:
        return {"torch": None, "cuda_available": None, "err": str(e)}
