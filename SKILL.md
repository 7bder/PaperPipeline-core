---
name: paper-pipeline
description: >-
  用于规划、撰写、审计或改投一篇基于已有学位论文/实验/模拟/临床/调查数据的科学稿件，
  且该工作由 orchd 引擎编排。它从领域 profile 生成 orchd 原生投喂物（task proposals、模块声明、
  规则片段、verify 断言清单），提供机器可判的验收脚本（引用门、文风、编号/图表一致性），
  并沉淀本流程的踩坑约束。触发短语：下一篇论文、把毕设改成论文、写 SCI、选刊、投稿前评审、
  引用审计、查文献真伪、合稿、定稿、论文 skill、paper pipeline、manuscript from thesis data。
  不适用于：从零设计实验/发明方法；替代 orchd 的 claim/done/review 状态机与 git 纪律；
  代替用户注册任务或替用户裁决选题。
---

**许可**：本技能以 MIT 许可发布。

# paper-pipeline

把"已有原始研究数据 → 可投稿英文稿件"的流程封装为 **orchd 引擎原生**技能。
本技能**不实现状态机**，只提供引擎不具备的三件事：**领域知识**（`profiles/`）、
**可机检判据**（`scripts/`）、**踩坑约束**（本文件"硬约束速查" + 各 reference）。

本工作空间与任何论文项目**无 git、无路径、无状态耦合**；生成物由使用者手动或经引擎命令投喂进论文项目，不在本目录隐式落盘。

## 何时使用

- 启动或接续一篇论文（学位论文改写、项目数据成稿、多组数据拆多篇连续产出）；
- 需要把论文流程注册进 orchd（生成 proposals 与模块声明）；
- 需要对稿件做机器可判检查（引用编号、图表覆盖、术语、字数、AI 腔、引用真伪）；
- 需要跨领域适配（材料/化工、生物医学、临床、社科、CS/ML、理论）。

## 何时不要使用

- 从零设计实验或发明方法（本技能只处理"已有数据"的成稿与合规）；
- 期望它替代 orchd 的 claim/done/review 状态机与 git 纪律；
- 期望它自动注册任务或替用户裁决选题（注册与 confirm/drop 永远归用户与引擎）。

## 入口模式（`entry.mode`，由 profile 选择）

| mode | 场景 | 前导阶段 | 人工闸门 |
|---|---|---|---|
| `data-first`（默认） | 已有一组数据，凝练故事线 | **执行序** P1 数据盘点 → P0 故事线收敛 | 用户选定故事线 |
| `idea-first` | 有研究问题，数据还没做 | P0 研究问题 + 数据收集计划 | 用户 confirm 后去做实验 |
| `multi-paper` | 多组数据，拆成多篇 | **P-1** 资产盘点 + 故事线发现 + 拆分决策 | 用户选定论文组合与优先级 |
| `inherited` | P-1 已选定，单篇执行 | 跳过故事线发现，直接逐值核对 | 无（方向已定） |

P2 之后四种模式完全汇合：claim 需求单 → 定向文献 → 写作 → 合稿 → 排版。

**P0/P1 为什么在这里是倒着的**（不是与 `10-idea-to-skeleton.md` 冲突）：该文件三段式表里的 P0/P1 是
**载体编号**——P0 = 苏格拉底式追问收敛出的可研究问题（落 `00-admin/00-plan.md`），P1 = 证据可行性与边界裁定
（落 `10-data/10-audit.md`），编号标的是产物归属与 idea 条目，不标执行时刻。本表"前导阶段"列写的是**执行序**。
`data-first` 刻意先做 P1 再做 P0：手里已有数据时，"能支撑什么"要先于"讲哪个故事"，否则故事线会在逐值核对时
被迫重来——同类代价该文件已有实证（"作者侧事实前置收集"被记为本项目最大延迟来源，10 项待确认里 3 项属此类）。
`idea-first` 无数据可扫，按编号序正向执行。

## 阶段序（canonical order，P2 之后不可颠倒）

| 阶段 | 干什么 | 产物（编号路径） | 必读 reference |
|---|---|---|---|
| **P-1** 资产规划（仅 multi-paper） | 全量数据盘点、候选故事线发现、拆分决策 | `00-admin/05-data-inventory.md`、`06-storyline-options.md`、`07-paper-roadmap.md` | 本文件 + `10-idea-to-skeleton.md` |
| **P0/P1** 前导（按 entry.mode） | data-first：数据盘点+故事线收敛；idea-first：问题+数据计划；inherited：跳过 | `00-admin/00-plan.md`、`10-data/10-audit.md` | `10-idea-to-skeleton.md` |
| **P2** claim 框架 | 建论证环与 claim 骨架 → 产出对文献的**需求单** | `20-lit/20-claims-map.md`、`00-admin/02-skeleton.md` | `20-claim-framework.md` |
| **P3** 定向文献 | 按需求单检索 → 验真 → 全文 → 归一 | `20-lit/21-candidates.json`、`22-refs.json`、`fulltext/`、`24-fulltext-inventory.md` | `30-literature-pipeline.md` |
| **P4** 综述与正文撰写 | 把引用钉进句子并机检落位 | `30-manuscript/sections/31-…` | `20-claim-framework.md` §4–6 |
| **P5** 合稿与引用审计 | 一致性检查 + 逐条判据级别 | `30-manuscript/36-draft.md`、`37-references.md`、`20-lit/25-citation-audit.md` | `40-draft-to-latex.md` |
| **P6** 评审/定稿/排版 | 六层评审 → 响应 → LaTeX 装配 | `50-review/50-review-report.md`、`30-manuscript/38-final.md`、`60-latex/main.pdf` | `40-draft-to-latex.md` |

**目录与文件命名规范见 `references/00-project-layout.md`**（阶段号前缀 + 产物/临时物/原始件三分 + orchd 联合约束检查表）。

### 顺序铁律

**先需求单（P2）、后采购（P3）、再落位（P4）。**
颠倒会得两种病：检索无目标 → **库存病**（库大但引用不上）；写作期临时找文献 → **临时凑引病**（over-claim、落位失控）。
**任何文献检索任务的数据输入必须是 `claims_map` 的待补行，禁止"尽可能多检"。**

## 与 orchd 的协同契约（硬约束）

1. **只生成、不注册**：产出 `proposals/*.json` 与 `_master` 片段，交 `orchd validate` 校验后由用户/引擎 `intake`/`amend --register` 注册。本技能永不代替用户注册。
2. **命令卫生**：协议命令（`claim/done/review/amend/idea`）不与管道、`Select-String` 组合；一次 shell 只放一条协议命令，并以其后 `orchd status` 复核是否落账。
3. **声明域自洽**：连带改动的既有文件**直接写入 `files_to_edit`**，不依赖 `exempt_files`。
4. **粒度**：单任务 ≤5 个 `files_to_edit`（超过触发 E029 告警）；写作按"节"切片、图表按"图"切片，保持严格串行。
5. **AC 一次到位**：`acceptance_criteria` 仅在 `pending` 可改；生成时必须可判定、可机检，避免模糊词与不自洽的列举集合。
6. **踩坑分层沉淀（不另建自由文档）**：`orchd lesson`（写 `lessons.jsonl`）只承载**引擎/平台/配置层**经验（环境、工具链、协议命令坑）；**领域方法论与论文流程**踩坑沉淀于 `CHANGELOG.md` / `references/`。注：这是本**协同契约**第 6 条，**不是引擎红线 6**——引擎红线 6 = 禁止自动摄入，两套清单不通用，勿互相指代。
7. **证据可追溯**：proposal 的 `source` 字段写 profile 指纹（含版本），便于 regenerate 时判定来源漂移。

## 判据基座（`scripts/70-verify.py`）

manifest 驱动的只读验收；每个任务的 `verify_command` 调用它。**断言类型集合不得回退**（逐字保持语义）。

**manifest 属受信输入**（P3，2026-10-05）：只接受本技能生成器产物或项目作者手写的 manifest；
来自不可信来源（网络下载、外部项目未审阅）的 manifest 不得直喂基座——`run` 段命令经 shell
解释执行，恶意 manifest 即任意命令执行面。

**run 断言预算口径**：基座内层超时 300s，但实际预算受引擎 `verify_command` 超时约束
（引擎默认 120s，例外通道 `amend --verify-timeout-seconds` 上界 600s）——配 120-300s 的
run 命令会先触发引擎 E014，须先走例外通道提高任务预算。

- 用法：`python 70-tools/70-verify.py <task-id>`；`--all` 全量；`--json` 机器可读；`--schema` 打印断言 schema；`--list` 列任务；`--root/--manifest` 可对别的项目跑。
- 退出码：`0`=PASS，`1`=有未满足断言，`2`=用法/manifest 问题（含坏 manifest）。
- 任务条目四段（均可省略；四段全空即空验收，直接 PASS——手工 manifest 勿写空条目）：
  - `files[]`（文本产物）：`path`、`min_bytes`、`contains[]`、`forbid[]`、`contains_regex[]`、`forbid_regex[]`、`min_matches{pattern,min}`、`count_distinct{pattern,min[,scope: line|all]}`（唯一计数，抗同串填充）、`declare_and_count{pattern,declare_regex}`（声明与计数绑死：声明行解析出的 N 须等于 pattern 实际匹配数）、`word_count[lo,hi]`（正文行数区间：跳过空行/纯表格行/图注行/代码围栏行后计数，标题行计入；中英文一律按行计数，中文不做逐字/切词换算——口径与 `--schema` 同文）
  - `json_files[]`：`path`、`min_items`/`max_items`、`require_keys[]`（查首项）、`require_keys_all[]`（查每项）、`require_values{键:期望值}`（逐项值判定，布尔/字符串等值；空列表 + require_values 无有效 min_items 判 FAIL(1)）
  - `globs[]`（批量产物）：`pattern`（支持 `**` 递归）、`min_count`、`min_bytes_each`
  - `absent_paths[]`：不得存在的路径（否定式验收）
  - `run`：额外命令，退出码非 0 即失败，超时 300 s（manifest 属受信输入，勿喂不可信来源）
- 命名两制：新项目 `70-tools/70-verify.py`；出处项目 paper1 冻结为 `scripts/verify.py`（22 条历史 verify_command 不可改，改名即失去回归能力）——该文件在 paper1 项目内，**不在本 skill 发货面**；两制沿革见 `CHANGELOG.md` D-18。

## 生成器（`scripts/30-gen-proposals.py`）

profile → orchd 原生投喂物。离线、秒级。

```
python -X utf8 scripts/30-gen-proposals.py --profile profiles/<x>.yaml --out <输出目录>
python -X utf8 scripts/30-gen-proposals.py --profile profiles/<x>.yaml --check --project <目标项目>    # 合成 master 并跑 orchd validate（对目标项目零写入）
python -X utf8 scripts/30-gen-proposals.py --profile profiles/<x>.yaml --regress --project <目标项目>  # 与真实项目任务结构对比
```

两制切换（F2）：`--verify-layout standard` 把 materials 等 scripts/ 冻结侧档的 `tool_dir/verify_tool/verify_manifest` 覆写为 `70-tools/`（新项目用）；缺省维持档声明（paper1 `--regress` parity 不变），且 emit 模式下对 scripts/ 冻结侧档案打 stderr 双制警告（`--check`/`--regress` 静默）。

`--check` 与 `--regress` 都必须同时给 `--project`：缺项目时无从核对，脚本以**退出码 2**（用法错）拒绝，
且**先拒后写**——不落任何生成物（旧口径是静默走 `emit` 写出 `--out`（默认 `./build/`）并 rc=0，看起来"跑过了"）。

产出：`proposals/task-<id>.json`、`_master.fragment.json`（项目+模块+任务图）、`rules.fragment.md`、`verify_manifest.fragment.json`。
支持 `extends` 继承（父档任务列表 + 子档新增/覆盖；同名任务的 `inject` 列表追加合并）；`depends:` 集中声明依赖图；生成期 `emit` 清理陈旧 `task-*.json`（幂等）。

自测：`python -X utf8 scripts/75-verify-selftest.py`（合成控制用例 + 退出码语义守卫 + 与真实项目历史 verify 的 parity；改基座或换项目时必跑；**引擎未接入时该段显式 SKIP 并 rc=0**）；`python -X utf8 scripts/76-doc-refs-selftest.py`（文档卫生 / 发布面膜守卫）；`python -X utf8 scripts/78-assertions-selftest.py`（profile 实质断言棘轮下限 + 断言形状 + 正反控制；改 profile 或生成器时必跑）。

## profiles 体系

四轴：论文类型 × 证据形态 × 出版社/刊 × 语言与报告规范。加一刊 = 加一个 profile 文件。跨出版社规则碎片（`static/` + `manifest.yaml`）已建成：profile 顶层 `fragments: [id...]` 声明即注入 rules.fragment.md（materials 档已激活三件；axes 声明含 `citation_style` 才做引用制校验）。

| 文件 | 角色 |
|---|---|
| `profiles/00-base-empirical.yaml` | 通用基类：evidence_policy（baseline/n 披露/raw-vs-processed/统计措辞/坐标轴/方法引用）、通用任务 `task-back-matter`、P-1 `task-data-asset-mapping`（仅 multi-paper 激活） |
| `profiles/10-materials-chemistry.yaml` | 材料/化工/涂层档（例证：真实项目 paper1），继承基类，24 任务；`tool_dir: scripts`、`verify_tool: scripts/verify.py`（命名两制之冻结侧，该文件在 paper1 项目内） |
| `profiles/10-clinical.yaml` | 临床档：效应量与 CI 页级核对、伦理注册、CONSORT/STROBE 报告规范；继承基类，加严统计措辞与效应量披露，22 任务 |
| `profiles/20-social-science.yaml` | 社科档：抽样框代表性、信效度、κ-α 编码一致性、因果措辞；继承基类，加严抽样与编码一致性，23 任务 |
| `profiles/30-cs-ml.yaml` | CS/ML 档：baseline 原文核对 + 复现声明；继承基类，加严对比基线与复现性，24 任务 |

领域加严（如临床效应量与 CI、CS/ML 的 baseline 复现声明、理论引理依赖）由 profile 注入；新增领域档时 `extends` 基类并只写学科差异。

## 资源索引（按需加载，勿一次全读）

| 文件 | 内容 | 何时读 |
|---|---|---|
| `references/00-project-layout.md` | 目录与命名规范 + orchd 联合约束检查表 + 迁移实证 | **P0 必读** |
| `references/10-idea-to-skeleton.md` | 立项三段式、Socratic 交互、边界裁定、骨架契约 | P0–P2 |
| `references/15-figure-guidance.md` | 图表可读性软约束：出图后 ≥6pt 字号、色盲安全配色、chartjunk 禁令、panel 规范（与规范面互补） | P4–P5 图件与合稿 |
| `references/20-claim-framework.md` | claim 需求单、分层证据门限、四步段、引用落位机检 5 条 | **P2 与 P4** |
| `references/30-literature-pipeline.md` | 按需求单定向检索→验真→全文→归一→审计 | **P3 与 P5** |
| `references/31-literature-endpoints.md` | 四索引 endpoint/参数/限速口径（发现面与验真门控面两面边界；数字真源见 35 号） | P3 定向文献与验真 |
| `references/40-draft-to-latex.md` | md 单一真源 → LaTeX 生成式排版 | **P5 与 P6** |
| `references/50-orchd-runbook.md` | orchd 取证/探针/汇报运行手册 | 每个任务执行时 |
| `scripts/72-assemble-draft.py`、`scripts/72-compose-raster-figures.py`、`scripts/72-latex-build-check.py` | LaTeX 三件套（确定性合稿 / 光栅图版合成 / 装配回读校验）。**工具链已随技能发货**：`install.py <论文项目> --mode project` 随判据基座一并 vendor 进项目 `70-tools/`，不必每个项目重建一遍（消除排版环节的自动化方差源）。三者各自 `--selftest` 离线可跑 | **P5** 合稿与图版、**P6** 定稿回读校验 |
| `references/60-capability-specs.md` | 已建能力规格（行为契约）：40 词表 schema 与三条判定 / 50 runbook 大纲与素材面 / static 碎片 manifest schema 与命中算法 | **修改或依赖该能力前必读** |
| `assets/00-proposal.template.json` | proposal 字段示范 | 新项目建 proposal 时 |
| `assets/10-verify-manifest.template.json` | 各断言类型示例 | 新项目建 verify manifest 时 |
| `CHANGELOG.md` | 设计决策 D-1…D-23 全文（本仓库实际决策记录位置；审查发现的 N-编号遗留清单在 D-13 §遗留） | 有疑问、判断引擎行为或回归时先查这里 |

## 硬约束速查（来自设计决策，勿重走老路）

- **全文获取（D-1）**：OA 优先自动取 → 需订阅者一次性批量人工 → **排除盗版源**；全文可得性**不是**引用前置条件，缺则降级标注"题录+摘要级/未核"。不投通用爬虫，投入倾斜验真+归一。
- **证据门限（D-2）**：所有 claim 需 ≥1 支撑文献或 `direct-data`；机制/因果需 ≥1 条 A 级全文核对；背景允许题录+摘要级但不得推定量结论；分歧需 ≥2 条立场相反文献；新颖性需全文核对 + 对比基线，禁用"首次"除非附检索覆盖声明。
- **立项讨论（D-3）**：走 `orchd idea propose`（status: study）→ 用户 `confirm`；条目 title 必须内嵌 `（id: slug）`。
- **多论文（D-4/D-12）**：`multi-paper` 激活 P-1 资产规划；P-1 做"选择题"（选故事线、拆文章），单篇 inherited 做"填空题"（逐值核对），不重复故事线发现。
- **文件组织（D-6）**：阶段号前缀 + 产物/临时物/原始件三分；中文仅存于 `10-data/raw/**` 且附 `MAPPING.md`；其余 ASCII kebab-case。
- **md 单一真源（40-draft-to-latex）**：正文在 `30-manuscript/*.md`，`.tex` 是派生物（头部标 `GENERATED — do not edit`）；禁止在 `.tex` 里改句子；排版只在 `finalize` 之后进入。
- **引擎部署（D-11）**：`.orchd/` 跟踪面对齐安装器契约（只豁免 `_master.json`、`shared/`、`IDEAS*.md`、`SKILL.md`、`__main__.py`、`rules/`、`VERSION`），引擎本体不入库；新项目引导顺序：基线提交 → vendor 引擎 → master 落项目内 → `init` → 提交 → `intake`（颠倒必失败）。
- **专有二进制闸门（D-10；例证来自真实项目 paper2）**：`task-origin-data-separation` 需在 Origin 中打开 `.opju` 判含/不含目标成分——agent 读不了专有二进制，属人工闸门。

## 能力注册表（可用性以磁盘为准）

"是否可用"**由对应路径是否在磁盘上决定，不靠本文件记忆**。agent 在依赖下列任一能力前，
必须先 `Test-Path <路径>` 确认；路径不存在即未建，禁止假设可用。
单元格内的字面竖线须写成 `\|` 转义（40 号行 `--domain material\|clinical\|…` 实证）；
`scripts/75-verify-selftest.py` 先占位再切列，并对账“肉眼行数 == 解析行数 == 8”，增删行同步改期望基线。

| 能力 | 落地路径 | 用途 / 何时用 | 状态 |
|---|---|---|---|
| 文献验真门控 | `scripts/35-refs-gate.py` | P3/P5：多索引交叉 + k 未命中计数 + 四态判定 + 缓存（需联网检索工具） | available |
| 无 AI 腔机检 | `scripts/40-style-check.py` | P4/P6：禁用词表/hedging 覆盖；`--domain material\|clinical\|social\|csml` 选量化信号组（缺省 material 口径） | available |
| 一致性检查 | `scripts/45-consistency-check.py` | P5：编号↔文献表、图表覆盖、术语归一、字数预算；`--stats` 另出统计报告 report-only 软提示面（p 无 CI/SE、显著无效应量、摘要数字无正文对应），命中只上屏 `[stats]` 行、不判 FAIL、不改退出码 | available |
| orchd 运行手册 | `references/50-orchd-runbook.md` | 每个任务执行时：取证规范、探针与反向控制、汇报纪律 | available |
| 出版社规则碎片 | `static/` + `manifest.yaml` | 四轴（出版社/引用制/报告规范/语言）命中；profile `fragments:` 声明即注入，未声明零回归 | available |
| 临床 profile | `profiles/10-clinical.yaml` | 多域适配验证（效应量与 CI 页级核对） | available |
| 社科 profile | `profiles/20-social-science.yaml` | 多域适配验证 | available |
| CS/ML profile | `profiles/30-cs-ml.yaml` | 多域适配验证（baseline 原文 + 复现声明） | available |

**建好后的动作**（一处改动，无需别处登记）：把该行 `状态` 改为 `available`，并在脚本行补一行
调用用法；磁盘路径本身即索引。已建能力见前文各索引（脚本/资源/profiles）。

**动工前先读规格**：注册表一行用途不足以实现。`35-refs-gate` 的规格在 `references/30-literature-pipeline.md` §1；
`40-style-check`、`50-orchd-runbook`、`static/` 碎片命中的规格在 `references/60-capability-specs.md` §1/§2/§3。
