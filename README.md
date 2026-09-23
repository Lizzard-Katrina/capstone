# prompt_exp — Agent 驱动 smoke test 的 prompt / 模型对比实验

## 目的

比较不同 system prompt 写法和不同模型,在"判断一个老仓库能不能跑"这个任务上
各自消耗多少 token、判断准不准、守不守约束。

## 快速开始

```bash
cp .env.example .env          # 填入 OPENROUTER_API_KEY
pip install -r requirements.txt

# 1. 抽样 + 检查 clone 状态(纯脚本,零 token)
python -m src.clone --manifest ../retrival/Capstone/data/manifest/nlp_paper_code_reviewed.csv \
                    --sample data/sample_repos.csv --n 25

# 2. 先小规模试跑,拿单次真实 token 数
python -m src.run_experiment --variants v0_baseline v1_minimal \
                             --models anthropic/claude-sonnet-4.5 \
                             --repeats 1 --limit 5

# 3. 核验 agent 的自述是否属实
python -m src.verify --results results/v0_baseline__anthropic-claude-sonnet-4.5

# 4. 汇总
python -m src.analyze
```

## 变体设计(单因子对照)

| 变体 | 详细度 | 约束位置 | 输出时机 | 语气 |
|---|---|---|---|---|
| v0_baseline | 详细 | 集中 | 末尾 | 中性 |
| v1_minimal | **精简** | 集中 | 末尾 | 中性 |
| v2_inline_constraints | 详细 | **穿插** | 末尾 | 中性 |
| v3_stepwise | 详细 | 集中 | **逐步** | 中性 |
| v4_strict_tone | 详细 | 集中 | 末尾 | **强调风险** |

每个变体只和 v0 差一处,任何差异都能归因到那一个改动。

## 关键设计约束

- **仓库只读**: `clone.py` 下载后 chmod 去写权限;`tools.py` 不提供写文件的工具。
  `write_file` 存在但永远拒绝,用来统计 agent "想改东西"的次数。
- **留痕**: 每次工具调用(命令、退出码、输出)写进 `logs/*.jsonl`。
- **核验**: `verify.py` 拿留痕对 agent 自己给的 verdict,查"声称跑过但其实没跑"。
- **用完即删**: 每个仓库测完立刻删除 clone 和 venv,不囤积。

## 还没解决的

- 隔离目前只是 chmod + venv,正式跑 6000 个之前应换 Docker(待与 mentor 确认)。
- H 环境(历史环境)还没实现,当前只测 M 环境。
- `data/gold_labels.csv` 需要人工标注,格式: `repo,gold_verdict`
  (gold_verdict 取值 runs / broken / undetermined)。
