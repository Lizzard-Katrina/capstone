# 从 API 版迁移到 Claude Code 版

## 变更清单

| 文件 | 操作 |
|---|---|
| `src/clone.py` | **保持不变** |
| `src/cc_runner.py` | **新增**,替代 agent_runner.py |
| `src/agent_runner.py` | **删除**(或改名留档) |
| `src/tools.py` | **删除**,Claude Code 自带工具 |
| `src/sandbox.py` | **删除**,不再自建 venv(见下方说明) |
| `src/verify.py` | **覆盖**,改为解析 Claude Code 的 stream-json |
| `src/analyze.py` | **覆盖**,去掉 token,改为比准确率和违规率 |
| `src/run_experiment.py` | **覆盖**,改调 cc_runner |
| `prompts/v5_refined.md` | **新增**,主力 prompt |
| `prompts/_shared_constraints.md` | **覆盖**,去掉 API 时代措辞 |
| `prompts/v0-v4.md` | 保留,后续做对比用 |
| `config/experiment.yaml` | **覆盖** |
| `.claude/settings.json` | **新增**,权限模板 |

## 应用方式

```bash
cd ~/prompt_exp
rm src/agent_runner.py src/tools.py src/sandbox.py
# 把 cc_patch 里的文件覆盖进来
```

## 关于 venv

原来 sandbox.py 会给每个仓库建独立 venv。现在交给 Claude Code 在
prompt 指导下自己处理,或者由你在跑之前手动准备。

**这是个待确认的点**:如果不隔离,不同仓库的依赖会互相污染。
建议先在少量仓库上测,看是否需要把 venv 创建重新加回来
(可以在 cc_runner 里跑 claude 之前先建好,然后把 python 路径写进 user_prompt)。

## 待验证

1. `claude -p` 的 stream-json 事件结构是否和 cc_runner.py 里假设的一致
   (type=assistant/user/result,tool_use/tool_result 块)
2. `--tools "Bash,Read,Glob,Grep"` 是否真的挡住了写入
3. Bash 里的 sed -i / 重定向能不能绕过限制
4. 权限拒绝时 tool_result 的错误文本长什么样(影响 blocked 检测的关键词)
