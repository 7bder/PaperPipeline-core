# 已建能力规格（行为契约）

> **本文件解决什么**：能力注册表（`SKILL.md` §能力注册表）每行只有一句用途，**不足以实现**。
> 本文件把此前"只存在于对话或外部件"的设计落到磁盘，成为实现任务的**必读规格**。
> **规则**：任务 AC 与本文件冲突时以本文件为准（AC 是验收面，本文件是行为面）；两处都要改时改本文件并在 `CHANGELOG.md` 留决策。
> 已有规格的能力不在本文件重复：`35-refs-gate.py` → `references/30-literature-pipeline.md:11-19`；
> `45-consistency-check.py` → `references/40-draft-to-latex.md` §装配链 + 任务 AC 五条（有范围、算法细节由实现者按 AC 自定）。

## 0. 共同约束（三项能力都适用，勿逐处重述）

- 编码：脚本顶部 `sys.stdout.reconfigure(encoding="utf-8", errors="replace")`；读文本一律 `utf-8-sig`；`subprocess` 显式 `encoding="utf-8"`（`conventions.md §2`）。
- 不得落 `.pyc`：跨进程调用带 `-B`，importlib 前设 `sys.dont_write_bytecode`（`conventions.md §2`）。
- 只读承诺：对**任何论文项目目录**零写入；输出只到 stdout 或 `--out`（`conventions.md §2`）。
- 退出码：0 = 通过，1 = 判据命中（FAIL），2 = 用法错误/输入或词表缺失/schema 不合。**FAIL 优先于 usage-error**，不得把 1 类糊成 0（`conventions.md §3`，与 `70-verify.py` 一致）。
- 自测：新脚本自带 `--selftest`，合成用例、完全离线、非常驻文件（临时目录用毕即删）；**不**把守卫塞进 `scripts/75-verify-selftest.py`（那是基座与生成器守卫面，且是多任务共享单写者文件）。
- 命名：`scripts/{序号}-{用途}.py`，序号即职责段；`static/` 下**两类文件并存**——`manifest.yaml`（§3 碎片的索引，工具约定名不加前缀）与 `40-ai-cavity-wordlist.yaml`（§1 词表，阶段号前缀），二者互不索引：碎片命中算法**只读 `manifest.yaml`**，词表只被 `40-style-check.py` 读（`conventions.md §1`）。

## 1. `scripts/40-style-check.py`（无 AI 腔机检）

### 1.1 与既有门禁的分工（防重复建设）

| 面 | 归属 | 粒度 | 何时跑 |
|---|---|---|---|
| `forbid` / `forbid_regex` 断言 | `70-verify.py`（已建） | 单任务、只看该任务 `files_to_edit` | `orchd done` |
| 全稿扫描（词表 + 段落 hedging 覆盖） | `40-style-check.py`（本规格） | 跨段、整篇 md | P4 每节写完、P6 定稿前，人工触发 |

**40 不进 verify manifest、不改 `70-verify.py` 断言类型集合**（`conventions.md §3` 不得回退）。它是 pre-check 报告器，FAIL 由人处置后写进审计。

### 1.2 CLI

```
python -X utf8 scripts/40-style-check.py <文件或目录>...        # 目录递归收 *.md
python -X utf8 scripts/40-style-check.py --wordlist <yaml> ...  # 覆盖缺省词表（自测用）
python -X utf8 scripts/40-style-check.py --domain <组> ...       # 量化信号换组（material/clinical/social/csml；缺省 = 顶层 regex 即 material 口径）
python -X utf8 scripts/40-style-check.py --selftest             # 离线自测
```
输出每条一行，**必须含 `file:line`**：`<relpath>:<line>: [<category_id>] <term>`。相对路径以输入根为基准，不回显绝对路径。

### 1.3 词表 `static/40-ai-cavity-wordlist.yaml`（键即契约）

```yaml
version: 2
categories:
  - id: hype                    # 夸大、无检索支撑的新颖性宣称
    match: word                 # word=词边界（不区分大小写）；substr=原样子串
    terms: ["unprecedented", "groundbreaking", "revolutionary", "first ever"]
  - id: cavity                  # AI 套话/元话语
    match: phrase
    terms: ["delve into", "it is important to note that", "plays a crucial role",
            "in today's world", "comprehensive understanding"]
  - id: vague_attribution       # 无编号的泛指引用（违反落位机检第 1 条）
    match: phrase
    terms: ["studies have shown", "it is widely accepted", "researchers believe"]
hedging:                        # 只用于 §1.4 规则 3，永不作为禁用项报错
  terms: ["suggests", "indicates", "may", "might", "likely", "appears to",
          "consistent with", "within the measurement uncertainty"]
quantitative_signal:            # 判"量化结论句"
  regex: "[0-9]+(\\.[0-9]+)?\\s*(%|MPa|GPa|kV|mA|nm|um|μm|wt\\s*%|at\\s*%|eV|°C|mg|g/L)"
  domains:                      # F9 按域拆分：--domain <名> 选用其一**替换**顶层 regex（非叠加）；缺省用顶层 regex
    material: "[0-9]+(\\.[0-9]+)?\\s*(%|MPa|GPa|kV|mA|nm|um|μm|wt\\s*%|at\\s*%|eV|°C|mg|g/L)"
    clinical: "((OR|HR|RR)\\s*[=≈]?\\s*[0-9]+(\\.[0-9]+)?|95\\s*%?\\s*CI|p\\s*[<=]\\s*0?\\.[0-9]+|n\\s*=\\s*[0-9]+|[0-9]+(\\.[0-9]+)?\\s*%)"
    social: "((β|beta|α|alpha|κ|kappa|r)\\s*=\\s*-?[0-9]+(\\.[0-9]+)?|p\\s*[<=]\\s*0?\\.[0-9]+|n\\s*=\\s*[0-9]+|[0-9]+(\\.[0-9]+)?\\s*%)"
    csml: "(accuracy|F1|AUC|mAP|BLEU|p\\s*[<=]\\s*0?\\.[0-9]+|n\\s*=\\s*[0-9]+|[0-9]+(\\.[0-9]+)?\\s*%)"
```

**脚本内不得硬编码任何词条**：增删 `terms` 即改行为（AC3 以此验证）。`categories` 允许为 0..n 个；`hedging`/`quantitative_signal` 缺键 → rc=2 并报缺失键名。`domains` 可缺（缺省 = 顶层 `regex`）；有则须为非空对象（域名 → 正则串）且含 `material` 组（缺省口径的显式锚，缺即 rc=2）；`--domain` 给未知名 → rc=2 并列出可用组。

### 1.4 判定规则（三条，逐条对应 AC）

1. **禁用词**：任一 `categories[*].terms` 命中 → 输出该行 → 整体 rc=1。`match: word` 用 `\b` 边界（避免 `may` 命中 `meaning`）；`match: phrase` 不区分大小写子串。
2. **段落定义**：以空行分隔的块；跳过纯标题行（`#`）、表格块（连续 `|` 行）、围栏代码块。段落标识输出为 `para<idx>@<起始行号>`，`idx` 从 1 起按文档序。
3. **hedging 覆盖只对量化段生效**：段内量化式（缺省 `quantitative_signal.regex`，`--domain <名>` 时换用 `domains.<名>` 整组替换）命中 ≥1 次，且该段无任何 `hedging.terms` → 报 `<file>:<起始行>: [missing-hedging] para<idx>` → 计入 rc=1。**不含量化结论的段不因缺 hedging 报错**（否则等于要求全文冲淡措辞）。理由：hedging 是"部分支持→收窄措辞"的处置手段，见 `references/20-claim-framework.md:60`。

### 1.5 `--selftest` 最小用例面

临时目录合成 4 份样本 + 1 份临时词表：命中样本（rc=1 且行号正确）、干净样本（rc=0）、
量化段缺 hedging 样本（rc=1 且报告含 `para` 与起始行号）、坏词表样本（缺 `hedging` 键 → rc=2）。
`--wordlist` 指向临时词表跑一遍，证明词条来自文件而非常数。
**反向对照一条**：从临时词表删掉唯一命中项 → 同一输入由 rc=1 变 rc=0。

## 2. `references/50-orchd-runbook.md`（论文任务执行运行手册）

### 2.1 定位

引擎协议（`.orchd/SKILL.md:22-53` 红线 MUST NOT 1–14 / MUST 1–8）之上的**论文与本仓场景细则**。
**不复述引擎条款**（复述即造第二真源）；每条细则末尾注明承接对象：`（承接红线 N / MUST N / conventions §N / CHANGELOG D-N）`（AC5）。

### 2.2 必含四个二级标题（AC1，顺序按下列编号）

`## 取证规范` · `## 探针设计` · `## 反向控制` · `## 汇报纪律`

### 2.3 各节最低内容量（实现时逐条落到可执行形式，AC2）

| 节 | 条目下限 | 素材出处（真实病历，不另造） |
|---|---|---|
| 取证规范 | ≥8 条，格式「判据 → 可执行命令或 `file:line` → 反例症状」 | ①"已修/已登记"须给 file:line + 生效机制链（`conventions.md §4`）；②含中文文本禁 shell 内嵌 python 改写（2026-09-24 反引号被 bash 吃掉、静默毁整份文件）；③orchd 协议命令**不接管道**（cp936 截 JSON），改写 `<临时目录>/*.json` 再读；④能力可用性以磁盘为准，引用前 `Test-Path`（`SKILL.md` 能力注册表）；⑤Windows 量中文/量文件五类假信号（管道 GBK 漏计、CRLF 假漂移、相邻 Edit 吞行、bash `/tmp` ≠ python `/tmp`、`du` 虚高）；⑥done 前 `status --audit-task` 清零声明文件告警（MUST 6）；⑦修一条=列出该病灶全部同型位置+每处一条反向对照（未列全即未闭环）；⑧元守卫行为级（合成正例必红且点名，字样级不算） |
| 探针设计 | ≥3 条 | 临时注入观察法；**还原只用 Edit 写回 + `sha256sum -c` 校验**，不得 `git checkout`（红线 1）；探针文件出仓前删除并核 `status` |
| 反向控制 | ≥2 个可套用模板（AC3） | 模板 A 断言拆除：把 `contains` 目标串改一个字符 → `70-verify.py` 必须 rc=1，还原 → rc=0。模板 B 词表摘除：删 `40` 词表中唯一命中项 → 由 rc=1 变 rc=0，证明报告由词表驱动而非常数。可选模板 C：manifest 某任务条目清空四段 → 生成期 die |
| 汇报纪律 | ≥4 条 | 每轮"改了什么 + 实测证据 + 下一项"；子代理/脚本报告未落盘核实不得转述为完成；不得替用户 `intake`/`confirm`/`drop`/`claim`（**引擎红线** 6/7/14：禁止自动摄入 / auto-claim / 无候选自行领任务——注意与 SKILL 协同契约第 6 条「踩坑分层沉淀」是两套清单，不互相指代）；档位逐项放行节奏（`CHANGELOG.md` D-13） |

### 2.4 显式禁止清单（AC4，原文三项，另可增不可减）

不要求手动 git 写操作 · 不替用户 intake/claim · 不替用户 confirm/drop 选题。

### 2.5 交付形态

纯文档，**无 `verify_command`**（豁免依据：拆解指南 §5.5.4；validate 的 2 条 E022 warning 即此）。
审查者按 AC 机检：`grep -c '^## '` = 4、`grep -c '承接'` ≥ 条目数、禁止清单三串必须命中。

## 3. `static/` + `static/manifest.yaml`（出版社/制式规则碎片命中）

### 3.1 目的与目录形态

跨出版社、跨刊的共性条款**一处写、多档用**；换刊 = 改 profile 声明（`fragments:` + `axes:`），不改脚本（锚 `SKILL.md`「profiles 体系」章；行号曾漂移，F13b 去行号化）。

- `static/manifest.yaml`：唯一索引（工具约定名，不加前缀）。
- 碎片本体：`static/<轴值>-<主题>.md`，**平铺、ASCII kebab-case**。
  本规格**取代** `references/40-draft-to-latex.md` 中 `static/publisher/<name>.md` 的旧口径——碎片不止出版社一个轴（引用制式、报告规范、语言都可能是共性），子目录按出版社分层会把跨刊共性条款塞错位置。该文档的相应改动归 `task-root-docs-drift-fix`。

### 3.2 `manifest.yaml` schema（键即契约）

```yaml
version: 1
fragments:
  - id: elsevier-numbered              # 唯一，profile 按此声明
    fragment: elsevier-numbered.md      # 相对 static/，磁盘必须存在（缺 → 生成期 die）
    axes:                               # 键 ⊆ {paper_type, evidence_form, publisher,
                                        #    citation_style, language, reporting}；
                                        #    值为标量或列表，列表按成员关系匹配
      publisher: elsevier
      citation_style: numbered
    note: "编号制 + 数字范围 + DOI 列法"  # 可选，一行给人看
```

- `axes` 允许键集合以 profile 实际键为准：`paper_type / evidence_form / publisher / language / reporting`
  （`profiles/10-materials-chemistry.yaml` 的 `axes:` 块）。引用制式以 `citation_policy.style` 为准（同文件 `citation_policy:` 块；F7 后 `axes.citation_style` 亦声明，用于碎片 axes 校验；锚块名而非行号），
  故本规格新增可选轴键 `citation_style`（`reporting` 已存在、值为列表，空列表即不参与比较）；
  领域 profile 想用该轴做一致性检查就在 `axes:` 补 `citation_style: <值>`，不补则该轴不参与比较（不报错）。
- 每条碎片 `axes` 至少 2 个键（AC1），少于 2 键 → 生成期 die 并报碎片 id。
- 条目数 ≥3（AC1），首个必须是 `elsevier-numbered`。
- **`static/40-ai-cavity-wordlist.yaml` 不进 `manifest.yaml`**：它是 `40-style-check.py` 的独立输入（§1.3，键即
  `version/categories/hedging/quantitative_signal`，与碎片 schema 无共同字段），不是注入 `rules.fragment.md`
  的规则碎片。两个任务向 `static/` 各放一类文件——**碎片（md，被 manifest 索引）** vs **工具词表（yaml，自成一类，
  不被 manifest 索引）**；生成器读到词表即错。

**强制点（不是描述，是 `load_fragment_manifest()`/`fragment_blocks()` 的判据；违反即 die、rc=2、不落半份生成物）**

| # | 判据 | 违反时的表现（返工前） |
|---|---|---|
| F1 | `id` 与 `fragment` 必须是**非空字符串** | `static_dir / frag` 抛 `TypeError` → rc=1 traceback（以崩代拒） |
| F2 | 索引里全部 `id` 为字符串，"未知 id"消息才允许 `sorted(index)` 构造 | 混入整数 id 时**在报错当场**崩（`sorted()` 混合类型） |
| F3 | `fragment` 必须是 `static/` 下的**裸文件名**（无 `/`、`\`、盘符、不以 `.` 开头）且以 `.md` 结尾，解析后仍在 `static/` 内 | `../profiles/00-base-empirical.yaml`、绝对路径、子目录、`.txt` 一律静默接受，把**别的文件**当规则注入且零提示 |
| F4 | 碎片正文必须是合法 UTF-8（读侧 `utf-8-sig`） | GBK 正文 → `UnicodeDecodeError` traceback（rc=1），或乱码进规则片段 |
| F5 | 碎片正文**不得含** `<!-- fragment:` | 拼接层 marker 与正文 marker 混淆，下游按 marker 计数的一致性判据失真 |
| F6 | profile `fragments` 列表内**不得重复声明**同一 id，元素必须全是字符串 | 同一片注入两次；非字符串元素在 `fid not in index` 处 `TypeError` |
| F7 | 诊断消息（含 die 与 warn）中的路径一律经 `_disp()` 只出末两段，不回显条目/声明本体 | 本机绝对路径进出生输出（与 CHANGELOG D-14 同族） |

以上七条由 `75-verify-selftest.py` 的"规则碎片守卫"段逐条把钉（每条含**反向对照**：合法输入必须仍 rc=0/逐字节注入成功，未声明路径不得因新校验产生任何失败面）。


### 3.3 命中与注入算法（`scripts/30-gen-proposals.py`，装配点 `rules_fragment()` / `fragment_blocks()` / `load_fragment_manifest()`；行号以磁盘为准，F13b 去行号化；任何 die 都发生在建目录之前）

1. profile 新增可选顶层键 `fragments: [<id>, ...]`；缺省 = 空。
2. `fragments` 缺省或为空 → **完全不读 `static/manifest.yaml`**：不产生新失败面，`rules.fragment.md` 与改动前**逐字节一致**（AC2 以 sha256 比对验证）。
3. 声明的 id 不在 manifest → die，消息含该 id 与已知 id 列表，rc≠0（AC4）。
4. 输出顺序 = profile 声明顺序；每个碎片写出：
   ```
   <!-- fragment: <id> -->
   <碎片正文原样全文>
   ```
   marker 独占一行、紧跟正文、碎片之间留一个空行。**不得折叠缩进、不得去空行、不得加前缀**——AC3 的判据是"碎片正文首行原样出现 + marker 行存在"。
   "原样"是**语义原样**：读侧走 universal newlines、写侧落平台换行，故 CRLF 碎片注入后按 LF 归一，判据不做逐字节等（要逐字节比请先归一换行）。
5. `axes` 只做一致性提示：与 profile `axes` 同键值不符时打印 warning（含 id 与不符键名），**不改退出码**（自动匹配不是本能力的激活路径，声明即命中）。

### 3.4 首个碎片内容要求（`static/elsevier-numbered.md`）

只写经真实定稿验证的口径（编号制 `[1]`、正文引用形式 `Ref. [n]`/上标、数字范围合并规则、DOI 是否必列、LaTeX 侧 `thebibliography`/`\bibitem` 约定、Graphical abstract 与 Highlights 有无），**逐条须来自某个真实项目的定稿验证并可回指出处（项目名不进碎片正文，出处记 `CHANGELOG.md` 沿革条目），不得写教科书式通用常识**。每条须可被 45/70 类机检或人工一眼判。

### 3.5 守卫面（进 `scripts/75-verify-selftest.py`，AC5）

三条：未声明零回归（hash 相等）、声明后 marker+首行同时出现、未知 id 退出码非 0 且 stderr/stdout 含该 id。
其中"未声明零回归"与"未知 id die"属**否定条件**，缺一即视为守卫不成立。
此外 §3.2 的强制点 F1–F7 各有一条守卫（含"合法输入仍成功"的反向对照，以及一条子进程级判据：
生成器复制到临时包后再跑，因为 `STATIC_DIR` 由脚本自身 `__file__` 推出，不复制就测不到造的坏索引）。
注意：`75` 与 `SKILL.md` 均为多任务共享单写者文件，同一时刻只允许一个在途写者。

### 3.6 建成后的收尾（不在本任务）

profile 中与碎片重复的出版社共性条款应移入碎片、profile 只留领域差异；`SKILL.md` 注册表该行 `状态` 改 `available`（`conventions.md` 单写真源：一处改动，无需别处登记）。
