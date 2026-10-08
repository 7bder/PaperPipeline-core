# 立项交互：从模糊主题到骨架契约（idea → skeleton）

回答"idea 与框架设计怎么借引擎 + skill 协作"。阶段号与 SKILL.md 的阶段序表同一口径（P0/P1/P2 → 执行期 P3–P6）。

## 三段式，各段有不同载体与人工闸门

| 段 | 干什么 | 载体（引擎原生） | 产物 | 闸门 |
|---|---|---|---|---|
| **P0 收敛**（=SKILL 的 P0） | 苏格拉底式追问，把模糊主题收成可研究问题（研究对象/变量口径/机制/读者/产出类型） | `orchd idea propose`（status: study） | `00-admin/00-plan.md`：候选标题、目标刊排序、证据路线、缺口、**不做清单** | **你 `idea confirm`** 才进管线 |
| **P1 证据可行性与边界裁定**（=SKILL 的 P1） | 扫已有数据"能支撑什么、不能支撑什么"，把边界写成硬契约 | 同上（或独立 idea 条目） | `10-data/10-audit.md`：缺口清单（G1…Gn + 逐条处置）、证据路线（Route A/B）、hedging 口径 | 你裁定边界 |
| **P2 claim 框架与骨架契约**（=SKILL 的 P2） | 建论证环与 claim 骨架（需求单），逐节列出论点/证据/边界/字数预算/图表清单 | 转为 orchd 任务（`task-claim-map` / `task-skeleton-contract`） | `20-lit/20-claims-map.md` + `00-admin/02-skeleton.md`、`01-meta.json`（**后续全部写作任务的 AC 来源**） | 引擎门禁 + 审查 |
| **P3+ 执行** | 任务链跑起来（=SKILL 的 P3–P6：定向文献→撰写→合稿审计→评审定稿排版） | `request → claim → done → review` | 各阶段产物 | 引擎门禁 |

## 为什么 P0/P1 必须走 idea 通道

1. **引擎原生**：`idea propose` 是引擎唯一的"非任务写入通道"，天然对应"讨论"这一阶段；`confirm/drop` 只归用户，边界干净。
2. **可追溯**：条目标题内嵌 `（id: slug）` 是引擎校验锚点（缺 id 会被 `missing_idea_id` 拒），后续任务用 `source` 引用它，形成"讨论 → 任务"的可审计链。
3. **不污染状态机**：讨论阶段没有 files_to_edit、没有 claim、不会产生空转任务；定不下来就不注册。

## 交互形态（经验证）

- **每轮 3–5 个问题**，不要一次问 20 个（一次问太多必然糊）。
- 每轮固定产出**三张清单**供你勾选/驳回：**候选 claim**、**候选缺口**、**候选边界**。
- 收敛规则：连续两轮无新增 claim/缺口 → 认为收敛，进入 P1 边界裁定。
- **边界先于写作**：本项目最有价值的一步就是把"不补 EIS/极化/FTIR/DLS、盐雾 216 h（节点 0/72/144/216）、除凝胶率 n=3 外全部 n=1、不宣称全局最优"写进契约；此后 20 个任务的 AC 全部受它约束，**从未越界**。
- **作者侧事实前置收集**（本项目最大的延迟来源）：仪器型号、配方与助剂、测试标准与时长、重复次数、口径"标准规定值 vs 实测值"——**必须在 P1 就问全**，否则会像本项目一样拖到合稿才暴露，卡住定稿（10 项待确认里有 3 项属此类）。

## 编译成任务集

`python scripts/30-gen-proposals.py --profile profiles/<x>.yaml --out <输出目录>`（离线跑；`--project`/`--check`/`--regress` 用法见 `--help`）→

- `proposals/*.json`（字段对齐 orchd schema，`source` 写 profile 指纹）
- `_master.fragment.json`（项目信息 + 模块声明 `mod-data/mod-lit/mod-draft/mod-fig/mod-final` + 任务图；模块粒度约定见引擎 vendor 文档 `.orchd/docs/decomposition-guide.md`，该文件属目标项目而非本 skill）
- `rules.fragment.md`（域口径规则片段）、`verify_manifest.fragment.json`（各任务的机检断言）

投喂顺序：`orchd validate` → **用户注册**（`intake` / `amend --register`）→ 引擎接管。

## 反模式（不要做）

- 用 skill 自己去写 `.orchd/_master.json`（绕过 `validate`，schema 漂移无法察觉）。
- 讨论阶段就 claim 任务（产生"claimed 但无实质工作"的僵尸任务，且会挡住文件）。
- 把边界写在正文里当"限制段"而不是写进契约（那样每个任务都得重新判断一次，必然漂移）。
