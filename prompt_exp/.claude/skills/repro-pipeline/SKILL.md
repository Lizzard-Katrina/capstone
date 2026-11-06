---
name: repro-pipeline
description: 用 Claude Code agent 在 Docker 里对老研究仓库做 smoke test,判定代码今天还能不能跑通、跑不通卡在哪一步(不复现论文数字)。凡是涉及 RepoRevive、smoke test、仓库复现、paper reproduction、判断仓库是否腐烂、跑 v12/v11/v10/v9 这些 prompt 变体、抽样 clone 仓库、统计 token 成本、分析 blocked_* 失败原因、把复现结果和 dead-api-scan 的结果合并的任务,都要用这个 skill,即使用户没有明说 "pipeline" 或 "skill" 这些词。
---

# RepoRevive 复现 Pipeline

判定 2017-2022 年的 NLP 论文仓库在现代环境能否跑通(smoke test),跑不通的话卡在哪一步。
跑通后,完整实验预计 30 分钟内能跑完的,再跑完并和论文数字比较(限时复现,v13 起);跑不完就不比较。
核心做法:用 Claude Code 作为 agent,让它自己判断需要什么环境、自己起 Docker、
自己找数据,全程**不修改仓库代码**。

**接手工作时先读 [docs/STATUS.md](../../../docs/STATUS.md)**:当前进度、已定的决定、试跑结果、待确认的问题和下一步。
本文件讲的是怎么做,STATUS.md 讲的是做到哪了。

## 在整个项目里的位置

这是"哪些论文代码已经跑不起来"分层漏斗里的**动态层**:真的装、真的跑,成本高,只能抽样。
静态层是队友的 `dead-api-scan` skill:不安装、不运行,只扫代码文本,每个 repo 1-2 秒,覆盖全部 manifest。
两层互不依赖,可以同时跑,最后按 repo join。

| 层 | 原因 | 谁来判断 |
|---|---|---|
| L0 | 仓库不可得(删除、私有、空),或仓库在但这篇论文的代码没发布 | dead-api-scan `UNSCANNABLE`;本 pipeline `clone.py` 的 `clone_status`;v13 `blocked_code_unreleased` |
| L1 | 外部服务死了 / 受限 / 需要 key | dead-api-scan `DEAD_API` / `RESTRICTED_API`(全量);v12 `blocked_*_api` |
| L2 | 环境装不上 | `blocked_image` / `blocked_deps_removed` / `blocked_deps_conflict` |
| L3 | 数据拿不到 | `blocked_data_licensed` / `blocked_data_link_dead` / `blocked_data_manual`(公开但要手动下载,pipeline) |
| L4 | 代码本身坏了 | `blocked_code` |
| L5 | 硬件限制 | `blocked_hardware` |
| L6 | 跑不到主循环 | `smoke_timeout`(10 分钟内连第一步都没走到)。不测是否复现出论文数字 |

报告的口径:L0/L1 用 dead-api-scan 的全量数字;L2-L6 用本 pipeline 的抽样估计,附置信区间。
抽样要从**全部** repo 里随机抽,不要先剔掉 DEAD_API 的,这样样本才是无偏的,落进 DEAD_API 的那几个还能顺便用来验证静态扫描。
想验证静态扫描的 precision,就从 DEAD_API 里另外定向抽 5-10 个,但这一批不计入比例估计。

**和 dead-api-scan 合并时的 key**:本 pipeline 的文件名是 `<owner>-<repo>-<commit 前 7 位>`,
dead-api-scan 的 key 是 `github.com__<owner>__<repo>@<commit>`(它的结果在 `<run>/summary_repos.csv`)。
按 owner/repo 加 commit 前缀匹配,不能直接字符串 join。两边判断不一致的 repo 挑出来人工看,
它们正好可以当报告里的案例。

## 环境要求

- WSL 或 Linux(Windows 原生不行,被测仓库基本都是为 Linux 写的)
- Claude Code 已登录(订阅制,不要用 API key)
- Docker daemon 在跑:`docker ps` 能出表头
- uv(可选,老仓库用不上,它最低只支持 Python 3.8)
- 项目放在 Linux 原生目录(如 `~/prompt_exp`),**不要放在 `/mnt/c/`**,会慢到无法接受

## 快速开始

```bash
cd ~/prompt_exp
source .venv/bin/activate

# 1. 抽样并下载仓库(纯脚本,不花额度)
python -m src.clone \
  --manifest "/mnt/c/.../nlp_paper_code_reviewed.csv" \
  --sample data/sample_repos.csv --n 20

# 2. 跑复现(会真的调 Claude Code)
python -u -m src.run_experiment --variants v12_smoke_docker --repeats 1 --limit 10

# 3. 看结果
python3 -c "
import json,glob,os
for f in sorted(glob.glob('results/v12_smoke_docker__default/[!_]*.json')):
    d=json.load(open(f)); p=d.get('agent_parsed_json') or {}
    dk=p.get('docker') or {}
    print(f\"{d['repo'][:32]:34} {str(p.get('smoke_verdict')):26} {str(dk.get('image_used')):22} {p.get('blocker_attribution')}\")
"
```

**跑的时候终端长时间没输出是正常的**:脚本要等一个仓库全部跑完(几分钟到 40 分钟)才打印一行。
想看进度,就看 `logs/` 里最新的 `.jsonl` 在不在变大,或者 `ps aux | grep "claude -p"`。

单个仓库调试用:

```bash
python -m src.clone --single https://github.com/owner/repo --keep
python -u -m src.cc_runner --repo workdir/owner_repo/解压出的目录 --variant v12_smoke_docker
```

## 架构

```
manifest CSV (paper_id, code_url, head_commit, paper_url, arxiv_id)
   ↓ src/clone.py          下载 tarball、chmod 只读、用完即删。纯脚本,零额度
workdir/owner_repo/...
   ↓ src/run_experiment.py 遍历样本,每个仓库调一次 cc_runner
   ↓ src/cc_runner.py      起 claude -p 子进程,stream-json 落盘
logs/*.jsonl               每条事件(工具调用、token usage)
results/变体__模型/*.json    结构化结果(agent_parsed_json 是 agent 按 prompt 输出的 JSON)
   ↓ src/verify.py         规则核对 agent 有没有谎报(可选)
   ↓ src/analyze.py        汇总
```

平时"让 Claude Code 跑 v12",实际上是它替你执行 `run_experiment.py`,再由脚本为每个仓库各起一个
后台的 `claude -p`。干活的是那些后台会话,它们能用哪些工具由 `cc_runner.py` 决定,和你当前对话里的工具无关。

`results/`、`logs/`、`workdir/` 在 `.gitignore` 里,不进 git。要分享结果需要单独打包。

## 调用 Claude Code 的关键参数

写在 `src/cc_runner.py` 的 `cmd` 列表里。这几个是踩坑换来的:

```python
"claude", "-p", user_prompt,
"--system-prompt", system_prompt,        # prompt 变体从 prompts/*.md 读
"--tools", tools,                        # 见下方"工具集"
"--output-format", "stream-json",        # 必须,否则拿不到 token 和执行记录
"--verbose",
"--permission-mode", "bypassPermissions",# 必须,见下
"--settings", str(ROOT/".claude"/"settings.json"),
"--no-session-persistence",
```

**`--permission-mode bypassPermissions` 是必须的。** 不加的话,非交互模式下每条
bash 命令都要人工确认,全部被拒,agent 会反复换写法重试。实测差异:

| | 轮数 | 耗时 | 成本 |
|---|---|---|---|
| 不加 | 23 | 87s | $0.39 |
| 加了 | 6 | 18s | $0.087 |

只读靠 `--tools` 不给 Edit + `clone.py` 的 chmod 保证,不靠权限确认。
代价是 agent 能执行任意 docker 命令,请在专用机器上跑。

**不要加 `--bare`。** 它强制用 `ANTHROPIC_API_KEY` 认证,不读 OAuth,
订阅登录会直接失败:`Not logged in · Please run /login`。

**工具集按变体切换:**

```python
if variant.startswith(("v6", "v8", "v9", "v10", "v11", "v12", "v13")):
    tools = "Bash,Read,Glob,Grep,WebFetch,WebSearch"   # 复现类,要读论文
else:
    tools = "Bash,Read,Glob,Grep"                       # smoke test,不上网
```

两者都不给 `Edit`/`Write`,这是"不修改仓库"的第一道防线。
**新增变体时记得把前缀加进这个元组**,否则它会静默地拿不到联网工具。
验证方法:看日志第一条 `system/init` 事件里的 `tools` 字段。

### 已知问题:v6-v11 实际没有联网工具

2026-09-28 之前,`cmd` 里写的是 `"--tools", ALLOWED_TOOLS`,而不是 `tools`,所以上面的切换从来没生效。
**v6-v11 的所有运行都只有 `Bash,Glob,Grep,Read`**,16 个 v11 日志的 init 事件都证实了这一点,
WebFetch 调用次数都是 0。agent 只能用 `curl` 读论文、找替代数据,或者直接跳过。

已经修复,从 v12 起生效。后果是 v11 和 v12 的差异不全是 prompt 造成的,有一部分来自工具可用性。
要严格比较两者,需要用修复后的代码重跑 v11。

## Prompt 变体

都在 `prompts/` 下。`{SHARED_CONSTRAINTS}`、`{OUTPUT_SCHEMA}`、`{MAX_TOOL_CALLS}`
会被 `load_prompt()` 替换。报告里引用结果时必须写明用的是哪个变体。

| 变体 | 做什么 | 状态 |
|---|---|---|
| v0-v4 | 老的单因子 prompt 对比,走 OpenRouter API | 已停用 |
| v5_refined | smoke test:只判断能不能跑 | **结果不可信**,见下 |
| v8_repro_paper | 复现,带 paper_url,无 Docker | 已废弃 |
| v9_repro_fair | 复现,允许下载数据,用 uv 建环境 | 已废弃(uv 最低 3.8) |
| v10_repro_docker | 复现,让 agent 自己用 Docker | 已被 v11 取代 |
| v11_repro_docker_data | v10 + 数据链接失效时找替代源 | 16 次运行,**无联网工具**(见上) |
| v12_repro_docker_api | v11 + 外部 API 检查(L1)、依赖失败拆两类、`all_blockers` 多标签、先查数据再决定跑不跑 | **已废弃**(完整复现版,项目不再做复现);1 次试跑 |
| v12_smoke_docker | 同上,但**只做 smoke test**:跑通主循环第一步就停,不比较论文数字 | 已被 v13 取代;pilot 2 的 6 个结果 |
| **v13_smoke_repro** | v12_smoke + 允许在 /tmp 写入口(要标注)+ L0 `blocked_code_unreleased` + 限时复现(估算 ≤30 分钟才跑完整实验并比数字) | **当前主力**,未试跑 |

v12 相比 v11 的输出新增了这些字段(smoke 版的主 verdict 字段叫 `smoke_verdict`):
- `external_apis[]`:每个外部服务的 status(dead / restricted / needs_key / alive_free)、是否在主路径上、运行时有没有真的碰到。
- `all_blockers[]`:所有卡点,每项标明 `confirmed_by` 是 `execution`(真的跑出来的报错)还是 `static`(只读代码判断)。
- `repro_verdict` / `smoke_verdict`:取 `all_blockers` 里层级最早的那一项。

### v5 的结果不可信

v5 在 Python 3.12 下跑,20 个仓库 19 个 broken。但同一个仓库(tdlm)在
`python:2.7` 容器里环境和代码完全正常。所以 v5 测的是"跟 3.12 兼容不兼容",
不是"坏没坏"——对老论文这个答案永远是否,没有信息量。

**smoke test 也必须在 Docker 里做。** 正确顺序是:
判断需要什么环境 → 起对应容器 → 用仓库自带的 toy 数据验证能跑(这就是 smoke test)
→ 再找真实数据复现数字。

## 失败分类

完整定义见 `prompts/v12_smoke_docker.md` 第八步。下面这张表是 v11 的旧分类(当时还做复现)。v11 的实测分布(15 个仓库,无联网工具):

| 值 | 数量 | 含义 | 有救吗 |
|---|---|---|---|
| `reproduced` | 1 | 跑出数字且与论文一致 | — |
| `ran_partially` | 2 | 代码跑起来了但没跑完 | — |
| `blocked_data_licensed` | 4 | 数据要签协议(LDC/DUC/OntoNotes) | 否,除非机构有授权 |
| `blocked_data_link_dead` | 3 | 作者当年的网盘挂了(404) | 可能,去别处找同一份数据 |
| `blocked_code` | 3 | 代码本身不完整(README 是 TODO) | 否,除非允许改代码 |
| `blocked_env_deps` | 1 | 镜像对了但依赖装不上 | v12 已拆分,见下 |
| `blocked_hardware` | 1 | 缺 GPU | 是,换台机器 |

`blocker_attribution` 区分责任:`genuine`(仓库真问题)vs `pipeline`(我们环境的问题)。
v11 实测 12 genuine / 2 pipeline。

### v12 的分类变化

- **目标改成 smoke test**(`v12_smoke_docker`):用真实数据跑到主循环第一步(输出 loss 或指标)就算跑通,不比较论文数字。
  跑通记 `smoke_passed`;真实数据拿不到但 toy 数据跑通记 `smoke_passed_toy`。
- **点同意就能下载的数据算公开数据**(Yelp Dataset、部分 Kaggle)。agent 点不了网页按钮,自动下载不了时记
  `blocked_data_manual`,attribution 是 `pipeline`。只有签协议、审批、付费才算 `blocked_data_licensed`。
  起因:v12 首次试跑把 Yelp 判成了 licensed。
- **先查数据再决定跑不跑**(第四步,在起 Docker 之前):真实数据拿得到就正常复现;拿不到但有 toy 数据,就用 toy 数据在 Docker 里真的跑一遍(smoke test);两者都没有,就不起 Docker,直接判数据那一类。
  起因:v12 首次试跑 disco4textcat 花了 36 分钟、$0.86 编译 C++,最后结论还是数据拿不到。
- **`blocked_code` / `blocked_deps_*` / `blocked_image` 必须有执行报错作证据**。v11 在 disco4textcat 上只看到 README 写着 TODO
  就判了 `blocked_code`,v12 实际编译后发现程序能编出来、能启动。v11 的 15 个结果里有 6 个一次 docker 都没跑。
- **新增 L1 三类**:`blocked_dead_api`(服务或模型已下线,通常是 genuine)、
  `blocked_restricted_api`(服务还在但不对公众开放)、`blocked_api_key`(服务活着,但本机没有 key,通常是 pipeline)。
  v11 碰到死 API 只能记成 `blocked_code`,会让 L4 虚高。
- **`blocked_env_deps` 拆成两类**,因为两者性质完全不同:
  - `blocked_deps_removed`:包已从 PyPI 永久删除,任何环境都救不了。
    实例:QuaternionTransformers 要 tensor2tensor 1.12,它依赖 tfds-nightly 的
    2019 年构建,已被永久移除。agent 在正确镜像里试装失败后,
    用 `curl https://pypi.org/pypi/tfds-nightly/json` 查发布列表确认了这一点。
  - `blocked_deps_conflict`:版本冲突、编译失败、缺系统库,换个环境可能就好。

## Docker 的边界

**能解决**:版本太老装不了。`python:2.7`、`python:3.6`、
`tensorflow/tensorflow:1.4.0-py3` 这些镜像都还在,agent 会自己读 README 的
Requirements 挑镜像,不需要维护映射表。

**不能解决**:
- 包从 PyPI 消失(上面那个 tfds-nightly)
- 镜像本身拉不动:`tensorflow/tensorflow:0.7.1` 因 manifest 格式太老,现在 Docker 拉不下来
- 数据要授权、代码不完整、缺 GPU、外部 API 已下线

仓库要**只读挂载**进容器,容器里要写东西就写 `/tmp`:

```bash
docker run --rm -v <仓库绝对路径>:/repo:ro -w /repo <镜像> \
  bash -c "pip install -r requirements.txt && python train.py"
```

每次 `docker run` 都是新容器,装的东西不保留,所以要用 `bash -c "... && ..."`
把多步串起来。

## token 统计

`--output-format stream-json` 会让每个 `assistant` 事件带 `message.usage`,
最后的 `result` 事件带整次总计和 `total_cost_usd`。

```bash
python3 -c "
import json, glob, os
from collections import defaultdict
agg = defaultdict(lambda: {'n':0,'in':0,'out':0,'cr':0,'cw':0,'cost':0.0,'turns':0})
for logf in glob.glob('logs/*.jsonl'):
    v = os.path.basename(logf).split('__')[0]
    for line in open(logf, encoding='utf-8'):
        try: ev = json.loads(line)
        except: continue
        if ev.get('type') != 'result': continue
        u = ev.get('usage') or {}; a = agg[v]
        a['n'] += 1
        a['in'] += u.get('input_tokens',0); a['out'] += u.get('output_tokens',0)
        a['cr'] += u.get('cache_read_input_tokens',0)
        a['cw'] += u.get('cache_creation_input_tokens',0)
        a['cost'] += ev.get('total_cost_usd') or 0
        a['turns'] += ev.get('num_turns') or 0
for v in sorted(agg):
    a = agg[v]; n = a['n']
    print(f\"{v:<26}{n:>4}次 {a['turns']/n:>5.1f}轮 缓存读{a['cr']/n:>8.0f} 总\${a['cost']:.2f}\")
"
```

实测(v11,每次平均):缓存读 64.5 万 token、缓存写 2.5 万、输出 5.8 千,
折算 $0.43。**绝大部分是缓存读,单价只有原价的 1/10**,所以数字看着吓人、
实际便宜。`total_cost_usd` 是按 API 价折算的等价值,订阅制下不真扣钱。

## 常见问题

**`extract_error_PermissionError`** — 上次 `--keep` 留下的目录是只读的,覆盖不了:

```bash
chmod -R u+w workdir/ 2>/dev/null; rm -rf workdir/*
```

**`terminal_reason: api_error` + `Not logged in`** — 用了 `--bare`,去掉。

**大量 `permission_denials`** — 没加 `--permission-mode bypassPermissions`。

**agent 没用 WebFetch / 日志里 tools 只有 4 个** — 变体前缀没加进 `cc_runner.py` 的工具切换元组。

**终端一直没输出** — 正常,见"快速开始"。

**WSL 连不上网** — 在 Windows PowerShell 跑 `wsl --shutdown`,重开终端。

**GitHub 限流** — 未认证每小时 60 次。在 `.env` 加 `GITHUB_TOKEN=ghp_xxx`。

**`elapsed_sec` 是负数** — WSL 时钟同步问题,该字段不可信,用日志里的
`duration_ms` 代替。

## 不要做的事

- **不要改仓库代码**。改了就拿不到"原样是什么状态"这个基线,
  而整个项目的前提就是"历史环境能跑 vs 现代环境跑不通"的对比。
  修复实验要另起一份**可写副本**,不能污染基线。
- **不要让 agent 伪造数据**。缺数据就是缺数据,如实记录。
- **不要把 venv 建在仓库目录里**,仓库是只读的,建到 `/tmp`。
- **不要囤积仓库**。每个测完立刻删,否则 6000 个会撑爆磁盘。
- **不要在已经出结果的 prompt 变体上直接改**。改了就另起一个版本号,否则同一个变体名下混着两版 prompt 的结果。

## 待解决

- **已定(mentor)**:只缺入口时允许 agent 在 `/tmp/agent_entry/` 写入口,只能调用仓库已有代码;
  输出里 `entrypoint.written_by_agent=true` 并附脚本全文,跑通记 `smoke_passed_with_entry`。
  代码整个没发布(如 ContextualSP 只有 'Coming soon')算 L0,记 `blocked_code_unreleased`。
- **下一阶段(修复)**:替换依赖、补 `__init__.py`、补编译步骤等都算改代码,smoke test 阶段不做,只在 detail 里记下"改什么能跑通"。
- smoke test 要迁进 Docker(v5 的结果因此不可信)
- `src/verify.py`、`src/analyze.py` 还只认 v5 的 `overall_verdict`。v12/v13 的结果用 `python -m src.analyze_smoke --variant v13_smoke_repro [--sample 样本.csv]` 汇总
  (按 L0-L6 分层 + Wilson 置信区间、attribution、限时复现、成本;逐仓库明细写到结果目录的 `_summary_repos*.csv`)
- 和 dead-api-scan 的合并脚本还没写;抽样脚本(从全部 repo 里分层抽样)也还没写
- `max_tool_calls` 已调到 60、会话超时调到 60 分钟(v13 多了限时复现),试跑后再看够不够
- 会话超时被杀时,agent 已经起的 docker 容器不会跟着停,要手动 `docker ps` 检查
- 数据集缓存:`blocked_data_link_dead` 占 3/15,建镜像能救这一类
- 没有 venv 隔离:所有仓库共用一个宿主环境(Docker 内部无所谓,但宿主上的探测会互相影响)
- 没做 H 环境(历史环境)vs M 环境的对比,现在只有单向判定
- 额度:跑几十次会撞 `out_of_credits` 和五小时限流
