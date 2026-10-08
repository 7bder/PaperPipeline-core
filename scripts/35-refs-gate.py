#!/usr/bin/env python3
"""35-refs-gate.py — 文献引用验真门控（P3 第②段的可机检面）。

规格：references/30-literature-pipeline.md §1（四索引、k 语义、四态（verified / id_mismatch /
     suspected / unresolvable，见 STATES）、反伪造偏置、gate.mode）。

输入 = `22-refs.json`（列表或 {"refs": [...]}），每条给 doi 或 arxiv_id 或 title 作为查询键；
      但要拿到 verified 还需可比字段：**最少 = 一个可解析标识符 + title + (year 或 venue)**。
      缺字段一律 unresolvable（题录不全 ≠ 文献可疑），报表以 `缺字段=` 单列提示。
      输入面归并（B10/G-10）：按去重键分组（DOI 小写主键 → ISBN 去连字符/空格归一 →
      arXiv 编号 → 标题小写辅键），同键条目只查一次、结论复用代表条目，报表以
      `重复条目=` 点名；缓存键保持原始大小写（归一化只决定"查几次"，不决定"缓存记在哪"）。
判定：四索引（openalex / crossref / semantic_scholar / arxiv）各出一个**源状态**
      matched / unmatched / unavailable / not_applicable；`answered` = 给出有效应答的索引数，
      `k = answered - hits`；门槛 `need = min(--min-hits, pool)`（pool = 四索引减去 --skip-indices）：
      answered < need → unresolvable（应答面不足，判不了）；hits < need → 有标识符才 suspected（覆盖不足），
      纯标题 → unresolvable；
      再过标题相似度（命中索引多数同意：同意数*2 >= 有标题命中数）、期刊或年份一致、非撤稿三关才 verified。
为什么要有 unavailable 与 not_applicable：**"服务说没有"（404/零条目）、"服务没回答"（429 限流、
      5xx、406 拒收、解码失败）、"该索引对这条文献结构性无从回答"（非 arXiv DOI 之于 arXiv）
      是三回事**。把后两类当"没有"计进 k，会让真文献成片降档：实测免 key 的 Semantic Scholar 连发
      两请求即 429、对个别真 DOI 直接 404；arXiv 对 `search_query` 有 IP 级速率罚时且**以 406 呈现**
      （实测：罚时窗口内 `ti:`/`all:`/`cat:`、带引号与裸词一起 406，而 `id_list` 照常 200，静置 240s
      未恢复，真源 ARXIV_QUIET_S），所以它的请求间隔单档提到 >=3s（HOST_INTERVAL_S），而不是改检索式去碰运气。
反伪造偏置：只有**按 DOI/编号**这一面（查不到、或与记录对不上）才允许 suspected；
      **纯标题条目一律 unresolvable**（真实的地方刊、非英语刊、未数字化文献长这样，不该被当成伪造嫌疑）；
      有效应答数低于 --min-answered 时一律 unresolvable（无据可判，不等于判死）。
      不变量：suspected 只可能来自标识符面或撤稿——无标识符条目在四面失败（全查不到 / 相似度不达标 /
      期刊年份对不上 / 命中数不足）上都不产出 suspected，撤稿是唯一例外（它是对文献本身的阳性结论）。
      "DOI/编号"同权是规格原话（references/30-literature-pipeline.md 反伪造偏置段）：arXiv 编号独立参与判定，
      无 DOI 只有编号的条目若四索引全否证，reason=arxiv_id_not_found_in_any_index → suspected。
标识符面：arXiv 一栏优先按 id_list 精确查（编号可来自 arxiv_id 字段，也可来自 10.48550 自家 DOI），
      没有可用编号才退成 ti: 短语检索——上一版把这段挂在 DOI 分支下，实测后果是无 DOI 的预印本条目
      带着伪造编号与带着真编号结论逐字相同（模糊标题检索把编号遮掉了）。
标题回退：按**标识符**的命中数凑不齐门槛时，对"按标识符答了没有"的索引再按标题问一次（实测 arXiv
      自家 DOI 在 OpenAlex/Crossref/S2 结构性 404，只有 arXiv 认——不回退则真文献必判可疑）。
      第一轮已按标题答过的索引不再重复问（无 DOI 条目三家本就走的标题面）。
      回退命中的索引记在 `title_fallback` 并随缓存回放，报告行以 `title-fallback=` 标明来路。
审计面：每条结果的 `index_status` 记 `{索引: 源状态:原因[出处]}`，`[id]`/`[title]` 区分精确直查与
      模糊检索命中（`matched:ok` 不分来路会让"伪造编号 + 真标题"读起来像编号核对通过）；
      控制台把 unavailable 连原因一起上屏——限流、5xx、解码失败的处置各不相同，不能只报索引名；
      n/a 与 unavailable 两类计数分行报，别把"结构性无从回答"说成"服务没答上"。
      走过标题回退的索引再缀 `<- id轮 源状态:原因`，标识符为何没命中不得被回退结果抹掉。
退出码：0 = 通过（advisory 下非 verified 只列建议）；1 = strict 模式存在非 verified 条目，
      或 --selftest 有用例失败；2 = 用法错误（输入缺失/坏 JSON/顶层形态不合/非法或重名或全摘
      --skip-indices/非法礼貌池环境变量/含重复键的 cache/--min-hits 为负）。
只读承诺：不写任何论文项目目录；仅 --cache / --report 显式给路径时才落盘。
缓存真源（G-7，2026-10-07 三轮 B06）：cache 须带顶层 `_meta.tool == "35-refs-gate"`（缺/不符
      即整份不采信，粗造假无标记即失效）且每条记 `written_at` + 缺省 30 天 TTL（过期重查）；
      载入走重复键检出（重键 → rc=2）。手写 per_index 全 matched 不再得 verified/零联网。
自测口径：`--selftest` 与 `--fixtures` 在 **fetch 层**注入原始字节（Crossref 双层 envelope、
      S2 404/429 报文、arXiv Atom XML 原文），`_decode` 以下全走真实代码；节流与退避在 `_fetch_raw`
      内部，故离线路径不产生 sleep。
礼貌池（G2，2026-10-07）：环境变量 `REFS_GATE_MAILTO`（或 `OPENALEX_POLITE_EMAIL` / `CROSSREF_MAILTO`）
      给 UA 加 `mailto:` 并给 OpenAlex 请求加 `mailto=` 参数；`S2_API_KEY` 只发给 Semantic Scholar。
      三者均缺省 → 行为与配置前**逐字一致**（UA 无 mailto、OpenAlex 无 mailto 参数、无 x-api-key）。
      B-1/B-2（2026-10-07 三轮 B06）：消毒扩到 HTTP 头合法字符（非 latin-1 / 控制字符一律
      rc=2），且逐源点名实际出错的环境变量（不再一律写 REFS_GATE_MAILTO）。
--skip-indices（G-2，2026-10-07 三轮 B06）：取**集合**语义（去重），重名或摘除全部索引 → rc=2
      （重名曾把 pool 门槛降档：`crossref,crossref,arxiv` 被算成摘 3 个）。
"""

import argparse
import copy
import difflib
import hashlib
import io
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

sys.dont_write_bytecode = True
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

INDICES = ("openalex", "crossref", "semantic_scholar", "arxiv")
SIM_THRESHOLD = 0.70
STATES = ("verified", "id_mismatch", "suspected", "unresolvable")
# id_mismatch（F5，2026-10-06）：真文献 + 编造 DOI——JSON 三家 id 轮一致否证、标题轮救回。
# 非 verified：strict 拦下、advisory 只提示；arXiv 编号与 10.48550/arxiv.* 形态 DOI 不适用
#（回退机制本为 arXiv 自家 DOI 的结构性 404 而设，口径保留）。
SOURCES = ("matched", "unmatched", "unavailable")
NOT_APPLICABLE = "not_applicable"
MIN_ANSWERED = 2
MIN_HITS = 2
MIN_INTERVAL_S = 1.0
# 节流按 host 分档：arXiv 官方要求程序化请求间隔 >=3s，而它的超速惩罚不是 429 而是 406，
# 且窗口会累积（2026-09-26 实测：连跑 10 条题录后同一 host 上 `id_list` 仍 200、`search_query`
# 整片 406，静置 240s 未恢复，真源 ARXIV_QUIET_S）。统一 1s 等于自己把 arXiv 标题面长期打成 unavailable。
HOST_INTERVAL_S = {"export.arxiv.org": 3.5}
# arXiv search_query 速率罚时恢复静置秒数真源（B11 A-10/C-4，离线收敛；联机复验待人工复核）：
# 31:52 的旧小值与本文件旧两处大值/一处小值收敛到此处一常量；改此一处并同步 31 文档同值
#（_doc_31_violations 对账：缺常量名或秒数即红，即"改一处两处同动"的强制面）。
# 取 240（两轮实测均为未恢复上界，取大不取小；小值那轮同样未恢复）。
ARXIV_QUIET_S = 240
# 真网络冒烟（--smoke-live）口径：题录固定、请求预算硬上限；只读、不作 CI 硬门禁。
# B11（离线修正）：第三条 DOI 10.1038/s41586-020-2649-2 真值=NumPy 篇
#（"Array programming with NumPy"），旧标题误配新冠论文；联机复验待人工复核。
SMOKE_MAX_REQUESTS = 12
SMOKE_PROBES = (
    {"doi": "10.1038/nature14539", "title": "Deep learning", "year": 2015, "venue": "Nature"},
    {"doi": "10.1103/PhysRevLett.116.061102",
     "title": "Observation of Gravitational Waves from a Binary Black Hole Merger",
     "year": 2016, "venue": "Physical Review Letters"},
    {"doi": "10.1038/s41586-020-2649-2",
     "title": "Array programming with NumPy",
     "year": 2020, "venue": "Nature"},
)
RETRIES = 2
BACKOFF_S = 2.0
# G-7（round3 B06）：查询缓存须为**本工具产物**且**未过期**才采信——手写 cache 把
# per_index 全写成 matched 曾直接得 verified/from_cache=True/零联网（验真过可以是纯声明）。
# `_meta` 是来源标记（缺/不符即整份忽略重查）；每条记录 `written_at` + 缺省 30 天 TTL。
CACHE_TTL_DAYS = 30
CACHE_META = {"tool": "35-refs-gate", "schema": 1}
THROTTLE_HOSTS = ("api.semanticscholar.org", "api.crossref.org", "api.openalex.org", "export.arxiv.org")
# arXiv 只出 Atom XML（实测 content-type），其余只出 JSON；Accept 一并声明，避免服务端按内容协商拒收。
HEADERS = {
    "User-Agent": "paper-pipeline-refs-gate/1.0 (+https://github.com/7bder/PaperPipeline-core)",
    "Accept": "application/json, application/atom+xml, text/xml, */*",
}
# G2（2026-10-07 审查）：礼貌池——缺省（未设环境变量）与现状**逐字一致**；配置后才带身份/提速。
# REFS_GATE_MAILTO 通用；亦可分别用 OPENALEX_POLITE_EMAIL / CROSSREF_MAILTO / S2_API_KEY。
# G-4（2026-10-07 二轮）：环境变量未消毒——含 CR/LF/空格的 mailto/key 会让 UA 头在
# _fetch_raw 建 Request 即崩。此处统一 strip + 非法空白拒绝；非法值不并入 HEADERS（不崩），
# 由 main() 归 rc=2 点名。
# B-1/B-2（round3 B06）：消毒扩到「HTTP 头合法字符」——非 latin-1（中文邮箱/全角）与控制字符
# 一律拒绝并在**建 Request 之前**归 rc=2（曾通过消毒，真发请求时 UnicodeEncodeError 被吞成
# transport_network → 四面 unavailable → advisory rc=0，全库不验而判绿）；且**逐源**调用，
# 报错点名值真正来自的环境变量（曾一律写 REFS_GATE_MAILTO，用户去查没设过的变量）。
def _clean_env(name: str, value: str):
    """返回 (clean_value, error)。name 空串 = 该源未设置（缺省零回归）；error 非空即非法。"""
    if not name:
        return "", None
    v = (value or "").strip()
    if not v:
        return "", None
    if any(ch in v for ch in "\r\n\t") or " " in v:
        return "", ("%s 取值含非法空白/CRLF（%r）——会破坏 HTTP 头（header 注入形态），"
                    "请去掉换行与空格后重试" % (name, value))
    if any(ord(ch) < 0x20 or ord(ch) == 0x7f for ch in v):
        return "", ("%s 取值含控制字符（%r）——不得进 HTTP 头" % (name, value))
    try:
        v.encode("latin-1")
    except UnicodeEncodeError:
        return "", ("%s 取值含非 latin-1 字符（%r）——HTTP 头只接受 latin-1，"
                    "中文邮箱/全角字符会在建 Request 时 UnicodeEncodeError 崩，"
                    "请改用 ASCII 值" % (name, value))
    return v, None


def _pick_env(names):
    """按顺序取第一个非空值的 (源变量名, 值)；都不设 → ("", "")（缺省零回归，错误点名来源真源）。"""
    for n in names:
        val = os.environ.get(n)
        if val:
            return n, val
    return "", ""


_POLITE_MAILTO_SRC, _POLITE_MAILTO_RAW = _pick_env(
    ("REFS_GATE_MAILTO", "OPENALEX_POLITE_EMAIL", "CROSSREF_MAILTO"))
POLITE_MAILTO, _env_err = _clean_env(_POLITE_MAILTO_SRC, _POLITE_MAILTO_RAW)
S2_API_KEY, _env_err2 = _clean_env("S2_API_KEY", os.environ.get("S2_API_KEY") or "")
# main() 前置：非空即归 rc=2（非法环境变量属用法/配置问题，非文献判定）。
_ENV_ERRORS = [e for e in (_env_err, _env_err2) if e]
if POLITE_MAILTO:
    HEADERS["User-Agent"] = HEADERS["User-Agent"] + " mailto:" + POLITE_MAILTO
RETRY_STATUS = (408, 425, 429, 406, 500, 502, 503, 504)
PREFIX = {
    "openalex": "https://api.openalex.org",
    "crossref": "https://api.crossref.org",
    "semantic_scholar": "https://api.semanticscholar.org",
    "arxiv": "https://export.arxiv.org",
}
ATOM = "{http://www.w3.org/2005/Atom}"
ARXIV_NS = "{http://arxiv.org/schemas/atom}"


class TransportError(Exception):
    """网络层失败（连接/超时）。与"索引回答了但没有这条文献"严格区分，故独立成类型。"""

    def __init__(self, kind, detail=""):
        super().__init__("%s:%s" % (kind, detail[:80]))
        self.kind = kind
        self.detail = detail


# ---------- 取数：fetch 拿原始字节，decode 按索引方言解析 ----------

_LAST_CALL = {}


def _throttle(host):
    now = time.time()
    if host in THROTTLE_HOSTS:
        gap = now - _LAST_CALL.get(host, 0.0)
        interval = HOST_INTERVAL_S.get(host, MIN_INTERVAL_S)
        if gap < interval:
            time.sleep(interval - gap)
    _LAST_CALL[host] = time.time()


def _polite_url(url, host, mailto):
    """OpenAlex 礼貌池：追加 `mailto=` 参数（mailto 空 → 原样返回，缺省零回归）。"""
    if mailto and host == "api.openalex.org":
        return url + ("&" if "?" in url else "?") + "mailto=" + urllib.parse.quote(mailto, safe="@")
    return url


def _polite_headers(host, key):
    """S2 API key 只发给 semanticscholar host；key 空 → 复用 HEADERS（同一对象，零回归）。"""
    if key and host == "api.semanticscholar.org":
        return dict(HEADERS, **{"x-api-key": key})
    return HEADERS


def _fetch_raw(url, retries=None, opener=None):
    """返回 (status, body_bytes, content_type)；传输层失败抛 TransportError。

    4xx/5xx 不抛：404 是"库里没有"的有效应答，429/406/5xx 是"没回答"——两者必须由判据层分开处置。
    `opener` 缺省为 urllib.request.urlopen，自测注入假 opener 以覆盖退避分支（不碰真实网络）。
    """
    retries = RETRIES if retries is None else retries
    opener = opener or urllib.request.urlopen
    host = urllib.parse.urlsplit(url).netloc
    attempt = 0
    while True:
        _throttle(host)
        try:
            req = urllib.request.Request(_polite_url(url, host, POLITE_MAILTO),
                                         headers=_polite_headers(host, S2_API_KEY))
            resp = opener(req, timeout=20)
            try:
                return resp.status, resp.read(), (resp.headers.get("Content-Type") or "")
            finally:
                close = getattr(resp, "close", None)
                if callable(close):
                    close()
        except urllib.error.HTTPError as exc:
            try:
                body = exc.read() or b""
            except Exception:
                body = b""
            ctype = (exc.headers.get("Content-Type") or "") if exc.headers else ""
            if exc.code in RETRY_STATUS and attempt < retries:
                attempt += 1
                time.sleep(BACKOFF_S * attempt)
                continue
            return exc.code, body, ctype
        except (urllib.error.URLError, OSError, ValueError) as exc:
            raise TransportError("network", "%s: %s" % (type(exc).__name__, str(exc)[:100]))


NO_RECORD = object()

# B14（G-11~G-14）：正则/相似度输入预算——单行（单次输入）超 32KB 走截断，
# 只用标准库 re/difflib，不引入第三方引擎；超长退化输入不断言位置语义，只保证不卡死。
REGEX_INPUT_BUDGET = 32 * 1024


def _looks_like_html(head):
    """lstripped 响应首部是否像 HTML 错误页（CDN/网关拦截页的常见根形态）。

    只认三个前缀：<html、<!doctype html、<head。arXiv 的正常形态是 <?xml/<feed，
    JSON 三家的正常形态是 { 或 [——三者与 HTML 前缀无交集，不会误伤正常响应。
    """
    low = head[:64].lower()
    return low.startswith("<html") or low.startswith("<!doctype html") or low.startswith("<head")


def _decode(index, status, body, ctype):
    """(obj, reason)。obj=None → 索引没给出可读应答（unavailable）；NO_RECORD → 明确没有这条（unmatched）。

    方言探测先于解析（B14 G-11/G-12）：按 Content-Type + 根元素决定用哪个解析器——
    CDN/网关错误页（200 + text/html 或 HTML 根）若按 JSON/XML 硬解析，会得出"库里没有"
    （unmatched）或含糊的 parse_error；而真相是"没回答"（unavailable，不计入 answered/k）。
    JSON 三家收到 XML、arXiv 收到 JSON 同理按方言不合归 unavailable 并保留原因串。
    JSON BOM（utf-8-sig）正常解码，不视为解析失败。
    """
    if status == 404:
        return NO_RECORD, "not_found_404"
    if status != 200:
        return None, "http_%d" % status
    if not body:
        return None, "empty_body"
    raw = body if isinstance(body, bytes) else str(body).encode("utf-8")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return None, "body_not_utf8"
    head = text.lstrip()
    ctype_low = (ctype or "").lower()
    if "html" in ctype_low or _looks_like_html(head):
        # 两边都不出 HTML：JSON 三家只出 JSON，arXiv 只出 Atom XML——HTML 必是错误页。
        return None, "html_error_page"
    if index == "arxiv" or "xml" in ctype_low:
        if index != "arxiv":
            # JSON 索引收到 XML（网关错配/拦截页变体）：方言不合，按 unavailable 保留原因串。
            return None, "unexpected_xml_for_json_index"
        parsed = _parse_atom(text)
        if parsed is not None:
            return parsed, "atom_ok"
        return None, "atom_parse_error"
    if head.startswith("<"):
        # Content-Type 没写 xml 但根元素是 <（HTML 已在上面拦截，此处是 XML 变体）：方言不合。
        return None, "unexpected_xml_for_json_index"
    try:
        return json.loads(text), "json_ok"
    except ValueError:
        return None, "json_parse_error"


def _parse_atom(text):
    """arXiv API 只出 Atom XML（实测 content-type=application/atom+xml），归一为 {"entry": {...}}。"""
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return None
    entries = [e for e in root.findall(ATOM + "entry") if e.find(ATOM + "title") is not None]
    if not entries:
        return {"entry": None}
    entry = entries[0]
    published = entry.findtext(ATOM + "published") or entry.findtext(ATOM + "updated") or ""
    year = int(published[:4]) if len(published) >= 4 and published[:4].isdigit() else None
    return {"entry": {"title": " ".join((entry.findtext(ATOM + "title") or "").split()),
                      "year": year,
                      "journal_ref": entry.findtext(ARXIV_NS + "journal_ref"),
                      "id": entry.findtext(ATOM + "id")}}


def _norm_title(s):
    return " ".join(str(s or "").lower().replace("-", " ").split())


def _norm_doi(s):
    """DOI 归一（B10/G-10 去重主键）：strip + 小写。DOI 大小写不敏感，
    `10.1038/X` 与 `10.1038/x` 是同一文献。只用于去重键，不改查询串与缓存键。"""
    return str(s or "").strip().lower()


def _norm_isbn(s):
    """ISBN 归一（B10/G-10）：去连字符（含常见全角/长横变体）/空格 + 大写。
    同一书号连字符写法不同属同一文献。只用于去重键（35 号无 ISBN 查询端点，
    ISBN 条目仍走标题面，归一后不再为连字符差异重复查询）。"""
    return re.sub(r"[\s\-‐‑‒–—―]", "", str(s or "").strip()).upper()


def _dup_key(entry, index):
    """B10/G-10 重复条目归并键：DOI 小写主键 → ISBN 归一次之 → arXiv 编号 →
    标题小写辅键。全空条目按序号单列，不归并（空键合并不叫去重，叫丢条目）。"""
    if not isinstance(entry, dict):
        return ("none", "#%d" % index)
    if _norm_doi(entry.get("doi")):
        return ("doi", _norm_doi(entry.get("doi")))
    isbn_raw = entry.get("isbn") or entry.get("ISBN") or entry.get("isbn13") or entry.get("isbn10")
    if _norm_isbn(isbn_raw):
        return ("isbn", _norm_isbn(isbn_raw))
    aid = _arxiv_id(str(entry.get("arxiv_id") or entry.get("arxivId") or ""))
    if aid:
        return ("arxiv", aid.lower())
    if _norm_title(entry.get("title")):
        return ("title", _norm_title(entry.get("title")))
    return ("none", "#%d" % index)


FETCH = _fetch_raw
"""缺省走真实 HTTP；自测与离线复放在这一层注入 fixture（`--fixtures` / `run_selftest`）。"""


def _crossref_year(item):
    """Crossref 的 date-parts 是**列表的列表**（[[2015,5,28]]）→ 取内层首元素为年份。

    旧写法只取外层 [0]，得到 [2015,5,28]，与题录年份 "2015" 永不相等（实测），
    于是 Crossref 对 year_ok 永不贡献。
    """
    for key in ("published-print", "published-online", "issued"):
        block = item.get(key)
        if not isinstance(block, dict):
            continue
        parts = block.get("date-parts")
        if not (isinstance(parts, list) and parts):
            continue
        inner = parts[0]
        if isinstance(inner, list) and inner:
            inner = inner[0]
        if isinstance(inner, bool):
            continue
        if isinstance(inner, int):
            return inner
        if isinstance(inner, str) and inner[:4].isdigit():
            return int(inner[:4])
    return None


def _extract(index, doc):
    """把各家响应归一为 {title, year, venue, retracted}；取不到即 None。"""
    if not isinstance(doc, dict):
        return None
    if index == "openalex":
        return {"title": doc.get("display_name") or doc.get("title"),
                "year": doc.get("publication_year"),
                "venue": ((doc.get("primary_location") or {}).get("source") or {}).get("display_name"),
                "retracted": bool(doc.get("is_retracted"))}
    if index == "crossref":
        item = doc.get("message") if isinstance(doc.get("message"), dict) else doc
        cnt = item.get("container-title") or []
        return {"title": (item.get("title") or [None])[0],
                "year": _crossref_year(item),
                "venue": cnt[0] if cnt else None,
                "retracted": bool(item.get("is-retracted"))}
    if index == "semantic_scholar":
        return {"title": doc.get("title"), "year": doc.get("year"),
                "venue": doc.get("venue") or (doc.get("publicationVenue") or {}).get("name"),
                "retracted": bool(doc.get("isRetracted"))}
    if index == "arxiv":
        entry = doc.get("entry")
        if not isinstance(entry, dict):
            return None
        return {"title": entry.get("title"), "year": entry.get("year"),
                "venue": entry.get("journal_ref") or "arXiv", "retracted": False}
    return None


_ARXIV_NEW_ID_RE = re.compile(r"^[0-9]{4}\.[0-9]{4,5}(v[0-9]+)?$")
_ARXIV_SLASH_ID_RE = re.compile(
    r"^[A-Za-z][A-Za-z.\-]*(?:\.[A-Za-z]{2})?/(?:[0-9]{7}|[0-9]{4}\.[0-9]{4,5})(?:v[0-9]+)?$")
"""旧式/带类目 arXiv id（quant-ph/9601029、cs.CL/0708.0384、math.GT/0309136）。
按形态匹配而非类目白名单——白名单漏 `quant-ph` 这类带连字符的类目，实测把真 id 判成非 arXiv。"""


def _arxiv_id(raw):
    """把各种写法收成 arXiv API 认的 id_list 形态；不是 arXiv id 就返回 None。

    实测：`id_list=arXiv.1706.03762`（10.48550 DOI 的原样后缀）与 `quant-ph/9601029`（带斜杠的旧式 id）
    都被 arXiv 直接 406 拒收，而 `1706.03762` 返回 200——所以必须规范化，而不是把 DOI 尾巴塞进去。
    """
    s = str(raw or "").strip()
    if not s:
        return None
    low = s.lower()
    for pre in ("arxiv:", "arxiv.", "arxiv/"):
        if low.startswith(pre):
            s, low = s[len(pre):], s[len(pre):].lower()
    if low.startswith("10.48550/"):
        tail = s[len("10.48550/"):]
        for pre in ("arXiv.", "arXiv:", "arxiv.", "arxiv/"):
            if tail.lower().startswith(pre):
                tail = tail[len(pre):]
                break
        s = tail
    if _ARXIV_NEW_ID_RE.match(s):
        return s
    if "/" in s and _ARXIV_SLASH_ID_RE.match(s):
        return urllib.parse.quote(s, safe="")
    return None


def _arxiv_phrase(title):
    """arXiv 标题检索式：短语加引号、词间 %20（2026-09-26 早上那轮真环境挑出来的形态）。

    口径提醒（同日傍晚复测）：这个 host 对 `search_query` 有 IP 级速率罚时，窗口内**所有**形态
    （`ti:`/`all:`/`cat:`、带引号与裸词）一起 406，连静置 240s 都没出来（真源 ARXIV_QUIET_S），而 `id_list` 照常 200。
    所以别把这条注释读成"换成别的前缀就能绕过 406"——406 是**没回答**，不是"库里没有"，
    判据层已按 unavailable 处理（不进 k 分母）；真要用 arXiv 标题面，靠的是 F9 的 >=3s 间隔而非改写式。
    """
    words = [w for w in _norm_title(title).split() if w]
    if not words:
        return None
    return "%22" + "%20".join(urllib.parse.quote(w, safe="") for w in words[:12]) + "%22"


def _endpoint(index, doi, title, arxiv_id=None):
    """按标识符优先、否则按标题构造查询端点，返回 (url|None, by_id, why_not_applicable)。

    标识符 = DOI **或** arXiv 编号，二者同权（规格 references/30-literature-pipeline.md 反伪造偏置段写的是
    "按 DOI/编号查不到"）。上一版只在**有 DOI** 的分支里才读 arxiv_id，实测后果：无 DOI 的预印本条目
    （`22-refs.json` 的常见形态）带着编号也只走模糊标题检索，真编号与伪造编号的结果逐字相同。

    url=None 表示该索引对这条文献**结构性无从回答**（既不是"没回答"也不是"没有"），
    必须与 unavailable 分开计：它不进 k 的分母，也不该被当成一次失败。
    arXiv 只认自家 id——实测把非 arXiv DOI 的后缀塞进 id_list 直接 406（请求被拒，不是零结果）。
    """
    if index == "arxiv":
        aid = _arxiv_id(arxiv_id) or _arxiv_id(doi)
        if aid:
            return PREFIX["arxiv"] + "/api/query?id_list=" + aid, True, ""
        if doi:
            return None, True, "no_arxiv_identifier"
    if doi:
        q = urllib.parse.quote(doi, safe="")
        by_id = True
        if index == "openalex":
            return PREFIX["openalex"] + "/works/doi:" + q, by_id, ""
        if index == "crossref":
            return PREFIX["crossref"] + "/works/" + q, by_id, ""
        if index == "semantic_scholar":
            return (PREFIX["semantic_scholar"] + "/graph/v1/paper/DOI:" + q
                    + "?fields=title,year,venue,isRetracted"), by_id, ""
    q = urllib.parse.quote_plus(title or "")
    by_id = False
    if not q:
        return None, by_id, "no_query_key"
    if index == "openalex":
        return PREFIX["openalex"] + "/works?search=" + q + "&per-page=1", by_id, ""
    if index == "crossref":
        return PREFIX["crossref"] + "/works?query.bibliographic=" + q + "&rows=1", by_id, ""
    if index == "semantic_scholar":
        return (PREFIX["semantic_scholar"] + "/graph/v1/paper/search?query=" + q
                + "&limit=1&fields=title,year,venue,isRetracted"), by_id, ""
    phrase = _arxiv_phrase(title)
    if not phrase:
        return None, by_id, "no_query_key"
    return PREFIX["arxiv"] + "/api/query?search_query=ti:" + phrase + "&max_results=1", by_id, ""


def _unwrap(index, raw):
    """检索式响应是列表 → 收成单条候选；DOI 直查的单对象响应原样返回。"""
    if not isinstance(raw, dict):
        return None
    if index == "openalex":
        if isinstance(raw.get("results"), list):
            return (raw["results"] or [None])[0]
        return raw
    if index == "crossref":
        msg = raw.get("message")
        if isinstance(msg, dict) and isinstance(msg.get("items"), list):
            return {"message": (msg["items"] or [None])[0]}
        return raw
    if index == "semantic_scholar":
        if isinstance(raw.get("data"), list):
            return (raw["data"] or [None])[0]
        return raw
    return raw


def query_index(index, doi, title, fetch=None, arxiv_id=None):
    """返回 (source, record|None, by_id, reason)，source ∈ SOURCES + NOT_APPLICABLE。异常收敛为 unavailable。"""
    fetch = fetch or FETCH
    url, by_id, why = _endpoint(index, doi, title, arxiv_id=arxiv_id)
    if url is None:
        return NOT_APPLICABLE, None, by_id, why
    try:
        status, body, ctype = fetch(url)
    except TransportError as exc:
        return "unavailable", None, by_id, "transport_" + exc.kind
    obj, reason = _decode(index, status, body, ctype)
    if obj is None:
        return "unavailable", None, by_id, reason
    if obj is NO_RECORD:
        return "unmatched", None, by_id, reason
    try:
        rec = _extract(index, _unwrap(index, obj))
    except (KeyError, AttributeError, TypeError, IndexError, ValueError) as exc:
        # G-8（round3 B06）：字段类型漂移曾以 KeyError/AttributeError 裸崩、整批判定与
        # report 丢失（实测 crossref `title` 给对象、S2 `publicationVenue` 给 str）。逐索引
        # 收敛为 unavailable 并保留原因串——与"服务没回答"同档：不能因一家字段漂移废掉整批。
        return "unavailable", None, by_id, "extract_%s:%s" % (type(exc).__name__, str(exc)[:60])
    if rec is None or not (rec.get("title") or rec.get("year")):
        return "unmatched", None, by_id, "no_record"
    return "matched", rec, by_id, "ok"


# ---------- 判定 ----------

def title_similarity(ref_title, rec_title):
    a, b = _norm_title(ref_title), _norm_title(rec_title)
    if not a or not b:
        return 0.0
    # B14 输入预算：difflib 在超长相异串上是平方级开销——题录/记录标题正常不过 KB 量级，
    # 超预算截断后比较（正常输入逐字一致，退化输入只保证不卡死）。
    if len(a) > REGEX_INPUT_BUDGET:
        a = a[:REGEX_INPUT_BUDGET]
    if len(b) > REGEX_INPUT_BUDGET:
        b = b[:REGEX_INPUT_BUDGET]
    return difflib.SequenceMatcher(None, a, b).ratio()


def decide(entry, per_index, min_hits=MIN_HITS, min_answered=MIN_ANSWERED, skipped=()):
    """per_index = {index: (source, record|None, by_doi, reason)} → (state, detail)。

    四个分母必须分清，混了就会把真文献判成可疑：
      pool        = INDICES 去掉 --skip-indices 人工摘除者；
      applicable  = pool 中对这条文献**结构性可答**者（排除 not_applicable，如非 arXiv DOI 之于 arXiv）；
      answered    = applicable 中真正给出可读应答者（排除 unavailable：429/5xx/解码失败）；
      hits        = answered 中 matched 者。k = answered - hits，只在 answered 上计。
    门槛 need = min(--min-hits, pool)：answered < need → unresolvable（应答面不足，判不了）；
    hits < need → suspected（应答够了但覆盖不足，即规格里的"覆盖率噪音"）。
    另有两条**前置**分母，缺了就会把判不了说成可疑：
      标识符面 = 条目持有可解析标识符（DOI **或** arXiv 编号，规格反伪造偏置段同权）——hits==0 时
                 只有这一面成立才允许 suspected，纯标题一律 unresolvable；
      可评面   = 条目自己给了哪些比较所需的字段（缺 title → 相似度关不可评；year 与 venue 全缺 →
                 期刊/年份关不可评）→ 一律 unresolvable（reason=input_field_missing:…），
                 哪怕标识符查得到：缺的是**比较的输入**，补齐字段再跑，不靠松判据放行。
    其余三处"字段给了但对不上"（相似度、期刊/年份、命中数不足）按**标识符面**分档：
    持有可解析标识符 → suspected（标识符与记录矛盾），纯标题 → unresolvable（检索式跑偏不是伪造证据）。
    retracted 是唯一不分档的：它是对文献本身的阳性结论。
    """
    # G-2（round3 B06）：skipped 取集合语义——重名不得重复扣减 pool（曾 `crossref,crossref,arxiv`
    # 被算成摘 3 个、pool 塌到 1，门槛被重名降档）。去重保序。
    skipped = tuple(dict.fromkeys(skipped or ()))
    applicable, answered, unavailable, not_applicable = [], [], [], []
    index_status = {}
    for ix in INDICES:
        t = per_index.get(ix) or (NOT_APPLICABLE, None, False, "missing")
        # 出处标在状态串里：`[id]` 是按标识符精确查、`[title]` 是模糊检索命中，强度不同。
        # 只写 matched:ok 会让"伪造编号 + 真标题"这条读起来像编号核对通过（实测正是上一轮的失真面）；
        # unmatched 带 [id] 同样重要——那就是规格里的"按编号查不到"这条证据本身。
        # unavailable / not_applicable 根本没给出应答，标出处纯属噪音。
        if t[0] in ("unavailable", NOT_APPLICABLE):
            origin = ""
        elif t[2]:
            origin = "[id]"
        else:
            origin = "[title]" if t[0] == "matched" else ""
        index_status[ix] = "%s:%s%s" % (t[0], t[3], origin)
        if ix in skipped:
            index_status[ix] = "skipped"
            continue
        source = t[0]
        if source == NOT_APPLICABLE:
            not_applicable.append(ix)
        elif source == "unavailable":
            unavailable.append(ix)
        else:
            applicable.append(ix)
            answered.append(ix)
    hits = sum(1 for ix in answered if per_index[ix][0] == "matched")
    k = len(answered) - hits
    pool = len(INDICES) - len(skipped)
    need = min(min_hits, pool)
    doi = str(entry.get("doi") or "").strip()
    raw_aid = _arxiv_id(str(entry.get("arxiv_id") or entry.get("arxivId") or ""))
    aid = raw_aid or _arxiv_id(doi)
    id_kinds = (["doi"] if doi else []) + (["arxiv_id"] if raw_aid else [])
    has_id = bool(id_kinds)
    recs = [per_index[ix][1] for ix in answered if per_index[ix][1]]
    sims = [title_similarity(entry.get("title"), r.get("title")) for r in recs if r.get("title")]
    sim = max(sims, default=0.0)
    # 标题判据按"多数索引一致同意"取：单索引检索式跑偏（DOI 命中的是另一篇）时，
    # 只要有一个索引兜住就放行等于没有判据；反之只允许一家跑偏，避免字幕/大小写差异误杀。
    agree = sum(1 for s in sims if s >= SIM_THRESHOLD)
    sim_ok = bool(sims) and agree * 2 >= len(sims)
    venue_ok = any(_norm_title(r.get("venue")) == _norm_title(entry.get("venue")) and _norm_title(r.get("venue"))
                   for r in recs)
    year_ok = any(str(r.get("year")) == str(entry.get("year")) and entry.get("year") is not None for r in recs)
    retracted = any(bool(r.get("retracted")) for r in recs)
    # 判据**可评性**：条目自己没给的字段无法比较。缺 title → 相似度关不可评；year 与 venue 全缺 →
    # 期刊/年份关不可评。注意这与"字段给了但对不上"是两回事，后者才该判 suspected。
    title_given = bool(str(entry.get("title") or "").strip())
    ctx_given = entry.get("year") is not None or bool(str(entry.get("venue") or "").strip())
    input_gap = ([] if title_given else ["title"]) + ([] if ctx_given else ["year|venue"])
    # 反伪造偏置（规格反伪造偏置段）不只管"查不到"那一面，三处"查到了但对不上"同样适用：suspected 的语义是
    # "你给的标识符与权威记录矛盾"，纯标题条目没有可矛盾的标识符。实测：无 DOI 的 "Attention Is All
    # You Need"（year=2017）被 OpenAlex 一条 2025 同名条目带偏，venue/year 全 False，上一版在 strict
    # 下把这篇真文献拦成"伪造嫌疑"。缺标识符是**证据不够**，与 hits==0 那一面同档处理。
    # retracted 是唯一例外：那是对文献本身的阳性结论，与条目有没有标识符无关。
    mismatch_state = "suspected" if has_id else "unresolvable"
    detail = {"answered": len(answered), "applicable": len(applicable), "need": need,
              "k": k, "hits": hits, "similarity": round(sim, 3),
              "similarity_agree": "%d/%d" % (agree, len(sims)),
              "venue_match": venue_ok, "year_match": year_ok, "retracted": retracted,
              "queried_by_id": has_id, "id_kinds": id_kinds, "input_gap": input_gap,
              "unavailable": unavailable,
              "not_applicable": not_applicable, "skipped": list(skipped),
              "index_status": index_status,
              "degraded": bool(unavailable or not_applicable or skipped)}
    if len(answered) < max(1, min_answered):
        detail["reason"] = "insufficient_index_coverage"
        return "unresolvable", detail
    if hits == 0:
        # 反伪造偏置：持有**可解析**标识符（DOI 或 arXiv 编号）而有效应答的索引一致说"没有" → suspected；
        # 纯标题查不到 → unresolvable。规格把 DOI 与编号同权（references/30-literature-pipeline.md 反伪造偏置段），
        # 上一版只认 DOI，于是无 DOI 的预印本条目拿着伪造编号也进不了这一档。
        detail["reason"] = ("doi_not_found_in_any_index" if doi
                            else "arxiv_id_not_found_in_any_index" if aid
                            else "title_only_no_match")
        return ("suspected" if has_id else "unresolvable"), detail
    if retracted:
        detail["reason"] = "retracted"
        return "suspected", detail
    if input_gap:
        # 实测：只给 doi+title 的真 Nature 论文（hits=3/3、sim=1.00）上一版被判 suspected，
        # 而 22-refs.json 声明的字段（grade/verify_checks/two_source_verified/doi）里本就没有 year/venue
        # ——门控会对技能自己的主产物系统性指控"可疑"。缺字段是**证据不够**，一律 unresolvable。
        detail["reason"] = "input_field_missing:" + "+".join(input_gap)
        return "unresolvable", detail
    if not sim_ok:
        detail["reason"] = "title_similarity_below_threshold"
        return mismatch_state, detail
    if not (venue_ok or year_ok):
        detail["reason"] = "neither_venue_nor_year_matches"
        return mismatch_state, detail
    if len(answered) < need:
        # 应答面本身凑不齐 need 票：判不了，不是文献可疑（真网络下最常见：S2 限流 + arXiv 对非预印本不适用）。
        # 必须先于命中数判据——否则 answered < need 时 hits 必然也 < need，会被误降成 suspected。
        detail["reason"] = "insufficient_index_coverage"
        return "unresolvable", detail
    if hits < need:
        detail["reason"] = "coverage_below_min_hits"
        return mismatch_state, detail
    detail["reason"] = "all_checks_passed"
    return "verified", detail


def grade_refs(refs, min_hits=MIN_HITS, fetch=None, cache=None, min_answered=MIN_ANSWERED, skipped=()):
    # B10/G-10 输入面归并：先按 _dup_key 分组，每组只有代表条目走查询（含回退轮），
    # 组内其余复用代表的 per_index/fallback 结论。
    # 根因纪律：缓存键保持原始字段大小写（doi|arxiv_id|title 原样），归一化只决定"查几次"，
    # 不决定"缓存记在哪"——旧缓存条目继续有效，回放结论一致；dup 自己的原始键同样落盘一行，
    # 下次顺序调换也能命中。
    dup_keys = [_dup_key(e, i) for i, e in enumerate(refs)]
    rep_of = {}
    for k in dict.fromkeys(dup_keys):
        members = [i for i, kk in enumerate(dup_keys) if kk == k]
        for i in members:
            rep_of[i] = members[0]
    out = [None] * len(refs)
    memo = {}
    for i, entry in enumerate(refs):
        rep = rep_of[i]
        doi = str(entry.get("doi") or "").strip()
        title = str(entry.get("title") or "").strip()
        arxiv_id = str(entry.get("arxiv_id") or entry.get("arxivId") or "").strip()
        per_index, cache_hit = {}, False
        fell_back, id_round = [], {}
        # 缓存键必须含 arxiv_id：无 DOI 的预印本条目彼此只差编号，键里不带编号会让两条不同条目
        # 串用同一行缓存（实测过这种串法：doi 空 + title 相同即碰撞）。
        key = hashlib.sha256(("%s|%s|%s" % (doi, arxiv_id, title)).encode("utf-8")).hexdigest()
        if rep != i and rep in memo:
            per_index, cache_hit, fell_back, id_round = copy.deepcopy(memo[rep])
            if cache is not None:
                cache[key] = {"per_index": {ix: [st, r, bool(b), why]
                                            for ix, (st, r, b, why) in per_index.items()},
                              "title_fallback": list(fell_back), "id_round": dict(id_round),
                              "written_at": _now_iso()}
            state, detail = decide(entry, per_index, min_hits=min_hits, min_answered=min_answered, skipped=skipped)
        else:
            cached = cache.get(key) if cache is not None else None
            if isinstance(cached, dict) and isinstance(cached.get("per_index"), dict) \
                    and _cache_fresh(cached):
                per_index = {ix: (str(v[0]), v[1], bool(v[2]), str(v[3]) if len(v) > 3 else "cache")
                             for ix, v in cached["per_index"].items()
                             if isinstance(v, (list, tuple)) and v
                             and str(v[0]) in SOURCES + (NOT_APPLICABLE,)}
                cache_hit = len(per_index) == len(INDICES)
                # 回退结论随缓存一起回放：缓存里已是"标识符 + 标题都问过"的合并结果，
                # 二跑若再回退一次就会破掉"缓存零查询"的承诺。
                if cache_hit:
                    fell_back = [str(x) for x in (cached.get("title_fallback") or [])]
                    id_round = {str(k): str(v) for k, v in (cached.get("id_round") or {}).items()}
            if not cache_hit:
                per_index = {index: query_index(index, doi or None, title or None, fetch=fetch,
                                                arxiv_id=arxiv_id or None) for index in INDICES}
                need = min(min_hits, len(INDICES) - len(set(skipped or ())))
                id_queried = bool(_arxiv_id(arxiv_id) or _arxiv_id(doi) or doi)
                rescue_need = max(1, need)   # --min-hits 0 不得关掉标题轮：那时 need=0，标识符面的否证将无人复核
                if id_queried and title and sum(1 for v in per_index.values() if v[0] == "matched") < rescue_need:
                    # 标识符查不到 ≠ 文献不存在：DOI 可能是 arXiv 自家 DOI（三家 JSON API 结构上无收录，
                    # 实测正是这条形状）、注册有误、或新注册尚未索引；arXiv 编号同理可能是笔误或旧版号。
                    # 只在「按标识符的命中数已不足以放行」时才补问标题，且只补问**按标识符**答了"没有"的索引：
                    # 第一轮已经按标题答过的索引再问一次纯属重复（无 DOI 条目三家本就走标题面）。
                    # 真文献少付一轮请求，伪造条目多付一轮（这一轮本身就是判据）。
                    for ix in INDICES:
                        st, _, by_id, why = per_index[ix]
                        if st != "unmatched" or not by_id:
                            continue
                        id_round[ix] = "%s:%s" % (st, why)
                        alt = query_index(ix, None, title, fetch=fetch)
                        if alt[0] == "matched":
                            per_index[ix] = alt
                            fell_back.append(ix)
                if cache is not None:
                    cache[key] = {"per_index": {ix: [st, r, bool(b), why]
                                                for ix, (st, r, b, why) in per_index.items()},
                                  "title_fallback": list(fell_back), "id_round": dict(id_round),
                                  "written_at": _now_iso()}
            state, detail = decide(entry, per_index, min_hits=min_hits, min_answered=min_answered, skipped=skipped)
            memo[i] = (per_index, cache_hit, fell_back, id_round)
        detail["state"] = state
        detail["from_cache"] = cache_hit
        detail["title_fallback"] = fell_back
        # F5：JSON 三家 id 轮一致否证 + 标题轮救回 ≠ 干净命中。DOI 被三家结构性缺席只发生在
        # arXiv 自家 DOI（10.48550/arxiv.*）上；其余 DOI 遭三家 404 而仅标题命中，正是
        # "真文献 + 编造标识符"这一幻觉引用的最常见形态——降档 id_mismatch（非 verified）。
        # arXiv 编号条目与 arXiv 形态 DOI 维持 verified（回退机制的本意，口径保留）。
        detail["id_mismatch"] = False
        json_rescued = any(ix in fell_back
                           for ix in ("openalex", "crossref", "semantic_scholar"))
        doi_non_arxiv = bool(doi) and not re.match(r"(?i)^10\.48550/arxiv\.", doi)
        if state == "verified" and json_rescued and doi_non_arxiv:
            state = "id_mismatch"
            detail["state"] = state
            detail["id_mismatch"] = True
            detail["reason"] = "id_round_denied_title_rescued"
        # 回退会把标识符轮的结果覆盖掉，但"编号直查为何没命中"恰恰是判伪造的关键证据（实测见过
        # 真 DOI 因网络抖动记 transport_network、也见过臆造 DOI 记 not_found_404）——留在状态串里。
        for ix, prev in sorted(id_round.items()):
            if ix in detail["index_status"]:
                detail["index_status"][ix] += " <- id轮 " + prev
        detail["ref"] = (doi or title)[:120]
        detail["index"] = i
        if rep != i:
            detail["duplicate_of"] = rep
            detail["dup_key"] = "%s:%s" % dup_keys[i]
        out[i] = detail
    return out


# ---------- I/O ----------

def _now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _cache_fresh(entry):
    """G-7：缓存条目须带 `written_at` 且在 CACHE_TTL_DAYS 内，否则不采信（按未命中重查）。"""
    ts = entry.get("written_at") if isinstance(entry, dict) else None
    if not isinstance(ts, str) or not ts:
        return False
    try:
        when = datetime.fromisoformat(ts)
    except ValueError:
        return False
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - when) <= timedelta(days=CACHE_TTL_DAYS)


def _is_trusted_cache(obj):
    """G-7：`_meta.tool` 标记本工具产物；缺/不符即整份不采信（粗造假无标记即失效）。"""
    meta = obj.get("_meta") if isinstance(obj, dict) else None
    return isinstance(meta, dict) and meta.get("tool") == CACHE_META["tool"]


def _load_cache(path):
    """返回 (cache, error)。error 非空 → rc=2（含重复键的缓存不可信——G-7 造假面）。

    损坏 JSON / 不可读 / 顶层非对象走 A6 口径（返回 (None, None)，调用方 warning + 覆盖），
    与"重复键"（明确拒用）区分开。
    """
    try:
        with open(path, "r", encoding="utf-8-sig") as fh:
            loaded = json.load(fh, object_pairs_hook=_reject_dup_keys)
    except _DuplicateKey as exc:
        return None, ("cache 含重复键 %r（JSON last-wins 会静默吞掉前一条；重键缓存不可信，"
                      "曾是 G-7 造假面）" % str(exc))
    except (ValueError, OSError):
        return None, None
    if not isinstance(loaded, dict):
        return None, None
    return loaded, None


def _load_json_object(path, what):
    """返回 (obj, error)。文件缺失/坏 JSON/顶层非对象/重复键 → error 非空。

    B05（2026-10-07 三轮）：与 load_refs 同口径走重复键检出——此前 `json.load(fh)` 是
    json last-wins，重复键会静默吞掉前一条（本文件 F-2 已覆盖 load_refs，此处补漏）。
    """
    if not os.path.exists(path):
        return None, "%s 文件不存在：%s" % (what, path)
    try:
        with open(path, "r", encoding="utf-8-sig") as fh:
            data = json.load(fh, object_pairs_hook=_reject_dup_keys)
    except _DuplicateKey as exc:
        return None, "%s 含重复键 %r（JSON last-wins 会静默吞掉前一条，请去重后再喂）" % (what, str(exc))
    except (ValueError, OSError) as exc:
        return None, "%s 不是合法 JSON（%s）：%s" % (what, type(exc).__name__, str(exc)[:120])
    if not isinstance(data, dict):
        return None, "%s 顶层须为对象，实际为 %s" % (what, type(data).__name__)
    return data, None


class _DuplicateKey(ValueError):
    """输入 JSON 含重复键（F-2，2026-10-07 二轮）：json last-wins 会静默吞掉前一条。"""


def _reject_dup_keys(pairs):
    """object_pairs_hook：任意层级重复键即抛 _DuplicateKey（load_refs 输入面同口径）。"""
    seen = {}
    for k, v in pairs:
        if k in seen:
            raise _DuplicateKey(k)
        seen[k] = v
    return seen


def load_refs(path):
    """返回 (refs, error)。error 非空即 rc=2。"""
    if not os.path.exists(path):
        return None, "输入文件不存在：%s" % path
    try:
        with open(path, "r", encoding="utf-8-sig") as fh:
            # F-2（2026-10-07 二轮）：输入 JSON 走重复键检出——默认 last-wins 会静默
            # 吞掉重复的 refs 键，前一条输入被忽略而不报错。
            data = json.load(fh, object_pairs_hook=_reject_dup_keys)
    except _DuplicateKey as exc:
        return None, ("输入含重复键 %r：JSON last-wins 会静默吞掉前一条，请去重后再喂"
                      % str(exc))
    except (ValueError, OSError) as exc:
        return None, "输入不是合法 JSON（%s）：%s" % (type(exc).__name__, str(exc)[:120])
    if isinstance(data, dict):
        data = data.get("refs")
    if not isinstance(data, list):
        return None, "输入顶层须为列表或含 refs 列表的对象，实际为 %s" % type(data).__name__
    bad = [i for i, e in enumerate(data) if not isinstance(e, dict)]
    if bad:
        return None, "refs 第 %s 项不是对象" % bad
    if not data:
        # A5（2026-10-07 审查）：空列表曾以 strict 判绿（rc=0）——「全通过」是空集上的假绿。
        # 空库属输入问题（与 70 号空 manifest 同口径），归 rc=2。
        return None, ("输入 refs 列表为空：无可验条目，属输入问题（并非「全部通过」）；"
                      "请核对 22-refs.json 是否漏写或 --refs 是否指错路径")
    return data, None


def _note_unavailable(r):
    """把 unavailable 渲染成 `unavail=crossref:http_429`：原因必须跟着上屏——429 该稍后再跑、
    5xx 该换时段、解码失败该查是不是被网关拦了，三种处置不同。"""
    st = r.get("index_status") or {}
    return "unavail=" + ",".join("%s:%s" % (ix, str(st.get(ix, "unavailable:?")).split(":", 1)[-1])
                                 for ix in r["unavailable"])


def print_report(results, mode, skipped=()):
    counts = {s: 0 for s in STATES}
    degraded = unavailable_total = na_total = gap_total = 0
    for r in results:
        counts[r["state"]] = counts.get(r["state"], 0) + 1
        degraded += 1 if r.get("degraded") else 0
        unavailable_total += len(r.get("unavailable") or [])
        na_total += len(r.get("not_applicable") or [])
        gap_total += 1 if r.get("input_gap") else 0
        line = ("[%d] %-10s %-56s hits=%d/%d need=%d k=%d sim=%.2f(%s) venue=%s year=%s retr=%s id=%s"
                % (r["index"], r["state"], r["ref"][:56], r["hits"], r["answered"], r.get("need", 0),
                   r["k"], r["similarity"], r.get("similarity_agree", "-"),
                   "Y" if r["venue_match"] else "N", "Y" if r["year_match"] else "N",
                   "Y" if r["retracted"] else "N", ",".join(r.get("id_kinds") or []) or "-"))
        extra = []
        if r.get("title_fallback"):
            # 如实标明：命中来自标题回退而非标识符直查——编号查不到这件事本身要留痕。
            extra.append("title-fallback=" + ",".join(r["title_fallback"]))
        if r.get("id_mismatch"):
            extra.append("id-mismatch=DOI遭三家id轮否证、标题轮救回（F5）")
        if r.get("input_gap"):
            # 与"可疑"分家的提示：这一条是题录缺字段，补字段再跑即可，不是指控伪造。
            extra.append("缺字段=" + "+".join(r["input_gap"]))
        if r.get("duplicate_of") is not None:
            # B10/G-10：归并条目必须点名——与代表条目同键、结论复用，原始条目未丢弃。
            extra.append("重复条目=与[%d]同%s归并（只查一次）" % (r["duplicate_of"], r.get("dup_key", "?")))
        if r.get("unavailable"):
            extra.append(_note_unavailable(r))
        if r.get("not_applicable"):
            extra.append("n/a=" + ",".join(r["not_applicable"]))
        if skipped:
            extra.append("skipped=" + ",".join(skipped))
        if r["state"] == "verified":
            print("  PASS %s%s" % (line, (" " + " ".join(extra)) if extra else ""))
        else:
            tag = "BLOCK" if mode == "strict" else "ADVISORY"
            print("  %s %s <- %s%s" % (tag, line, r["reason"],
                                       (" [" + "; ".join(extra) + "]") if extra else ""))
    print("汇总：verified=%d id_mismatch=%d suspected=%d unresolvable=%d（mode=%s, 共 %d 条）"
          % (counts.get("verified", 0), counts.get("id_mismatch", 0), counts.get("suspected", 0),
             counts.get("unresolvable", 0), mode, len(results)))
    if gap_total:
        print("题录提示：%d 条因条目自身缺字段而判不了（unresolvable，非可疑）。"
              "verified 最少需要 title + (year 或 venue) 加一个可解析标识符；"
              "补齐字段再跑，别去松判据。" % gap_total)
    if unavailable_total or na_total:
        # 两个数分开报：n/a 是"该索引对这条文献结构性无从回答"（非 arXiv 文献的 arXiv 面，正常现象），
        # unavailable 是"服务没答上"（429/5xx/解码失败，该重跑）。混在一句里会出现"应答面不足四全
        # （unavailable 累计 0 次）"这种读起来自相矛盾的提示（实测上一版就是这样）。
        print("覆盖面提示：n/a=%d 次（结构性无从回答，如非预印本之于 arXiv）、unavailable=%d 次"
              "（服务没答上，稍后重跑）。两者都不计入 k 的分母；应答面不足四全的条目共 %d 条，"
              "这类条目是**证据不够**，不是伪造嫌疑。" % (na_total, unavailable_total, degraded))
    if skipped:
        print("人工摘除索引：%s —— 该集合不计入 hits/k 分母，verified 所需命中数随之下降，"
              "须在投稿材料里声明验真覆盖面。" % ",".join(skipped))
    if counts.get("unresolvable", 0):
        print("提示：unresolvable 不等于伪造——suspected 只留给「标识符与权威记录矛盾」（含撤稿）；"
              "缺标识符的条目无论查不到还是题录对不上，都只是证据不够（地方刊/非英语刊/未数字化文献"
              "的正常形态）。请按 30-literature-pipeline.md §2 走人工题录核对，不得据此判死。")
    dup_total = sum(1 for r in results if r.get("duplicate_of") is not None)
    if dup_total:
        print("归并提示：%d 条为重复条目（DOI 小写主键 / ISBN 去连字符归一 / 标题小写辅键），"
              "已与代表条目合并查询、结论复用；干净单条目输入无此行。" % dup_total)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="35-refs-gate.py",
                                 description="文献引用验真门控（四索引源状态分立 → k 汇总四态："
                                             "verified / id_mismatch / suspected / unresolvable）")
    ap.add_argument("--refs", help="22-refs.json 路径")
    ap.add_argument("--min-hits", type=int, default=MIN_HITS,
                    help="verified 所需最少命中索引数（缺省 2；实测：非预印本文献 arXiv 结构性不适用、"
                         "S2 免 key 常 404/429，按规格原口径 3 会把真文献判成覆盖不足。CS/ML 预印本库建议 3）")
    ap.add_argument("--min-answered", type=int, default=MIN_ANSWERED,
                    help="有效应答索引数低于此值即判 unresolvable（缺省 %d）" % MIN_ANSWERED)
    ap.add_argument("--skip-indices", help="逗号分隔，人工摘除的索引（如 semantic_scholar 长期 429）")
    ap.add_argument("--mode", choices=("advisory", "strict"), default="advisory")
    ap.add_argument("--cache", help="可选：查询缓存 JSON 路径（只读写该显式路径）")
    ap.add_argument("--report", help="可选：把结果 JSON 写到该路径")
    ap.add_argument("--fixtures", help="可选：离线复放 {index: {status,body,content_type}} JSON 路径，不联网")
    ap.add_argument("--max-retries", type=int, default=RETRIES,
                    help="429/5xx 退避重试次数（缺省 %d）" % RETRIES)
    ap.add_argument("--selftest", action="store_true", help="离线自测（真实响应形状 fixture，不联网）")
    ap.add_argument("--smoke-live", action="store_true",
                    help="真网络只读冒烟（四索引 source 分布 + 较上次漂移；不作 CI 硬门禁，需联网）")
    ap.add_argument("--probe", action="append", default=None,
                    help="冒烟题录 DOI 或 arXiv 编号（可多次；缺省内置 %d 条已知真题录）" % len(SMOKE_PROBES))
    ap.add_argument("--max-smoke-requests", type=int, default=SMOKE_MAX_REQUESTS,
                    help="冒烟总请求上限（缺省 %d）" % SMOKE_MAX_REQUESTS)
    args = ap.parse_args(argv)

    if _ENV_ERRORS:
        # G-4（2026-10-07 二轮）：非法礼貌池环境变量在此归 rc=2 点名——不得等建 Request 才崩。
        print("用法错误：%s" % "；".join(_ENV_ERRORS), file=sys.stderr)
        return 2

    if args.selftest:
        return run_selftest() | run_smoke_selftest()
    # B14（G-14）：--min-hits 下界为 0（0 = 只关门槛、不关标题轮，见 rescue_need；
    # 自测有用 0 的合法用例）。负数无判据语义，归 rc=2（用法错），不得按 need 算。
    if args.min_hits is not None and args.min_hits < 0:
        print("用法错误：--min-hits 下界违规（%r）：下界为 0，负数无判据语义" % (args.min_hits,),
              file=sys.stderr)
        return 2
    if args.smoke_live:
        if args.fixtures:
            fx, err = _load_json_object(args.fixtures, "fixtures")
            if err:
                print("用法错误：%s" % err, file=sys.stderr)
                return 2
            globals()["FETCH"] = _fixture_fetch(fx, [])
        rc, _ = run_smoke_live(_smoke_probes(args.probe),
                               max_requests=max(1, args.max_smoke_requests), report_path=args.report)
        return rc
    if not args.refs:
        print("用法错误：--refs 必需（或用 --selftest）", file=sys.stderr)
        return 2
    skipped = []
    if args.skip_indices:
        raw_skipped = [s.strip() for s in args.skip_indices.split(",") if s.strip()]
        bad = [s for s in raw_skipped if s not in INDICES]
        if bad:
            print("用法错误：--skip-indices 取值非法 %s，可选 %s" % (bad, list(INDICES)), file=sys.stderr)
            return 2
        # G-2（round3 B06）：取集合语义——重名曾把 pool 降档（`crossref,crossref,arxiv` 被算成
        # 摘 3 个、pool=1，门槛塌）；重名点名归 rc=2，全摘（池为空）也拒（无验真面）。
        dups = sorted({s for s in raw_skipped if raw_skipped.count(s) > 1})
        if dups:
            print("用法错误：--skip-indices 含重名 %s（取集合语义，重名会把 pool 门槛降档）"
                  % dups, file=sys.stderr)
            return 2
        skipped = list(dict.fromkeys(raw_skipped))
        if len(skipped) >= len(INDICES):
            print("用法错误：--skip-indices 摘除了全部索引（%s）：池为空即无验真面，"
                  "至少保留一个索引" % skipped, file=sys.stderr)
            return 2
    globals()["RETRIES"] = max(0, args.max_retries)
    if args.fixtures:
        fx, err = _load_json_object(args.fixtures, "fixtures")
        if err:
            print("用法错误：%s" % err, file=sys.stderr)
            return 2
        globals()["FETCH"] = _fixture_fetch(fx, [])
    refs, err = load_refs(args.refs)
    if err:
        print("用法错误：%s" % err, file=sys.stderr)
        return 2
    cache = None
    if args.cache:
        if os.path.exists(args.cache):
            loaded, cerr = _load_cache(args.cache)
            if cerr:
                # G-7（round3 B06）：含重复键的缓存不可信——rc=2 点名（last-wins 曾是造假面）。
                print("用法错误：%s" % cerr, file=sys.stderr)
                return 2
            if loaded is not None and _is_trusted_cache(loaded):
                cache = loaded
            elif loaded is not None:
                # G-7：缺/不符 _meta 的既有文件不当缓存用（粗造假无标记即失效），重查并覆盖。
                print("警告：cache 非本工具产物（缺/不符 _meta=%r），忽略并按未命中重查，"
                      "本次以新内容覆盖：%s" % (CACHE_META, args.cache), file=sys.stderr)
                cache = {}
            else:
                # A6（2026-10-07 审查）：损坏 cache 曾静默清空覆写用户文件（实测 21B→646B、零 warning）。
                # 现先上屏 warning 点名路径（留痕），再以新内容覆盖——不静默。
                print("警告：cache 文件损坏或不可读，本次将以新内容覆盖：%s（原内容非合法缓存 JSON）"
                      % args.cache, file=sys.stderr)
                cache = {}
        else:
            cache = {}
    results = grade_refs(refs, min_hits=args.min_hits, cache=cache, min_answered=args.min_answered,
                         skipped=skipped)
    # A6（2026-10-07 审查）：落盘一律前置于任何成功汇总（写失败时不得先打满汇总）；
    # 写失败（父目录不可建 / 目标是目录）→ 用法错 rc=2，脱敏且不裸 traceback。
    def _write_json(path, obj, what):
        parent = os.path.dirname(os.path.abspath(path))
        try:
            os.makedirs(parent, exist_ok=True)
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(obj, fh, ensure_ascii=False, indent=1)
        except OSError as exc:                       # IsADirectoryError 等均属 OSError
            print("用法错误：%s 无法写入 %s（%s）" % (what, path, type(exc).__name__),
                  file=sys.stderr)
            return False
        return True

    if cache is not None:
        cache["_meta"] = CACHE_META           # G-7：写出来源标记，下次载入据此判定是否本工具产物
        if not _write_json(args.cache, cache, "--cache"):
            return 2
    if args.report:
        if not _write_json(args.report, results, "--report"):
            return 2
    print_report(results, args.mode, skipped=skipped)
    if args.mode == "strict" and any(r["state"] != "verified" for r in results):
        return 1
    return 0


# ---------- 离线自测 ----------

def _fixture_fetch(records, calls):
    """在 fetch 层注入：records = {index: {status, body, content_type}}，body 为原始文本或 dict。

    意义：`_decode` 及其以下（Atom 解析、Crossref date-parts 解包、404/429 分档）走真实代码，
    只有真正联网的那一段被替换——上一版把 fixture 放在解码之上，才让 406/XML 这类真环境失败面测不到。
    """
    def fetch(url):
        for index in INDICES:
            if url.startswith(PREFIX[index]):
                calls.append(index)
                rec = records.get(index)
                if rec is None:
                    raise TransportError("fixture_missing", index)
                body = rec.get("body", "")
                if not isinstance(body, str):
                    body = json.dumps(body, ensure_ascii=False)
                ctype = rec.get("content_type") or (
                    "application/atom+xml; charset=utf-8" if index == "arxiv" else "application/json")
                return int(rec.get("status", 200)), body.encode("utf-8"), ctype
        calls.append("unknown")
        raise TransportError("unknown_endpoint", url[:60])
    return fetch


ATOM_ONE = ("<?xml version='1.0' encoding='UTF-8'?>\n<feed xmlns=\"http://www.w3.org/2005/Atom\" "
            "xmlns:arxiv=\"http://arxiv.org/schemas/atom\">\n  <title>arXiv Query</title>\n"
            "  <entry>\n    <id>http://arxiv.org/abs/1905.11481v1</id>\n"
            "    <updated>2019-05-28T00:00:00Z</updated>\n    <published>2019-05-28T00:00:00Z</published>\n"
            "    <title>Graphene Oxide Membranes for Nanofiltration</title>\n"
            "    <arxiv:journal_ref>Nature Water</arxiv:journal_ref>\n  </entry>\n</feed>\n")
ATOM_ZERO = ("<?xml version='1.0' encoding='UTF-8'?>\n<feed xmlns=\"http://www.w3.org/2005/Atom\">\n"
             "  <title>arXiv Query: no results</title>\n</feed>\n")

ENTRY = {"doi": "10.1038/s41545-019-0031-1", "title": "Graphene Oxide Membranes for Nanofiltration",
         "year": 2019, "venue": "Nature Water", "arxiv_id": "1905.11481"}


def _real_shape_records():
    """2026-09-26 实测的**响应形状**：Crossref 双层 envelope + date-parts 套列表、
    OpenAlex DOI 直查为单对象、S2 直查为单对象、arXiv 为 Atom XML 原文。

    注意口径：形状取自真响应，条目本身是合成样本——ENTRY 那组 doi/venue/year 是编的
    （实测该 DOI 在 OpenAlex/Crossref 均 404）。故这些 fixture 只用于验解码与判据分档，
    不得当作"真文献已验真"的证据；真环境证据另跑（不带 --fixtures 直连四索引）。
    """
    return {
        "openalex": {"body": {"display_name": "Graphene Oxide Membranes for Nanofiltration",
                              "publication_year": 2019,
                              "primary_location": {"source": {"display_name": "Nature Water"}},
                              "is_retracted": False}},
        "crossref": {"body": {"status": "ok", "message-type": "work", "message-version": "1.0.0",
                              "message": {"indexed": {"date-parts": [[2026, 9, 1]]},
                                          "title": ["Graphene Oxide Membranes for Nanofiltration"],
                                          "container-title": ["Nature Water"],
                                          "published-print": {"date-parts": [[2019, 5, 28]]}}}},
        "semantic_scholar": {"body": {"paperId": "a1b2",
                                      "title": "Graphene oxide membranes for nanofiltration",
                                      "year": 2019, "venue": "Nature Water", "isRetracted": False}},
        "arxiv": {"body": ATOM_ONE},
    }


# ---------- 真网络冒烟（--smoke-live，只读，不作硬门禁）----------

def _smoke_probes(specs):
    """把 CLI --probe 规范为 refs 条目；缺省用内置已知真题录。"""
    if not specs:
        return [dict(p) for p in SMOKE_PROBES]
    return [{"doi": s.strip()} for s in specs if s and s.strip()]


def smoke_distribution(results):
    """四索引 source 状态分布：{index: {matched/unmatched/unavailable/not_applicable: count}}。"""
    dist = {ix: {} for ix in INDICES}
    for r in results:
        for ix, st in (r.get("index_status") or {}).items():
            bucket = str(st).split(":", 1)[0]
            if ix in dist:
                dist[ix][bucket] = dist[ix].get(bucket, 0) + 1
    return dist


def diff_smoke(baseline, current):
    """对拍上次冒烟结果：返回漂移串列表；baseline 为 None 表示首次（返回 None，不误报漂移）。"""
    if baseline is None:
        return None
    old = {str(r.get("ref") or r.get("index")): r for r in baseline}
    drift = []
    for r in current:
        key = str(r.get("ref") or r.get("index"))
        o = old.get(key)
        if o is None:
            drift.append("%s: 新增条目" % key)
        elif o.get("state") != r.get("state"):
            drift.append("%s: %s -> %s" % (key, o.get("state"), r.get("state")))
    return drift


def run_smoke_live(probes, min_hits=MIN_HITS, min_answered=MIN_ANSWERED, fetch=None,
                   report_path=None, max_requests=SMOKE_MAX_REQUESTS, quiet=False):
    """只读冒烟：合规间隔跑四索引，输出分布与较上次基线漂移。返回 (rc, summary)。

    rc 恒为 0（漂移只告警）：外部服务限流非本仓可控，不得作 CI 硬门禁。
    """
    fetch = fetch or FETCH
    counter = {"n": 0}

    def counting_fetch(url):
        if counter["n"] >= max_requests:
            raise TransportError("smoke_budget_exceeded", "requests>=%d" % max_requests)
        counter["n"] += 1
        return fetch(url)

    results = grade_refs([dict(p) for p in probes], min_hits=min_hits,
                         fetch=counting_fetch, min_answered=min_answered)
    dist = smoke_distribution(results)
    baseline = None
    if report_path and os.path.exists(report_path):
        try:
            with open(report_path, "r", encoding="utf-8-sig") as fh:
                baseline = json.load(fh)
        except (ValueError, OSError):
            baseline = None
    drift = diff_smoke(baseline if isinstance(baseline, list) else None, results)

    def emit(*a):
        if not quiet:
            print(*a)

    emit("== 文献验真冒烟（--smoke-live；只读，不作 CI 硬门禁：外部服务限流非本仓可控）==")
    emit("probes=%d requests=%d/%d baseline=%s"
         % (len(probes), counter["n"], max_requests, "首次" if drift is None else "已加载"))
    for ix in INDICES:
        cells = dist.get(ix, {})
        emit("  %-18s %s" % (ix, " ".join("%s=%d" % (k, cells[k]) for k in sorted(cells)) or "(无应答)"))
    for r in results:
        emit("  %-12s %s" % (r.get("state"), str(r.get("ref") or "")[:60]))
    if drift is None:
        emit("  漂移：首次运行，无基线可比")
    elif drift:
        emit("  漂移告警（%d 处）：%s" % (len(drift), "；".join(drift[:6])))
    else:
        emit("  漂移：无（与上次基线一致）")
    if report_path:
        with open(report_path, "w", encoding="utf-8") as fh:
            json.dump(results, fh, ensure_ascii=False, indent=1)
        emit("  基线已写入：%s" % report_path)
    return 0, {"requests": counter["n"], "distribution": dist, "drift": drift,
               "states": [r.get("state") for r in results]}


def run_smoke_selftest():
    """离线覆盖 --smoke-live 的题录解析 / 请求预算 / 分布与漂移（fixture 注入，不联网）。"""
    print("== 冒烟子面离线自测（--smoke-live）==")
    fails = []

    def check(name, got, want):
        if got != want:
            fails.append(name)
        print("  %-4s %s" % ("OK" if got == want else "FAIL", name))

    recs = _real_shape_records()
    check("smoke：缺省内置题录 = %d 条" % len(SMOKE_PROBES), len(_smoke_probes(None)), len(SMOKE_PROBES))
    check("smoke：--probe 覆盖内置", [p["doi"] for p in _smoke_probes(["10.1/x", "arXiv:1706.03762"])],
          ["10.1/x", "arXiv:1706.03762"])
    rc, s = run_smoke_live([dict(ENTRY)], fetch=_fixture_fetch(recs, []),
                           report_path=None, max_requests=SMOKE_MAX_REQUESTS, quiet=True)
    check("smoke：请求数在 1..预算内", 1 <= s["requests"] <= SMOKE_MAX_REQUESTS, True)
    check("smoke：分布含四索引键", sorted(s["distribution"]) == sorted(INDICES), True)
    check("smoke：首次无基线不报漂移", s["drift"], None)
    check("smoke：永不因非 verified 变非零（不作硬门禁）", rc, 0)
    rc1, s1 = run_smoke_live([dict(ENTRY)], fetch=_fixture_fetch(recs, []),
                             report_path=None, max_requests=1, quiet=True)
    check("smoke：预算耗尽不崩溃（收敛记录）", (rc1, s1["requests"]), (0, 1))
    check("diff_smoke：state 变化 -> 漂移",
          diff_smoke([{"ref": "x", "state": "verified"}], [{"ref": "x", "state": "suspected"}]),
          ["x: verified -> suspected"])
    check("diff_smoke：None -> 首次 None", diff_smoke(None, [{"ref": "x"}]), None)
    check("diff_smoke：一致 -> 空", diff_smoke([{"ref": "x", "state": "verified"}],
                                               [{"ref": "x", "state": "verified"}]), [])
    print("smoke-selftest %s" % ("PASS" if not fails else "FAIL"))
    return 1 if fails else 0


# ---------- A-8 礼貌池接线守卫（行为级）+ A-9 31↔代码对账 ----------

def _polite_request_violations(url, headers, mailto="probe@example.com", key="PROBEKEY123"):
    """对单个已发请求的礼貌池期望（A-8 探针的判定核）：openalex 必须带 mailto、
    S2 必须带 x-api-key，双方不得串扰。headers 为已捕获的请求头 dict。"""
    host = urllib.parse.urlsplit(url).netloc
    low = {str(k).lower(): v for k, v in dict(headers).items()}
    out = []
    if host == "api.openalex.org":
        if "mailto=" not in url:
            out.append("openalex 请求缺 mailto（须经 _polite_url 追加；摘除接线即此处变红）")
    elif "mailto=" in url:
        out.append("%s 请求串入 mailto（礼貌池只许 openalex 带）" % host)
    if host == "api.semanticscholar.org":
        if low.get("x-api-key") != key:
            out.append("S2 请求缺 x-api-key（须经 _polite_headers 下发；摘除接线即此处变红）")
    elif "x-api-key" in low:
        out.append("%s 请求串入 x-api-key（S2 key 只许发 S2）" % host)
    return out


def _polite_wiring_violations():
    """A-8：_fetch_raw 必须经礼貌池发请求（行为级接线断言），返回违规串（空=接线完备）。

    纯函数单测（_polite_url/_polite_headers）只能证明"工具有这能力"，证明不了
    "_fetch_raw 真的用了它"——摘除 _fetch_raw 内两行调用后纯函数单测照绿。
    本探针双保险：① 源码名检查（_fetch_raw 的 co_names 须含两符号）；
    ② 行为探针（打测试值 + 假 opener 捕获真实 Request，断言 wiring 生效）。
    离线（假 opener 零联网），节流/退避清零后恢复（零真实 sleep）。
    """
    problems = []
    names = _fetch_raw.__code__.co_names
    for sym in ("_polite_url", "_polite_headers"):
        if sym not in names:
            problems.append("_fetch_raw 未接线 %s（摘除礼貌池调用即此处变红；纯函数单测覆盖不到该接线）" % sym)

    class _OK(object):
        status = 200
        headers = {"Content-Type": "application/json"}

        def read(self):
            return b"{}"

        def close(self):
            pass

    captured = {}

    def _opener(req, timeout=None):
        try:
            headers = dict(req.header_items())
        except Exception:
            headers = dict(getattr(req, "headers", {}) or {})
        captured[req.full_url] = headers
        return _OK()

    saved = (globals()["POLITE_MAILTO"], globals()["S2_API_KEY"],
             globals()["BACKOFF_S"], globals()["MIN_INTERVAL_S"], dict(_LAST_CALL))
    globals()["POLITE_MAILTO"], globals()["S2_API_KEY"] = "probe@example.com", "PROBEKEY123"
    globals()["BACKOFF_S"], globals()["MIN_INTERVAL_S"] = 0.0, 0.0
    _LAST_CALL.clear()
    try:
        _fetch_raw(PREFIX["openalex"] + "/works/doi:10.1%2Fx", retries=0, opener=_opener)
        _fetch_raw(PREFIX["semantic_scholar"] + "/graph/v1/paper/DOI:10.1%2Fx",
                   retries=0, opener=_opener)
        _fetch_raw(PREFIX["crossref"] + "/works/10.1%2Fx", retries=0, opener=_opener)
    except Exception as exc:
        problems.append("礼貌池行为探针异常（%s：%s）" % (type(exc).__name__, str(exc)[:80]))
        return problems
    finally:
        (globals()["POLITE_MAILTO"], globals()["S2_API_KEY"],
         globals()["BACKOFF_S"], globals()["MIN_INTERVAL_S"]) = saved[:4]
        _LAST_CALL.clear()
        _LAST_CALL.update(saved[4])
    for url, headers in sorted(captured.items()):
        problems.extend(_polite_request_violations(url, headers))
    if len(captured) != 3:
        problems.append("礼貌池行为探针只捕获 %d 个请求（期望 3，探针自身失效）" % len(captured))
    return problems


def _doc_31_violations(doc=None):
    """A-9：31↔代码数字对账（端点/参数名/限速数字以代码为真源），返回违规串（空=对账一致）。

    真值全部从 live 对象派生（PREFIX / _endpoint 实时输出 / 节流与重试常量 /
    SIM_THRESHOLD），不抄字面量；参数名先在 live URL 里验存在（代码改了参数而
    守卫没跟进时先报"守卫自身漂移"，不静默放行）。文档写错字面值即此处变红；
    PubMed 发现面无代码真源（E3：不参与验真门控），不在对账面。
    """
    if doc is None:
        here = os.path.dirname(os.path.abspath(__file__))
        path = os.path.join(here, "..", "references", "31-literature-endpoints.md")
        try:
            with open(path, "r", encoding="utf-8-sig") as fh:
                doc = fh.read()
        except OSError:
            return ["31 文档读不到：%s（对账无从判定，不放行）" % path]
    out = []

    def need(sub, label):
        if sub not in doc:
            out.append("31 文档缺代码真值 %s=%r（真源=scripts/35-refs-gate.py；文档写字面值即此处变红）"
                       % (label, sub))

    for ix in INDICES:
        need(PREFIX[ix], ix + " base URL")
    live = {
        "openalex": [_endpoint("openalex", "10.1/PROBE", "Probe Title")[0],
                     _endpoint("openalex", None, "Probe Title")[0]],
        "crossref": [_endpoint("crossref", "10.1/PROBE", "Probe Title")[0],
                     _endpoint("crossref", None, "Probe Title")[0]],
        "semantic_scholar": [_endpoint("semantic_scholar", "10.1/PROBE", "Probe Title")[0],
                             _endpoint("semantic_scholar", None, "Probe Title")[0]],
        "arxiv": [_endpoint("arxiv", None, "Probe Title", arxiv_id="1706.03762")[0],
                  _endpoint("arxiv", None, "Probe Title")[0]],
    }
    needles = {
        "openalex": ("/works/doi:", "per-page=1"),
        "crossref": ("query.bibliographic=", "rows=1"),
        "semantic_scholar": ("/graph/v1/paper/DOI:", "/graph/v1/paper/search",
                             "limit=1", "fields=title,year,venue,isRetracted"),
        "arxiv": ("id_list=", "search_query=ti:", "max_results=1"),
    }
    for ix, subs in needles.items():
        urls = [u for u in live[ix] if u]
        for sub in subs:
            if not any(sub in u for u in urls):
                out.append("对账守卫自身漂移：%s 参数 %r 已不在 live 端点里（先修守卫再对账）" % (ix, sub))
            else:
                need(sub, ix + " 参数 " + sub)
    need("HOST_INTERVAL_S", "节流分档表名")
    need("%.1f" % HOST_INTERVAL_S["export.arxiv.org"], "arxiv 节流秒数")
    need("ARXIV_QUIET_S", "静置秒数真源常量名（B11 A-10/C-4）")
    need("%ds" % ARXIV_QUIET_S, "arxiv 罚时静置秒数（B11 A-10/C-4）")
    need("MIN_INTERVAL_S = %s" % MIN_INTERVAL_S, "缺省节流秒数")
    need("RETRIES = %d" % RETRIES, "重试次数")
    need("BACKOFF_S = %s" % BACKOFF_S, "退避秒数")
    for code in RETRY_STATUS:
        need(str(code), "重试状态码 %d" % code)
    need("%.2f" % SIM_THRESHOLD, "标题相似度阈值")
    need("mailto", "礼貌池 mailto")
    need("S2_API_KEY", "S2 key 名")
    for host in THROTTLE_HOSTS:
        need(host, "节流 host")
    need(HEADERS["User-Agent"].split(" ")[0], "UA 前缀")
    return out


def run_selftest():
    fails = []

    def check(name, got, want):
        if got != want:
            fails.append("%s: got %r want %r" % (name, got, want))
            print("  FAIL %s: got %r want %r" % (name, got, want))
        else:
            print("  OK   %s" % name)

    def grade(entry, records, min_hits=MIN_HITS, min_answered=MIN_ANSWERED, skipped=()):
        calls = []
        fetch = _fixture_fetch(records, calls)
        per = {ix: query_index(ix, str(entry.get("doi") or "") or None,
                               str(entry.get("title") or "") or None, fetch=fetch,
                               arxiv_id=str(entry.get("arxiv_id") or "") or None) for ix in INDICES}
        state, detail = decide(entry, per, min_hits=min_hits, min_answered=min_answered, skipped=skipped)
        return state, calls, detail

    good = _real_shape_records()

    # AC1：真实形状四索引 fixture 下 verified，且样本面确实打到四个端点
    st, calls, _ = grade(ENTRY, good)
    check("真实形状样本（Crossref 双层 envelope + arXiv Atom XML）-> verified", st, "verified")
    check("样本面覆盖四索引", sorted(set(calls)), sorted(INDICES))
    # G2（2026-10-07）：礼貌池纯函数——缺省零回归 / 配置生效（无网）
    check("G2 缺省 UA 不含 mailto", "mailto:" in HEADERS["User-Agent"], False)
    check("G2 缺省 openalex URL 原样",
          _polite_url("https://api.openalex.org/works?search=x", "api.openalex.org", ""),
          "https://api.openalex.org/works?search=x")
    check("G2 配置 mailto：openalex 无 ? 时用 ? 追加",
          _polite_url("https://api.openalex.org/works/doi:10.1/x", "api.openalex.org", "a@b.c"),
          "https://api.openalex.org/works/doi:10.1/x?mailto=a@b.c")
    check("G2 配置 mailto：openalex 已有 ? 用 & 追加",
          _polite_url("https://api.openalex.org/works?search=x&per-page=1", "api.openalex.org", "a@b.c"),
          "https://api.openalex.org/works?search=x&per-page=1&mailto=a@b.c")
    check("G2 mailto 不发给非 openalex host",
          _polite_url("https://api.crossref.org/works/x", "api.crossref.org", "a@b.c"),
          "https://api.crossref.org/works/x")
    check("G2 S2 key 只发给 semanticscholar",
          (_polite_headers("api.semanticscholar.org", "K").get("x-api-key"),
           "x-api-key" in _polite_headers("api.openalex.org", "K")), ("K", False))
    check("G2 S2 key 缺省复用 HEADERS（零回归）",
          _polite_headers("api.semanticscholar.org", "") is HEADERS, True)
    # G-4（2026-10-07 二轮）：礼貌池环境变量消毒——CRLF/空格拒绝、合法通过、main 归 rc=2。
    check("G4 非法 mailto（CRLF）被拒", _clean_env("REFS_GATE_MAILTO", "a@b.c\r\nX: y")[1] is not None, True)
    check("G4 非法 mailto（内部空格）被拒", _clean_env("REFS_GATE_MAILTO", "a @b.c")[1] is not None, True)
    check("G4 合法 mailto 通过（strip 后原样）", _clean_env("REFS_GATE_MAILTO", "  a@b.c "), ("a@b.c", None))
    check("G4 空值不报错（缺省零回归）", _clean_env("S2_API_KEY", ""), ("", None))
    # B-1/B-2（round3 B06）：消毒扩到 HTTP 头合法字符（非 latin-1 / 控制字符），且逐源点名。
    check("B1 非 latin-1 mailto（中文邮箱）被拒",
          _clean_env("REFS_GATE_MAILTO", "陈@x.cn")[1] is not None, True)
    check("B1 非 latin-1 S2 key 被拒", _clean_env("S2_API_KEY", "密钥ABC")[1] is not None, True)
    check("B1 控制字符 mailto 被拒", _clean_env("REFS_GATE_MAILTO", "a@b\x01c")[1] is not None, True)
    check("B2 报错点名实际来源变量（OPENALEX_POLITE_EMAIL）",
          "OPENALEX_POLITE_EMAIL" in (_clean_env("OPENALEX_POLITE_EMAIL", "陈@x.cn")[1] or ""), True)
    check("B2 未设源（name 空）零回归", _clean_env("", ""), ("", None))
    _rc_env = subprocess.run([sys.executable, "-X", "utf8", "-B", __file__, "--selftest"],
                             capture_output=True, env=dict(os.environ, REFS_GATE_MAILTO="陈@x.cn"))
    check("B1 非 latin-1 mailto 经真实进程 -> rc=2（建 Request 前拦截）", _rc_env.returncode, 2)
    check("B2 真实进程报错点名 REFS_GATE_MAILTO",
          "REFS_GATE_MAILTO" in _rc_env.stderr.decode("utf-8", "replace"), True)
    _env_cr = {k: v for k, v in os.environ.items()
               if k not in ("REFS_GATE_MAILTO", "OPENALEX_POLITE_EMAIL", "CROSSREF_MAILTO")}
    _env_cr["CROSSREF_MAILTO"] = "陈@x.cn"
    _rc_env2 = subprocess.run([sys.executable, "-X", "utf8", "-B", __file__, "--selftest"],
                              capture_output=True, env=_env_cr)
    _err2 = _rc_env2.stderr.decode("utf-8", "replace")
    check("B2 值来自 CROSSREF_MAILTO 就点名 CROSSREF_MAILTO（不再一律 REFS_GATE_MAILTO）",
          ("CROSSREF_MAILTO" in _err2 and "REFS_GATE_MAILTO" not in _err2), True)
    _saved_env_errors = globals().get("_ENV_ERRORS")
    globals()["_ENV_ERRORS"] = ["REFS_GATE_MAILTO 取值含非法空白/CRLF"]
    try:
        check("G4 非法 env → main 归 rc=2（前置拦截，不递归）", main(["--selftest"]), 2)
    finally:
        globals()["_ENV_ERRORS"] = _saved_env_errors if _saved_env_errors is not None else []
    # A-8（B11）：礼貌池接线行为级断言——摘除 _fetch_raw 内礼貌池调用即红。
    check("A-8 _fetch_raw 接线完备（行为探针零违规）", _polite_wiring_violations(), [])

    def _bare_fetch(url):
        return urllib.request.Request(url, headers=dict(HEADERS))

    check("A-8 反向对照：接线名检查能咬住未接线函数",
          ("_polite_url" in _bare_fetch.__code__.co_names,
           "_polite_headers" in _bare_fetch.__code__.co_names), (False, False))
    _bare_req = urllib.request.Request(PREFIX["openalex"] + "/works/doi:10.1%2Fx",
                                      headers=dict(HEADERS))
    check("A-8 反向对照：绕过礼貌池的裸请求被判违规（探针非空转）",
          bool(_polite_request_violations(_bare_req.full_url, dict(_bare_req.header_items()))), True)
    # A-9（B11）：31↔代码数字对账——端点/参数名/限速数字从代码取真值。
    _here31 = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "..", "references", "31-literature-endpoints.md")
    try:
        with open(_here31, "r", encoding="utf-8-sig") as _fh31:
            _doc31 = _fh31.read()
    except OSError:
        _doc31 = ""
    check("A-9 31 文档在盘可读（对账输入）", bool(_doc31), True)
    check("A-9 31↔代码对账全绿（端点/参数/限速数字皆命中）", _doc_31_violations(_doc31), [])
    check("A-9 反向对照：改限速字面值（3.5→9.9）即红",
          bool(_doc_31_violations(_doc31.replace("3.5", "9.9"))), True)
    check("A-9 反向对照：改端点字面值（/works/doi:→/works/DOI:）即红",
          bool(_doc_31_violations(_doc31.replace("/works/doi:", "/works/DOI:"))), True)
    check("A-10/C-4 反向对照：改静置秒数字面值（240s→999s）即红",
          bool(_doc_31_violations(_doc31.replace("240s", "999s"))), True)
    check("A-10/C-4 反向对照：删静置真源常量名即红",
          bool(_doc_31_violations(_doc31.replace("ARXIV_QUIET_S", "NO_SUCH_CONST"))), True)
    try:
        with open(os.path.abspath(__file__), "r", encoding="utf-8-sig") as _fh35:
            _src35 = _fh35.read()
    except OSError:
        _src35 = ""
    _quiet_old = '静置 7' + '5s'
    check('A-10/C-4 35 内双数消除（无旧小值残留）', _quiet_old in _src35, False)
    check("A-10/C-4 35 侧静置秒数与真源一致", ("静置 %ds" % ARXIV_QUIET_S) in _src35, True)
    check("B11 smoke 第三条 DOI 真值=NumPy 篇（离线修正）",
          dict((p.get("doi"), p.get("title")) for p in SMOKE_PROBES).get("10.1038/s41586-020-2649-2"),
          "Array programming with NumPy")
    # F-2（2026-10-07 二轮）：load_refs 输入重复键 → rc=2 点名；正常输入反向对照。
    import tempfile as _tempfile
    with _tempfile.TemporaryDirectory() as _td:
        _dup = os.path.join(_td, "dup.json")
        with open(_dup, "w", encoding="utf-8") as _fh:
            _fh.write('[{"refs": [{"doi": "10.1/a"}], "refs": [{"doi": "10.1/b"}]}]')
        _drefs, _derr = load_refs(_dup)
        check("F2 load_refs 输入重复键 → 报错点名", bool(_derr) and "重复键" in _derr, True)
        _okf = os.path.join(_td, "ok.json")
        with open(_okf, "w", encoding="utf-8") as _fh:
            _fh.write('[{"doi": "10.1/a", "title": "T"}]')
        _orefs, _oerr = load_refs(_okf)
        check("F2 正常输入无重复键 → 通过（反向对照）", (_oerr, len(_orefs or [])), (None, 1))
    # F1/F2 回归：解码层本身
    check("Crossref date-parts [[2019,5,28]] -> 2019（F2）", _extract("crossref", good["crossref"]["body"])["year"], 2019)
    # G-8（round3 B06）：字段类型漂移（crossref title 给对象 / S2 publicationVenue 给 str）
    # 逐索引收敛为 unavailable（保留原因串），不得裸 KeyError/AttributeError 崩掉整批。
    _drift_cr = copy.deepcopy(good)
    _drift_cr["crossref"]["body"]["message"]["title"] = {"weird": "object"}
    _st_cr = query_index("crossref", ENTRY["doi"], None, fetch=_fixture_fetch(_drift_cr, []))
    check("G-8 crossref title 给对象 -> unavailable（不裸 KeyError）",
          (_st_cr[0], str(_st_cr[3]).startswith("extract_")), ("unavailable", True))
    _drift_s2 = copy.deepcopy(good)
    _drift_s2["semantic_scholar"]["body"].pop("venue", None)   # venue 缺，逼出 publicationVenue 分支
    _drift_s2["semantic_scholar"]["body"]["publicationVenue"] = "str-not-dict"
    _st_s2 = query_index("semantic_scholar", ENTRY["doi"], None, fetch=_fixture_fetch(_drift_s2, []))
    check("G-8 S2 publicationVenue 给 str -> unavailable（不裸 AttributeError）",
          (_st_s2[0], str(_st_s2[3]).startswith("extract_")), ("unavailable", True))
    check("arXiv Atom XML -> 归一条目（F1）",
          _extract("arxiv", _decode("arxiv", 200, ATOM_ONE.encode("utf-8"), "application/atom+xml; charset=utf-8")[0]),
          {"title": "Graphene Oxide Membranes for Nanofiltration", "year": 2019,
           "venue": "Nature Water", "retracted": False})
    check("arXiv Atom 零条目 -> unmatched（应答了但没有，不是没回答）",
          query_index("arxiv", None, "Whatever", fetch=_fixture_fetch({"arxiv": {"body": ATOM_ZERO}}, []))[0],
          "unmatched")
    check("arXiv 406（实测：查询形状不合服务端胃口时直接拒，不是零结果）-> unavailable",
          query_index("arxiv", ENTRY["doi"], None, arxiv_id=ENTRY["arxiv_id"],
                      fetch=_fixture_fetch({"arxiv": {"status": 406, "body": "Not Acceptable"}}, []))[0],
          "unavailable")
    # not_applicable：arXiv 只认自家 id，拿非 arXiv DOI 的后缀去查是发无意义请求（实测直接 406）
    na_calls = []
    na = query_index("arxiv", "10.1038/nature14539", None,
                     fetch=_fixture_fetch(_real_shape_records(), na_calls))
    check("非 arXiv DOI 且无 arxiv_id -> not_applicable", (na[0], na[3]),
          ("not_applicable", "no_arxiv_identifier"))
    check("not_applicable 不发请求（调用面为空）", na_calls, [])
    check("arXiv DOI（10.48550/ 前缀）仍走 id_list",
          query_index("arxiv", "10.48550/arXiv.1706.03762", None,
                      fetch=_fixture_fetch({"arxiv": {"body": ATOM_ONE}}, []))[0],
          "matched")
    # F1 的规范化面：实测 `id_list=arXiv.1706.03762` 与带斜杠旧式 id 都被 406 拒收
    check("_arxiv_id：10.48550 DOI -> 裸 id", _arxiv_id("10.48550/arXiv.1706.03762"), "1706.03762")
    check("_arxiv_id：arXiv: 前缀 + 版本号", _arxiv_id("arXiv:1706.03762v5"), "1706.03762v5")
    check("_arxiv_id：裸 id 原样", _arxiv_id("1706.03762"), "1706.03762")
    check("_arxiv_id：旧式带斜杠 -> %2F 转义（斜杠会被 arXiv 拒）",
          _arxiv_id("quant-ph/9601029"), "quant-ph%2F9601029")
    check("_arxiv_id：非 arXiv DOI -> None（不得发无意义请求）", _arxiv_id("10.1038/s41545-019-0031-1"), None)
    check("_arxiv_id：空/None -> None", (_arxiv_id(""), _arxiv_id(None)), (None, None))
    check("_arxiv_phrase：词间用 %20、短语用 %22 包裹（实测 + 分隔一律 406）",
          _arxiv_phrase("Graphene Oxide Membranes for Nanofiltration"),
          "%22graphene%20oxide%20membranes%20for%20nanofiltration%22")
    check("_arxiv_phrase：空标题 -> None", _arxiv_phrase("  --- "), None)
    check("标题模式 arXiv 端点用 ti: + 短语式",
          _endpoint("arxiv", None, "Graphene Oxide Membranes")[0].endswith(
              "/api/query?search_query=ti:%22graphene%20oxide%20membranes%22&max_results=1"), True)
    check("JSON 解码失败 -> unavailable 而非 unmatched",
          query_index("openalex", ENTRY["doi"], None,
                      fetch=_fixture_fetch({"openalex": {"body": "<html>blocked</html>",
                                                         "content_type": "text/html"}}, []))[0],
          "unavailable")

    # F3 第 4 项：429/406 退避重试（假 opener，离线且零 sleep）
    class _Resp(object):
        def __init__(self, status, body, ctype):
            self.status, self._body = status, body.encode("utf-8")
            self.headers = {"Content-Type": ctype}

        def read(self):
            return self._body

        def close(self):
            pass

    box = {"n": 0, "slept": []}

    def flaky_opener(req, timeout=None):
        box["n"] += 1
        if box["n"] == 1:
            raise urllib.error.HTTPError(req.full_url, 406, "Not Acceptable", {"Content-Type": "text/html"}, None)
        return _Resp(200, '{"display_name": "Graphene Oxide Membranes for Nanofiltration",'
                         '"publication_year": 2019, "is_retracted": false}', "application/json")

    saved_backoff, saved_fetch = globals()["BACKOFF_S"], globals()["FETCH"]
    saved_interval = globals()["MIN_INTERVAL_S"]
    globals()["BACKOFF_S"] = 0.0
    globals()["MIN_INTERVAL_S"] = 0.0
    try:
        retried = _fetch_raw(PREFIX["openalex"] + "/works/doi:x", retries=2, opener=flaky_opener)
        time_calls = box["n"]
        globals()["BACKOFF_S"] = 0.0
        exhausted_box = {"n": 0}

        def always_429(req, timeout=None):
            exhausted_box["n"] += 1
            raise urllib.error.HTTPError(req.full_url, 429, "Too Many Requests",
                                         {"Content-Type": "application/json"}, None)

        gave_up = _fetch_raw(PREFIX["openalex"] + "/works/doi:x", retries=1, opener=always_429)
        globals()["FETCH"] = _fixture_fetch(_real_shape_records(), [])
        live_status = query_index("openalex", ENTRY["doi"], None)[0]
        check("406 首次即退避重试并成功（请求数=2）", time_calls, 2)
        check("退避后拿到 200 即按 matched 走真解码", retried[0], 200)
        check("重试用尽仍 429 -> 返回状态码交判据层分档", (gave_up[0], exhausted_box["n"]), (429, 2))
        check("反向对照：同一条目经缺省 FETCH（含退避路径）仍 matched", live_status, "matched")
    finally:
        globals()["BACKOFF_S"], globals()["FETCH"] = saved_backoff, saved_fetch
        globals()["MIN_INTERVAL_S"] = saved_interval

    # ---------- F9：节流按 host 分档（arXiv 的 406 是自己 1s 连发喂出来的） ----------
    # 用假 time 驱动，断言的是"真的按 host 取间隔"这个机制，而不是表里的数字；零真实 sleep。
    check("节流表里的 host 必须在节流名单内（否则 HOST_INTERVAL_S 是死配置）",
          [h for h in HOST_INTERVAL_S if h not in THROTTLE_HOSTS], [])
    check("arXiv 间隔 >=3s（官方下限），其余 host 用缺省值",
          (HOST_INTERVAL_S["export.arxiv.org"] >= 3.0, MIN_INTERVAL_S), (True, 1.0))

    class _FakeTime(object):
        def __init__(self, start):
            self.t, self.slept = start, []

        def time(self):
            return self.t

        def sleep(self, seconds):
            self.slept.append(seconds)
            self.t += seconds

    ft = _FakeTime(1000.0)
    saved_time, saved_last = globals()["time"], dict(_LAST_CALL)
    globals()["time"] = ft
    try:
        def probe(host, since):
            globals()["_LAST_CALL"][host] = ft.t - since
            del ft.slept[:]
            _throttle(host)
            return ft.slept[0] if ft.slept else 0.0
        arx = probe("export.arxiv.org", 0.5)
        oal = probe("api.openalex.org", 0.5)
        ok_fast = probe("api.openalex.org", 5.0)
        free = probe("example.org", 0.0)
    finally:
        globals()["time"] = saved_time
        _LAST_CALL.clear()
        _LAST_CALL.update(saved_last)
    check("0.5s 前刚请求过 arXiv -> 补足到 3.5s（旧版只补到 1s，等于持续违规）",
          round(arx, 3), 3.0)
    check("同样 0.5s 间隔对 OpenAlex 只补到 1s（没有一刀切拖慢）", round(oal, 3), 0.5)
    check("距上次 5s 则 arXiv 之外不等待", (ok_fast, free), (0.0, 0.0))

    # AC2：--min-hits 覆盖 k 阈值后同一条目判定随动
    hits3 = json.loads(json.dumps(good))
    hits3["arxiv"] = {"status": 404, "body": '{"error":"no such id"}'}
    check("hits=3/answered=4 且 min-hits=3 -> verified", grade(ENTRY, hits3, min_hits=3)[0], "verified")
    check("同一条目 min-hits=4 -> suspected（判定随动）", grade(ENTRY, hits3, min_hits=4)[0], "suspected")

    # F3：unavailable 不进 k 分母；限流不等于文献可疑
    throttle = json.loads(json.dumps(good))
    throttle["semantic_scholar"] = {"status": 429, "body": '{"code":"429","message":"Too Many Requests"}'}
    st_t, _, det_t = grade(ENTRY, throttle)
    check("S2 429 -> 该索引记 unavailable", det_t["unavailable"], ["semantic_scholar"])
    check("S2 429 时 answered/hits/k = 3/3/0", (det_t["answered"], det_t["hits"], det_t["k"]), (3, 3, 0))
    check("S2 429 时仍 verified", st_t, "verified")
    check("限流样本标 degraded", det_t["degraded"], True)
    # F3 审计面：三类"没答上"要能分开处置（稍后再跑 / 换时段 / --skip-indices 摘除）
    check("index_status 记 unavailable 的原因串（429 ≠ 5xx ≠ 解码失败）",
          det_t["index_status"]["semantic_scholar"], "unavailable:http_429")
    check("报告行把 unavailable 连原因一起上屏", _note_unavailable(det_t),
          "unavail=semantic_scholar:http_429")
    check("index_status 记结构性不适用（不是失败，是没得答）",
          grade(dict(ENTRY, arxiv_id=""), good)[2]["index_status"]["arxiv"],
          "not_applicable:no_arxiv_identifier")
    check("index_status 记人工摘除",
          grade(ENTRY, throttle, skipped=("semantic_scholar",))[2]["index_status"]["semantic_scholar"],
          "skipped")
    # G-2（round3 B06）：skipped 取集合语义——重名不得重复扣减 pool/need。
    check("G-2 池按集合算：重名 skipped 不重复扣减 need",
          grade(ENTRY, good, skipped=("crossref", "crossref", "arxiv"))[2]["need"], 2)
    notfound = json.loads(json.dumps(good))
    notfound["semantic_scholar"] = {"status": 404, "body": '{"error":"Paper with id DOI:... not found"}'}
    _, _, det_n = grade(ENTRY, notfound)
    check("反向对照：S2 404（服务答了没有）-> answered=4、k=1、无 unavailable",
          (det_n["answered"], det_n["k"], det_n["unavailable"]), (4, 1, []))
    check("index_status 分得开「服务说没有」与「服务没回答」，且带标识符出处 [id]",
          (det_n["index_status"]["semantic_scholar"], det_n["index_status"]["openalex"]),
          ("unmatched:not_found_404[id]", "matched:ok[id]"))
    check("反向对照：同条件 min-hits=4 时 404 样本降为 suspected、429 样本降为 unresolvable",
          (grade(ENTRY, notfound, min_hits=4)[0], grade(ENTRY, throttle, min_hits=4)[0]),
          ("suspected", "unresolvable"))
    # 实测回归（2026-09-26 真网络首跑）：只有 OpenAlex+Crossref 应答时，按严格口径不得放行
    two_only = json.loads(json.dumps(good))
    two_only["semantic_scholar"] = {"status": 503, "body": "down"}
    two_only["arxiv"] = {"status": 503, "body": "down"}
    st_2, _, det_2 = grade(ENTRY, two_only, min_hits=3)
    check("answered=2 < need=3 -> unresolvable（应答面不足，判不了）", st_2, "unresolvable")
    check("该降级不得伪装成伪造嫌疑（reason 串区分）", det_2["reason"], "insufficient_index_coverage")
    check("反向对照：同样本 min-hits=2（缺省）时放行 verified", grade(ENTRY, two_only)[0], "verified")
    silent = {ix: {"status": 503, "body": "service down"} for ix in INDICES}
    st_s, _, det_s = grade(ENTRY, silent)
    check("四索引全无应答 -> unresolvable（不得判成伪造嫌疑）", st_s, "unresolvable")
    check("无应答时的原因串", det_s["reason"], "insufficient_index_coverage")

    # AC3 反伪造偏置
    all_no = {ix: {"status": 404, "body": '{"error":"not found"}'} for ix in INDICES}
    check("DOI 在有效应答的索引全查不到 -> suspected", grade(ENTRY, all_no)[0], "suspected")
    title_only = {"title": ENTRY["title"], "year": 2019, "venue": "Nature Water"}
    check("纯标题查不到 -> unresolvable", grade(title_only, all_no)[0], "unresolvable")

    # AC4：三条判据各破坏一条 -> suspected
    low_sim = json.loads(json.dumps(good))
    low_sim["openalex"]["body"]["display_name"] = "Totally Different Title About Soils"
    low_sim["crossref"]["body"]["message"]["title"] = ["Totally Different Title About Soils"]
    low_sim["semantic_scholar"]["body"]["title"] = "Totally Different Title About Soils"
    check("相似度 <0.70 -> suspected", grade(ENTRY, low_sim)[0], "suspected")

    one_off = json.loads(json.dumps(good))
    one_off["openalex"]["body"]["display_name"] = "Totally Different Title About Soils"
    check("仅一家索引标题跑偏（3/4 同意）-> 仍 verified（多数判据不过杀）", grade(ENTRY, one_off)[0], "verified")

    no_ctx = json.loads(json.dumps(good))
    no_ctx["openalex"]["body"]["primary_location"]["source"]["display_name"] = "Journal of Fictional Studies"
    no_ctx["openalex"]["body"]["publication_year"] = 1901
    no_ctx["crossref"]["body"]["message"]["container-title"] = ["Journal of Fictional Studies"]
    no_ctx["crossref"]["body"]["message"]["published-print"] = {"date-parts": [[1901, 1, 1]]}
    no_ctx["semantic_scholar"]["body"]["venue"] = "Journal of Fictional Studies"
    no_ctx["semantic_scholar"]["body"]["year"] = 1901
    no_ctx["arxiv"]["body"] = ATOM_ONE.replace("2019-05-28", "1901-01-01").replace(
        "Nature Water", "Journal of Fictional Studies")
    check("期刊与年份均不一致 -> suspected", grade(ENTRY, no_ctx)[0], "suspected")

    year_only = json.loads(json.dumps(good))
    year_only["openalex"]["body"]["primary_location"] = {"source": None}
    year_only["crossref"]["body"]["message"]["container-title"] = []
    year_only["semantic_scholar"]["body"]["venue"] = ""
    year_only["arxiv"]["body"] = ATOM_ONE.replace(
        "<arxiv:journal_ref>Nature Water</arxiv:journal_ref>", "")
    check("期刊全缺、仅年份一致时仍可 verified（F2 的生效面）", grade(ENTRY, year_only)[0], "verified")

    retracted = json.loads(json.dumps(good))
    retracted["openalex"]["body"]["is_retracted"] = True
    check("is_retracted=true -> suspected", grade(ENTRY, retracted)[0], "suspected")

    check("显式摘除 S2 -> skipped 记名且仍 verified",
          (grade(ENTRY, throttle, skipped=("semantic_scholar",))[2]["skipped"],
           grade(ENTRY, throttle, skipped=("semantic_scholar",))[0]),
          (["semantic_scholar"], "verified"))

    # ---------- 标题回退：真网络 2026-09-26 跑出的假阳性 ----------
    # DOI 是 arXiv DOI（10.48550/…）时，OpenAlex/Crossref/S2 结构上没有这篇，只有 arXiv 认；
    # 没有回退时必然 hits=1 < need=2 → 把真实文献判成可疑。fixture 按 URL 区分两种模式。
    def _two_mode_fetch(records, calls):
        def fetch(url):
            mode = "doi" if any(m in url for m in ("doi:", "DOI:", "/works/10.", "id_list=")) else "title"
            for index in INDICES:
                if url.startswith(PREFIX[index]):
                    calls.append(index + ":" + mode)
                    rec = records[index][mode]
                    if rec is None:
                        raise TransportError("fixture_missing", index + ":" + mode)
                    spec = rec if isinstance(rec, dict) and "body" in rec else {"body": rec}
                    body = spec.get("body", "")
                    if not isinstance(body, str):
                        body = json.dumps(body, ensure_ascii=False)
                    ctype = spec.get("content_type") or (
                        "application/atom+xml; charset=utf-8" if index == "arxiv" else "application/json")
                    return int(spec.get("status", 200)), body.encode("utf-8"), ctype
            calls.append("unknown:" + mode)
            raise TransportError("unknown_endpoint", url[:60])
        return fetch

    atom_transformer = ATOM_ONE.replace("Graphene Oxide Membranes for Nanofiltration",
                                        "Attention Is All You Need").replace(
        "2019-05-28", "2017-06-12").replace(
        "\n    <arxiv:journal_ref>Nature Water</arxiv:journal_ref>", "")
    ENTRY_MODES = {"openalex": {"doi": good["openalex"]["body"], "title": None},
                   "crossref": {"doi": good["crossref"]["body"], "title": None},
                   "semantic_scholar": {"doi": good["semantic_scholar"]["body"], "title": None},
                   "arxiv": {"doi": ATOM_ONE, "title": None}}
    arxiv_entry = {"doi": "10.48550/arXiv.1706.03762", "title": "Attention Is All You Need",
                   "year": 2017, "venue": "arXiv"}
    NOT_IN_DOI = {"openalex": {"doi": {"status": 404, "body": '{"error":"no work"}'},
                               "title": {"results": [{"display_name": "Attention Is All You Need",
                                                      "publication_year": 2017,
                                                      "primary_location": {"source": None},
                                                      "is_retracted": False}]}},
                  "crossref": {"doi": {"status": 404, "body": '{"status":"error","message":"not found"}'},
                               "title": {"status": "ok", "message-type": "work-list",
                                         "message-version": "1.0.0",
                                         "message": {"facets": {}, "total-results": 1, "items": [
                                             {"title": ["Attention Is All You Need"],
                                              "container-title": [],
                                              "published-print": {"date-parts": [[2017, 6, 12]]}}]}}},
                  "semantic_scholar": {"doi": {"status": 404, "body": '{"error":"Paper not found"}'},
                                       "title": {"data": [{"paperId": "cccf",
                                                           "title": "Attention Is All You Need",
                                                           "year": 2017, "venue": "",
                                                           "isRetracted": False}]}},
                  "arxiv": {"doi": atom_transformer, "title": atom_transformer}}
    fb_calls = []
    fb = grade_refs([arxiv_entry], fetch=_two_mode_fetch(NOT_IN_DOI, fb_calls))[0]
    check("DOI 全 404 而 arXiv 命中 -> 标题回退后 verified（旧版判 suspected 的假阳性）",
          (fb["state"], fb["hits"], fb["reason"]), ("verified", 4, "all_checks_passed"))
    check("回退只补查 DOI 模式判 unmatched 的三家", fb["title_fallback"],
          ["openalex", "crossref", "semantic_scholar"])
    check("回退调用面 = DOI 轮 4 + 标题轮 3", sorted(fb_calls),
          sorted(["openalex:doi", "crossref:doi", "semantic_scholar:doi", "arxiv:doi",
                  "openalex:title", "crossref:title", "semantic_scholar:title"]))
    check("index_status 保留标识符轮结论并标出来路（回退不得抹掉「编号为何没命中」）",
          fb["index_status"]["openalex"], "matched:ok[title] <- id轮 unmatched:not_found_404")
    check("回退后凑满 4 票：min-hits=4 也可 verified（回退补的是真证据）",
          grade_refs([arxiv_entry], min_hits=4, fetch=_two_mode_fetch(NOT_IN_DOI, []))[0]["state"],
          "verified")
    PARTIAL = json.loads(json.dumps(NOT_IN_DOI))
    PARTIAL["semantic_scholar"]["title"] = {"status": 404, "body": '{"error":"Paper not found"}'}
    check("反向对照：仅 2/4 家标题可查（S2 标题也 404）时 min-hits=4 -> suspected",
          (grade_refs([arxiv_entry], min_hits=4, fetch=_two_mode_fetch(PARTIAL, []))[0]["state"],
           grade_refs([arxiv_entry], min_hits=4, fetch=_two_mode_fetch(PARTIAL, []))[0]["reason"]),
          ("suspected", "coverage_below_min_hits"))
    check("反向对照：同样本 min-hits=2 时放行（阈值真的随动）",
          grade_refs([arxiv_entry], min_hits=2, fetch=_two_mode_fetch(PARTIAL, []))[0]["state"], "verified")
    NO_WHERE = json.loads(json.dumps(NOT_IN_DOI))
    for ix in ("openalex", "crossref", "semantic_scholar"):
        NO_WHERE[ix]["title"] = {"status": 404, "body": '{"error":"no match"}'}
    NO_WHERE["arxiv"] = {"doi": ATOM_ZERO, "title": ATOM_ZERO}
    nw_calls = []
    nw = grade_refs([arxiv_entry], fetch=_two_mode_fetch(NO_WHERE, nw_calls))[0]
    check("反向对照：DOI 与标题都查不到 -> suspected，且不得有回退命中",
          (nw["state"], nw["reason"], nw["title_fallback"]),
          ("suspected", "doi_not_found_in_any_index", []))
    check("反向对照：回退两轮共 8 次查询（每索引 DOI + 标题各一次）", len(nw_calls), 8)
    nm_calls = []
    nm = grade_refs([ENTRY], fetch=_two_mode_fetch(ENTRY_MODES, nm_calls))[0]
    check("反向对照：DOI 已命中时不回退标题（调用面恰为 4，省一半请求）",
          (nm["state"], nm["title_fallback"], sorted(set(nm_calls))),
          ("verified", [], ["arxiv:doi", "crossref:doi", "openalex:doi", "semantic_scholar:doi"]))
    fb_cache = {}
    box1, box2 = [], []
    grade_refs([arxiv_entry], fetch=_two_mode_fetch(NOT_IN_DOI, box1), cache=fb_cache)
    r2 = grade_refs([arxiv_entry], fetch=_two_mode_fetch(NOT_IN_DOI, box2), cache=fb_cache)[0]
    check("回退结论随缓存回放：首跑 7 次、二跑 0 次",
          (len(box1), len(box2)), (7, 0))
    check("缓存回放不丢回退标记",
          (r2["state"], r2["from_cache"], r2["title_fallback"], r2["index_status"]["openalex"]),
          ("verified", True, ["openalex", "crossref", "semantic_scholar"],
           "matched:ok[title] <- id轮 unmatched:not_found_404"))

    # ---------- F7：标识符面（arXiv 编号与 DOI 同权，规格反伪造偏置段的「按 DOI/编号查不到」） ----------
    url_nod, bid_nod, _ = _endpoint("arxiv", None, "Attention Is All You Need", arxiv_id="1706.03762")
    check("无 DOI 但有编号 → 按 id_list 精确查（旧版在这里退成模糊标题检索）",
          ("id_list=1706.03762" in url_nod, bid_nod), (True, True))
    check("反向对照：既无编号也无 DOI 才退成 ti: 短语检索",
          _endpoint("arxiv", None, "Attention Is All You Need")[0].startswith(
              PREFIX["arxiv"] + "/api/query?search_query=ti:"), True)
    check("反向对照：非 arXiv DOI 且无编号 → 不发请求（实测畸形 id_list 直接被 406 拒）",
          (_endpoint("arxiv", "10.1038/s41545-019-0031-1", "Whatever")[0],
           _endpoint("arxiv", "10.1038/s41545-019-0031-1", "Whatever")[2]),
          (None, "no_arxiv_identifier"))
    preprint = {"arxiv_id": "1706.03762", "title": "Attention Is All You Need", "year": 2017, "venue": "arXiv"}
    dead = {ix: {"status": 404, "body": '{"error":"no match"}'} for ix in INDICES}
    dead["arxiv"] = {"body": ATOM_ZERO}
    st_pid, _, det_pid = grade(preprint, dead)
    check("AC3 编号臂：无 DOI、持失效 arXiv 编号且四索引一致否证 → suspected",
          (st_pid, det_pid["reason"], det_pid["id_kinds"], det_pid["queried_by_id"]),
          ("suspected", "arxiv_id_not_found_in_any_index", ["arxiv_id"], True))
    st_tit, _, det_tit = grade({k: v for k, v in preprint.items() if k != "arxiv_id"}, dead)
    check("反向对照：同一条目去掉编号（纯标题否证）→ unresolvable，不得指控伪造",
          (st_tit, det_tit["reason"], det_tit["id_kinds"]),
          ("unresolvable", "title_only_no_match", []))
    fakeid = json.loads(json.dumps(NOT_IN_DOI))
    fakeid["arxiv"] = {"doi": ATOM_ZERO, "title": atom_transformer}
    fx = grade_refs([dict(preprint, arxiv_id="9999.99999")], fetch=_two_mode_fetch(fakeid, []))[0]
    check("审计面不撒谎：伪造编号 + 真标题被三家认下时，arXiv 行要显示编号那轮否证",
          (fx["index_status"]["arxiv"].startswith("unmatched"), "[id]" in fx["index_status"]["arxiv"],
           fx["state"], fx["index_status"]["openalex"]),
          (True, True, "verified", "matched:ok[title]"))
    check("同一条目写成 10.48550 DOI 形态时，编号轮的否证照样留痕（标题回退不得抹掉它）",
          grade_refs([dict(preprint, doi="10.48550/arXiv.9999.99999", arxiv_id="")],
                     fetch=_two_mode_fetch(fakeid, []))[0]["index_status"]["arxiv"],
          "matched:ok[title] <- id轮 unmatched:no_record")
    id_cache, second_calls = {}, []
    grade_refs([preprint], fetch=_two_mode_fetch(NOT_IN_DOI, []), cache=id_cache)
    grade_refs([dict(preprint, arxiv_id="9999.99999")], fetch=_two_mode_fetch(NOT_IN_DOI, second_calls),
               cache=id_cache)
    check("缓存键含 arxiv_id：只差编号的两条不得串用同一行（第二条必须重查 4 次）",
          (len(id_cache), len(second_calls)), (2, 4))
    # ---------- F5：真文献 + 编造 DOI（JSON 三家 id 轮否证、标题轮救回）→ id_mismatch ----------
    fab = {"doi": "10.9999/j.fabricated.2024", "title": "Attention Is All You Need",
           "year": 2017, "venue": "NeurIPS"}
    f5 = grade_refs([fab], fetch=_two_mode_fetch(NOT_IN_DOI, []))[0]
    check("F5 主案：编造 DOI + 真标题被三家 id 轮否证、标题轮救回 → id_mismatch（旧版 verified）",
          (f5["state"], f5["id_mismatch"], f5["reason"], f5["hits"]),
          ("id_mismatch", True, "id_round_denied_title_rescued", 3))   # hits=3：非 arXiv DOI 之于 arXiv 面不适用
    check("F5 留痕：index_status 仍显示 id 轮否证（审计面不撒谎）",
          (f5["index_status"]["openalex"].startswith("matched:ok[title] <- id轮 unmatched"),
           f5["index_status"]["openalex"][:60]),
          (True, "matched:ok[title] <- id轮 unmatched:not_found_404"))
    f5c, f5_calls2 = {}, []
    grade_refs([fab], fetch=_two_mode_fetch(NOT_IN_DOI, []), cache=f5c)[0]
    f5_cached = grade_refs([fab], fetch=_two_mode_fetch(NOT_IN_DOI, f5_calls2), cache=f5c)[0]
    check("F5 缓存二跑结论一致（id_mismatch 可经缓存复放，且二跑零查询）",
          (f5_cached["state"], f5_cached["from_cache"], f5_calls2),
          ("id_mismatch", True, []))
    _f5_arxiv = grade_refs([dict(fab, doi="10.48550/arXiv.1706.03762")],
                           fetch=_two_mode_fetch(NOT_IN_DOI, []))[0]
    check("F5 反向对照：同条目换 arXiv 形态 DOI → verified（结构性 404 口径保留）",
          (_f5_arxiv["state"], _f5_arxiv["id_mismatch"]), ("verified", False))
    _f5_clean = grade_refs([ENTRY], fetch=_fixture_fetch(good, []))[0]
    check("F5 反向对照：真 DOI 命中（无回退）→ verified 且 id_mismatch=False",
          (_f5_clean["state"], _f5_clean["id_mismatch"]), ("verified", False))
    z_calls = []
    zentry = {"doi": "10.1000/no.such.doi", "title": "Attention Is All You Need", "year": 2017, "venue": "arXiv"}
    z = grade_refs([zentry], min_hits=0, fetch=_two_mode_fetch(NOT_IN_DOI, z_calls))[0]
    check("--min-hits 0 仍付标题轮：need=0 时标识符面的否证不得无人复核（旧版在此直接判可疑）",
          (len(z_calls), z["state"], z["reason"]),
          (6, "id_mismatch", "id_round_denied_title_rescued"))   # F5：zentry 的 DOI 非 arXiv 形态且遭三家 id 轮否证，救回后降档
    check("反向对照：同条目换 arXiv 编号形态（无 DOI）→ 救回后维持 verified（F5 口径保留）",
          grade_refs([dict(zentry, doi="", arxiv_id="9999.99999")],
                     min_hits=0, fetch=_two_mode_fetch(NOT_IN_DOI, []))[0]["state"],
          "verified")
    check("反向对照：同样本在标识符与标题两面都查不到时仍 suspected",
          grade_refs([zentry], min_hits=0, fetch=_two_mode_fetch(NO_WHERE, []))[0]["reason"],
          "doi_not_found_in_any_index")

    # ---------- F6：判据可评性（题录缺字段是判不了，不是可疑） ----------
    no_ctx = {k: v for k, v in ENTRY.items() if k not in ("year", "venue")}
    st_nc, _, det_nc = grade(no_ctx, good)
    check("F6：标识符与标题全命中（hits=4、sim=1.0）但条目没给 year/venue → unresolvable",
          (st_nc, det_nc["reason"], det_nc["input_gap"], det_nc["hits"]),
          ("unresolvable", "input_field_missing:year|venue", ["year|venue"], 4))
    no_title = {k: v for k, v in ENTRY.items() if k != "title"}
    st_nt, _, det_nt = grade(no_title, good)
    check("F6：只给标识符（无 title）→ 相似度关不可评，unresolvable 而非疑似伪造",
          (st_nt, det_nt["reason"], det_nt["input_gap"]),
          ("unresolvable", "input_field_missing:title", ["title"]))
    check("反向对照：字段在场而对不上，照旧 suspected（没把判据松掉）",
          grade(dict(ENTRY, year=1901, venue="Journal of Fictional Studies"), good)[0], "suspected")
    check("只有 year（venue 留空）仍可 verified：判据是「期刊或年份」，单字段缺席不算不可评",
          grade(dict(ENTRY, venue=""), good)[0], "verified")
    check("只有 venue（year 不给）同上", grade(dict(ENTRY, year=None), good)[0], "verified")
    gap_res = grade_refs([no_ctx], fetch=_two_mode_fetch(ENTRY_MODES, []))
    na_res = grade_refs([dict(ENTRY, arxiv_id="")], fetch=_two_mode_fetch(ENTRY_MODES, []))
    buf = io.StringIO()
    old_out = sys.stdout
    sys.stdout = buf
    try:
        print_report(gap_res, "advisory")
        print_report(na_res, "advisory")
    finally:
        sys.stdout = old_out
    rpt = buf.getvalue()
    check("报表把缺字段单列，并给「补字段再跑、别松判据」的题录提示",
          ("缺字段=year|venue" in rpt, "题录提示" in rpt, "id=doi,arxiv_id" in rpt),
          (True, True, True))
    check("n/a 与 unavailable 分开计数（旧版混成一句，实测出现过「应答面不足四全（unavailable 累计 0 次）」）",
          ("覆盖面提示" in rpt, "n/a=1 次" in rpt, "unavailable=0 次" in rpt), (True, True, True))

    # ---------- F8：suspected 只允许由标识符面（或撤稿）触发 ----------
    # 规格反伪造偏置段字面上只管"查不到"那一面，但"查到了对不上"的三处判据同样在指控作者伪造，
    # 而纯标题条目根本没有可矛盾的标识符：真环境实测（2026-09-26 直连四索引）"Attention Is All You
    # Need"（无 DOI、year=2017）被 OpenAlex 一条 2025 同名条目带偏 → suspected → strict 模式拦下
    # 一篇真文献。四处失败面逐个补对照，另加撤稿这条例外。
    no_id = {k: v for k, v in ENTRY.items() if k not in ("doi", "arxiv_id")}
    thin = json.loads(json.dumps(good))
    for ix in ("crossref", "semantic_scholar"):
        thin[ix] = {"status": 404, "body": '{"error":"no match"}'}
    nowhere = {"openalex": {"status": 404, "body": '{"error":"no work"}'},
               "crossref": {"status": 404, "body": '{"status":"error","message":"not found"}'},
               "semantic_scholar": {"status": 404, "body": '{"error":"Paper not found"}'},
               "arxiv": {"body": ATOM_ZERO}}
    st_ctx, _, det_ctx = grade(dict(no_id, year=1901, venue="Journal of Fictional Studies"), good)
    check("F8：纯标题条目「期刊/年份对不上」→ unresolvable（真网络那条假阳性的离线复现）",
          (st_ctx, det_ctx["reason"], det_ctx["queried_by_id"]),
          ("unresolvable", "neither_venue_nor_year_matches", False))
    check("反向对照：同样记录、条目带 DOI 时照旧 suspected（标识符与记录矛盾才是伪造信号）",
          grade(dict(ENTRY, year=1901, venue="Journal of Fictional Studies"), good)[0], "suspected")
    st_sim, _, det_sim = grade(dict(no_id, title="Zzz Fabricated Title Qqq"), good)
    check("F8：纯标题条目「相似度不达标」→ unresolvable（检索式跑偏不是伪造证据）",
          (st_sim, det_sim["reason"]), ("unresolvable", "title_similarity_below_threshold"))
    check("反向对照：同样样本带 DOI → suspected",
          grade(dict(ENTRY, title="Zzz Fabricated Title Qqq"), good)[0], "suspected")
    st_cov, _, det_cov = grade(no_id, thin, min_hits=4)
    check("F8：纯标题条目「命中数不足」→ unresolvable",
          (st_cov, det_cov["reason"], det_cov["hits"]), ("unresolvable", "coverage_below_min_hits", 2))
    check("反向对照：同样本带 DOI → suspected（规格 :17 的 k=3/4 强信号只属于标识符面）",
          grade(ENTRY, thin, min_hits=4)[0], "suspected")
    st_none, _, det_none = grade(dict(no_id, title="Zzz Fabricated Title Qqq"), nowhere)
    check("F8：纯标题条目「四面全查不到」→ unresolvable",
          (st_none, det_none["reason"]), ("unresolvable", "title_only_no_match"))
    check("反向对照：同样本带 DOI → suspected",
          grade(dict(ENTRY, title="Zzz Fabricated Title Qqq"), nowhere)[0], "suspected")
    retr = json.loads(json.dumps(good))
    retr["openalex"]["body"]["is_retracted"] = True
    st_ret, _, det_ret = grade(no_id, retr)
    check("不变量唯一例外：撤稿是对文献本身的阳性结论，纯标题条目照旧 suspected",
          (st_ret, det_ret["reason"]), ("suspected", "retracted"))
    check("不变量成文：无标识符条目在四类失败面上都不产出 suspected，只有撤稿那一格例外",
          sorted({st_ctx, st_sim, st_cov, st_none}) + ["retracted->" + st_ret],
          ["unresolvable", "retracted->suspected"])
    f8_rows = grade_refs([dict(no_id, year=1901, venue="Journal of Fictional Studies")],
                         fetch=_fixture_fetch(good, []))
    buf8 = io.StringIO()
    old8 = sys.stdout
    sys.stdout = buf8
    try:
        print_report(f8_rows, "advisory")
    finally:
        sys.stdout = old8
    check("报表尾提示跟着改口径：unresolvable 不再只解释成「查不到」（F8 后含「对不上」那一面）",
          "标识符与权威记录矛盾" in buf8.getvalue(), True)

    # AC1/AC5：CLI 全链路 + 退出码
    tmp = os.environ.get("TEMP", "/tmp")
    refs_file = os.path.join(tmp, "rg-selftest-refs.json")
    report_file = os.path.join(tmp, "rg-selftest-report.json")
    fx_file = os.path.join(tmp, "rg-selftest-fixtures.json")
    cache_file = os.path.join(tmp, "rg-selftest-cache.json")
    bogus = {"doi": "10.0000/not-a-real-record", "title": "Zzzz Nonexistent Paper Qqqq",
             "year": 1999, "venue": "Nowhere"}
    with open(fx_file, "w", encoding="utf-8") as fh:
        json.dump(good, fh, ensure_ascii=False)
    saved_fetch = globals()["FETCH"]
    globals()["FETCH"] = _fixture_fetch(good, [])
    try:
        with open(refs_file, "w", encoding="utf-8") as fh:
            json.dump([ENTRY, bogus], fh, ensure_ascii=False)
        check("advisory 下存在非 verified 仍 rc=0",
              main(["--refs", refs_file, "--mode", "advisory", "--report", report_file]), 0)
        check("strict 下同一样本 rc!=0",
              main(["--refs", refs_file, "--mode", "strict", "--report", report_file]) != 0, True)
        with open(refs_file, "w", encoding="utf-8") as fh:
            json.dump([ENTRY], fh, ensure_ascii=False)
        check("全 verified 时 strict rc=0（反向对照）", main(["--refs", refs_file, "--mode", "strict"]), 0)
        check("--fixtures 复放走真实解码面", main(["--refs", refs_file, "--fixtures", fx_file]), 0)
        check("非法 --skip-indices -> rc=2", main(["--refs", refs_file, "--skip-indices", "google_scholar"]), 2)
        # G-2（round3 B06）：重名/全摘拒；合法单次摘除是反向对照。
        check("G2 重名 --skip-indices -> rc=2 点名重复",
              main(["--refs", refs_file, "--skip-indices", "crossref,crossref,arxiv"]), 2)
        check("G2 全摘 --skip-indices -> rc=2（池为空无验真面）",
              main(["--refs", refs_file, "--skip-indices",
                    "openalex,crossref,semantic_scholar,arxiv"]), 2)
        check("G2 合法单次摘除 -> 不误拒（反向对照，池仍够门槛）",
              main(["--refs", refs_file, "--skip-indices", "semantic_scholar"]), 0)
        check("缺 --refs -> rc=2", main([]), 2)
        check("不存在的 --refs -> rc=2", main(["--refs", refs_file + ".nope"]), 2)
        with open(refs_file, "w", encoding="utf-8") as fh:
            fh.write("{not json")
        check("坏 JSON -> rc=2", main(["--refs", refs_file]), 2)
        with open(refs_file, "w", encoding="utf-8") as fh:
            json.dump("scalar", fh)
        check("顶层非列表 -> rc=2", main(["--refs", refs_file]), 2)

        # ── A5/A6（2026-10-07 审查）：空库判绿 / 写盘失败裸崩 / 坏 cache 静默覆写 ──
        with open(refs_file, "w", encoding="utf-8") as fh:
            json.dump([], fh)
        check("空 refs 列表 -> rc=2（空库不判绿，A5）",
              main(["--refs", refs_file, "--mode", "strict"]), 2)

        with open(refs_file, "w", encoding="utf-8") as fh:
            json.dump([ENTRY], fh, ensure_ascii=False)
        rep_dir = os.path.join(tmp, "rg-selftest-reportdir")
        os.makedirs(rep_dir, exist_ok=True)
        buf_dir = io.StringIO()
        _e, _o = sys.stderr, sys.stdout
        sys.stderr, sys.stdout = buf_dir, io.StringIO()
        try:
            rc_dir = main(["--refs", refs_file, "--report", rep_dir])
        finally:
            sys.stderr, sys.stdout = _e, _o
        check("--report <目录> -> rc=2（不裸崩，A6）", rc_dir, 2)
        check("--report <目录> 输出无 Traceback", "Traceback" in buf_dir.getvalue(), False)

        nested = os.path.join(tmp, "rg-selftest-nested", "sub", "r.json")
        check("--report 父目录不存在 -> 自动建目录后正常结束（非裸崩，A6）",
              main(["--refs", refs_file, "--report", nested]) in (0, 1), True)
        check("--report 父目录不存在 已落盘", os.path.isfile(nested), True)

        bad_cache = os.path.join(tmp, "rg-selftest-badcache.json")
        with open(bad_cache, "w", encoding="utf-8") as fh:
            fh.write("NOT-JSON-GARBAGE")
        buf_bc = io.StringIO()
        _e, _o = sys.stderr, sys.stdout
        sys.stderr, sys.stdout = buf_bc, io.StringIO()
        try:
            main(["--refs", refs_file, "--mode", "advisory", "--cache", bad_cache])
        finally:
            sys.stderr, sys.stdout = _e, _o
        check("损坏 cache -> warning 点名路径且不静默（A6）",
              ("cache" in buf_bc.getvalue().lower()
               and "rg-selftest-badcache.json" in buf_bc.getvalue()), True)
        check("损坏 cache -> 不裸崩", "Traceback" in buf_bc.getvalue(), False)

        for p in (refs_file, cache_file):
            try:
                os.remove(p)
            except OSError:
                pass
        with open(refs_file, "w", encoding="utf-8") as fh:
            json.dump([ENTRY], fh, ensure_ascii=False)
        calls_box = []
        globals()["FETCH"] = _fixture_fetch(good, calls_box)
        main(["--refs", refs_file, "--cache", cache_file])
        first = len(calls_box)
        main(["--refs", refs_file, "--cache", cache_file])
        check("缓存首跑查四索引", first, 4)
        check("缓存二跑零查询（幂等）", len(calls_box) - first, 0)
        check("缓存回放后仍无网络（取数面零调用）", len(calls_box) - first, 0)

        # G-7（round3 B06）：缓存须为**本工具产物**且**未过期**——伪造/过期不再得 verified/零联网。
        forge_cache = os.path.join(tmp, "rg-selftest-forge-cache.json")
        dup_cache = os.path.join(tmp, "rg-selftest-dup-cache.json")
        _key = hashlib.sha256(("%s|%s|%s" % (ENTRY["doi"], ENTRY["arxiv_id"], ENTRY["title"]))
                              .encode("utf-8")).hexdigest()
        _per = {ix: ["matched", {"title": ENTRY["title"], "year": ENTRY["year"],
                                 "venue": ENTRY["venue"], "retracted": False}, True, "ok"]
                for ix in INDICES}
        _allmiss = {ix: {"status": 404, "body": '{"error":"not found"}'} for ix in INDICES}
        # (a) 过期缓存（合法 _meta 但 written_at 超 TTL）→ 不采信、重新查询、不得 verified
        with open(forge_cache, "w", encoding="utf-8") as fh:
            json.dump({"_meta": CACHE_META,
                       _key: {"per_index": _per, "title_fallback": [], "id_round": {},
                              "written_at": "2000-01-01T00:00:00+00:00"}}, fh, ensure_ascii=False)
        calls_g7 = []
        globals()["FETCH"] = _fixture_fetch(_allmiss, calls_g7)
        main(["--refs", refs_file, "--cache", forge_cache, "--report", report_file])
        check("G7 过期 cache 不采信 -> 重新查询（非零联网）", len(calls_g7) >= 4, True)
        with open(report_file, encoding="utf-8") as fh:
            _rep = json.load(fh, object_pairs_hook=_reject_dup_keys)
        check("G7 过期 cache 伪造 matched 不再得 verified", _rep[0]["state"], "suspected")
        check("G7 过期 cache 未走缓存（from_cache=False）", _rep[0]["from_cache"], False)
        # (b) 缺 _meta 的手写 cache → 整份忽略 + warning 点名（来源校验）
        with open(forge_cache, "w", encoding="utf-8") as fh:
            json.dump({_key: {"per_index": _per, "title_fallback": [], "id_round": {},
                              "written_at": _now_iso()}}, fh, ensure_ascii=False)
        buf_fg = io.StringIO()
        _e, _o = sys.stderr, sys.stdout
        sys.stderr, sys.stdout = buf_fg, io.StringIO()
        try:
            main(["--refs", refs_file, "--cache", forge_cache])
        finally:
            sys.stderr, sys.stdout = _e, _o
        check("G7 缺 _meta 的伪造 cache -> 忽略并警告（来源校验）",
              "非本工具产物" in buf_fg.getvalue(), True)
        # (c) 含重复键的 cache → rc=2（重键缓存不可信）
        with open(dup_cache, "w", encoding="utf-8") as fh:
            fh.write('{"_meta": {"tool": "35-refs-gate"}, "_meta": {"tool": "x"}}')
        check("G7 cache 重复键 -> rc=2 点名",
              main(["--refs", refs_file, "--cache", dup_cache]), 2)
    finally:
        globals()["FETCH"] = saved_fetch
        for p in (refs_file, report_file, cache_file, fx_file, nested, bad_cache,
                  forge_cache, dup_cache):
            try:
                os.remove(p)
            except OSError:
                pass
        for d in (rep_dir, os.path.dirname(nested), os.path.dirname(os.path.dirname(nested))):
            try:
                os.rmdir(d)
            except OSError:
                pass

    # ---------- B10/G-10：重复条目归并（DOI 小写主键 + 标题小写辅键 + ISBN 去连字符） ----------
    check("B10 _norm_doi：strip + 小写", _norm_doi(" 10.1038/Nature14539 "), "10.1038/nature14539")
    check("B10 _norm_isbn：连字符/空格差异归一",
          (_norm_isbn("978-3-16-148410-0"), _norm_isbn("9783161484100"), _norm_isbn("978 3 16 148410 0")),
          ("9783161484100", "9783161484100", "9783161484100"))
    check("B10 同 DOI 大小写两形同键",
          _dup_key({"doi": "10.1038/NATURE14539", "title": "A"}, 0)
          == _dup_key({"doi": "10.1038/nature14539", "title": "A"}, 1), True)
    check("B10 标题辅键大小写归一（无 DOI 时）",
          _dup_key({"title": "Deep Learning"}, 0) == _dup_key({"title": "DEEP  learning"}, 1), True)
    check("B10 ISBN 连字符差异同键",
          _dup_key({"isbn": "978-3-16-148410-0", "title": "B"}, 0)
          == _dup_key({"isbn": "9783161484100", "title": "B"}, 1), True)
    check("B10 不同 DOI 不同键",
          _dup_key({"doi": "10.1/a", "title": "A"}, 0) == _dup_key({"doi": "10.1/b", "title": "A"}, 1), False)
    check("B10 空条目按序号单列不归并", _dup_key({}, 0) == _dup_key({}, 1), False)
    dup_calls = []
    dup_refs = [dict(ENTRY), dict(ENTRY, doi=ENTRY["doi"].upper())]
    dup_res = grade_refs(dup_refs, fetch=_fixture_fetch(good, dup_calls))
    check("B10 同 DOI 大小写两条只查一次（4 次而非 8 次）", len(dup_calls), 4)
    check("B10 两条结论一致且第二条记 duplicate_of",
          (dup_res[0]["state"], dup_res[1]["state"], dup_res[1].get("duplicate_of"),
           dup_res[1].get("dup_key", "").startswith("doi:")),
          ("verified", "verified", 0, True))
    book1 = {"isbn": "978-3-16-148410-0", "title": ENTRY["title"], "year": 2019, "venue": "Nature Water"}
    book2 = {"isbn": "9783161484100", "title": ENTRY["title"], "year": 2019, "venue": "Nature Water"}
    isbn_calls = []
    isbn_res = grade_refs([book1, book2], fetch=_fixture_fetch(good, isbn_calls))
    check("B10 ISBN 连字符差异归一后不重复查询", len(isbn_calls), 4)
    check("B10 ISBN 组第二条被点名",
          (isbn_res[1].get("duplicate_of"), isbn_res[1].get("dup_key", "").startswith("isbn:")),
          (0, True))
    cache_probe = {}
    c1_calls = []
    grade_refs(dup_refs, fetch=_fixture_fetch(good, c1_calls), cache=cache_probe)
    check("B10 缓存键保持原始大小写：两条原始键各落一行",
          len([k for k in cache_probe if k != "_meta"]), 2)
    c2_calls = []
    r2 = grade_refs(list(reversed(dup_refs)), fetch=_fixture_fetch(good, c2_calls), cache=cache_probe)
    check("B10 顺序调换后二跑零查询（回放路径不受归一化影响）", len(c2_calls), 0)
    check("B10 回放结论一致", (r2[0]["state"], r2[1]["state"]), ("verified", "verified"))
    buf_dup = io.StringIO()
    _o_dup, sys.stdout = sys.stdout, buf_dup
    try:
        print_report(dup_res, "advisory")
    finally:
        sys.stdout = _o_dup
    check("B10 报表点名重复条目（同 DOI 两条含大小写两形）",
          ("重复条目=与[0]" in buf_dup.getvalue(), "归并提示" in buf_dup.getvalue()), (True, True))
    buf_one = io.StringIO()
    _o_one, sys.stdout = sys.stdout, buf_one
    try:
        print_report(grade_refs([dict(ENTRY)], fetch=_fixture_fetch(good, [])), "advisory")
    finally:
        sys.stdout = _o_one
    check("B10 反向对照：干净单条目无归并提示",
          ("重复条目" in buf_one.getvalue(), "归并提示" in buf_one.getvalue()), (False, False))

    # ---------- B14（G-11~G-14）：方言探测 + 输入预算 + 下界 ----------
    # 根因纪律：只做离线探针（fixture/_decode 直调），禁止真实联网。
    _cdn_html = (b"<html><head><title>403 Forbidden</title></head>"
                 b"<body>Attention Required! | Cloudflare</body></html>")
    check("B14 CDN 错误页（200 + text/html）-> unavailable，原因串保留",
          _decode("openalex", 200, _cdn_html, "text/html"), (None, "html_error_page"))
    check("B14 CDN 错误页（ctype 缺失、靠根元素探测）-> unavailable",
          _decode("crossref", 200, b"\n  <!DOCTYPE html><html><body>blocked</body></html>", "")[1],
          "html_error_page")
    check("B14 HTML 页经 query_index -> unavailable（不计入 answered/k）",
          query_index("openalex", ENTRY["doi"], None,
                      fetch=_fixture_fetch({"openalex": {"body": _cdn_html.decode("utf-8"),
                                                         "content_type": "text/html"}}, []))[:2],
          ("unavailable", None))
    _st_cdn, _, _det_cdn = grade(ENTRY, {"openalex": {"status": 200,
                                                     "body": _cdn_html.decode("utf-8"),
                                                     "content_type": "text/html"},
                                        "crossref": good["crossref"],
                                        "semantic_scholar": good["semantic_scholar"],
                                        "arxiv": good["arxiv"]})
    check("B14 CDN 页不计入 answered/k（3/3/0）且原因串进 index_status",
          ((_det_cdn["answered"], _det_cdn["hits"], _det_cdn["k"]),
           _det_cdn["index_status"]["openalex"]),
          ((3, 3, 0), "unavailable:html_error_page"))
    check("B14 JSON 索引收到 XML -> 方言不合 unavailable（不硬解析）",
          _decode("crossref", 200,
                  b'<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"></feed>',
                  "text/xml"),
          (None, "unexpected_xml_for_json_index"))
    _bom_body = ('\ufeff{"display_name": "Graphene Oxide Membranes for Nanofiltration",'
                 '"publication_year": 2019, "is_retracted": false}').encode("utf-8")
    _bom_obj, _bom_why = _decode("openalex", 200, _bom_body, "application/json; charset=utf-8")
    check("B14 JSON BOM 正常解码（不视为解析失败）",
          ((_bom_obj or {}).get("display_name"), _bom_why),
          ("Graphene Oxide Membranes for Nanofiltration", "json_ok"))
    check("B14 非 UTF-8 响应体 -> unavailable（不按替换字符硬解）",
          _decode("openalex", 200, b"\xff\xfe\x00bad", "application/json"),
          (None, "body_not_utf8"))
    check("B14 超长标题相似度不卡死（截断后同串仍 1.0）",
          title_similarity("ab " * 100000, "ab " * 100000), 1.0)
    check("B14 超长相异标题相似度有界（0.0~1.0 之间）",
          0.0 <= title_similarity("a" * 200000, "b" * 200000) <= 1.0, True)
    with open(refs_file, "w", encoding="utf-8") as fh:
        json.dump([ENTRY], fh, ensure_ascii=False)
    check("B14 --min-hits 负数 -> rc=2（下界违规，用法错）",
          main(["--refs", refs_file, "--min-hits", "-1"]), 2)
    # 下界反向对照必须离线：--fixtures 复放真实解码面，不触真实网络（根因纪律）。
    _b14_fx = os.path.join(tmp, "rg-selftest-b14-fixtures.json")
    with open(_b14_fx, "w", encoding="utf-8") as fh:
        json.dump(good, fh, ensure_ascii=False)
    _b14_saved_fetch = globals()["FETCH"]
    try:
        check("B14 反向对照：--min-hits 0 合法（不误拒，离线复放 rc=0）",
              main(["--refs", refs_file, "--fixtures", _b14_fx, "--min-hits", "0"]), 0)
    finally:
        globals()["FETCH"] = _b14_saved_fetch
    for _p in (refs_file, _b14_fx):
        try:
            os.remove(_p)
        except OSError:
            pass

    if fails:
        print("REFS-GATE SELFTEST FAIL（%d 项）" % len(fails))
        for f in fails:
            print("  - " + f)
        return 1
    print("REFS-GATE SELFTEST PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
