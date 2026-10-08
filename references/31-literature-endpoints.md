# 文献索引 endpoint 参考（P3 发现面 / 验真门控面）

> **定位**：`30-literature-pipeline.md` §1 的本表补充——把**发现面检索**与**验真门控**用到的
> 每个索引的 base URL、检索式参数、`select=`/`fields=` 裁剪、限速与「命中记录原样入库」约定
> 固化成可复现口径。**只写本仓已实测/已实现的行为**（实现真源 = `scripts/35-refs-gate.py`），
> 不写教科书式通用常识（守 `references/60-capability-specs.md` 防杜撰约束）。
>
> **两面边界（E3，2026-10-07）**：**发现面**（找候选，命中入 `20-lit/21-candidates.json`）
> 允许领域专有源（如 clinical 档的 PubMed）；**验真门控面**（`scripts/35-refs-gate.py` 的
> `INDICES = openalex / crossref / semantic_scholar / arxiv`）**只认这四家**做 DOI/标题交叉
> 验真与四态判定。**PubMed 属发现面专用，不参与验真门控**。

## 0. 公共约定（四索引通吃）

- **User-Agent**：`paper-pipeline-refs-gate/1.0 (+https://github.com/7bder/PaperPipeline-core)`（见 `35-refs-gate.py` `HEADERS`）。
- **Accept**：`application/json, application/atom+xml, text/xml, */*`——arXiv 只出 Atom XML，其余出 JSON，一并声明避免内容协商拒收。
- **限速（节流真源）**：默认 `MIN_INTERVAL_S = 1.0`；**按 host 分档** `HOST_INTERVAL_S`——`export.arxiv.org` 取 **3.5s**（官方要求程序化请求间隔 ≥3s，且其超速惩罚是 **406** 而非 429、窗口会累积）。
- **重试**：`RETRIES = 2`、`BACKOFF_S = 2.0`；重试状态码 `RETRY_STATUS = (408, 425, 429, 406, 500, 502, 503, 504)`。
- **反幻觉约定（关键）**：命中记录**原样入** `20-lit/21-candidates.json`（每源命中 + 引用数 + 年份），**不得**由 agent 重写题名/年份/指标；验真阶段只做「相似度 ≥0.70 **且** 期刊/年份一致 **且** 未撤稿」的比对，不改写库内容（详见 `30-literature-pipeline.md` §1）。
- **礼貌池（G2，2026-10-07）**：Crossref 可在 UA 尾附 `mailto:`、OpenAlex 用 `mailto` 参数、S2 可用 API key 提速；**缺省（未配置）行为与现状逐字一致**（详见 `scripts/35-refs-gate.py`）。
- **数字真源（A-9，2026-10-08）**：本表端点路径、参数名与限速数字以 `scripts/35-refs-gate.py` 的 `PREFIX` / `_endpoint` 实时输出 / `MIN_INTERVAL_S` / `HOST_INTERVAL_S` / `ARXIV_QUIET_S` / `RETRIES` / `BACKOFF_S` / `RETRY_STATUS` / `SIM_THRESHOLD` 为真源；改代码未同步本文即 `35-refs-gate.py --selftest` 对账变红。

## 1. OpenAlex（验真门控面）

- **base URL**：`https://api.openalex.org`
- **DOI 直查**：`GET /works/doi:<doi>`（DOI 走 `quote(doi, safe="")`）。
- **检索式**：`GET /works?search=<query>&per-page=1`（标题面单条候选）。
- **字段裁剪**：`select=` 可限定返回字段；本仓实现按需读 `title / doi / publication_year / cited_by_count`（期刊由 `primary_location.source.display_name` 取）。
- **限速**：1 req/s（`HOST_INTERVAL_S` 未覆盖 → `MIN_INTERVAL_S`）。

## 2. Crossref（验真门控面；DOI 权威面）

- **base URL**：`https://api.crossref.org`
- **DOI 直查**：`GET /works/<doi>`。
- **检索式**：`GET /works?query.bibliographic=<query>&rows=1`。
- **字段裁剪**：`select=DOI,title,container-title,issued,is-referenced-by-count`。
- **限速**：1 req/s；礼貌池经 UA 尾 `mailto:`。

## 3. Semantic Scholar（验真门控面；CS/交叉面）

- **base URL**：`https://api.semanticscholar.org`
- **DOI 直查**：`GET /graph/v1/paper/DOI:<doi>?fields=title,year,venue,isRetracted`
- **检索式**：`GET /graph/v1/paper/search?query=<query>&limit=1&fields=title,year,venue,isRetracted`
- **限速**：免 key 连发即 **429**（`THROTTLE_HOSTS` 覆盖）；`HOST_INTERVAL_S` 未配置时取 1s；有 `S2_API_KEY` 时可提速（属可选，不作 CI 硬门禁）。

## 4. arXiv（验真门控面；预印本面）

- **base URL**：`https://export.arxiv.org`
- **编号直查**：`GET /api/query?id_list=<id>`（`_arxiv_id` 归一后的裸编号：`10.48550` DOI 尾巴与 `arXiv:` 前缀先剥掉，旧式斜杠 id 做 `%2F` 转义；非 arXiv DOI 无可用编号即不发请求）。
- **检索式**：`GET /api/query?search_query=ti:<phrase>&max_results=1`（标题词组，`_arxiv_phrase` 归一）。
- **响应**：**Atom XML**（命名空间 `http://www.w3.org/2005/Atom`）。
- **限速**：**≥3.5s**；超速返回 **406** 且窗口累积（2026-09-26 实测：连跑 10 条后 `id_list` 仍 200、`search_query` 整片 406，静置 240s 未恢复，真源 `ARXIV_QUIET_S = 240` 见 `scripts/35-refs-gate.py`；改常量一处即两处同动，对账见 `--selftest` A-10/C-4）。
- **口径保留**：arXiv 编号与 `10.48550/arxiv.*` 形态 DOI 不做 `id_mismatch` 降档（三家 JSON 索引对其结构性缺席，标题回退为其而设；见 `30-literature-pipeline.md` 门控段）。

## 5. PubMed（**发现面专用**，不参与验真门控）

- **base URL**：`https://eutils.ncbi.nlm.nih.gov/entrez/eutils/`
- **检索（esearch）**：`GET esearch.fcgi?db=pubmed&term=<query>&retmode=json&retmax=<n>`
- **题录（esummary）**：`GET esummary.fcgi?db=pubmed&id=<pmid,...>&retmode=json`
- **DOI→PMID（ID Converter）**：`GET https://www.ncbi.nlm.nih.gov/pmc/utils/idconv/v1.0/?ids=<doi>&format=json`
- **限速**：免 key 程序化请求 ≤3 req/s（建议 1 req/s 保守口径）。
- **用途限定（E3，2026-10-07 裁定 A）**：**只用于发现/收集候选**，命中原样入 `21-candidates.json`；**不参与** `35-refs-gate.py` 的 DOI/标题交叉验真与四态判定（`INDICES` 不含 pubmed）。clinical 档以 `discovery_only_sources: [pubmed]` 显式声明该边界。
