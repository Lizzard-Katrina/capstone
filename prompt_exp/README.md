# prompt_exp — 用 Agent 在 Docker 里复现 NLP 论文代码

给一个论文代码仓库(pinned commit)和论文地址,让 Claude Code 在 Docker 里真的装环境、下数据、跑代码,
判断代码**今天还能不能跑通**(smoke test,不比较论文数字);跑不通的话,**卡在哪一步**。

**完整文档见 [.claude/skills/repro-pipeline/SKILL.md](.claude/skills/repro-pipeline/SKILL.md)**,
包括环境要求、运行命令、prompt 版本对照、失败分类、踩坑记录,以及和队友的 dead-api-scan 怎么合并。
在这个目录里用 Claude Code 时,它会自动加载这份 skill。

## 最短路径

需要 Linux/WSL、Docker、已登录的 Claude Code CLI、Python ≥ 3.9。

```bash
pip install -r requirements.txt

python -m src.clone --manifest <path/to/nlp_paper_code_reviewed.csv> \
                    --sample data/sample_repos.csv --n 20
python -u -m src.run_experiment --variants v12_smoke_docker --limit 1
```

结果在 `results/v12_smoke_docker__default/`,完整执行记录在 `logs/`。
