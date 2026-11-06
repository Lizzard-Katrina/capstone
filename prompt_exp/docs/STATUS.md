# 当前进度(交接用)

最后更新:2026-10-08。怎么跑、各字段什么意思,看 [SKILL.md](../.claude/skills/repro-pipeline/SKILL.md);这里只记**做到哪了、定了什么、还差什么**。

## 已经定下的决定

| 决定 | 来源 |
|---|---|
| 先做 smoke test;跑通后,完整实验能在限定时间内跑完(估算 ≤30 分钟)的,跑完并和论文数字比较,超出就不比较 | 和 mentor 讨论,用户确认(2026-10-08) |
| 主力 prompt 是 `prompts/v13_smoke_repro.md`;`v12_smoke_docker` 被取代;`v12_repro_docker_api`(无时间限制的完整复现版)废弃 | 同上 |
| 只缺入口代码时,允许 agent 在 /tmp 写入口(只能调用仓库已有代码),输出里标注并附脚本全文,跑通记 `smoke_passed_with_entry` | mentor |
| 仓库在、但这篇论文的代码没发布(例如 ContextualSP 只有 "Coming soon")算 L0,记 `blocked_code_unreleased` | 用户 |
| `smoke_passed_toy` 的 attribution 填数据那一项的归属;`smoke_passed_with_entry` 填 genuine | 用户确认的 prompt 修改 |
| 先查数据再决定跑不跑:真实数据能拿到就用真实数据跑;拿不到但有 toy 数据就用 toy 跑;都没有就不起 Docker,直接判数据类 | 用户 |
| "点同意就能下载"的数据(Yelp、部分 Kaggle)算公开数据。agent 自动下载不了时记 `blocked_data_manual`,attribution 记 pipeline | 用户 |
| 不改仓库代码。**替换依赖**(`--no-deps`、改装别的包顶替已下架的包)也算改代码,smoke test 阶段不做,只在 detail 里记下怎么改能跑通,留给下一阶段修复 | 用户 |
| 仓库声明了 Python 版本(例如 README 写 2.7)就按它跑,不换版本去试 | 用户 |
| 同一层有多个卡点时,verdict 取 genuine 的那一项 | 用户 |
| 后台用 `claude -p` 跑(订阅登录,不走 API key),不在交互对话里跑,保证每个仓库都是全新会话、同一个 prompt、只读工具 | 讨论后确认 |

## 试跑结果(pilot 2)

样本:`data/pilot_v12_smoke.csv`,共 6 个仓库,都在 v11 里跑过,方便对比。
结果:`results/v12_smoke_docker__default/`。pilot 1 有 3 个因为 403 认证错误中断,结果归档在 `results_archive/v12_smoke_pilot1/`。

| 仓库 | v11 | v12_smoke(pilot 2) | 用时 | 评价 |
|---|---|---|---|---|
| falcondai/lm-steganography | reproduced | `smoke_passed` | 8 分钟 | 正面对照,通过 |
| jhlau/topically-driven-language-model | blocked_data_link_dead | `smoke_passed_toy` | 15 分钟 | 论文数据链接 404,用 toy 数据在 py2.7 + TF 0.12.1 里跑通 |
| hxbai/Deep_Enhanced_Repr_for_IDRR | blocked_data_licensed | `blocked_data_licensed` | 1 分钟 | PDTB 2.0 需要 LDC 授权 |
| jiyfeng/disco4textcat | blocked_code | `blocked_data_manual` | 2 分钟 | **按现在的规则应该是 `blocked_data_link_dead`**:RST 解析文件仓库没提供(genuine),比 Yelp 要手动下载(pipeline)优先 |
| microsoft/ContextualSP | blocked_code | `blocked_code` | <1 分钟 | 合集仓库,这篇论文的子目录里只有 "Coming soon",代码从没发布 |
| vanzytay/QuaternionTransformers | blocked_env_deps | `blocked_code` | 30 分钟 | **按现在的规则应该是 `blocked_deps_removed`**:agent 用替换依赖的办法才装上,之后才碰到缺 `layers/__init__.py`。现在已禁止替换依赖 |

## 试跑结果(pilot 3,v13,2026-10-08)

同样 6 个仓库,`v13_smoke_repro`。结果:`results/v13_smoke_repro__default/`,运行输出 `logs/_pilot3_v13.out`。
共约 53 分钟,等价 API 价约 $2.8。**4 个预期的变化全部生效**:

| 仓库 | v12_smoke(pilot 2) | v13(pilot 3) | 用时 | 限时复现 |
|---|---|---|---|---|
| falcondai/lm-steganography | `smoke_passed` | `smoke_passed` | 19 分钟 | **completed, match**:Huffman 编码 KL 均值 0.1246 bits vs 论文 0.12(估算 5 分钟) |
| jhlau/topically-driven-language-model | `smoke_passed_toy` | `smoke_passed_toy`(attr genuine) | 5 分钟 | skipped:只有 toy 数据 |
| hxbai/Deep_Enhanced_Repr_for_IDRR | `blocked_data_licensed` | `blocked_data_licensed` | 1 分钟 | skipped |
| jiyfeng/disco4textcat | `blocked_data_manual` | **`blocked_data_link_dead`** ✓ | 1 分钟 | skipped |
| microsoft/ContextualSP | `blocked_code` | **`blocked_code_unreleased`** ✓ | 1 分钟 | skipped |
| vanzytay/QuaternionTransformers | `blocked_code` | **`blocked_deps_removed`** ✓(execution 证据) | 26 分钟 | skipped |

jhlau 和 lm-steganography 各有 1-2 次 permission denial,都是 agent 在 `/tmp` 里 `rm -rf` 被 settings.json 的 deny 规则拦下,不影响结论。
pilot 里仍没有"只缺入口"的仓库,写入口的规则要靠随机样本里碰到的来验证。

## 随机样本结果(v13,2026-10-08,18 个)

样本 `data/sample_v13_random60.csv`(从全部 5,977 个里简单随机抽 60 个,按随机顺序跑),共跑 2 段约 13 小时,完成前 18 个
(另有 2 个被 403 打断后已重跑)。汇总:`python -m src.analyze_smoke --variant v13_smoke_repro --sample data/sample_v13_random60.csv`,
逐仓库明细 `results/v13_smoke_repro__default/_summary_repos__sample_v13_random60.csv`。

| 结果 | 数量 | 比例(95% CI) | 仓库 |
|---|---|---|---|
| 跑通 `smoke_passed` | 5 | | glp-pos、interexp、conv-emotion、linguistic-features、pl-marker |
| 跑通 `smoke_passed_toy` | 1 | | adjust_cwe(16GB 向量本机内存装不下,pipeline) |
| 跑通 `smoke_passed_with_entry` | 1 | | granular-similarity(agent 写了入口) |
| **跑通合计** | **7** | 39%(20–61%) | |
| L4 `blocked_code`(genuine) | 4 | 22%(9–45%) | hypmix(`async` 语法)、artificial-languages(fairseq 架构不存在)、document-level-sentiment(`logger` 未定义)、c2f-far(流水线文件名硬编码不一致) |
| L5 `blocked_hardware`(pipeline) | 3 | 17%(6–39%) | chapter-captor、GradLRE、IS-BERT:都硬编码 `.cuda()`,本机 Docker 没有 GPU |
| 会话超时(60 分钟,无结论) | 4 | 22%(9–45%) | SimCLS、snli_logic(CPU 上 smoke 训练太慢);EmpGPT-3、CR-Walker(装环境太久) |

- **限时复现**:跑完并比较的 3 个**全部 match**(91.898 vs 91.89、88.86 vs 89.2、64.46 vs 64.18);interexp 的评测脚本缺模块(failed);其余多为估算远超 30 分钟而跳过。
- **随机样本里 L0-L3 一个都没有**,和 pilot(按 v11 已知卡点挑的)很不一样。样本还小,不能说明 L0-L3 少见。
- **GPU 相关**:3 个 `blocked_hardware` + 2 个 CPU 太慢导致的超时 = 5/18 的结论可能因为有合适的 GPU 而改变。
  这比中午 12 个结果时估计的 1-2 成高。见"已知的坑"里的 GPU 一条。
- **成本**:每个仓库平均 28 分钟、等价 API 价约 $1.0;18 个合计 6.6 小时、$13.9。

### 补跑(2026-10-08 傍晚,+3 个,共 21 个)

pointer-generator、VWS-PR、bran 全部 `smoke_passed`。21 个的汇总:跑通 10(48%,95% CI 28–68%)、`blocked_code` 4(19%)、
`blocked_hardware` 3(14%)、会话超时 4(19%)。限时复现完成 4 个,全部 match(新增 VWS-PR:Micro F1 0.84329 vs 0.8431)。
第 22 个 covidfact 会话超时(60 分钟还在编译 fairseq 环境)。**含它共 22 个:跑通 10(45%)、blocked_code 4、blocked_hardware 3、超时 5(23%)**。

要人工复核的两处:
- **VWS-PR**:`--test` 默认指向训练集,agent 改用 dev 集的 F1 和论文比较。论文的 0.8431 是 dev 还是 test 要看论文确认。
- **pointer-generator**:agent 装了 requirements 里没有的 `pyrouge`。装仓库没声明但代码需要的包算不算"替换依赖",规则里没写清。

**人工复核 L4 和跑通结果后发现的问题(2026-10-08 晚)**:
- hypmix 判 `blocked_code` 不对:`async=True` 只在 Python 3.7+ 报错,仓库年代的 Python 3.6 能解析。在 3.6 镜像里真正卡住的是 `.cuda()` 找不到 GPU,应判 `blocked_hardware`(pipeline)。
- c2f-far 的 `blocked_code` 证据弱:第 1 步因为 batch_size=4096 在 7GB 内存下被 OOM kill,第 2 步的 FileNotFoundError 可能只是第 1 步没产出;"文件名不一致"是读配置推断的。
- pointer-generator 的 `smoke_passed` 有疑问:agent 自己写了数据预处理脚本(CNN/DM → .bin + vocab),还装了未声明的 `pyrouge`。
- L4 里证据扎实的是 document-level-sentiment(`logger` 未定义)和 artificial-languages(fairseq 没有 `transformer_lm_small`)。
- 结论:agent 判定需要人工抽查,不能全信;`src/verify.py` 要适配 v13。

**WSL 时钟会跳**:这次跳了约 57 分钟,`--deadline-hours` 按进程内时间算,实际截止被推迟。要准时停,得在外面盯着手动停。

## v13 prompt 的问题(给下一版 prompt 用)

2026-10-08 晚人工复核 v13 结果后整理。每条写:表面上看到什么、实际错在哪、prompt 哪里导致的、去哪看证据。
结果文件在 `results/v13_smoke_repro__default/`,日志在 `logs/`(文件名 `v13_smoke_repro__default__<结果文件名>.jsonl`)。

### P1(最严重)agent 会为了"跑通"偏离仓库声明的环境,而且拿偏离环境的报错当证据

本机有 GPU(RTX 5060)但老 torch 用不了,agent 看到 GPU 就想办法用上,于是去试现代环境(Python 3.12、PyTorch 2.x / CUDA 12.8),
或者在声明版本之外挑"更新一点"的版本。我们要的是**仓库声明的(或年代对应的)环境里能不能跑**,其他环境的结果不该进结论。

| 仓库 | 表面结论 | 实际问题 | 证据位置 |
|---|---|---|---|
| hypmix | `blocked_code`(genuine) | 第 9 步还没搭 3.6 环境,先用 `python:3.12` 解析代码得到 `async` 语法错误,并把它当成 L4 证据;3.6 里这行完全合法。README 声明 torch 1.0.0(PyPI 上有 cp36 包),agent 没试,直接装 1.10.2。在 3.6 环境里真正卡住的是 `.cuda()` 没有 GPU → 应为 `blocked_hardware`(pipeline) | `caisa-lab-hypmix-emnlp-52f663a__ccc630aa`,看 tool_uses 第 9、12 步 |
| PL-Marker | `smoke_passed` | torch 没写版本,按规则该选 2022 年前后的 1.x,agent 先试 `pytorch:2.7.1-cuda12.8`,最后在 python:3.8 里装了 **torch 2.4.1** 跑通。不是在年代环境里跑通的,要按年代版本重跑才能算 | `thunlp-PL-Marker-dd19a85__9b2ed38f`,第 14、18-21 步 |
| Document-level-Sentiment | `blocked_code` | 结论本身对(`logger` 未定义,与环境无关,最终在声明的 torch 1.3.0 里复现)。但中间 3 次用 `pytorch:2.7.1-cuda12.8 --gpus all` 试 GPU,浪费时间 | `lyuchenyang-...-e8dd0db__53eadd94`,第 23、29、33 步 |
| IS-BERT | `blocked_hardware` | 结论对。中间挂 WSL 的 `/dev/dxg` 想绕过 Docker 拿 GPU | `yanzhangnlp-IS-BERT-ea6622c__9c257ea4`,第 15 步 |
| GradLRE、CR-Walker | — | 拉 `pytorch:2.7.x-cuda12.8`(每个 12GB)试探,GradLRE 最终用声明的 1.6.0 | `THU-BPM-GradLRE-ed9972e__eda15e7a` 第 9 步;`truthless11-CR-Walker-9e69b09__06e7ac34` |

**prompt 里导致这个问题的地方:**
1. 开头"**首要目标是跑通**":目标写成跑通,agent 就会为跑通去调整环境。
2. 硬性约束表把"**换镜像、换 Python 版本**"列为"允许(属于环境)"(第 20 行)。这和我们定的"仓库声明了 Python 版本就按它跑,不换版本去试"(本文件"已经定下的决定"表)直接矛盾——**这条决定从来没写进 prompt**。
3. "按 requirements 或仓库年代推断的版本装包"只是"允许",没写"必须先装声明的确切版本,装不上才能换,换了要记录原因"。README 里写的版本(hypmix 的 torch 1.0.0)不在 requirements.txt 里,规则也没覆盖。
4. 第八步证据要求只说"必须有**真实执行的报错**",没说"必须是**在声明环境里**执行的报错"。3.12 解析是真实执行,字面上满足了要求。
5. prompt 完全没提 GPU:没告诉 agent 本机 GPU 对老框架不可用、不要尝试启用 GPU。第五步还列了 `pytorch/pytorch:1.4-cuda10.1-...` 这类 CUDA 镜像作为例子。
6. 第八步"选流水线顺序中最早卡住的那一层":L4 排在 L5 前面,于是"别的环境里的代码问题"压过了"声明环境里的硬件问题"。

### P2 机器资源不足被判成仓库的问题

| 仓库 | 表面结论 | 实际问题 | 证据位置 |
|---|---|---|---|
| c2f-far | `blocked_code`(genuine) | 第 1 步因 `batch_size=4096`(README 说是 4×V100 32G 的配置)在 7GB 内存下被 OOM kill(exit 137);第 2 步的 `FileNotFoundError` 可能只是第 1 步没产出。"文件名不一致"是读配置推断的,没有独立执行证据 | `xnliang98-c2f-far-b5c970b__0ce6b6df`,`run.output_tail` |

**prompt 原因**:没告诉 agent 本机只有 7GB 内存、OOM(exit 137)应归为资源问题(pipeline);
也没要求"后一步的报错必须在前一步成功的前提下才算证据"。

### P3 规则没写清的灰色地带

| 仓库 | 情况 | 证据位置 | prompt 原因 |
|---|---|---|---|
| pointer-generator | `smoke_passed`,但 agent 自己写了整套数据预处理(`/tmp/prep/make_bin.py`:把 HF 上的 CNN/DM 转成仓库要的 .bin 和 vocab),原仓库的预处理在另一个仓库里;还装了 requirements 没有的 `pyrouge` | `abisee-pointer-generator-b29e986__a5eda153` | "缺入口"一节禁止在入口里重新实现数据处理,但没说**数据预处理脚本**能不能自己写;也没说没声明的依赖能不能装 |
| VWS-PR | 复现 `match`,但 `--test` 默认指向训练集,agent 改用 dev 和论文数字比 | `HKUST-KnowComp-VWS-PR-1a63309__28f971e3`,`repro.note` | 第九步没规定论文数字和我们的数字必须是同一个 split |

### P4 超时就什么都留不下

22 个里 5 个会话超时(SimCLS、snli_logic、EmpGPT-3、CR-Walker、covidfact),结论全空,前面查到的环境、数据信息全丢。
SimCLS、snli_logic 是 CPU 上 smoke 训练太慢;另外 3 个是装环境太久(其中 CR-Walker 在拉多个 6-12GB 的镜像)。
**prompt 原因**:只要求最后输出一次 JSON;没有"每完成一步输出阶段性结果";没限制拉多少个大镜像(只说"最多试 3 个")。

### 下一版(v14)要改的
1. 删掉"换镜像、换 Python 版本"这一条"允许";改成:**必须用声明的 Python 版本和声明的包版本**;没声明的按年代选,并写明依据;
   声明版本装不上时才能换,要在输出里列出每一处偏离和原因。
2. 证据必须来自声明环境;其他环境里的观察只能写进 detail,不能作为 verdict。
3. 明确写:**本机 GPU 对老框架不可用,不要尝试 `--gpus`、不要用 CUDA 12 镜像**;代码硬编码 CUDA 就判 `blocked_hardware`。
4. 写明本机内存 7GB;exit 137 / OOM 归为 pipeline。后一步的报错只有在前一步成功时才算证据。
5. 数据预处理脚本、未声明依赖的规则(待和 mentor 定)。
6. 每完成一步输出阶段性 JSON(或写到 `/tmp/agent_progress.json`),超时也能拿到。
7. 复现比较必须同一个 split,对不上记 `not_comparable`。

### verify(自动核对)要查什么(待讨论)

`src/verify.py` 还停在 v5。上面的问题大多可以自动从日志里查出来,不用人工一个个看:
- 声明版本 vs 实际安装版本(从 tool_uses 的 `pip install` / 镜像名提取),偏离的标出来
- 是否用过现代镜像(`cuda12`、`torch==2.`、`python:3.1x`)、是否用过 `--gpus` / `/dev/dxg`
- verdict 的执行证据是否出自 `docker.image_used` 那个环境
- 是否在 `/tmp/agent_entry` 以外写了 .py / .sh(`cat >`、`.write(`)
- verdict 和 all_blockers、attribution 是否自洽(层级最早、同层取 genuine)
- 复现的 split 是否一致(只能半自动)
这些只读日志,可以对所有已有结果跑一遍,算出"多少比例的结论需要人工复核"。

## 待确认(找 mentor)

1. **会话超时 22%**:60 分钟上限要不要放宽?或者下一版 prompt 要求 agent 每完成一步就输出阶段性 JSON,超时也能知道卡在哪。
2. **GPU**:约 1/4 的结论受没有 GPU 影响。学校有没有老架构 GPU(V100 / A100 / RTX 8000,支持 CUDA 10/11)可以用?
   cap263@10.208.2.89 的 RTX 5090 和本机一样是 Blackwell(sm_120),老 PyTorch 用不了,只能测允许新 torch 的仓库或做"修复"阶段的实验。
3. **样本量**:每个仓库约 30 分钟,100 个约 50 小时。正式样本要多大?复现的时间预算要不要从 30 分钟降下来?


(上次的两个问题:缺入口、代码没发布,已定,见"已经定下的决定"。)

## 下一步

1. (已完成 2026-10-08)用 v13 重跑 pilot,见上。
2. (进行中 2026-10-08 夜)随机样本:从全部 5,977 个仓库里简单随机抽 60 个(`data/sample_v13_random60.csv`,seed 20261008,排除 pilot 的 6 个),
   串行跑,6.5 小时截止,输出 `logs/_batch_v13_random60.out`。顺序是随机的,截止时跑完的前 N 个仍是无偏样本。
   中断了就加 `--skip-done` 续跑。
3. (已完成 2026-10-08)v13 prompt;`cc_runner.py` 工具切换加 v13、修复会话超时不生效(改成计时器杀整个进程组)。
4. 改 `src/analyze.py`,让它认 `smoke_verdict` / `all_blockers`(现在只认 v5 的 `overall_verdict`)。
5. 写合并脚本,和队友 dead-api-scan 的 `summary_repos.csv` 按 owner/repo + commit 前缀 join,两边不一致的挑出来人工看。

## 已知的坑(这次遇到的)

- **(2026-10-08)远程 GPU 服务器 cap263@10.208.2.89 暂时不能用**:WSL 免密登录已通(用户配好,host key 已核对)。
  条件:RTX 5090(sm_120,和本机 5060 同代)、驱动 580、32 核、62GB 内存;cap263 在 docker 组,**已装 nvidia runtime**。
  但根分区 100% 满,只剩 2.9GB;Docker 数据在 `/var/lib/docker`(同一分区),上面 264GB 镜像都是别人的。
  老 PyTorch 镜像每个 3-7GB,一拉就会写满磁盘,影响所有用户。别人的镜像不能删。要先让管理员或镜像主人清出空间(建议至少 50GB)。
  另外服务器上有 `reporevive-tiopifdpo:modern/historical` 镜像,可能是队友在做同一个项目。
  能用之后第一件事:用老镜像(pytorch 1.4 / 1.10)在 5090 上跑一个最小 GPU 运算,确认老 torch 到底能不能用 sm_120。

- **(2026-10-08 夜)随机样本比 pilot 慢得多**:平均每个仓库 32 分钟(pilot 9 分钟),因为随机样本里能跑通的多,跑通就要进限时复现。
  按这个速度,一晚 9 小时只能跑 12-15 个;60 个要 30 多小时。
- **(2026-10-08 夜)登录 token 中途失效**:07:09 出现 `403 Request not allowed`,自动停止生效。被打断的 2 个结果归档在
  `results_archive/v13_auth_fail_20261008/`(不归档的话 `--skip-done` 会把它们当成已完成跳过)。
- **agent 会用后台 Bash 任务**跑长实验,任务结束会再触发一轮:一个会话里有多个 `result` 事件,结论 JSON 也不一定在最后一条消息里。
  已修:`cc_runner.py` 倒序在所有消息里找 JSON;`analyze_smoke.py` 把所有 result 事件的耗时、token、成本加起来。
  结果文件里的 `total_cost_usd` 只是最后一个 result 事件的,**以 `analyze_smoke.py` 的数字为准**。conv-emotion 的结论是从日志重新解析的(`reparsed_from_log: true`)。
- **agent 会把仓库拷到 /tmp 再挂载、或 `docker run -d ... sleep infinity`**,按挂载路径认不出,留下了一个跑了 2 小时的容器。
  已改成按会话前后 `docker ps` 的差集清理(要求串行跑)。
- **Docker 没有 GPU 直通**:prompt 里的 `docker run` 没有 `--gpus all`,强制 CUDA 的仓库会判 `blocked_hardware`(pipeline),例如 chapter-captor。
  本机是 RTX 5060(Blackwell),老 CUDA 镜像本来也不支持,加 `--gpus` 能救的只有较新的 PyTorch 镜像。要不要加待定。

- **manifest 里的 code_url 指向仓库根目录**。合集仓库(例如 microsoft/ContextualSP)要靠 agent 自己找出这篇论文对应的子目录,可能出错。
- **仓库改名**:样本表里写的是 `diccooo/deep_enhanced_repr_for_idrr`,GitHub 重定向到 `hxbai/...`,所以结果文件名用的是新名字。按 URL 匹配时要考虑这一点。
- **长时间运行可能遇到 `403 Request not allowed`**:登录 token 中途失效。重跑即可,先用 `claude -p "ok"` 测一下登录。
- **后台运行找不到 `claude`**:PATH 里没有 `~/.local/bin`。先 `export PATH="$HOME/.local/bin:$PATH"`。
- **`~/prompt_exp/.git` 是误建的空仓库**,remote 指向 capstone,但目录结构和 capstone 对不上(capstone 里是 `prompt_exp/` 子目录)。不要在这里 `git push`;应删除。推送方法是 clone capstone 到别处,把文件同步进它的 `prompt_exp/` 子目录再提交。
