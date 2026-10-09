# 论文任务执行运行手册（orchd WORKER 协议之上的场景细则）

> **定位**：引擎条款在 `.orchd/SKILL.md:22-53`（红线 MUST NOT 1–14 / MUST 1–8），本文件**不复述**它们，
> 只补两类内容：① 论文任务（P-1…P6）执行期特有的取证与探针要求；② 本仓与 Windows 环境下已付出过代价的踩坑口径。
> **冲突处理**：与引擎红线冲突时以引擎为准；与 `references/60-capability-specs.md §2` 冲突时以规格为准并回改本文件。
> 规格：`references/60-capability-specs.md` §2；每条末尾的 `（承接 …）` 指向它的真源（AC5）。

## 取证规范

**通则**：一条取证 = 判据 → 可执行命令或 `file:line` → 反例症状。三样缺一即视为纯散文，不算取证。

1. **判据：任何"已修 / 已登记 / 已核对"都要给 `file:line` + 生效机制链，且必须在说出之前实测一次。**
   命令：`grep -n "<你声称已写入的字符串>" <文件>`（命中即贴 `文件:行号`）；机制链另附"谁读它、读了会改变什么行为"。
   反例症状：口头"已登记"而 `grep` 零命中；或字符串在盘上但没有任何脚本/任务读它（登记 = 写了没人读的废纸）。
   （承接 `conventions.md §4` 证据要求条）

2. **判据：含中文的文本文件只用 Edit/Write 工具改，不用 shell 内嵌 `python -c` 改写；改后只做只读核验。**
   命令（只读核验）：`python -X utf8 -c "import pathlib;t=pathlib.Path(r'<文件>').read_text(encoding='utf-8-sig');print(t.count('<关键串>'), len(t))"`
   反例症状：2026-09-24 实测——反引号被 bash 吃掉，`python -c` 以 rc=0 静默毁掉整份文件的中文正文；事后 `git diff` 看不出编码问题，只有字符数对不上。
   （承接 `conventions.md §2` 编码条）

3. **判据：orchd 协议命令一律不接管道，先重定向到临时文件再以 UTF-8 读。**
   命令：`python .orchd/__main__.py status > <临时目录>/status.json 2>&1` 后用 `python -X utf8` 解析，不通向 `grep`/`head`/`| jq`。
   反例症状：管道下宿主 console 为 cp936，JSON 中文字段被截成半行，`json.loads` 崩在文档中段——被误读成"引擎返回了坏数据"。
   （承接 `conventions.md §4` verify_command 无管道条；本条是同一约束的人跑侧）

4. **判据：引用任何能力前先确认落盘路径存在，可用性以磁盘为准而非注册表记忆。**
   命令：`python -X utf8 -c "import pathlib;print(pathlib.Path('scripts/40-style-check.py').exists())"`（PowerShell 侧等价 `Test-Path`）。
   反例症状：注册表写 `planned` 就假设脚本已建 → 下游 import 崩、或把「脚本不存在」当成「判据通过」。
   （承接 技能根文件 `SKILL.md` 能力注册表章的"以磁盘为准"条——锚到小节名而非行号，行号曾漂移（F13a）；注意与引擎协议文件 `.orchd/SKILL.md` 是两个文件。另见 `conventions.md §4` 所引路径必须存在）

5. **判据：Windows 五类假信号在测量前逐项排除，否则计数不可信。**
   命令：计数一律显式 `encoding="utf-8-sig"` 读；行尾以 blob 为准 `git show HEAD:<path>`（工作树 CRLF 是 autocrlf 正常态）；临时目录用 Python 的 `tempfile`，不用 shell 的 `/tmp` 字面量；目录体积以 `git ls-files` 清单为准而非 `du`。
   反例症状：管道 GBK 漏计中文命中；CRLF 假漂移把 3 行改动显示成整文件重写；相邻两次 Edit 吞掉中间一行；bash `/tmp` ≠ python `/tmp` 导致探针读到空文件；`du` 虚高约 58%。
   （承接 `conventions.md §2` 读侧 `utf-8-sig` 条）

6. **判据：`done` 之前把声明文件的完整性告警清零，声明与实际改动逐条对上。**
   命令：`python .orchd/__main__.py status --audit-task > <临时目录>/audit.json 2>&1` 后读该 JSON；同时 `git diff --name-only HEAD` 比对 `files_to_edit`。
   反例症状：声明文件没随分支提交进 diff（红线 13），或改了未声明文件（越界）——两者都会在 merge 巡检里变成永久告警。
   （承接 MUST 6）

7. **判据：论文任务的数字与引用结论必须能被第三方在同一磁盘态复算，不接受"读起来合理"。**
   命令：`python -X utf8 scripts/45-consistency-check.py <稿件目录> --refs <文献表文件>`（编号↔文献表、图表覆盖、术语、字数预算）；
   `python -X utf8 scripts/35-refs-gate.py --refs <22-refs.json> --mode strict`（引用验真四态；**终局/投稿门用 `--mode strict`**——存在非 `verified`（含 `id_mismatch`/`suspected`/`unresolvable`）条目即退出码非 0 阻断；中间态检索或单条核查可用缺省 `--mode advisory`（只逐条提示不阻断）；各索引 base URL/检索式/`select=`·`fields=`/限速与反幻觉约定见 `references/31-literature-endpoints.md`）。
   反例症状：孤儿引用 > 0（正文引了但 claim 行没有）、孤儿 claim > 0（写了论断没有句子承载）、带单位的数值在 `data/` 源里找不到可复算路径。
   （承接 `references/20-claim-framework.md:50-56` 引用落位机检 5 条）

8. **判据：机制/因果与新颖性类 claim 的取证有最低强度门槛，不到门槛必须降级措辞而不是加修辞。**
   命令：查 `references/20-claim-framework.md:33-41` 门限表逐行核对（机制/因果 ≥1 条 A 级全文核对；新颖性 ≥1 条全文核对 + 1 条对比基线）；
   措辞面用 `python -X utf8 scripts/40-style-check.py <稿件目录>` 出 `file:line: [类别] 词` 的行级报告。
   反例症状：只有题录+摘要级证据却写了"首次证明 / 机制是"；或 AI 腔报告只给"文风有问题"而不给行号，无法定位也无法回归。
   （承接 D-2 证据强度分层，`references/60-capability-specs.md §1.2` 行级输出条）

9. **判据：修一条判据必须列出该病灶的全部同型位置，每处各挂一条反向对照，否则视为未闭环。**
   命令：同族清单逐行 `grep -n "<同型模式>" <文件>` 给改/不改+理由；每处配"摘掉该处判据必红且点名"的反向对照（合规输入仍绿、摘判据变红）。
   反例症状：修一条、同族其余不动 → 下轮同型复发（2026-10-07 第三轮审查实测：F-1 只修 76 而 75 同型必红、F-2 只修消费端而 profile 真源未修）。
   （承接 `conventions.md §4` 反向对照条；`references/60-capability-specs.md §2` 取证规范第 ⑦ 项）

10. **判据：元守卫必须是行为级（喂合成正例必红且点名），字样级不算。**
    命令：对每条守卫喂一个"该守卫唯一负责"的合成正例 → 必须产出 ≥1 条违规且点名到档/任务/键/行；产出 0 条即判该守卫为死守卫。
    反例症状：元守卫只查源码里有没有接线字样 → 把判据改恒真（字样保留）后门禁仍全绿（2026-10-07 第三轮 E-1 实测）。
    （承接 `conventions.md §4` 证据要求条；`references/60-capability-specs.md §2` 取证规范第 ⑧ 项）

## 探针设计

1. **临时注入观察法**：验证一条判据真的在起作用，就构造一次**最小违规**（把要禁的东西写进真文件、或把词表加一个自造词），
   观察是否按预期变红，随后还原。反例症状：判据从未被真触发过，绿灯只代表"没跑到"。命令面同 §取证规范 第 8 条，输入换成临时副本。
   （承接 `conventions.md §4` 反向对照条）

2. **还原只走 Edit/Write + 哈希校验，不走 git**：注入前先记 `sha256`，还原后再记一次并比对。
   命令：`python -X utf8 -c "import hashlib,pathlib;print(hashlib.sha256(pathlib.Path(r'<文件>').read_bytes()).hexdigest())"`
   反例症状：用 `git checkout -- <文件>` 还原 → 连带抹掉同文件里**本任务尚未提交**的真实改动（红线 1 存在的理由）。
   （承接 红线 1；`conventions.md §5`）

3. **探针必须自消**：临时目录用 `tempfile`（或 pytest `--basetemp` 指向系统临时目录），探针文件在 `done` 前删除，并用 `status` + `git status --porcelain` 双重确认无残留。
   反例症状：探针样本留在发货面被 `40`/`45` 号扫到，或探针生成的 `.pyc` 内嵌本机绝对路径进发布物。
   （承接 MUST 4；`conventions.md §2` 不落 `.pyc` 条——跨进程带 `-B`、importlib 前设 `sys.dont_write_bytecode`）

4. **自测面与守卫面分开**：脚本自带 `--selftest`，合成用例、完全离线、非常驻文件；基座与生成器的守卫才进 `scripts/75-verify-selftest.py`。
   命令：`python -X utf8 scripts/45-consistency-check.py --selftest` / `python -X utf8 scripts/75-verify-selftest.py`（75 在引擎未接入时显式 SKIP 并 rc=0）
   反例症状：把某能力的用例塞进 75 号 → 该文件是多任务共享单写者，直接撞车。
   （承接 `conventions.md §2` 末条，`references/60-capability-specs.md §0` 自测条）

## 反向控制

**通则（AC3）**：每条判据配一次"把它拆掉，测试必须变红"的对照。绿而不红 = 判据是摆设；红而不绿（还原后仍红）= 探针污染了磁盘态。两个方向都要跑。
以下模板可直接套用；模板内的 `<…>` 换成实际路径即可，命令一律不接管道。

### 模板 A：断言拆除（判据基座 `70-verify.py`）

```
1) 基线：python -X utf8 scripts/70-verify.py <task-id> --manifest <项目 verify.manifest.json> --json  → 期望 rc=0
2) 拆除：Edit 把该任务 manifest 条目里 contains 的目标串改掉一个字符
3) 变红：重跑同一命令 → 期望 rc=1，且 JSON 点名该断言
4) 还原：Edit 改回 → sha256 比对第 1 步前的快照 → 重跑 → 期望 rc=0
```
反例症状：第 3 步仍 rc=0 ⇒ 该断言从未生效（写错键名、或条目根本没被展开）；把断言四段全清空而 rc 仍为 0 ⇒ 门禁空转，生成期应当 die。
`--manifest` 不给时按约定自动查找，容易验到另一份 manifest 而得出假绿，故模板内一律显式给路径。
（承接 `conventions.md §3` 四段全空 = 门禁空转；`conventions.md §4` 反向对照）

### 模板 B：词表摘除（`40-style-check.py` 词条来自文件而非常数）

```
1) 基线：python -X utf8 scripts/40-style-check.py <含一个已知命中词的样本目录>  → 期望 rc=1
2) 拆除：把 --wordlist 指向临时副本，删掉唯一命中项（脚本内不得硬编码词条）
3) 变红/翻转：同一输入重跑 → 期望由 rc=1 变 rc=0
4) 反向加词：临时词表加一个自造词，样本里写入该词 → 期望 rc=1 且行号正确
5) 还原：删临时词表与临时样本 → 重跑第 1 步（不带 --wordlist）→ 期望回到 rc=1，且 static/ 词表 sha256 与拆除前一致
```
反例症状：第 3 步仍 rc=1 ⇒ 报告由脚本内常数驱动，换刊/换域改词表无效；第 4 步不报行号 ⇒ 命中不可定位，等于没检查；
第 5 步回不到 rc=1 ⇒ 拆除时改的是 `static/` 真词表（越界写入发货面），当场还原并复核哈希。
（承接 `references/60-capability-specs.md §1.3`/`§1.5`）

### 模板 C（可选）：注入链拆除（`static/` 碎片与生成器）

```
1) 基线：python -X utf8 scripts/30-gen-proposals.py --profile profiles/<档> --out <临时目录>  → rc=0 且生成物含已声明碎片 marker
2) 拆除：把 profile 的 fragments 声明改成一个不存在的 id
3) 变红：重跑 → 期望 rc=2、消息含该 id、且临时输出目录不留下半份生成物（先拒后写）
4) 还原：删掉声明 → 期望与改动前逐字节一致（未声明零回归）
```
反例症状：第 3 步 rc=1 + traceback ⇒ 用"崩"冒充"拒"；目录里留有半成品 ⇒ 失败后下游会读到旧稿。
（承接 `conventions.md §3` 退出码语义；`references/60-capability-specs.md §3.2` 强制点 F1–F7）

### 模板 D（论文场景）：引用落位注入

```
1) 基线：python -X utf8 scripts/45-consistency-check.py <稿件目录> --refs <文献表>  → rc=0
2) 拆除：在正文某句临时加一个文献表里不存在的 [99]
3) 变红：重跑 → 期望 rc=1 且报告指出该编号（孤儿引用）
4) 还原：按模板 A 第 4 步的哈希校验口径还原 → rc=0
```
反例症状：改了稿件目录里的编号却报告路径仍是旧行号 ⇒ 缓存或读错文件；只报"有问题"不报 `file:line` ⇒ 不可回归。
（承接 `references/20-claim-framework.md:50-56` 第 2 条）

## 汇报纪律

1. **每轮收尾固定三件套**：改了什么（`file:line`）+ 实测证据（命令与 rc/计数）+ 下一项是什么。不夹带第二件待确认事项。
   反例症状：汇报只有"完成了"而无命令输出，下一轮无法判断是绿还是空转。
   （承接 `conventions.md §4` 证据要求；节奏见 D-13）

2. **修复按档位逐项放行，不并档、不跳档**：清单每轮只做一项，做完立即实测验证并预告下一项；档位顺序与遗留台账以 `CHANGELOG.md` 的 D-13/D-15 为准。
   反例症状：一次改跨两档 → 回滚时无法界定是哪一项引入的回归。
   （承接 D-13 逐档放行）

3. **子代理与脚本的报告一律视为待证陈述**：转述前自己跑一次命令或读一次文件；未核实不得说成"已完成/已通过"。
   反例症状：把子代理"全部通过"原样上报，实盘却有 FAIL——本仓已发生过一次伪报。
   （承接 MUST 3「done/review 后核对引擎响应」，`conventions.md §4`）

4. **异常即停即报，不擅自处置**：任何未预期的报错、脏工作区、陌生未跟踪文件，先报告并给只读诊断输出，等指示。
   反例症状：为让流程"看起来通了"而 `--force`、`git clean` 或手改 `_master.json` / `_ledger.jsonl`。
   （承接 MUST 5、红线 9）

5. **单会话自托管确需自审时，在 review comments 首句显式披露自审**，并说明会话指纹与绕过档位。
   反例症状：同会话既实现又审查却不披露，审查结论失去可信度记录。
   （承接 红线 4 自审三档）

6. **不得制造空验收**：AC 若写了某文件/某判据，交付里必须能机检到；纯文档任务被补 `verify_command`、或实现任务被清空判据，都要在 CHANGELOG 留决策。
   反例症状：为解除池级阻塞把某任务判据清空 → 该项永远"通过"，等于没做。
   （承接 红线 13 声明文件随分支提交；`conventions.md §3`）

### 显式禁止清单（原文三项不可减，另可增）

- **不要求手动 git 写操作**：本手册所有命令不得出现 `git checkout / reset / stash / clean / branch / merge / push` 作为处置手段；git 写只由引擎执行，唯一豁免 = 任务分支上的 `git commit` 与受管出口 `orchd git merge main`。（承接 红线 1、2）
  - **发版豁免（用户点名的受权通道）**：`scripts/79-release-publish.py` 是开发仓发版器，其 `git push` 属用户显式要求的发布动作（发版 = 推 tag，`.githooks/pre-push` 自动组装并推双仓；手动跑亦须显式给 TAG）——与"处置手段"无关，不属本红线管辖；代理不得在任务执行期借发版器 push，发版只由用户在命令行发起。
- **不替用户 intake/claim**：摄入只由用户指定，`request --auto-claim` 默认拒绝；代理不得自行 `intake` 或在无候选时 `claim`。（承接 红线 6、7、14）
- **不替用户 confirm/drop 选题**：`confirm`/`drop` 仅用户可执行，代理只能 `idea propose` 记入 study；灵感类直接写 IDEAS.md 而非自行入池。（承接 红线 6、10）
- **不手改引擎运行时文件与声明真源**：`_ledger.jsonl` / `_checkpoint.json` / `mod-*/spec.json` / `_master.json` 只读，改声明走 `amend`。（承接 红线 3、9）
- **不在任务分支执行 intake/amend**：amend 只在主工作树、工作区干净时做。（承接 红线 8）
