# paper-pipeline

> 把"**手上已有一堆研究数据**"变成"**一篇可以直接投出去的英文 SCI 稿件**"的全套工作方法，
> 封装成任务编排引擎 [orchd] 的一个原生技能。

这是一个**技能开发工作空间**，与本机任何论文项目（无论叫 paper1 还是别的）
**无 git、无路径、无状态耦合**：论文项目里的 orchd 引擎不读本目录；本目录也不向论文项目写任何东西，
除非某个脚本被显式以路径参数指过去。生成物由你（或引擎命令）手动投喂进论文项目。
技能的**发布面清单**以 `MANIFEST.in` 为单一真源，安装方式见下方[安装与发布边界](#安装与发布边界)。

---

## 它解决什么问题

orchd 这类任务引擎只给你一套状态机（claim → done → review）和 git 纪律，但它**不知道写论文这件事**：
不知道论文该分几步、每步该产出什么、什么算"写完了"、文献怎么找才不浪费、数据口径怎么才不漂移。

而真实写一篇论文（从学位论文/项目数据改写成 SCI）会反复踩同一批坑
（下表症状均来自真实项目实测，仅作例证）：

| 坑 | 真实症状 |
|---|---|
| **库存病** | 文献库攒了 74 条，正文实际只引 49 条，25 条白攒——因为检索时没有"到底需要什么证据"的清单 |
| **临时凑引病** | 写到 Discussion 才发现某句没人支撑，临时搜一篇往上贴，结果 over-claim、引用落位失控 |
| **口径漂移** | n=1 的数据敢写 significantly，没测 EIS 敢给阻抗结论，纵轴截断夸大差异 |
| **返工地狱** | md 改一遍、tex 改一遍，两边分叉；投稿前才发现编号和文献表对不上 |

paper-pipeline 把这些从真实论文项目中踩坑沉淀下来的打法做成可复用技能
（各决策的项目出处统一记录在 [`CHANGELOG.md`](CHANGELOG.md) 的设计决策条目，D-1 起连续编号）。
它只做三件引擎不做的事：**领域知识**（`profiles/`）、**可机检的验收判据**（`scripts/`）、
**踩过的坑**（`references/` + 决策记录）。

## 核心亮点

1. **顺序铁律：先需求单，后采购，再落位。**
   先用 claim 框架（P2）把"这篇文章每个论点需要什么证据"列成一张需求单，
   再按单子去定向检索（P3），最后写作时把引用钉进句子（P4）。
   禁止"先广搜一圈再找用途"——这是库存病和临时凑引病的根。

2. **四种入口，适配你的真实处境。**
   不是只有"有 idea 做实验"这一种正统路径——大多数人是数据已经有了、不知道讲什么故事。
   `data-first`（有数据找故事）、`idea-first`（有问题补实验）、`multi-paper`（多组数据拆多篇）、
   `inherited`（故事线已定直接干），P2 之后四条路汇合成同一条管线。

3. **profile 驱动，加一个领域 = 加一个 YAML。**
   所有学科差异（证据形态、禁止的论断、必检清单、图件要求、引用策略）都写在 profile 里，
   用 `extends` 继承基类。例证（真实项目 paper2）：把 evidence_form 从"普通实验"换成
   "Origin 工程 + 有 EIS"，就自动多出"Origin 数据分离导出""补实验裁定"两个任务，并把
   "禁止阻抗结论"改成"阻抗结论必须有等效电路拟合依据"——**不改一行代码**。
   已随技能发货的领域档见下方目录结构；新增领域档时 `extends` 基类、只写学科差异。

4. **每个任务都有机器可判的验收。**
   不是"写完了就行"，而是每个 done 之前由 `70-verify.py` 跑断言：
   产物存在且非空、不含 TODO/AUTHOR CONFIRM 残留、字数在预算内、引用编号连续、
   JSON 必填字段齐全……判据即契约。

5. **md 单一真源，LaTeX 只是派生物。**
   正文只在 `30-manuscript/*.md` 里改，`.tex` 由脚本生成（头部标 `GENERATED — do not edit`）。
   这样"编号↔文献表一致""图表全覆盖""术语归一"这些检查才能全部脚本化
   ——出处项目（paper1）的定稿因此一次都没在编号上返工。

6. **严守边界：只生成，不替你做主。**
   它生成 proposals 给引擎校验，但**注册任务永远由你执行**；选题、拆几篇、选哪个刊、
   做不做补实验、投稿——这些策略判断全部是人工闸门，agent 不替你拍板。

## 一次完整使用长什么样

**示例（真实项目改编，人机对话示意）**：

```
你："我手上有 KH-550 改性水性聚氨酯的防腐数据，想写一篇 SCI"
 │
 ├─ 1. agent 判断 entry.mode（你有几组数据？有没有 idea？）→ 通常 data-first
 │
 ├─ 2. 选/写 profile（profiles/10-materials-chemistry.yaml），跑生成器：
 │      python scripts/30-gen-proposals.py --profile profiles/10-materials-chemistry.yaml --out <论文项目>/
 │      python scripts/30-gen-proposals.py --profile profiles/<x>.yaml --check --project <论文项目>   # orchd validate 必须通过
 │
 ├─ 3. 你在论文项目里执行注册： orchd intake / amend --register   ← 人工闸门，agent 不代劳
 │
 ├─ 4. orchd 引擎接管，逐任务 request → claim → done → review
 │      每个 done 前自动跑 70-verify.py 机检；agent 负责数据核对、文献验真、逐节写作、合稿
 │
 ├─ 5. 你在人工闸门处介入：选故事线 / 选刊 / 开 Origin .opju / 裁定补不做实验
 │
 └─ 6. P6：六层评审 → 定稿 → 按期刊模板生成 LaTeX → Tectonic 构建 PDF
        ↓
      可投稿 PDF
```

产物目录按阶段编号（`00-admin/` `10-data/` `20-lit/` `30-manuscript/` `40-figures/`
`50-review/` `60-latex/` `70-tools/` `90-notebooks/`），看文件名就知道在第几阶段。

## 目录结构

```
paper-pipeline/
├── SKILL.md                  技能入口（机器读：何时触发、阶段序、协同契约、硬约束）
├── README.md                 本文件（人读）
├── ROADMAP.md                研发路线图（开发层，不入发布面）
├── AGENTS.md                 orchd AI 协作入口指针（开发层，不入发布面）
├── MANIFEST.in               发布面清单（单一真源；由发版流程维护）
├── CHANGELOG.md              设计决策记录 D-1…D-23（开发层备查，不入发布面）
├── profiles/                 领域档（四轴：论文类型×证据形态×出版社×语言/报告规范）
│   ├── 00-base-empirical.yaml        通用基类：证据口径 + back-matter + P-1 资产规划
│   ├── 10-materials-chemistry.yaml   材料/化工/涂层（源自真实项目 paper1，回归基线档，24 任务）
│   ├── 10-clinical.yaml              临床档（效应量 CI 页级核对 / 伦理注册 / CONSORT-STROBE，22 任务）
│   ├── 20-social-science.yaml        社科档（抽样框代表性 / 信效度 / κ-α 编码一致性 / 因果措辞，23 任务）
│   └── 30-cs-ml.yaml                 CS/ML 档（baseline 原文 + 复现声明，24 任务）
├── scripts/                  判据与生成脚本（全部离线、秒级）
│   ├── 30-gen-proposals.py    profile → proposals/master/rules/断言片段
│   ├── 35-refs-gate.py        文献验真门控（多索引交叉 + 四态判定 + 缓存）
│   ├── 40-style-check.py      无 AI 腔机检（词表驱动）
│   ├── 45-consistency-check.py 编号/图表/术语/字数一致性
│   ├── 70-verify.py           判据基座（manifest 驱动的结构化验收）
│   ├── 72-assemble-draft.py   确定性合稿（md 单一真源 → draft）
│   ├── 72-compose-raster-figures.py  光栅图版合成
│   ├── 72-latex-build-check.py  LaTeX 装配回读校验
│   ├── 75-verify-selftest.py  基座自测（合成用例 + 生成器/碎片/编码/注册表守卫）
│   ├── 78-assertions-selftest.py  profile 实质断言棘轮守卫
│   └── 76-doc-refs-selftest.py    本仓文档卫生自检（开发层，不入发布面）
├── assets/                   投喂模板（proposal 模板、verify manifest 模板）
├── references/               运行手册（按阶段号命名，见 SKILL.md 资源索引）
├── static/                   跨出版社/制式规则碎片（manifest.yaml 索引，profile 按需声明注入）
├── build/                    本机生成物沙盒（不入库；随时可重生成）
├── reports/                  本机审计档案（不入库）
└── .orchd/                   开发编排引擎工作区（开发层，不入发布面）
```

## 从零安装（手动 / Agent）

一套命令从空目录装到可 `intake` 的 orchd 论文项目。两条外部依赖都来自 GitHub，
装完克隆副本即可删（`--cleanup` 自动删）。

**前置条件**：`git`、`python`（≥3.10）、`PyYAML`（生成器依赖：`pip install pyyaml`）。

**① 安装 orchd 引擎**（论文项目的任务状态机 + git 纪律；仓库 <https://github.com/7bder/orchd-core>）：

```powershell
git clone https://github.com/7bder/orchd-core.git $env:TEMP\orchd-core
python $env:TEMP\orchd-core\install.py <论文项目> --agent --cleanup
```

**② 安装 paper-pipeline**（本技能；发布仓 <https://github.com/7bder/PaperPipeline-core>。skill 模式装进宿主
agent 技能目录，一次即可）：

```powershell
git clone https://github.com/7bder/PaperPipeline-core.git $env:TEMP\PaperPipeline-core
python $env:TEMP\PaperPipeline-core\install.py <技能目录> --mode skill --cleanup
```

本机已有源码时免 clone：`python <PaperPipeline-core 仓库路径>\install.py <目标> --mode <skill|project> ...`。

**③ 新论文项目装配（最简流程，顺序不可颠倒）**：

> 注意：①② 的 `--cleanup` 会删掉临时克隆，故 ③ 一律引用**持久路径**（`<技能目录>` = ② 的安装目标；
> `<orchd-core 仓库路径>` = 本机 orchd 源码/持久克隆），不得再引用被删的 `$env:TEMP\...`。

```powershell
cd <论文项目>
git init; git add -A; git commit -m "baseline"
python <orchd-core 仓库路径>\install.py . --agent                              # 引擎（本机源码或非临时克隆）
python <技能目录>\install.py . --mode project --profile <技能目录>\profiles\<档>                    # 判据基座（不可跳过）
python -X utf8 <技能目录>\scripts\30-gen-proposals.py `
  --profile <技能目录>\profiles\<档> --out .\build --verify-layout standard   # proposals + 片段（materials 冻结侧档必须加 standard 重写为 70-tools）
python -X utf8 -c "import json; frag=json.load(open(r'build/_master.fragment.json',encoding='utf-8-sig')); live=json.load(open(r'.orchd/_master.json',encoding='utf-8-sig')); live.update(frag); json.dump(live, open(r'.orchd/_master.json','w',encoding='utf-8'), ensure_ascii=False, indent=2)"   # master 落项目内（保留 shared）
Move-Item .\build\verify_manifest.fragment.json .\70-tools\71-verify-manifest.json      # 断言片段改名为项目 manifest（install.py 只 vendor 模板 71-verify-manifest.template.json）
python .orchd\__main__.py init
python .orchd\__main__.py validate     # errors=0（E029 为警告、E037 为阻断级，见 CHANGELOG D-9）
git add -A; git commit -m "vendor + proposals"
python .orchd\__main__.py intake       # 人工闸门：只能你执行
```

> 合并前可先零写入预检 master 与引擎版本兼容：`30-gen-proposals.py --profile profiles/<档> --check --project <论文项目>`。

**④ 装完验证清单**：`.orchd\__main__.py` 在盘、`70-tools\70-verify.py` 在盘、
`70-tools\71-verify-manifest.json` 在盘、`validate` errors=0、`status` 任务全 pending。

**手动 vs Agent**：手动照抄上述命令即可；Agent 代执行时把「目标 + 步骤要点」交给 agent
（本 README 与 SKILL.md 即操作依据），由 agent 逐条执行并核对，`intake` 停在人工闸门等你确认——
本技能约定 **agent 永不代注册**（见[人工闸门](#哪些事必须你亲自做人工闸门)）。

## 与 orchd 的接法（唯一正确姿势）

1. 跑生成器：`python scripts/30-gen-proposals.py --profile profiles/<x>.yaml --out <输出目录>`
   （输出目录直接放目标论文项目内，或生成后拷入）
2. **装配判据基座（不可跳过）**：`python PaperPipeline-core/install.py <论文项目>/ --mode project --profile profiles/<profile 文件名>`
   ——把 `70-verify.py`、`71-verify-manifest.template.json`（**模板**，项目侧由断言片段 `verify_manifest.fragment.json`
   改名为 `71-verify-manifest.json`）与 LaTeX 三件套 vendor 进项目 `70-tools/`。跳过此步的话，
   任务 done 时 `verify_command` 引用的脚本在项目里不存在，E014/E037 必撞墙。
   两种安装模式的完整说明见下方[安装与发布边界](#安装与发布边界)。
3. **master 落项目内**：把生成物 `_master.fragment.json` 并入 `.orchd/_master.json`（保留引擎的
   `shared`，project/modules/tasks 用片段覆盖；具体命令见[从零安装](#从零安装手动--agent)③），
   再把 `verify_manifest.fragment.json` 改名为 `71-verify-manifest.json` 放入 `70-tools/`、
   `rules.fragment.md` 并入项目 `rules/`。
4. 在**目标论文项目**内：`python .orchd/__main__.py init` 后 `python .orchd/__main__.py validate`
   （必须 errors=0），随后 `git commit`（引导顺序：基线提交 → 引擎 → master 落位 → init → 提交 → intake，颠倒必失败）。
5. **由你**执行注册：`intake` / `amend --register`（本技能永不代注册）
6. 之后全程走引擎：`request → claim → done → review → merge`，判据脚本经 `verify_command` 调用
7. 踩坑按层回灌、不另建自由文档：**引擎/平台/配置层**用 `python .orchd/__main__.py lesson ...`（写 `lessons.jsonl`）；**领域方法论与论文流程**沉淀到 `CHANGELOG.md` / `references/`

## 哪些事必须你亲自做（人工闸门）

| 时机 | 你做什么 | agent 做不了什么 |
|---|---|---|
| 判断入口模式 | 告诉它你有几组数据、有没有 idea | 不知道你的实验进展 |
| multi-paper 拆分 | 拍板发几篇、先后顺序、共享数据边界 | 发表策略是你的决定 |
| 注册 proposals | 你跑 `orchd intake` | agent 不替你注册 |
| idea-first 做实验 | 你去实验室 | agent 不能跑实验 |
| 专有二进制 | Origin `.opju`、仪器软件导出由你打开确认 | agent 读不了专有格式 |
| 选刊 | agent 给三档建议，你定投哪个 | 期刊匹配是策略判断 |
| 投稿 | 你提交、回复审稿意见 | agent 不替你投稿 |

其余（数据核对、文献检索验真、逐节写作、合稿、引用审计、LaTeX 排版、机检）都由 agent + orchd 自动推进。

## 安装与发布边界

**发布面以 `MANIFEST.in` 为单一真源**：清单内 = 发布，清单外 = 开发层（清单完整性由 76 号 G7 守卫机检）。
安装器 `install.py` 按清单装配，两种模式：

```bash
# skill 模式：整套发布面装进宿主的 agent 技能目录
git clone https://github.com/7bder/PaperPipeline-core.git && python PaperPipeline-core/install.py <技能目录> --mode skill --cleanup
# project 模式：判据基座 vendor 进论文项目（70-tools/ 规范路径）
python PaperPipeline-core/install.py <论文项目>/ --mode project --profile profiles/<profile 文件名>
```

> project 模式即上方[与 orchd 的接法](#与-orchd-的接法唯一正确姿势)第 2 步的装配动作，**不可跳过**。

**开发层（不入发布面）**：`.orchd/`（开发编排引擎工作区）、`build/`（生成物沙盒）、
`reports/`（审计档案）、`scripts/76-doc-refs-selftest.py`
（本仓文档卫生自检——机检的是本仓自己的台账与引用，装出去无意义）、
`scripts/79-release-publish.py`（发版器——开发仓→组装→双仓推送，推 tag 由 `.githooks/pre-push`
自动触发，发行版不带发版器）、`.githooks/`（发版同步 hook，开发仓本地生效）、
仓根维护件
`.gitignore`（本仓忽略规则）、`.gitattributes`（hook 行尾契约，保 pre-push 为 LF）、
`ROADMAP.md`（研发路线图）、`AGENTS.md`（orchd 协作入口指针）、
`CHANGELOG.md`（设计决策史，开发层备查）。

### 自动发版（开发仓 → 组装 → 双仓推送）

与 [orchd-core](https://github.com/7bder/orchd-core) 同构的发版通道：发布版本 = 推 tag。
开发仓是开发面，发版时按 `MANIFEST.in` 纯白名单组装**最小纯净版**（只含发布面，
开发层物理上不进组装流），提交到常驻发布仓克隆，随后**双仓推送**（开发仓 main +
发布仓 main + 同名 tag）；使用者 clone 发布仓即得发行版。

```bash
# 一次性启用发版 hook（本地配置，不随 clone 传播；在仓库根执行）
git config core.hooksPath .githooks
# 正常发版：打 tag 并推送，hook 自动组装并推双仓（同步失败则本次 push 被拒）
git tag v0.4.0 && git push origin v0.4.0
# 预览组装（不写发布仓、不联网）：先看产物与文件数
python scripts/79-release-publish.py v0.4.0 --dry-run
# 手动发版（与 hook 同语义，hook 未启用时用；TAG 缺省为最新 tag）
python scripts/79-release-publish.py v0.4.0
```

前置：开发仓与发布仓工作树干净、发布仓在 main 分支、`TAG` 与 `VERSION` 首行一致、
`MANIFEST.in` 在盘——任一不满足即 rc=2，不碰发布仓。发布仓须为**常驻本地克隆**
（缺省为开发仓同级 `../PaperPipeline-core`，`--dist-dir` / `PP_DIST_DIR` 可覆盖；
远端名缺省 origin，`--dist-remote` / `--main-remote` 可覆盖）；推送任一步失败 rc=1
不伪装成功。开发层（`.orchd/` 等）由白名单机制物理隔离，`79` 号自测含"开发层缺席"反向断言。
后五者与 76 号 `DEV_TIER` 中声明的开发层清单**一本账**（均未列 MANIFEST；仓根未归类跟踪件由 G7 对账判红）。
本目录**永不承载论文项目执行件**：试点与生成一律在独立项目目录进行，`build/` 只放生成物沙盒。

## 开发与回归

- **回归基线**：真实项目（paper1）的已完工 proposal 集与 verify manifest 是"标准答案"。
  任何生成器改动都必须能对真实项目重生成等价集合且 `validate` 通过（`--regress --project` 比对）。
- **自测**（改基座或换 profile 后必跑，两条命令按原文逐条复制执行均应退出码 0；
  守卫条目随能力演进增删，不在此绑定具体数字）：
  - `python -X utf8 scripts/75-verify-selftest.py`——合成控制用例（每个断言类型一对"应过/应失败"）+ 生成器/碎片/编码/注册表守卫面；**引擎未接入（如干净克隆，缺 `.orchd/orchd/`）时该段显式 SKIP 并 rc=0**，不判 FAIL
  - `python -X utf8 scripts/78-assertions-selftest.py`——profile 实质断言棘轮（下限 + 形状 + 正反控制 + 反向对照）
- **多领域验收（唯一可信证明）**：用一个**非材料领域**的最小真实项目跑通 `validate` + 1–2 个真任务闭环；不通过不发布。

## 当前状态

**已完成**：生成器 + 判据基座 + 自测；真实项目回归与试点验证通过（paper1 回归、paper2 试点，见 `CHANGELOG.md`）；
四种入口模式落地；五个领域档（材料/临床/社科/CS-ML/试点）；设计决策沉淀于 `CHANGELOG.md`。

**待建能力**：统一登记在 [`SKILL.md`](SKILL.md) 的「能力注册表」中，带落地路径与状态（planned/available）；
可用性以磁盘文件是否存在为准，建好即把状态改为 available，不在此重复维护。

**待人工推进事项**：正式引导下一个论文项目（需你指定项目目录）。

## 设计决策

所有"为什么这么做"的来龙去脉（含 orchd 引擎实测出的 bug、迁移血的教训、全文获取路线取舍）
都记录在 [`CHANGELOG.md`](CHANGELOG.md) 的设计决策条目里——有疑问先查那里，不要凭印象重走老路。
