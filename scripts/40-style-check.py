#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# vendor-tool: 40-style-check.py version 1
"""40-style-check.py — 无 AI 腔机检（词表命中 + 量化段 hedging 覆盖）。

规格：references/60-capability-specs.md §1（CLI §1.2、词表 schema §1.3、三条判定规则 §1.4、自测面 §1.5）。

输入面：位置参数给文件或目录（目录递归收 *.md，跳过点目录）。md 是单一真源，真实输入是论文项目的
      30-manuscript/*.md（references/40-draft-to-latex.md）。
词条来源：static/40-ai-cavity-wordlist.yaml（键即契约）。**脚本内不硬编码任何词条**——增删 terms
      即改行为，换领域用 --wordlist 指别的表。这条由两面共同证明：行为面（临时词表加自造词即命中、
      删掉唯一命中项即由 rc=1 变 rc=0）与结构面（_st_hardcode_violations 扫本模块 AST 的字符串字面量，
      生产代码段不得含任何缺省词条；自测样本区除外，因为样本正文必须把词写进去才扫得出来）。
两条扫描面分开，别混成一条：
      规则 1（禁用词）逐行扫全文，只跳过围栏代码块（含围栏标记行）——代码块里是命令与库名，不是文风。
      围栏状态机按 CommonMark 取两条硬约束（标记行缩进 <=3、闭合符须与开启符同种，见 `_line_kinds`）：
      少一条都会让状态整体错位一格，把**真散文判成围栏内**而免扫，且标记行总数仍是偶数、
      连「未闭合」都报不出来（实测旧写法 rc=0 静默通过）。免扫一律记账：未闭合围栏上报错误行。
      **标题行与表格行照扫**：AI 腔进标题更该报；§1.4 规则 2 的「跳过纯标题/表格」只界定**段落**，
      不是把这两类行从词表扫描里豁免掉。
      规则 3（hedging 覆盖）只在段落上判：空行分块，**段内容只取正文行**（`PARAGRAPH_KINDS`）——
      纯标题块 / 纯表格块 / 围栏块因此自然不成段、不占段号，段起始行即块内首个正文行。
      方向性理由：标题后不空行、表格紧贴正文都是 md 常态，若把标题行/表格行算进段，
      ① 报告行号会指到标题（作者还得自己找句子），② **表格单元里的数字**会替整段制造量化信号，
      把本该直陈的散文判成「缺 hedging」——§1.4 规则 2 要跳过的正是这两类。
为什么 hedging 只约束含量化信号的段（§1.4 规则 3）：否则等于要求全文冲淡措辞——背景段、方法段本该
      直陈。hedging 是「部分支持 → 收窄措辞」的处置手段（references/20-claim-framework.md §6），
      只有「数字结论」才必须留下收窄痕迹。
匹配语义：word 用 \\b 边界 + 不区分大小写；phrase 不区分大小写子串；substr 原样子串。
      word 只在词条首末字符是词字符时补 \\b——`etc.` 这类末字符非词词的词条，硬加 \\b 永远匹配不上。
      **缺 match 键即 rc=2，不猜默认值**：word 与 substr 的假阳性方向相反，猜错等于换了判据。
退出码：0 = 无命中；1 = 有命中（禁用词或量化段缺 hedging）；2 = 用法错误 / 词表缺失或 schema 不合 /
      输入读不了。**FAIL 优先于 usage-error**（§0）：同一次运行里既有命中又有坏输入时返 1，命中不得
      被路径错误糊成 0；词表本身坏了则无从扫描，直接 2。
      缺键一律 rc=2，不做「当作空表」的宽松处理：键名打错（`category:`、`hedging_terms:`）时宽松等于
      零命中通过，正是 §0 禁止的方向。
      词表**不是合法 YAML** 同样 rc=2：`yaml.YAMLError` 的 MRO 只有 Exception（实测不继承 ValueError），
      所以 except 必须显式列它——只捕 (OSError, ValueError) 时坏 YAML 未捕获崩溃、进程退出码 1，
      等于把「输入坏了」伪装成「你有 AI 腔」。
      两处**静默免扫**按同一条反伪造方向处置（与「读不了的文件记账报错」同标准，因为本脚本最危险的
      失败模式是读起来干净）：围栏不配对即视为「其后至文末一路在围栏里」→ 记错误行（含开标记行号），
      零命中时 rc=2、有命中时仍 rc=1。配对判定由 `_line_kinds` 的状态机自报，**不用标记行数奇偶相消**——
      后者在「缩进 ≤3 之外的 ``` 被当闭合符」或「~~~ 与 ``` 跨种互关」时算成偶数，状态错位却不报错，
      实测会把带禁用词的真散文整行吞掉（rc=0、零报告）。闭合只认同种标记、且缩进 ≤3。
只读承诺：不写任何目录（本脚本没有 --out，输出只到 stdout / stderr）；读文件严格 UTF-8（utf-8-sig 剥
      BOM），解码失败记为错误而不是跳过——跳过等于替作者把这一篇判成「干净」。
报告路径：以输入根为基准的相对路径，绝不回显绝对路径（本机路径进报告属发布物污染，CHANGELOG D-14 同族）：
      目录输入 → 相对该目录；相对路径的单文件输入 → 原样回显该相对串；绝对路径的单文件输入 → 只回显文件名。
与既有门禁的分工（§1.1）：本脚本不进 verify manifest、不改 70-verify.py 的断言类型集合，也不塞进
      75-verify-selftest.py（那是基座与生成器守卫面、且是多任务共享单写者文件）。它是 P4 每节写完、
      P6 定稿前人工触发的 pre-check 报告器，FAIL 由人逐条处置后写进审计。
自测口径：--selftest 全离线（本模块不 import 任何网络栈，由 _st_offline_guard 结构面证明），样本与
      临时词表写在临时目录、用毕即删；不起子进程（进程内直调 main()），故 -B 面不在本脚本；
      sys.dont_write_bytecode 早于第三方 import 置位（由 _st_import_guard 证明，.pyc 内嵌本机路径）。
      缺省词表读不出来时（脚本被单拷到没有兄弟 static/ 的目录、或词表本身坏了）先打 ABORT 行再返 2：
      余下用例全要索引 wl，不中止会在 `wl["categories"]` 上抛 TypeError，traceback 直出 + 进程退出码 1，
      与 D-1 同族地「把环境坏了伪装成判据命中」；该中止路径由 _st_wordlist_abort 的结构面守住。
"""

import argparse
import ast
import io
import os
import re
import shutil
import sys
import tempfile

sys.dont_write_bytecode = True
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

import yaml  # noqa: E402  必须晚于上一行的置位：yaml 的 .pyc 会内嵌本机绝对路径

EXIT_OK, EXIT_FAIL, EXIT_USAGE = 0, 1, 2
REQUIRED_KEYS = ("categories", "hedging", "quantitative_signal")
MATCH_MODES = ("word", "phrase", "substr")
SCANNED_KINDS = ("heading", "table", "text")
PARAGRAPH_KINDS = ("text",)
FENCE_MARKS = ("```", "~~~")
WORD_CHAR_RE = re.compile("[A-Za-z0-9_]")
MISSING_TAG = "[missing-hedging]"
DEFAULT_WORDLIST = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                "static", "40-ai-cavity-wordlist.yaml")
# B14（G-13）：正则输入预算——单行超 32KB 走截断，只用标准库 re，不引入第三方引擎。
# 超长退化行不断言尾部命中（宁可漏报行尾，不卡死）；行号/段号不受影响（只截内容不断行）。
REGEX_LINE_BUDGET = 32 * 1024


def _budget_line(s):
    """单行超预算即截断（B14 G-13）。短行原样返回，零开销。"""
    return s if len(s) <= REGEX_LINE_BUDGET else s[:REGEX_LINE_BUDGET]


# ---------- 词表：schema 即契约，缺键即 rc=2 ----------

def _term_regex(term, mode):
    """按 match 语义编译词条。"""
    esc = re.escape(term)
    if mode == "substr":
        return re.compile(esc)
    lead = trail = ""
    if mode == "word":
        if WORD_CHAR_RE.match(term[0]):
            lead = r"\b"
        if WORD_CHAR_RE.match(term[-1]):
            trail = r"\b"
    return re.compile(lead + esc + trail, re.IGNORECASE)


def _str_list(value, where, errors):
    if not isinstance(value, list):
        errors.append("%s 须为字符串列表，实际为 %s" % (where, type(value).__name__))
        return []
    out = []
    for i, item in enumerate(value):
        if not isinstance(item, str) or not item.strip():
            errors.append("%s[%d] 须为非空字符串，实际为 %r" % (where, i, item))
            continue
        out.append(item)
    return out


def _clean_categories(value, errors):
    if not isinstance(value, list):
        errors.append("categories 须为列表（允许 0 个），实际为 %s" % type(value).__name__)
        return []
    out = []
    for i, item in enumerate(value):
        where = "categories[%d]" % i
        if not isinstance(item, dict):
            errors.append("%s 须为对象，实际为 %s" % (where, type(item).__name__))
            continue
        cid = str(item.get("id") or "").strip()
        if not cid:
            errors.append("%s 缺 id（报告行的 [<category_id>] 要用它）" % where)
        mode = item.get("match")
        if mode not in MATCH_MODES:
            errors.append("%s 的 match 缺失或取值非法：%r，可选 %s" % (where, mode, list(MATCH_MODES)))
            continue
        terms = _str_list(item.get("terms"), where + ".terms", errors)
        if cid:
            out.append({"id": cid, "match": mode, "terms": terms})
    return out


class DuplicateYamlKey(yaml.YAMLError):
    """YAML 映射含重复键（A3，2026-10-07 审查）。

    yaml 默认 last-wins：重复的 categories / hedging / quantitative_signal 等键会让前一条
    定义被静默吞掉（实测词表末行追加 `categories: []` → 禁用词全表静默失效，命中 rc=1 翻 0）。
    """


class _NoDuplicateKeyLoader(yaml.SafeLoader):
    """安全加载器 + **任意层级**重复键检出（A3）。键名随异常上抛，由 load_* 归 rc=2。"""

    def construct_mapping(self, node, deep=False):
        self.flatten_mapping(node)
        mapping = {}
        for key_node, value_node in node.value:
            key = self.construct_object(key_node, deep=deep)
            try:
                duplicate = key in mapping
            except TypeError:            # 不可哈希键（YAML 允许序列键）：交给下面照常赋值
                duplicate = False
            if duplicate:
                raise DuplicateYamlKey("重复键 %r" % (key,))
            mapping[key] = self.construct_object(value_node, deep=deep)
        return mapping


def load_wordlist(path):
    """返回 (wordlist, errors)。errors 非空即 rc=2。"""
    if not os.path.exists(path):
        return None, ["词表文件不存在：%s" % path]
    try:
        with open(path, "r", encoding="utf-8-sig") as fh:
            raw = yaml.load(fh, Loader=_NoDuplicateKeyLoader)
    except DuplicateYamlKey as exc:
        # 重复键 last-wins 属静默失效（A3）：先于通用 YAMLError 分支点名键名。
        return None, ["词表含重复键：%s（yaml 默认 last-wins 会静默覆盖前一条定义，请去重）" % exc]
    except (OSError, ValueError, yaml.YAMLError) as exc:
        # 必须显式捕 yaml.YAMLError：实测它的 MRO 是 (YAMLError, Exception) —— **不继承 ValueError**，
        # 只写 (OSError, ValueError) 时坏 YAML 会未捕获崩溃、进程退出码 1，与「rc=1 = 判据命中」撞车。
        return None, ["词表不是合法 YAML（%s）：%s" % (type(exc).__name__, str(exc)[:120])]
    if not isinstance(raw, dict):
        return None, ["词表顶层须为对象，实际为 %s" % type(raw).__name__]
    missing = [k for k in REQUIRED_KEYS if k not in raw]
    if missing:
        return None, ["词表缺键：%s（键即契约，见 references/60-capability-specs.md §1.3）"
                      % ", ".join(missing)]
    errors = []
    cats = _clean_categories(raw["categories"], errors)
    hedging = raw["hedging"]
    if not isinstance(hedging, dict):
        errors.append("hedging 须为对象（含 terms 列表），实际为 %s" % type(hedging).__name__)
        hedging_terms = []
    else:
        if "terms" not in hedging:
            errors.append("词表缺键：hedging.terms")
        hedging_terms = _str_list(hedging.get("terms", []), "hedging.terms", errors)
    quant = None
    signal = raw["quantitative_signal"]
    if not isinstance(signal, dict) or "regex" not in signal:
        errors.append("词表缺键：quantitative_signal.regex")
    else:
        pat = signal["regex"]
        if not isinstance(pat, str) or not pat:
            errors.append("quantitative_signal.regex 须为非空字符串")
        else:
            try:
                quant = re.compile(pat)
            except re.error as exc:
                errors.append("quantitative_signal.regex 不是合法正则（%s）：%s" % (exc, pat[:80]))
    quant_domains = {}
    doms = signal.get("domains") if isinstance(signal, dict) else None
    if doms is not None:
        if not isinstance(doms, dict) or not doms:
            errors.append("quantitative_signal.domains 须为非空对象（域名 -> 正则串）")
        else:
            for dname, dpat in doms.items():
                if not isinstance(dpat, str) or not dpat:
                    errors.append("quantitative_signal.domains.%s 须为非空字符串" % dname)
                    continue
                try:
                    quant_domains[str(dname)] = re.compile(dpat)
                except re.error as exc:
                    errors.append("quantitative_signal.domains.%s 不是合法正则（%s）"
                                  % (dname, exc))
            if "material" not in quant_domains and quant_domains:
                errors.append("quantitative_signal.domains 缺 material 组（--domain 缺省口径的显式锚）")
    if errors:
        return None, errors
    return {"version": raw.get("version"), "categories": cats,
            "hedging": hedging_terms, "quant": quant, "quant_domains": quant_domains}, []


def build_matchers(wl):
    """[(category_id, term, compiled)]，按词表声明序——声明序决定同一行的报告序。"""
    out = []
    for cat in wl["categories"]:
        for term in cat["terms"]:
            out.append((cat["id"], term, _term_regex(term, cat["match"])))
    return out


def hedging_regexes(wl):
    """hedging 一律按 word 语义：收窄措辞要的是「确有此词」，不是子串（`may` 不得命中 `dismay`）。"""
    return [_term_regex(t, "word") for t in wl["hedging"]]


# ---------- 分段：规则 2 ----------

def _line_kinds(lines):
    """逐行定性，返回 (kinds, 未闭合围栏的起始行号|None)。

    kinds ∈ fence（围栏标记行）/ infence（围栏内）/ blank / heading / table / text。
    围栏的认法按 CommonMark 的两条硬约束，缺一条就会**静默吞掉真散文**（实测）：
      ① 开/闭标记行的缩进 ≤3 空格——围栏内缩进 4 格的 ``` 是**代码内容**，不是闭合符；
      ② 闭合符必须与开启符同种（`~~~` 开的只能由 `~~~` 关，` ``` ` 反之）。
    少了 ① 或少了 ②，围栏状态会整体错位一格：真散文被判成「围栏内」而免扫，而标记行总数仍是偶数，
    于是连「未闭合」都报不出来——一个字符级别的误判换来整段静默通过，正是本工具最危险的方向。
    未闭合的行号由状态机自己给出（不是事后按奇偶相消猜），配对错位时无从遁形。
    """
    kinds, open_mark, open_line = [], None, None
    for i, ln in enumerate(lines, 1):
        s = ln.strip()
        mark = None
        if len(ln) - len(ln.lstrip()) <= 3 and s.startswith(FENCE_MARKS):
            mark = s[0]
        if open_mark is not None:
            if mark == open_mark:
                kinds.append("fence")
                open_mark = open_line = None
            else:
                kinds.append("infence")
        elif mark is not None:
            kinds.append("fence")
            open_mark, open_line = mark, i
        elif not s:
            kinds.append("blank")
        elif s.startswith("#"):
            kinds.append("heading")
        elif s.startswith("|"):
            kinds.append("table")
        else:
            kinds.append("text")
    return kinds, open_line


def scanned_lines(lines, kinds):
    """规则 1 的扫描面：全文逐行，只排除围栏（标记行与围栏内）。"""
    return [(i, ln) for i, (ln, k) in enumerate(zip(lines, kinds), 1) if k in SCANNED_KINDS]


def paragraphs(lines, kinds):
    """规则 2：空行分块 → [(起始行号, [(行号, 文本)])]。

    段内容只取 `text` 行（`PARAGRAPH_KINDS`）：标题行与表格行**不算进段**，于是纯标题块 / 纯表格块 /
    围栏块自然不成段、不占段号，段起始行即块内首个正文行。两点方向性理由：
      ① 标题与正文之间不空行是 md 常见形态，若把标题行算进段，报告行号会指到标题（作者还得自己找句子）；
      ② 表格与正文不空行时，若把表格行算进段，**表格单元里的数字**会替整段制造量化信号，
         把一段本该直陈的散文判成「缺 hedging」——§1.4 规则 2 要跳过的正是这两类。
    规则 1 的扫描面不受此影响（标题行、表格行照扫禁用词，见 `scanned_lines`）。
    """
    paras, run = [], []

    def flush(run):
        kept = [(i, ln) for i, ln, k in run if k in PARAGRAPH_KINDS]
        if kept:
            paras.append((kept[0][0], kept))

    for i, (ln, k) in enumerate(zip(lines, kinds), 1):
        if k == "blank":
            flush(run)
            run = []
        else:
            run.append((i, ln, k))
    flush(run)
    return paras


# ---------- 扫描 ----------

def scan_file(display, text, wl, matchers, hedging_rxs, quant=None):
    """返回 (entries, 段数, 未闭合围栏行号|None)。entries = [(display, 行号, 序, 渲染串)]，序 0 = missing-hedging 置顶。"""
    lines = [_budget_line(ln) for ln in text.splitlines()]
    kinds, fence = _line_kinds(lines)
    entries = []
    for rank, (cid, term, rx) in enumerate(matchers, 1):
        for ln, txt in scanned_lines(lines, kinds):
            if rx.search(txt):
                entries.append((display, ln, rank, "[%s] %s" % (cid, term)))
    paras = paragraphs(lines, kinds)
    for idx, (start, pairs) in enumerate(paras, 1):
        body = "\n".join(t for _, t in pairs)
        if not (quant or wl["quant"]).search(body):
            continue
        if any(rx.search(body) for rx in hedging_rxs):
            continue
        entries.append((display, start, 0, "%s para%d@%d" % (MISSING_TAG, idx, start)))
    return entries, len(paras), fence


def _iter_md(root):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if not d.startswith("."))
        for name in sorted(filenames):
            if name.lower().endswith(".md"):
                yield os.path.join(dirpath, name)


def collect_inputs(paths):
    """返回 [(display, abspath)] 与 errors。display 的口径见模块 docstring。"""
    files, errors, seen = [], [], set()
    for arg in paths:
        clean = arg.rstrip("/\\") or arg
        if not os.path.exists(clean):
            errors.append("输入路径不存在：%s" % arg)
            continue
        if os.path.isdir(clean):
            found = list(_iter_md(clean))
            if not found:
                errors.append("目录内没有 *.md：%s" % arg)
            for path in found:
                key = os.path.realpath(path)
                if key in seen:
                    continue
                seen.add(key)
                files.append((os.path.relpath(path, clean).replace(os.sep, "/"), path))
        else:
            key = os.path.realpath(clean)
            if key in seen:
                continue
            seen.add(key)
            display = os.path.basename(clean) if os.path.isabs(arg) else arg.replace(os.sep, "/")
            files.append((display, clean))
    return files, errors


def run_scan(paths, wl_path, domain=None):
    """扫描入口（main 与自测共用）。返回 (rc, 报告行, 汇总 dict, errors)。"""
    wl, errs = load_wordlist(wl_path)
    if errs:
        return EXIT_USAGE, [], {}, ["词表错误：" + e for e in errs]
    if domain is not None and domain not in wl["quant_domains"]:
        return EXIT_USAGE, [], {}, ["--domain %s 不在词表 domains 内（可用：%s）"
                                    % (domain, ", ".join(sorted(wl["quant_domains"])))]
    quant = wl["quant_domains"][domain] if domain is not None else None
    matchers, h_rxs = build_matchers(wl), hedging_regexes(wl)
    files, errors = collect_inputs(paths)
    entries, para_total = [], 0
    for display, path in files:
        try:
            with open(path, "r", encoding="utf-8-sig") as fh:
                text = fh.read()
        except (OSError, UnicodeDecodeError) as exc:
            # 解码失败计入 rc=2 面，绝不"跳过这一篇"——跳过等于替作者判成干净。
            errors.append("读不了 %s（%s：%s）" % (display, type(exc).__name__, str(exc)[:80]))
            continue
        if "\ufffd" in text or "\x00" in text:
            # B14（G-14）：复用 70 号严格解码——解码结果含 U+FFFD 替换字符或 NUL
            # 即记错误（rc=2 面），不按干净文本扫描（替换字符会吞掉命中标记）。
            errors.append("读不了 %s（文本含 U+FFFD 替换字符或 NUL：疑似非 UTF-8/二进制混入，"
                          "按 70 号口径归输入错）" % display)
            continue
        got, paras, fence = scan_file(display, text, wl, matchers, h_rxs, quant)
        if fence is not None:
            # 与「读不了的文件」同标准：一个不配对的 ``` 会让后文整片免扫，
            # 静默通过（读起来干净）比报错危险，必须上屏。
            errors.append("未闭合围栏：%s 第 %d 行的围栏标记直到文末都没配对，其后至文末未参与禁用词扫描"
                          % (display, fence))
        entries.extend(got)
        para_total += paras
    n_hed = sum(1 for e in entries if e[3].startswith(MISSING_TAG))
    lines = ["%s:%d: %s" % (disp, ln, body) for disp, ln, _, body in sorted(entries)]
    stats = {"files": len(files), "paras": para_total, "hits": len(entries),
             "terms": len(entries) - n_hed, "hedging": n_hed}
    rc = EXIT_FAIL if entries else (EXIT_USAGE if errors else EXIT_OK)
    return rc, lines, stats, errors


def emit(lines, stats, errors):
    for line in lines:
        print(line)
    print("汇总：%d 个文件 / %d 段，命中 %d 条（禁用词 %d、量化段缺 hedging %d）"
          % (stats.get("files", 0), stats.get("paras", 0), stats.get("hits", 0),
             stats.get("terms", 0), stats.get("hedging", 0)))
    if stats.get("hits"):
        print("提示：命中不等于必删。逐条按 references/20-claim-framework.md §6 三选一处置"
              "（替换文献 / 降级措辞 / 删除断言）并留痕；本脚本是 pre-check 报告器，不进 verify manifest。")
    if stats.get("hedging"):
        print("提示：missing-hedging 只判「数字结论句所在段无任何收窄措辞」，背景段与方法段本该直陈，"
              "不要为了这条在全文堆可能。词条与量化式都只改 static/40-ai-cavity-wordlist.yaml。")
    for e in errors:
        print("错误：" + e, file=sys.stderr)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="40-style-check.py",
                                 description="无 AI 腔机检：词表命中 + 量化段 hedging 覆盖（只读，报告到 stdout）")
    ap.add_argument("paths", nargs="*", metavar="<文件或目录>...",
                    help="待扫的 md 文件或目录（目录递归收 *.md）")
    ap.add_argument("--wordlist", help="覆盖缺省词表 static/40-ai-cavity-wordlist.yaml（换领域或自测用）")
    ap.add_argument("--domain", help="量化信号组选择（F9）：material/clinical/social/csml；"
                                     "缺省 = 词表顶层 regex（material 口径）")
    ap.add_argument("--selftest", action="store_true", help="离线自测：合成样本 + 临时词表，用毕即删")
    args = ap.parse_args(argv)
    if args.selftest:
        return run_selftest()
    if not args.paths:
        print("用法错误：给出要扫描的文件或目录（或用 --selftest）", file=sys.stderr)
        return EXIT_USAGE
    rc, lines, stats, errors = run_scan(args.paths, args.wordlist or DEFAULT_WORDLIST,
                                        domain=args.domain)
    emit(lines, stats, errors)
    return rc


# ---------- 离线自测 ----------

def _st_capture(argv):
    """进程内跑一次扫描，返回 (rc, stdout, stderr)。"""
    out, err = io.StringIO(), io.StringIO()
    old_out, old_err = sys.stdout, sys.stderr
    sys.stdout, sys.stderr = out, err
    try:
        rc = main(argv)
    finally:
        sys.stdout, sys.stderr = old_out, old_err
    return rc, out.getvalue(), err.getvalue()


def _st_write(path, lines):
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")


def _st_dump(path, data):
    with open(path, "w", encoding="utf-8") as fh:
        yaml.safe_dump(data, fh, allow_unicode=True, sort_keys=False)


def _st_hardcode_violations(src, terms):
    """生产代码段的字符串字面量不得含任何词条（AC3 的结构面）。

    两处除外，理由都要能复查：
      1) docstring——口径说明必然要举例提到词（`may` 不命中 `dismay` 这种话只能写在 docstring 里）；
      2) 自测区（`run_selftest` 与 `_st_*` 前缀函数）——样本正文必须把词写进去才扫得出来。
    """
    tree = ast.parse(src)
    excluded, docstrings = [], set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name == "run_selftest" or node.name.startswith("_st_"):
                excluded.append((node.lineno, node.end_lineno))
            if node.body and isinstance(node.body[0], ast.Expr) \
                    and isinstance(node.body[0].value, ast.Constant):
                docstrings.add(id(node.body[0].value))
        elif isinstance(node, ast.Module):
            if node.body and isinstance(node.body[0], ast.Expr) \
                    and isinstance(node.body[0].value, ast.Constant):
                docstrings.add(id(node.body[0].value))
    lowered = [t.lower() for t in terms if isinstance(t, str) and t.strip()]
    hits = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
            continue
        if id(node) in docstrings:
            continue
        if any(start <= node.lineno <= end for start, end in excluded):
            continue
        low = node.value.lower()
        for term in lowered:
            if term in low:
                hits.append("L%d 字面量含词条 %r：%r" % (node.lineno, term, node.value[:60]))
    return hits


def _st_import_guard(src, third_party):
    """置位 sys.dont_write_bytecode 必须早于第三方 import（.pyc 内嵌本机绝对路径）。"""
    tree = ast.parse(src)
    flag_line, dep_line = None, None
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant) \
                and node.value.value is True:
            for tgt in node.targets:
                if isinstance(tgt, ast.Attribute) and tgt.attr == "dont_write_bytecode":
                    flag_line = node.lineno if flag_line is None else min(flag_line, node.lineno)
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = [a.name.split(".")[0] for a in node.names] if isinstance(node, ast.Import) \
                else [(node.module or "").split(".")[0]]
            if third_party in names:
                dep_line = node.lineno if dep_line is None else min(dep_line, node.lineno)
    if flag_line is None:
        return ["没有 sys.dont_write_bytecode 置位"]
    if dep_line is not None and dep_line < flag_line:
        return ["第 %d 行 import %s 早于第 %d 行的 dont_write_bytecode 置位" % (dep_line, third_party, flag_line)]
    return []


NET_STACK = ("urllib", "http", "socket", "requests", "ftplib", "urllib3", "ssl")


def _st_yaml_error_caught(src):
    """load_wordlist 读表的 try 必须捕住 yaml.YAMLError（实测它不继承 ValueError）。"""
    for node in ast.walk(ast.parse(src)):
        if not isinstance(node, ast.FunctionDef) or node.name != "load_wordlist":
            continue
        for sub in ast.walk(node):
            if not isinstance(sub, ast.Try):
                continue
            for handler in sub.handlers:
                t = handler.type
                if isinstance(t, ast.Tuple):
                    names = [ast.unparse(e) for e in t.elts]
                elif t is not None:
                    names = [ast.unparse(t)]
                else:
                    names = []
                if any(n.endswith("YAMLError") for n in names):
                    return True
    return False


def _st_selfread_by_filename(src):
    """run_selftest 是否仍按硬编码文件名读自身源码（正确做法是用 __file__）。"""
    for node in ast.walk(ast.parse(src)):
        if not isinstance(node, ast.FunctionDef) or node.name != "run_selftest":
            continue
        for sub in ast.walk(node):
            if isinstance(sub, ast.Call) and getattr(sub.func, "id", "") == "open":
                for arg in ast.walk(sub):
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str) \
                            and arg.value.endswith(".py"):
                        return True
    return False


def _st_offline_guard(src, banned=NET_STACK):
    """完全离线（AC5）的结构面：本模块不得 import 任何网络栈。"""
    mods = set()
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Import):
            mods.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            mods.add((node.module or "").split(".")[0])
    return sorted(m for m in mods if m in banned)


def _st_wordlist_abort(src):
    """run_selftest 必须在索引 wl 之前先中止「缺省词表读不出来」这条路径。

    无守卫时 wl 为 None，wl["categories"] 抛 TypeError —— traceback 直出、进程 rc=1，
    把「环境坏了」伪装成「判据命中」。判据：守卫 If（含 return）的行号早于首个 wl[...] 索引。
    """
    for node in ast.walk(ast.parse(src)):
        if not isinstance(node, ast.FunctionDef) or node.name != "run_selftest":
            continue
        guard, index = None, None
        for sub in ast.walk(node):
            if isinstance(sub, ast.If):
                test = ast.unparse(sub.test)
                if "wl" in test and ("is None" in test or test.startswith("not wl")):
                    if any(isinstance(x, ast.Return) for x in ast.walk(sub)):
                        guard = sub.lineno if guard is None else min(guard, sub.lineno)
            if isinstance(sub, ast.Subscript) and isinstance(sub.value, ast.Name) \
                    and sub.value.id == "wl":
                index = sub.lineno if index is None else min(index, sub.lineno)
        return guard is not None and index is not None and guard < index
    return False


def run_selftest():
    fails = []

    def check(name, got, want):
        if got != want:
            fails.append("%s: got %r want %r" % (name, got, want))
            print("  FAIL %s: got %r want %r" % (name, got, want))
        else:
            print("  OK   %s" % name)

    def report_lines(out, prefix):
        return [ln for ln in out.splitlines() if ln.startswith(prefix)]

    scripts_dir = os.path.dirname(os.path.abspath(__file__))
    with open(os.path.abspath(__file__), "r", encoding="utf-8-sig") as fh:
        own_src = fh.read()
    before_listing = sorted(os.listdir(scripts_dir))
    tmp = tempfile.mkdtemp(prefix="sc-selftest-")
    old_cwd = os.getcwd()
    try:
        # ---------- 缺省词表（§1.3 键即契约） ----------
        wl, errs = load_wordlist(DEFAULT_WORDLIST)
        check("缺省词表可读（static/40-ai-cavity-wordlist.yaml）", errs, [])
        if wl is None:
            # 余下用例全都要索引 wl，不先中止会抛 TypeError：traceback 直出 + rc=1，
            # 把「环境坏了」伪装成「判据命中」。中止记号用两空格前缀，与 OK/FAIL 同级可读。
            print("  ABORT 缺省词表不可读，词表相关用例未执行")
            return EXIT_USAGE
        check("缺省词表类别与 §1.3 一致", [c["id"] for c in wl["categories"]],
              ["hype", "cavity", "vague_attribution"])
        check("缺省词表每类都显式给了 match", [c["match"] for c in wl["categories"]],
              ["word", "phrase", "phrase"])
        all_terms = [t for c in wl["categories"] for t in c["terms"]] + list(wl["hedging"])
        check("缺省词表 version 标注存在（F9 起 schema v2：+quantitative_signal.domains）",
              wl["version"], 2)

        t_hype = wl["categories"][0]["terms"][0]
        t_cavity = wl["categories"][1]["terms"][0]
        t_vague = wl["categories"][2]["terms"][0]
        hed = wl["hedging"]

        # ---------- AC1 命中样本：逐条 file:line + 命中词，rc=1 ----------
        a = os.path.join(tmp, "a.md")
        _st_write(a, ["# %s claims" % t_hype, "", "We %s the topic." % t_cavity,
                      "The sample is %s." % t_hype, "", "%s a trend." % t_vague])
        with open(a, "rb") as fh:
            digest_before = fh.read()
        rc, out, errb = _st_capture([a])
        got = report_lines(out, "a.md:")
        check("AC1 逐条 file:line + [<category_id>] + 命中词（按行号升序）", got,
              ["a.md:1: [hype] %s" % t_hype, "a.md:3: [cavity] %s" % t_cavity,
               "a.md:4: [hype] %s" % t_hype, "a.md:6: [vague_attribution] %s" % t_vague])
        check("AC1 命中样本 rc=1", rc, EXIT_FAIL)
        check("AC1 报告行格式：相对路径:行号: [id] 词",
              bool(re.match(r"^[^:]+:\d+: \[[a-z_]+\] \S", got[0])), True)
        check("AC1 标题行照扫（第一行即命中）", got[0].startswith("a.md:1: [hype]"), True)
        check("AC1 不回显绝对路径（本机临时目录名不入报告）", tmp in out, False)
        check("AC1 汇总计数", "命中 4 条（禁用词 4、量化段缺 hedging 0）" in out, True)
        check("只读承诺：扫描不改输入文件字节", open(a, "rb").read(), digest_before)

        # ---------- AC2 干净样本：不含禁用词且各段含 hedging，rc=0 ----------
        b = os.path.join(tmp, "b.md")
        _st_write(b, ["# Methods", "", "The coating %s a modest gain of 12 MPa." % hed[0], "",
                      "The spectra %s a shift of 3.1 GPa." % hed[1]])
        rc, out, errb = _st_capture([b])
        check("AC2 干净样本 rc=0", rc, EXIT_OK)
        check("AC2 干净样本零命中", report_lines(out, "b.md:"), [])
        check("AC2 量化段有 hedging 时不报（段数计数含 2 段）", "1 个文件 / 2 段，命中 0 条" in out, True)

        # ---------- AC4 量化段缺 hedging：段号 + 起始行号入报告 ----------
        c = os.path.join(tmp, "c.md")
        _st_write(c, ["# Results", "", "The control group showed no difference.", "",
                      "The cell reached 25 MPa and 3.1 GPa."])
        rc, out, errb = _st_capture([c])
        check("AC4 量化段缺 hedging -> rc=1", rc, EXIT_FAIL)
        check("AC4 报告含段号与起始行号", report_lines(out, "c.md:"), ["c.md:5: [missing-hedging] para2@5"])
        check("AC4 汇总分栏计数", "命中 1 条（禁用词 0、量化段缺 hedging 1）" in out, True)

        # 反向对照 A：给这一段补上 hedging 词 -> rc=0（判据真的在数 hedging）
        c2 = os.path.join(tmp, "c2.md")
        _st_write(c2, ["# Results", "", "The control group showed no difference.", "",
                       "The cell reached 25 MPa, which %s a plateau." % hed[0]])
        check("反向对照：同一段补 hedging 词后 rc=0", _st_capture([c2])[0], EXIT_OK)
        # 反向对照 B：给无量化信号的段加数字 -> 它也开始被报（规则 3 只约束量化段的边界）
        c3 = os.path.join(tmp, "c3.md")
        _st_write(c3, ["# Results", "", "The control group showed 0 MPa difference.", "",
                       "The cell reached 25 MPa and 3.1 GPa."])
        check("反向对照：背景段一旦带上数字结论就照报", report_lines(_st_capture([c3])[1], "c3.md:"),
              ["c3.md:3: [missing-hedging] para1@3", "c3.md:5: [missing-hedging] para2@5"])

        # ---------- §1.4 规则 2：段落边界（纯标题块 / 表格块 / 围栏块不算段落，围栏内不扫词） ----------
        d = os.path.join(tmp, "d.md")
        _st_write(d, ["# Heading only", "", "| a | b |", "|---|---|", "The sample is %s." % t_hype, "",
                      "```", "The sample is %s." % t_hype, "```", "",
                      "A plain sentence with 25 MPa."])
        rc, out, errb = _st_capture([d])
        check("表格行照扫词，但纯表格块不占段号", [ln for ln in report_lines(out, "d.md:")
                                              if ln.startswith("d.md:5")],
              ["d.md:5: [hype] %s" % t_hype])
        check("围栏代码块内不扫词（命令与库名不是文风）",
              [ln for ln in report_lines(out, "d.md:") if ln.startswith("d.md:8")], [])
        check("跳过块后段号仍从 1 起、起始行号取块内首个正文行",
              report_lines(out, "d.md:11"), ["d.md:11: [missing-hedging] para2@11"])
        check("反向对照：纯标题块不算段落（整份文档只 2 段）", "2 段，命中 2 条" in out, True)

        # ---------- 返工 R-3：段内容只取正文行（标题行与表格行不算进段） ----------
        h1 = os.path.join(tmp, "head_body.md")
        _st_write(h1, ["## 3.1 Results", "The cell reached 40 % gain."])
        rc, out, errb = _st_capture([h1])
        check("R-3 标题与正文之间不空行时，段起始行取正文行（报告不指到标题）",
              report_lines(out, "head_body.md:"), ["head_body.md:2: [missing-hedging] para1@2"])
        h2 = os.path.join(tmp, "head_num.md")
        _st_write(h2, ["## 3.1 Results at 25 MPa", "No numbers at all in this sentence."])
        check("R-3 反向对照：标题里的数字不替正文制造量化信号（算进段内容即变红）",
              _st_capture([h2])[0], EXIT_OK)
        h3 = os.path.join(tmp, "table_glue.md")
        _st_write(h3, ["Comparison follows.", "| sample | strength |", "|---|---|", "| A | 25 MPa |"])
        check("R-3 表格单元里的数字不替散文制造 missing-hedging", _st_capture([h3])[0], EXIT_OK)
        h4 = os.path.join(tmp, "table_scan.md")
        _st_write(h4, ["Comparison follows.", "| it is %s |" % t_hype])
        check("R-3 规则 1 扫描面不变：表格行照扫禁用词",
              report_lines(_st_capture([h4])[1], "table_scan.md:"),
              ["table_scan.md:2: [hype] %s" % t_hype])

        # ---------- 返工 R-2：未闭合围栏不得把后文静默免扫 ----------
        u1 = os.path.join(tmp, "unclosed.md")
        _st_write(u1, ["clean prose line", "```", "%s inside a fence that never closes" % t_hype])
        rc, out, errb = _st_capture([u1])
        check("R-2 未闭合围栏 + 零命中 -> rc=2 并报出免扫的起始行",
              (rc, "未闭合围栏" in errb and "第 2 行" in errb), (EXIT_USAGE, True))
        u2 = os.path.join(tmp, "closed.md")
        _st_write(u2, ["clean prose line", "```", "%s inside a closed fence" % t_hype, "```"])
        check("R-2 反向对照：补上闭合围栏后同一内容 rc=0", _st_capture([u2])[0], EXIT_OK)
        u3 = os.path.join(tmp, "unclosed_hit.md")
        _st_write(u3, ["%s before the fence" % t_hype, "```", "code with no closer"])
        rc, out, errb = _st_capture([u3])
        check("R-2 FAIL 优先：未闭合围栏 + 有命中 -> rc=1 且错误行仍上报",
              (rc, "未闭合围栏" in errb), (EXIT_FAIL, True))

        # ---------- 返工 R-5：围栏状态机的两条硬约束（缩进 <=3 / 闭合符同种） ----------
        g1 = os.path.join(tmp, "indent_fence.md")
        _st_write(g1, ["intro line", "```", "    ```", "```",
                       "The sample is %s and must not be swallowed." % t_hype])
        rc, out, errb = _st_capture([g1])
        check("R-5 围栏内缩进 4 格的 ``` 是代码内容而非闭合符（真散文照扫，旧写法在此静默吞词）",
              (report_lines(out, "indent_fence.md:"), "未闭合围栏" in errb),
              (["indent_fence.md:5: [hype] %s" % t_hype], False))
        g2 = os.path.join(tmp, "marker_swap.md")
        _st_write(g2, ["intro line", "~~~", "code", "```", "%s inside a still-open block" % t_hype])
        rc, out, errb = _st_capture([g2])
        check("R-5 ~~~ 开的围栏不被 ``` 关闭：整块免扫但必须记账（免扫不静默）",
              (rc, report_lines(out, "marker_swap.md:"), "未闭合围栏" in errb and "第 2 行" in errb),
              (EXIT_USAGE, [], True))

        # ---------- 返工 R-1：非法 YAML 词表必须 rc=2，不得 traceback 直出 ----------
        by = os.path.join(tmp, "broken.yaml")
        with open(by, "w", encoding="utf-8") as fh:
            fh.write("this is not: [valid yaml\n")
        rc, out, errb = _st_capture(["--wordlist", by, a])
        check("R-1 非法 YAML 词表 -> rc=2 且报异常名（YAMLError 不继承 ValueError，实测）",
              (rc, "词表不是合法 YAML" in (out + errb)), (EXIT_USAGE, True))
        check("R-1 结构面：load_wordlist 的 except 确实含 YAMLError", _st_yaml_error_caught(own_src), True)
        check("R-1 反向对照：只捕 (OSError, ValueError) 的源码判红",
              _st_yaml_error_caught("def load_wordlist():\n    try:\n        x = 1\n"
                                    "    except (OSError, ValueError):\n        x = 2\n"), False)

        # ---------- 返工 R-4：自测读自身源码用 __file__，不依赖文件名 ----------
        check("R-4 own_src 确实读到本模块（含 run_selftest 定义）", "def run_selftest(" in own_src, True)
        check("R-4 结构面：run_selftest 不再按硬编码文件名 open", _st_selfread_by_filename(own_src), False)
        check("R-4 反向对照：按文件名读自身的写法一出现即判红",
              _st_selfread_by_filename('def run_selftest():\n    with open("40-style-check.py") as fh'
                                       ":\n        return fh.read()\n"), True)

        # ---------- 返工 R-6：缺省词表不可读时先中止，不得索引 None 抛 TypeError ----------
        check("R-6 结构面：run_selftest 在首个 wl[...] 索引之前有 wl is None 的 return 守卫",
              _st_wordlist_abort(own_src), True)
        check("R-6 反向对照：无守卫（直接索引 wl）的源码判红",
              _st_wordlist_abort('def run_selftest():\n    wl = load()\n'
                                 '    print(wl["categories"])\n'), False)
        check("R-6 反向对照：守卫排在索引之后仍判红",
              _st_wordlist_abort('def run_selftest():\n    wl = load()\n'
                                 '    print(wl["categories"])\n'
                                 '    if wl is None:\n        return 2\n'), False)

        # ---------- AC3 词条只来自词表（行为面：临时词表） ----------
        coin = "zymurgyx"
        wl_tmp = os.path.join(tmp, "words.yaml")
        z = os.path.join(tmp, "z.md")
        _st_write(z, ["The signal is %s here." % coin])
        table = {"version": 1,
                 "categories": [{"id": "labcoin", "match": "word", "terms": [coin]}],
                 "hedging": {"terms": ["suggests"]},
                 "quantitative_signal": {"regex": "[0-9]+\\s*MPa"}}
        _st_dump(wl_tmp, table)
        args = ["--wordlist", wl_tmp, z]
        check("AC3 临时词表加自造词即命中（词条来自文件而非常数）", _st_capture(args)[0], EXIT_FAIL)
        table["categories"][0]["terms"] = []
        _st_dump(wl_tmp, table)
        check("AC3 反向对照：删掉唯一命中项后同一输入 rc=0（§1.5）", _st_capture(args)[0], EXIT_OK)
        check("AC3 categories 允许 0 个（空表不报 schema 错）", _st_capture(args)[2], "")

        # ---------- §1.4 规则 1：match 三语义 ----------
        mw = os.path.join(tmp, "modes.yaml")
        m = os.path.join(tmp, "m.md")
        _st_dump(mw, {"version": 1, "categories": [
            {"id": "wb", "match": "word", "terms": ["may", "etc."]},
            {"id": "ph", "match": "phrase", "terms": ["Zzq Ab"]},
            {"id": "sb", "match": "substr", "terms": ["KkMm"]}],
            "hedging": {"terms": []},
            "quantitative_signal": {"regex": "[0-9]+ MPa"}})
        _st_write(m, ["a dismay signal", "it may rain", "say zzq ab loudly", "KkMm here", "kkmm there",
                      "and etc. more"])
        rc, out, errb = _st_capture(["--wordlist", mw, m])
        check("match=word 用词边界（may 不命中 dismay）", [ln for ln in report_lines(out, "m.md:")
                                                        if "may" in ln], ["m.md:2: [wb] may"])
        check("match=phrase 不区分大小写子串", [ln for ln in report_lines(out, "m.md:")
                                               if "Zzq" in ln], ["m.md:3: [ph] Zzq Ab"])
        check("match=substr 大小写敏感", [ln for ln in report_lines(out, "m.md:") if "KkMm" in ln],
              ["m.md:4: [sb] KkMm", "m.md:5: [sb] KkMm"][:1])
        check("match=word 末字符非词字符时不硬加 \\b（etc. 仍可命中）",
              [ln for ln in report_lines(out, "m.md:") if "etc." in ln], ["m.md:6: [wb] etc."])

        # ---------- §0 退出码：FAIL 优先于 usage-error ----------
        miss = os.path.join(tmp, "nope.md")
        clean = os.path.join(tmp, "clean.md")
        _st_write(clean, ["# Methods", "", "The coating %s nothing." % hed[0]])
        rc, out, errb = _st_capture([miss, a])
        check("退出码优先级：坏路径 + 命中样本 -> rc=1（不得把 1 类糊成 0）", rc, EXIT_FAIL)
        check("坏路径仍上报到 stderr", "输入路径不存在" in errb, True)
        rc, out, errb = _st_capture([miss, clean])
        check("反向对照：坏路径 + 干净样本 -> rc=2", rc, EXIT_USAGE)
        check("无输入路径 -> rc=2", _st_capture([])[0], EXIT_USAGE)

        # ---------- 读不了的文件：记错误，不跳过当干净 ----------
        bad = os.path.join(tmp, "bad.md")
        with open(bad, "wb") as fh:
            fh.write(b"\xff\xfe# Results\nplain text\n")
        rc, out, errb = _st_capture([bad])
        check("非 UTF-8 输入 -> rc=2 并报路径（跳过等于判它干净）",
              (rc, "读不了 bad.md" in errb), (EXIT_USAGE, True))
        check("反向对照：同一路径集合里只要有命中就 rc=1", _st_capture([bad, a])[0], EXIT_FAIL)

        # ---------- 词表 schema：缺键 / 非法 match / 坏正则 ----------
        def wl_case(mutate, needle, name):
            box = {"version": 1, "categories": [{"id": "x", "match": "word", "terms": [coin]}],
                   "hedging": {"terms": ["suggests"]},
                   "quantitative_signal": {"regex": "[0-9]+ MPa"}}
            mutate(box)
            p = os.path.join(tmp, "case.yaml")
            _st_dump(p, box)
            rc, out, errb = _st_capture(["--wordlist", p, z])
            got = (rc, needle in errb)
            check(name, got, (EXIT_USAGE, True))

        wl_case(lambda x: x.pop("hedging"), "hedging", "缺 hedging 键 -> rc=2 且报键名")
        wl_case(lambda x: x.pop("quantitative_signal"), "quantitative_signal",
                "缺 quantitative_signal 键 -> rc=2 且报键名")
        # 否定条件：键名打错不得被当成空表放行（否则 FAIL 面糊成 0）
        wl_case(lambda x: (x.pop("categories"), x.update({"category": []})), "categories",
                "反向对照：categories 键名打错 -> rc=2，不当空表放行")
        wl_case(lambda x: x["categories"][0].pop("match"), "match", "缺 match 键 -> rc=2（不猜默认值）")
        wl_case(lambda x: x["categories"][0].update({"match": "glob"}), "glob", "非法 match 取值 -> rc=2")
        wl_case(lambda x: x["quantitative_signal"].update({"regex": "[0-9+"}), "正则", "坏正则 -> rc=2")
        wl_case(lambda x: x["hedging"].pop("terms"), "hedging.terms", "缺 hedging.terms -> rc=2")
        check("不存在的词表路径 -> rc=2",
              _st_capture(["--wordlist", os.path.join(tmp, "nowhere.yaml"), z])[0], EXIT_USAGE)
        with open(os.path.join(tmp, "list.yaml"), "w", encoding="utf-8") as fh:
            yaml.safe_dump([1, 2], fh)
        check("词表顶层非对象 -> rc=2",
              _st_capture(["--wordlist", os.path.join(tmp, "list.yaml"), z])[0], EXIT_USAGE)

        # ---------- A3（2026-10-07 审查）：重复键不得 last-wins 静默失效 ----------
        # 锚点：yaml.safe_load 默认 last-wins——末尾再写一行 categories: [] 会静默清空整表。
        check("A3 锚点：yaml.safe_load 对重复键 last-wins（静默覆盖，洞真实存在）",
              yaml.safe_load("categories:\n  - id: x\ncategories: []\n") == {"categories": []}, True)
        _dup_tpl = ("version: 1\n"
                    "categories:\n  - id: labcoin\n    match: word\n    terms: [%s]\n"
                    "hedging:\n  terms: [suggests]\n"
                    "quantitative_signal:\n  regex: '[0-9]+ MPa'\n" % coin)

        def _wl_dup(key):
            p = os.path.join(tmp, "dup_%s.yaml" % key)
            with open(p, "w", encoding="utf-8") as fh:
                fh.write(_dup_tpl + "%s: []\n" % key)
            return p

        for _key in ("categories", "hedging", "quantitative_signal"):
            _rc, _out, _errb = _st_capture(["--wordlist", _wl_dup(_key), z])
            check("A3 重复顶层键 %s -> rc=2 且点名键名" % _key,
                  (_rc, _key in _errb and "重复键" in _errb), (EXIT_USAGE, True))
        _clean = os.path.join(tmp, "dup_clean.yaml")
        with open(_clean, "w", encoding="utf-8") as fh:
            fh.write(_dup_tpl)
        check("A3 反向对照：去重后同一词表照常命中（rc=1）",
              _st_capture(["--wordlist", _clean, z])[0], EXIT_FAIL)

        # ---------- 输入根与相对路径口径 ----------
        pkg = os.path.join(tmp, "pkg")
        os.makedirs(os.path.join(pkg, "sub"))
        os.makedirs(os.path.join(pkg, ".hidden"))
        _st_write(os.path.join(pkg, "top.md"), ["# Top", "", "Nothing here."])
        _st_write(os.path.join(pkg, "sub", "deep.md"), ["The sample is %s." % t_hype])
        _st_write(os.path.join(pkg, ".hidden", "ghost.md"), ["The sample is %s." % t_hype])
        with open(os.path.join(pkg, "notes.txt"), "w", encoding="utf-8") as fh:
            fh.write("The sample is %s.\n" % t_hype)
        rc, out, errb = _st_capture([pkg])
        check("目录递归收 *.md（子目录进、点目录与 *.txt 不进）", report_lines(out, "sub/"),
              ["sub/deep.md:1: [hype] %s" % t_hype])
        check("目录输入的报告路径用 / 分隔（Windows 反斜杠不进报告）", "\\" in out, False)
        try:
            os.chdir(tmp)
            rc, out, errb = _st_capture([os.path.join("pkg", "sub", "deep.md")])
            check("相对路径单文件输入：原样回显相对串（含目录段）", report_lines(out, "pkg/sub/"),
                  ["pkg/sub/deep.md:1: [hype] %s" % t_hype])
        finally:
            os.chdir(old_cwd)
        rc, out, errb = _st_capture([os.path.join(pkg, "sub", "deep.md")])
        check("绝对路径单文件输入：只回显文件名", report_lines(out, "deep.md:"),
              ["deep.md:1: [hype] %s" % t_hype])
        empty_dir = os.path.join(tmp, "empty")
        os.makedirs(empty_dir)
        check("空目录（没有 *.md）-> rc=2，不静默 rc=0", _st_capture([empty_dir])[0], EXIT_USAGE)

        # ---------- 结构面：不硬编码词条 / 编码 / 离线 ----------
        check("AC3 结构面：生产代码段无任何缺省词条字面量",
              _st_hardcode_violations(own_src, all_terms), [])
        check("反向对照：硬编码守卫真的在扫（拿生产代码里的词问它）",
              bool(_st_hardcode_violations(own_src, ["汇总"])), True)
        check("AC5 结构面：本模块不 import 网络栈", _st_offline_guard(own_src), [])
        check("反向对照：离线守卫真的在扫（喂一段 import urllib）",
              _st_offline_guard("import urllib.request\n"), ["urllib"])
        check("编码面：dont_write_bytecode 早于第三方 import",
              _st_import_guard(own_src, "yaml"), [])
        check("反向对照：置位晚于 import 时守卫变红",
              bool(_st_import_guard("import yaml\nimport sys\nsys.dont_write_bytecode = True\n", "yaml")),
              True)

        # ---------- AC5 CLI 面：缺省词表全链路可跑 ----------
        check("AC5 缺省词表全链路可跑（干净样本 rc=0）", _st_capture([b])[0], EXIT_OK)

        # ---------- B14（G-13/G-14）：正则输入预算 + 严格解码 ----------
        check("B14 预算常量 32KB（单行超限走截断）", REGEX_LINE_BUDGET, 32 * 1024)
        check("B14 短行原样（零开销）", _budget_line("abc"), "abc")
        check("B14 超限行截断到预算", len(_budget_line("a" * (REGEX_LINE_BUDGET + 1))),
              REGEX_LINE_BUDGET)
        big_hit = os.path.join(tmp, "big_hit.md")
        _st_write(big_hit, ["%s %s" % (t_hype, "x" * 200000)])
        rc, out, errb = _st_capture([big_hit])
        check("B14 超长行不卡死：预算内命中照报（行号正确）",
              (rc, report_lines(out, "big_hit.md:")),
              (EXIT_FAIL, ["big_hit.md:1: [hype] %s" % t_hype]))
        big_tail = os.path.join(tmp, "big_tail.md")
        _st_write(big_tail, ["The cell reached " + "x" * 40000 + " 25 MPa."])
        check("B14 退化方向：量化信号只在截断尾部时不报（宁可漏报行尾，不卡死）",
              _st_capture([big_tail])[0], EXIT_OK)
        big_head = os.path.join(tmp, "big_head.md")
        _st_write(big_head, ["The cell reached 25 MPa " + "x" * 200000 + "."])
        rc, out, errb = _st_capture([big_head])
        check("B14 超长行头部量化信号照报 missing-hedging（含段号与起始行）",
              (rc, report_lines(out, "big_head.md:")),
              (EXIT_FAIL, ["big_head.md:1: [missing-hedging] para1@1"]))
        fffd = os.path.join(tmp, "fffd.md")
        _st_write(fffd, ["clean line", "text with \ufffd replacement here"])
        rc, out, errb = _st_capture([fffd])
        check("B14 含 U+FFFD 的文本 -> rc=2 且点名文件（复用 70 号严格解码，不按干净扫）",
              (rc, "读不了 fffd.md" in errb), (EXIT_USAGE, True))
        nul = os.path.join(tmp, "nul.md")
        with open(nul, "wb") as fh:
            fh.write("abc\x00def\n".encode("utf-8"))
        rc, out, errb = _st_capture([nul])
        check("B14 含 NUL 的文本 -> rc=2 且点名文件（疑二进制混入）",
              (rc, "读不了 nul.md" in errb), (EXIT_USAGE, True))

        # ---------- F9（2026-10-06）：--domain 量化信号四域正反用例 ----------
        dom_cases = {
            "clinical": "Treatment halved events (OR 2.1, 95% CI 1.2-3.4). The effect was robust across sites.",
            "social": "Model fit was strong (beta = 0.42, p <= 0.01). Attitudes predicted behavior.",
            "csml": "The model reached 94% accuracy and F1 0.91 on the test split. Latency stayed low.",
        }
        for dname, sent in dom_cases.items():
            qpath = os.path.join(tmp, "dom-%s.md" % dname)
            with open(qpath, "w", encoding="utf-8") as fh:
                fh.write(sent)
            rc_dom, out_dom, _ = _st_capture([qpath, "--domain", dname])
            check("F9 %s: 量化段无 hedging -> missing-hedging" % dname,
                  (rc_dom, "[missing-hedging]" in out_dom), (EXIT_FAIL, True))
            hedged = sent + " This may reflect sampling variation."
            qh = os.path.join(tmp, "dom-%s-hedged.md" % dname)
            with open(qh, "w", encoding="utf-8") as fh:
                fh.write(hedged)
            rc_h, out_h, _ = _st_capture([qh, "--domain", dname])
            check("F9 %s: 有 hedging -> 干净" % dname,
                  (rc_h, "[missing-hedging]" in out_h), (EXIT_OK, False))
        # 缺省（material 口径）不误报统计信号段：样本不含 % 等材料单位
        nostat = os.path.join(tmp, "dom-no-stat.md")
        with open(nostat, "w", encoding="utf-8") as fh:
            fh.write("Attrition OR 2.1 and HR 0.8 with p <= 0.05 remained stable.")
        rc_def, out_def, _ = _st_capture([nostat])
        check("F9: 缺省（material 口径）不报纯统计信号段", (rc_def, "[missing-hedging]" in out_def),
              (EXIT_OK, False))
        rc_cli, out_cli, _ = _st_capture([nostat, "--domain", "clinical"])
        check("F9: 同段 --domain clinical 报 missing-hedging", (rc_cli, "[missing-hedging]" in out_cli),
              (EXIT_FAIL, True))
        rc_bad, _, err_bad = _st_capture([b, "--domain", "nosuch"])
        check("F9: 未知名 -> rc=2 并列出可用域", (rc_bad, "nosuch" in err_bad),
              (EXIT_USAGE, True))
    finally:
        os.chdir(old_cwd)
        shutil.rmtree(tmp, ignore_errors=True)
        check("临时目录用毕即删（无常驻文件）", os.path.isdir(tmp), False)
        check("自测不在 scripts/ 留任何文件（含 __pycache__）", sorted(os.listdir(scripts_dir)), before_listing)

    if fails:
        print("STYLE-CHECK SELFTEST FAIL（%d 项）" % len(fails))
        for f in fails:
            print("  - " + f)
        return 1
    print("STYLE-CHECK SELFTEST PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
