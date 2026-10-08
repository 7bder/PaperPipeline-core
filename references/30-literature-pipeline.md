# 文献流水线（P3）：定向检索 → 验真 → 全文 → 归一 → 审计

> **阶段定位**：本文件属 **P3**，**输入 = P2 产出的 `20-lit/20-claims-map.md` 需求单**。
> 综述框架、证据强度门限与引用落位规则在 `20-claim-framework.md`（P2 定义 / P4 执行）。
> **本文件只管"按需求采购"，不做无目标广检**——广检会导致"库很大但用不上"的库存病（本项目实测：74 条库、实引 49 条、25 条未引）。

## 1. 五段式流水线（可机检的只有后三段，投入应倾斜于此）

| 段 | 动作 | 判据/产物 |
|---|---|---|
| ① 发现 | 多源并行检索：OpenAlex（免 key，覆盖广）、Crossref（DOI 权威）、Semantic Scholar（CS/交叉）、arXiv（预印本） | `20-lit/21-candidates.json`（每源命中 + 引用数 + 年份） |
| ② 验真 | 标题相似度 ≥0.70 **且** 期刊/年份一致 **且** 撤稿检查（`is_retracted`） | `20-lit/22-refs.json`：`grade`（A/B）、`verify_checks`、`two_source_verified`、`doi` |
| ③ 全文 | OA 优先 → 机构订阅（CARSI）→ 图书馆文献传递；**明令排除盗版源** | `20-lit/23-download-checklist.md` + `20-lit/fulltext/` |
| ④ 归一 | 文件名 → `ref_no` **唯一回溯**（DOI 规则 + 描述性命名走带校验的 pin）；可得性分层 | `20-lit/24-fulltext-inventory.md`（机制承载 / 背景支撑 / 备选） |
| ⑤ 审计 | 逐条：位置、判定（支持/部分支持/不支持）、判据级别（全文页 / 题录+摘要 / 未核） | `20-lit/25-citation-audit.md` |

**发现面 vs 验真门控面（E3，2026-10-07）**：① **发现面**（上表①，按 `profile.discovery_sources` 并行检索）**允许**领域专有源（如 clinical 档的 **PubMed**）只为**找候选**，命中原样入 `21-candidates.json`（clinical 档以 `discovery_only_sources: [pubmed]` 显式声明）；② **验真门控面**（上表②，`scripts/35-refs-gate.py` 的 INDICES）**固定**为 **openalex / crossref / semantic_scholar / arxiv** 四家——**任何未列入 INDICES 的源（含 PubMed）不参与** DOI/标题交叉验真与四态判定，声明里不得把发现面专有源与验真门控面混列为"验真索引"。各源 **base URL / 检索式参数 / `select=`·`fields=` 裁剪 / 限速 / 命中原样入库** 的逐源明细见 `references/31-literature-endpoints.md`。

**grade A/B 定义（F13b，2026-10-06 补——此前全仓用而未定义）**：
- **A 级（全文核对级）**：已获取全文且关键论断可回引页码/图表号复核；机制/因果与新颖性 claim 的支撑文献必须达 A 级（见 `20-claim-framework.md` §"A 级全文核对"）。
- **B 级（题录+摘要级）**：仅有题录与摘要，未做全文核对；只支撑背景与非定量论断，不得推定量结论。A/B 由 `task-lit-fulltext-inventory` 按全文可得性判定写入 `22-refs.json.grade`，降级（全文不可得）在 `24-fulltext-inventory.md` 显式登记。

**门控（借 ARS 思路，作增量）**：四索引各自出 `unmatched` 布尔 → 未命中数 k（k=1 视为覆盖率噪音；k=3/4 才是强信号）→ 四态 `verified / id_mismatch / suspected / unresolvable`。
**id_mismatch（F5，2026-10-06）**：**真文献 + 编造标识符**的专项降档——非 arXiv 形态 DOI 在 OpenAlex/Crossref/Semantic Scholar 三家 id 轮一致否证（404）、标题轮救回命中时判此态（非 `verified`：`strict` 拦下、`advisory` 只提示；report 含 `id_mismatch=true` 与 id 轮否证留痕）。arXiv 编号与 `10.48550/arxiv.*` 形态 DOI **不适用**此降档——三家 JSON 索引对 arXiv 自家 DOI 结构性缺席，标题回退机制正是为其而设（口径保留）。缓存复放结论一致。
**反伪造偏置（关键）**：`suspected` 只可能来自**标识符面或撤稿**，共三处——① 持有可解析标识符（DOI 或 arXiv 编号）而有效应答的索引一致查不到；② 持有可解析标识符但命中记录与题录对不上（标题相似度不达阈值，或期刊与年份**两者均**不匹配）；③ 记录被标撤稿（`is_retracted`，对文献本身的阳性结论，与有无标识符无关）。**纯标题条目**在上列任一面失败一律 `unresolvable`（真实的地方刊、非英语刊、未数字化文献都长这样）。**题录字段缺失**（缺 title 则相似度关不可评、year 与 venue 全缺则期刊/年份关不可评）同样 `unresolvable`——证据不够不等于可疑，与"字段给了但对不上"严格区分；有效应答数低于 `--min-answered` 亦为 `unresolvable`（无据可判，不等于判死）。不变量：无标识符条目在四面失败（全查不到 / 相似度不达标 / 期刊年份对不上 / 命中数不足）上都不产 `suspected`。
`gate.mode = advisory`（缺省，逐条列出建议、不阻断，退出码 0）｜`strict`（存在非 `verified`（含 `id_mismatch`/`suspected`/`unresolvable`）条目即退出码非 0 阻断，草稿不得进入 ready-for-review）。**运行口径（B06，2026-10-07 三轮）**：终局/投稿门一律走 `strict`——`task-finalize-manuscript` 的 done 门禁按 profile 的 `fulltext_gate.mode: strict` 与 `22-refs.json` 的 `two_source_verified` 逐条判定（存在 `false` 即 rc=1，未验真即阻断）；中间态检索/单条核查可用缺省 `advisory`。`--mode` 取值、四态与退出码以 `scripts/35-refs-gate.py` 为准。

## 2. 全文获取的分工（对"我锁 DOI、你给链接、我批量下"的评估）

**结论：可行，但要把"下全文"从关键路径上摘掉。**

推荐分工：

1. **我先锁定并产出一张工单**：`download_tasks.csv`（`doi,target_filename,publisher,oa_status,oa_url,needs_institution,priority,cited_in,reason`）。
   priority 由「是否承载 §3 机制论断」决定——机制承载文献**必须**拿全文，背景性引用可停在题录级。
2. **能自动的自动拿**：OA 直链（OpenAlex `best_oa_location` / Unpaywall / arXiv 预印本）批量下载并校验 DOI 一致性。
3. **要订阅的走一次性人工**：两条路都行——(a) 你按表批量导出/粘贴链接，我批量下载；(b) **你 CARSI 登录一次，我复用持久化浏览器 profile 抓取**（比逐条给链接省事，但需控制速率并遵守出版社条款）。
4. **拿不到不阻塞**：全文可得性**不是引用前置条件**，而是**判据分级**。缺全文者一律显式标「题录+摘要级 / 未核（全文不可得）」，并在审计与投稿材料中如实声明。

**本项目实证（作为取舍依据）**：
- 25 条标"可自动下载"实际只有 2 条成功、23 条 403；脚本直连被 ScienceDirect 拦截；为此留下了 **8 个 `batch_download_*` 变体**——这是典型的**无效投入**。
- 而"验真 + 归一 + 审计"三段全部可机检且零返工：42/42 全匹配、0 异常、3 个描述性命名经带校验的 pin 正确认领。
- 因此：**不要在通用爬虫上投入，投入在验真与归一**；把"人工取全文"压缩成一次性批量动作。

## 3. 需求驱动检索（本段的输入是需求单，不是"话题"）

1. 读 `20-lit/20-claims-map.md`，取全部 `needs` 非空的行 → 生成**采购清单**（每条需求 1 行：`need_id | claim_id | 需要的证据类型 | 检索式 | 目标等级 A/B`）。
2. 逐条检索（多源并行），**命中即回填** `claims_map.refs` 与 `evidence_strength`；同一文献服务多条需求时只入库一次、多处引用。
3. **不做**"话题相关就收录"：与任何 `needs` 都不匹配的候选一律留 `21-candidates.json`，不升级为 `22-refs.json`（避免未引库存）。
4. 收口判据：所有 `needs` 非空行要么回填了 `refs`，要么显式标为 `unsupported`（此时该 claim 必须改写或删除）。

## 4. 审计（P5）与框架层的关系

审计只对"已被 `claims_map` 引用的条目"负责：逐条给出位置、判定（支持/部分支持/不支持）、判据级别（全文页 / 题录+摘要 / 未核）。
**不支持项的处置规则写在 `20-claim-framework.md §6`**（替换 / 降级措辞 / 删除，三者必留痕）。
