```json
{
  "dependency_file_used": "requirements.txt | setup.py | environment.yml | pyproject.toml | none",
  "install": {
    "status": "success | failed | not_attempted",
    "exit_code": 0,
    "log_tail": "最后若干行"
  },
  "entry_scripts": [
    {"name": "train.py", "test_type": "help | import",
     "status": "success | failed | timeout | hardware_limited",
     "error_type": "ModuleNotFoundError | AttributeError | SyntaxError | CUDA | other | null"}
  ],
  "readme_commands": [
    {"command": "python train.py --config x.yaml",
     "status": "success | data_boundary | failed | timeout | not_applicable",
     "error_type": "FileNotFoundError | CUDA | other | null",
     "produced_output_before_failure": true}
  ],
  "hardware": {"gpu_available_in_env": false, "hardware_limited_flagged": false},
  "blocked_write_attempts": [{"what_it_tried": "编辑 requirements.txt", "when": "安装依赖时"}],
  "extra_install_attempts": [{"package": "numpy==1.19", "reason": "解决冲突"}],
  "overall_verdict": "runs | broken | undetermined",
  "verdict_reason": "一句话说明依据",
  "tool_call_count": 0,
  "hit_iteration_limit": false
}
```
