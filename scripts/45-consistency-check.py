#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# vendor-tool: 45-consistency-check.py version 1
"""45-consistency-check.py — 合稿一致性机检（四类，只读，报告到 stdout）。

契约面：本脚本在 `references/60-capability-specs.md` 里没有章节，判据真源是任务卡 AC 五条
      + `references/40-draft-to-latex.md` §装配链第 3 条（编号↔文献表一一对应、Fig.1..N 与 Table
      全被引用、字数区间、术语归一）+ `.orchd/shared/conventions.md §2/§3`。
      命名以 **45** 为唯一后续命名（同文档明写「不再另造 consistency_check」）。

输入面：位置参数给 md 文件或目录（目录递归收 *.md，跳过点目录），真实输入是论文项目的
      `30-manuscript/*.md`。报告路径口径与 40 号脚本逐字一致：目录输入→相对该目录；相对单文件→
      原样回显；绝对单文件→只回显文件名。绝不回显绝对路径（本机路径进报告属发布物污染）。
      --refs FILE：编号制文献表所在文件（须是单个文件，不给目录）。给了它就以该文件的**行首 [n]**
        为唯一条目源：① 该文件**不参与引用抽取**（条目里别人题名中的 [12] 不是本文的引用）；
        ② 其余文件里的行首 [n] 改按**引用**处理（条目源唯一化后不允许第二处声明编号，否则两处文献表
        各自编号会互相打脸）。不给时：所有输入里的行首 [n] 都是条目行。
      --budget FILE：YAML，顶层 budget 映射 {节名: [lo, hi]}；区间语义与 70-verify 的 word_count
        同口径（两元整数、含端点、词按空白切分）。给目录直接 rc=2 说清是目录（不落成「不是合法 YAML」
        那种把读者往错方向引的措辞）；两个键规范化后同名（`Methods` 与 `3. Methods`）也 rc=2——
        静默覆盖会变成「配了两条、实检一条」，而汇总里的预算项数还是诚实的，读者无从起疑。

四类判据（每条都写清「什么算命中」与「为什么不静默」）：
  1 引用编号 ↔ 文献表：正文 `[n]` / `[n,m]` / `[n-m]` 展开为引用号集合；行首 `[n]` 为条目行
      （该行剥掉前导标记后其余内容仍参与引用抽取）。两个方向都报：引用了不存在的条目号（AC1）、
      条目从未被引用（AC2）。**一个条目都找不到时返 rc=2**，不静默按「零条目零命中」通过——
      文献表换了格式（`- [1] ...`、`\\bibitem`）时静默通过等于宣布检查①绿了。
      条目号重复、区间反序、区间宽于 500 均计入 rc=2 面（疑似笔误，不猜作者要哪个）。
      **形似引用而正则不吃的括号标记也计入 rc=2**：`[ 2 ]`、`[1,]`、`[1-]`、`［２］`、`[1、2]` 若静默
      放过，就是「那条引用根本没参与检查①」而报告照样打绿（expand_cite 里「引用标记无法解析」那条
      兜底走不到：对 CITE_RE 的全体可达输入穷举过，零命中，所以另开这条面）。判据是「逗号分出的每段
      都像编号或区间」，因此 md 链接、脚注 `[^1]`、数学区间 `[-1, 2]`、`[0.5, 1.0]`、`[a1]` 都不算
      （含小数点/字母/负号即否掉），判成引用笔误属假阳性。
  2 图表编号 ↔ 正文提及：图注/表注 = 行首的 `Fig. 1.` / `Table 2:` / `图 1 —` 形态（数字后紧跟
      分隔符），正文提及 = 全文任何 `Fig./Figure/Figs/Table/Tab/图/表 + 数字`。图注自身不算对
      自己的提及（否则「声明未被提及」永不触发）。两个方向都报：有注无提及（AC3，列编号与声明所在
      产物行号）、有提及无注（悬空交叉引用，同一族的另一侧）。
      边界：`表 1 不同温度……`（数字后是空格）只算**提及**不算图注——反过来会把真图注判成漏检，
      方向危险；该形态若确是图注，会以「悬空提及」上屏，作者补分隔符即消。
      编号按 1–999 建模，四位及以上（`Fig. 1000`、`表 2020`）两侧正则都收不到，静默 rc=0 等于宣布
      检查②绿了 → 计入 rc=2 面并给三条出路（换制式 / 改笔误 / 指年份就写「2020 年」）。
      编号**连续性**（缺 Fig. 2）不在本脚本，属 `72-latex-build-check.py` 的 PDF 回读面。
  3 术语归一：只判**同一术语两种写法共存**，不判哪种对——所以不需要外置词表，也不会因词表缺项而静默。
      两类结构式：① 百分号前的空格（`wt%` 与 `wt %` 共存）；② 下标写法（`CO2` 与 `CO_2`/`CO_{2}`
      共存）。共存要求闭合形真的出现过，因此 `in 2020` 这类正常散文不会单独触发。
      下标面**不含空格形**（`CO 2` 不进候选）：收了它，「词 + 数字」的普通散文对（`reached 45`、
      `Figure 1`）全都变成候选项，汇总里的「术语候选」就失去意义；`Fig. 1` 这类编号面另由检查②判。
      扫描面排除围栏与文献表条目行：条目里是他人论文的题名，改它属于篡改引文，不是本文术语面。
  4 分节字数预算：节区间 = 该标题行之后到**下一个同级或更高级标题**之前（含其子节），词按空白切分，
      只计正文行（标题行、表格行、围栏内、文献表条目行不计——最后一项是因为参考文献常挂在末节标题下，
      算进去会把「Methods 超预算」判在引文上）。预算项匹配：去编号后的标题与键**规范化相等**
      （`## 3. Methods` → `methods`）。给了 --budget 却有键匹配不到任何节 → rc=2 报该键，
      因为「配置写了、节名改了、于是什么都没检查」正是假绿。
6 条目重复 / 近似重复（B10/G-10，软约束 report-only，常开）：文献表条目行（口径与检查①的
      条目源唯一化一致）归一化（小写 + 去非字母数字）后逐字相同 → 重复；difflib 比值 ≥0.90 →
      近似重复。阈值再高也拦不住同作者系列（2020a/2020b 天然高相似），故只提示、由作者裁定；
      命中只进软提示通道（notes），不判 FAIL、不改变退出码、不进 verify manifest（与⑤同通道）。

退出码：0 = 四类无不一致；1 = 有不一致；2 = 用法或输入坏（路径不存在 / 读不了 / 解码失败 /
      条目源为空 / 预算配置不合 schema / 无输入）。**FAIL 优先于 usage-error**（conventions §3）：
      同一次运行里既有不一致又有坏输入时返 1，不一致不得被路径错误糊成 0。
只读承诺：无 --out，输出只到 stdout / stderr，输入文件字节零改动（自测有断言）。
自测口径：--selftest 全离线、进程内直调 main()（不起子进程），样本与预算配置写在临时目录、用毕即删；
      每条判据配「正反一对」（共存触发 / 单一写法不触发、缺项报错 / 补齐即绿），收尾断言
      「未给 --budget 时汇总行必须写明检查④未执行」——跳过必须可见。
      围栏状态机与 40 号同实现（闭合只认同种标记、缩进 <=3）：用标记行数奇偶相消的旧写法在状态错位时
      会既免扫又不报错（40 号 code 审查 D-5 实测），本脚本同样不吃这个亏。
"""

import argparse
import ast
import difflib
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

import yaml  # noqa: E402  置位必须早于第三方 import：.pyc 内嵌本机绝对路径，属发布物污染

EXIT_OK, EXIT_FAIL, EXIT_USAGE = 0, 1, 2
FENCE_MARKS = ("```", "~~~", "***")
SCANNED_KINDS = ("heading", "table", "text")
MAX_RANGE_SPAN = 500
# B14（G-13）：正则输入预算——单行超 32KB 走截断，只用标准库 re，不引入第三方引擎。
# 超长退化行不断言尾部命中（宁可漏报行尾，不卡死）；行号不受影响（只截内容不断行）。
REGEX_LINE_BUDGET = 32 * 1024


def _budget_line(s):
    """单行超预算即截断（B14 G-13）。短行原样返回，零开销。"""
    return s if len(s) <= REGEX_LINE_BUDGET else s[:REGEX_LINE_BUDGET]

HEADING_RE = re.compile(r"^(#{1,6})[ \t]+(.*)$")
ENTRY_RE = re.compile(r"^[ \t]*\[(\d+)\]")
CITE_RE = re.compile(r"\[([0-9]+(?:[ \t]*[,，\-–][ \t]*[0-9]+)*)\]")
RANGE_SEP_RE = re.compile(r"[-–]")
FIG_TOKENS = r"Figures|Figure|Figs|Fig|Tables|Table|Tab|图|表"
KIND_OF_TOKEN = {"Figures": "fig", "Figure": "fig", "Figs": "fig", "Fig": "fig", "图": "fig",
                 "Tables": "table", "Table": "table", "Tab": "table", "表": "table"}
MENTION_RE = re.compile(r"(?<![A-Za-z])(" + FIG_TOKENS + r")[ \t]*\.?[ \t]*([0-9]{1,3})(?![0-9])")
CAPTION_RE = re.compile(r"^[ \t]*(?:\*\*|__)?[ \t]*(" + FIG_TOKENS + r")[ \t]*\.?[ \t]*"
                        r"([0-9]{1,3})[ \t]*[.:：)—]")
PCT_RE = re.compile(r"(?<![A-Za-z0-9])([A-Za-z][A-Za-z0-9]{1,})[ \t]?%")
SUB_RE = re.compile(r"(?<![A-Za-z0-9])([A-Za-z]{1,})_?\{?([0-9]{1,3})\}?(?![0-9A-Za-z])")
SEC_NUM_PREFIX_RE = re.compile(r"^[0-9]+(?:\.[0-9]+)*[.)]?[ \t]*")
# 编号位数上限之外的形态：CITE_RE 太窄，坏标记根本进不了解析器（实测「引用标记无法解析」那条
# 兜底分支对 CITE_RE 的全体可达输入零命中），所以另开一条「像引用但不是」的面来上屏。
LOOKALIKE_RE = re.compile(r"[\[［]([^\[\]［］\n]{0,24})[\]］]")
DIGIT_ANY_RE = re.compile(r"[0-9０-９]")
NUM_PIECE_RE = re.compile(r"[0-9０-９]+(?:[ \t]*[-–][ \t]*[0-9０-９]+)?")
OPEN_NUM_RE = re.compile(r"[0-9０-９]+[ \t]*[-–]")
# 图/表编号按 1–3 位建模；更长的数字既进不了 CAPTION_RE 也进不了 MENTION_RE，必须点名而不是静默。
OVERLONG_RE = re.compile(r"(?<![A-Za-z])(" + FIG_TOKENS + r")[ \t]*\.?[ \t]*([0-9]{4,})")

# ── 检查⑤（--stats）：统计报告 report-only 软约束 ──────────────────────────
# F17 用户裁决（2026-10-06）：统计报告合规一律软约束——命中只上屏 [stats] 提示行，
# **永不改变退出码**（与检查①–④的硬判据分属两条通道；report-only 口径见
# references/60-capability-specs.md §0 退出码语义——§1 是 40 号词表规格，此处置 §1 属误指）。
P_VALUE_RE = re.compile(r"(?<![A-Za-z_])[pP][ \t]*(?:=|≤|=<|<=|<|≥|=>|>)[ \t]*0?\.\d+|\b[Pp]-[ \t]*0?\.\d+")
CI_SE_RE = re.compile(r"(?:\bCIs?\b|\bSEs?\b|confidence[ \t]+interval|standard[ \t]+error)", re.IGNORECASE)
SIGNIFICANT_RE = re.compile(r"significant(?:ly)?|显著", re.IGNORECASE)
EFFECT_SIZE_RE = re.compile(
    r"Cohen'?s?[ \t]*d|\bd[ \t]*(?:=|:)[ \t]*-?\d|\br[ \t]*(?:=|:)[ \t]*-?\d"
    r"|\b(?:OR|RR|HR|WHR|β)\b|\bodds[ \t]+ratio\b|\brisk[ \t]+ratio\b|\bhazard[ \t]+ratio\b"
    r"|\beffect[ \t]+size\b|效应量|η2|η²|omega|Cramér", re.IGNORECASE)
MEAN_SD_RE = re.compile(r"(\d+(?:\.\d+)?)[ \t]*(?:±|\+/-)[ \t]*(\d+(?:\.\d+)?)")
NUM_PCT_RE = re.compile(r"(?<![A-Za-z0-9])(\d+(?:\.\d+)?)[ \t]*%")
# 置信水平排除集：这三个数在 % 语境下最可能是 CI 的置信水平而非统计结果，见 _stat_numbers 注释。
CI_LEVEL_PCT = ("90%", "95%", "99%")
ABSTRACT_HEAD_RE = re.compile(r"^#{1,6}[ \t]*(?:abstract|摘[ \t]*要|summary)\b", re.IGNORECASE)


# ---------- 分段与输入 ----------

def _line_kinds(lines):
    """逐行定性，返回 (kinds, 未闭合围栏的起始行号|None)。

    两条硬约束都来自 40 号脚本的 code 审查：① 标记行缩进 <=3（缩进 4 格的 ``` 是代码内容）
    ② 闭合符须与开启符同种。少一条都会让状态整体错位一格，把真散文判成围栏内，
    而且标记行总数仍是偶数、连「未闭合」都报不出来。
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


def _iter_md(root):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if not d.startswith("."))
        for name in sorted(filenames):
            if name.lower().endswith(".md"):
                yield os.path.join(dirpath, name)


def collect_inputs(paths):
    """返回 (files, errors)。files = [(display, abspath)] 按 display 升序；display 口径见 docstring。"""
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
            files.append((os.path.basename(clean) if os.path.isabs(clean)
                          else clean.replace(os.sep, "/"), os.path.abspath(clean)))
    files.sort(key=lambda p: p[0])
    return files, errors


def load_docs(files):
    """返回 (docs, errors)。docs = [(display, lines, kinds)]。"""
    docs, errors = [], []
    for display, path in files:
        try:
            with open(path, "r", encoding="utf-8-sig") as fh:
                text = fh.read()
        except (OSError, UnicodeDecodeError) as exc:
            # 解码失败计入 rc=2 面，绝不「跳过这一篇」——跳过等于替作者判成干净。
            errors.append("读不了 %s（%s：%s）" % (display, type(exc).__name__, str(exc)[:80]))
            continue
        if "\ufffd" in text or "\x00" in text:
            # B14（G-14）：复用 70 号严格解码——解码结果含 U+FFFD 替换字符或 NUL
            # 即记错误（rc=2 面），不按干净文本检查（替换字符会吞掉引用/编号标记）。
            errors.append("读不了 %s（文本含 U+FFFD 替换字符或 NUL：疑似非 UTF-8/二进制混入，"
                          "按 70 号口径归输入错）" % display)
            continue
        lines = [_budget_line(ln) for ln in text.splitlines()]
        kinds, fence = _line_kinds(lines)
        if fence is not None:
            errors.append("未闭合围栏：%s 第 %d 行的围栏标记直到文末都没配对，其后至文末未参与一致性检查"
                          % (display, fence))
        docs.append((display, lines, kinds))
    return docs, errors


# ---------- 判据 1：引用编号 ↔ 文献表 ----------

def expand_cite(inner, display, lineno, errors):
    """把 `[3]` / `[3,4]` / `[2-5]` 展开成引用号；坏区间计入 errors。"""
    nums = []
    for part in re.split(r"[,，]", inner):
        part = part.strip()
        if not part:
            continue
        if RANGE_SEP_RE.search(part):
            ends = [e.strip() for e in RANGE_SEP_RE.split(part)]
            if len(ends) != 2 or not all(e.isdigit() for e in ends):
                errors.append("引用区间无法解析：%s:%d 的 [%s]" % (display, lineno, inner))
                continue
            lo, hi = int(ends[0]), int(ends[1])
            if hi < lo:
                errors.append("引用区间反序：%s:%d 的 [%s]（不猜作者要哪个）" % (display, lineno, inner))
                continue
            if hi - lo > MAX_RANGE_SPAN:
                errors.append("引用区间过宽：%s:%d 的 [%s]，跨度 > %d 视为笔误"
                              % (display, lineno, inner, MAX_RANGE_SPAN))
                continue
            nums.extend(range(lo, hi + 1))
        elif part.isdigit():
            nums.append(int(part))
        else:
            # 对 CITE_RE 的全体可达输入穷举过：这条走不到。留着是因为解析面在正则之外，
            # 一旦正则放宽，缺了它就变成「不认识的标记静默不算引用」——那正是本脚本要堵的洞。
            errors.append("引用标记无法解析：%s:%d 的 [%s]" % (display, lineno, inner))
    return nums


def _looks_like_num_list(inner):
    """括号内容是否「像编号列表」：含数字，且逗号分出的每段都是编号/区间（或悬空逗号、缺右端区间）。

    判不成编号列表的（含字母、小数点、负号）不报：那是 markdown 链接、脚注或数学区间
    （`[-1, 2]`、`[0.5, 1.0]`），把它们判成引用笔误是假阳性。
    """
    if not DIGIT_ANY_RE.search(inner):
        return False
    for piece in re.split(r"[,，、]", inner):
        p = piece.strip()
        if not p or OPEN_NUM_RE.fullmatch(p):
            return True
        if NUM_PIECE_RE.fullmatch(p):
            continue
        return False
    return True


def cite_lookalikes(txt, display, lineno, errors):
    """CITE_RE 没吃掉、但形态像引用的括号标记一律上屏（不静默免扫）。"""
    valid = set(txt[m.start():m.end()] for m in CITE_RE.finditer(txt))
    for m in LOOKALIKE_RE.finditer(txt):
        token = txt[m.start():m.end()]
        if token in valid or not _looks_like_num_list(m.group(1)):
            continue
        errors.append("引用标记不合口径：%s:%d 的 %s（只认半角 [n] / [n,m] / [n-m]；"
                      "全角括号、括号内空格、悬空逗号、缺右端的区间都不参与检查①）"
                      % (display, lineno, token))


def check_refs(docs, refs_display):
    entries, entry_loc, cites, errors = [], {}, [], []
    for display, lines, kinds in docs:
        ref_only = refs_display is not None and display == refs_display
        for idx, (txt, k) in enumerate(zip(lines, kinds), 1):
            if k not in SCANNED_KINDS:
                continue
            m = None if (refs_display is not None and not ref_only) else ENTRY_RE.match(txt)
            if m:
                num = int(m.group(1))
                if num in entry_loc:
                    errors.append("文献表条目号重复：[%d]，%s:%d 与 %s:%d"
                                  % (num, entry_loc[num][0], entry_loc[num][1], display, idx))
                else:
                    entries.append(num)
                    entry_loc[num] = (display, idx)
                if ref_only:
                    continue
                txt = txt[m.end():]
            elif ref_only:
                continue
            for c in CITE_RE.finditer(txt):
                for n in expand_cite(c.group(1), display, idx, errors):
                    cites.append((n, display, idx))
            cite_lookalikes(txt, display, idx, errors)
    stats = {"entries": len(entries), "cites": len(cites), "missing": 0, "uncited": 0}
    if not entries:
        errors.append("未找到编号制文献表条目（行首 [n]）：检查①无法进行。"
                      "文献表独立成文件时用 --refs 指明；换制式（如 bibitem）不在本脚本口径内")
        return [], stats, errors
    cited = set(n for n, _d, _i in cites)
    hits = []
    for n, display, idx in cites:
        if n not in entry_loc:
            hits.append((display, idx, "ref-missing", "正文引用 [%d]，文献表无该条目号" % n))
    for n in sorted(set(entries) - cited):
        display, idx = entry_loc[n]
        hits.append((display, idx, "ref-uncited", "条目 [%d] 正文从未引用" % n))
    stats["missing"] = sum(1 for h in hits if h[2] == "ref-missing")
    stats["uncited"] = sum(1 for h in hits if h[2] == "ref-uncited")
    return hits, stats, errors


# ---------- 判据 6：条目重复 / 近似重复（report-only 软约束，永不改退出码） ----------

DUP_NEAR_THRESHOLD = 0.90


def _norm_entry_text(body):
    """条目归一（B10/G-10）：小写 + 去非字母数字。连字符/空格/标点差异不掩盖重复。"""
    return re.sub(r"\W+", "", str(body or "").lower(), flags=re.UNICODE)


def check_ref_entry_dups(docs, refs_display):
    """文献表条目内容去重提示。返回 (hits, stats, errors)。

    report-only 口径（B10/G-10，与⑤同通道）：hits 只能进软提示通道（run_all 的 notes），
    **不得并入 all_hits** —— 并入即等于把软约束变成硬门禁，是本面头号回归。
    条目源口径与 check_refs 一致（给了 --refs 则只看该文件的行首 [n] 行）。
    每个后出现的条目最多报一条（优先报最早的逐字重复，否则报最早的近似重复）。
    """
    entries = []
    for display, lines, kinds in docs:
        ref_only = refs_display is not None and display == refs_display
        for idx, (txt, k) in enumerate(zip(lines, kinds), 1):
            if k not in SCANNED_KINDS:
                continue
            if refs_display is not None and not ref_only:
                continue
            m = ENTRY_RE.match(txt)
            if not m:
                continue
            body = txt[m.end():].strip()
            if not body:
                continue
            entries.append((display, idx, body))
    hits, errors = [], []
    n_dup = n_near = 0
    for j in range(1, len(entries)):
        norm_j = _norm_entry_text(entries[j][2])
        if not norm_j:
            continue
        plain_j = " ".join(str(entries[j][2]).lower().split())
        exact = near = None
        for i in range(j):
            if _norm_entry_text(entries[i][2]) == norm_j:
                exact = i
                break
        if exact is None:
            for i in range(j):
                plain_i = " ".join(str(entries[i][2]).lower().split())
                if difflib.SequenceMatcher(None, plain_i, plain_j).ratio() >= DUP_NEAR_THRESHOLD:
                    near = i
                    break
        if exact is not None:
            n_dup += 1
            hits.append((entries[j][0], entries[j][1], "ref-dup",
                         "条目内容与 %s:%d 重复（归一后逐字相同，请核对是否同一文献被录两次）"
                         % (entries[exact][0], entries[exact][1])))
        elif near is not None:
            n_near += 1
            hits.append((entries[j][0], entries[j][1], "ref-dup",
                         "条目内容与 %s:%d 近似重复（相似度 ≥%.2f，请核对是否同一文献、或补区分信息）"
                         % (entries[near][0], entries[near][1], DUP_NEAR_THRESHOLD)))
    return hits, {"entries": len(entries), "dup": n_dup, "near": n_near}, errors


# ---------- 判据 2：图表编号 ↔ 正文提及 ----------

def _cn(kind):
    return "图" if kind == "fig" else "表"


def check_figures(docs):
    hits, errors = [], []
    declared, mentioned = {}, {}
    for display, lines, kinds in docs:
        for idx, (txt, k) in enumerate(zip(lines, kinds), 1):
            if k not in SCANNED_KINDS:
                continue
            body = txt
            cap = CAPTION_RE.match(txt)
            if cap:
                key = (KIND_OF_TOKEN[cap.group(1)], int(cap.group(2)))
                if key in declared:
                    prev = declared[key]
                    if prev != (display, idx):
                        errors.append("图注编号重复：%s %d，%s:%d 与 %s:%d"
                                      % (_cn(key[0]), key[1], prev[0], prev[1], display, idx))
                else:
                    declared[key] = (display, idx)
                body = txt[cap.end():]
            for m in MENTION_RE.finditer(body):
                mentioned.setdefault((KIND_OF_TOKEN[m.group(1)], int(m.group(2))), (display, idx))
            # 编号位数之外：CAPTION_RE/MENTION_RE 的 [0-9]{1,3} 会让四位以上整体失明，
            # 静默 rc=0 就是「检查②绿了」的假信号，所以宁可判成输入不合口径。
            for m in OVERLONG_RE.finditer(txt):
                errors.append("图/表编号超出 1–999 口径：%s:%d 的 %s（本脚本按 1–3 位编号建模；"
                              "若确是超大编号请换制式，若是笔误请改正，若指年份请写成「2020 年」以免歧义）"
                              % (display, idx, m.group(0).strip()))
    for key in sorted(set(declared) - set(mentioned)):
        display, idx = declared[key]
        hits.append((display, idx, "fig-uncited",
                     "%s %d 有注但正文从未提及（声明于 %s:%d）" % (_cn(key[0]), key[1], display, idx)))
    for key in sorted(set(mentioned) - set(declared)):
        display, idx = mentioned[key]
        hits.append((display, idx, "fig-dangling",
                     "%s %d 在正文被提及，但没有该编号的图注/表注（提及于 %s:%d；"
                     "图注须以分隔符收尾，如 Fig. %d.）"
                     % (_cn(key[0]), key[1], display, idx, key[1])))
    st = {"caps": len(declared), "mentions": len(mentioned),
          "uncited": sum(1 for h in hits if h[2] == "fig-uncited"),
          "dangling": sum(1 for h in hits if h[2] == "fig-dangling")}
    return hits, st, errors


# ---------- 判据 3：术语归一 ----------

def check_terms(docs):
    groups = {}
    for display, lines, kinds in docs:
        for idx, (txt, k) in enumerate(zip(lines, kinds), 1):
            if k not in SCANNED_KINDS or ENTRY_RE.match(txt):
                continue
            for rx, cls in ((PCT_RE, "pct"), (SUB_RE, "sub")):
                for m in rx.finditer(txt):
                    if cls == "pct":
                        key, surface = ("pct", m.group(1).lower()), m.group(0)
                    else:
                        key = ("sub", m.group(1).lower() + m.group(2))
                        surface = m.group(0)
                    slot = groups.setdefault(key, {})
                    if surface not in slot:
                        slot[surface] = [0, display, idx]
                    slot[surface][0] += 1
    hits = []
    for key in sorted(groups):
        slot = groups[key]
        if len(slot) < 2:
            continue
        forms = sorted(slot, key=lambda s: (slot[s][1], slot[s][2]))
        shown = " 与 ".join("%r（%d 次，首现 %s:%d）" % (f, slot[f][0], slot[f][1], slot[f][2])
                            for f in forms)
        hits.append((slot[forms[0]][1], slot[forms[0]][2], "terms-unnormalized",
                     "术语未归一：%s" % shown))
    return hits, {"candidates": len(groups), "mixed": len(hits)}, []


# ---------- 判据 4：分节字数预算 ----------

def norm_title(raw):
    t = SEC_NUM_PREFIX_RE.sub("", raw.strip())
    t = re.sub(r"[*_`]", "", t)
    return re.sub(r"[ \t]+", " ", t).strip().strip(":：.。").lower()


def sections_of(docs):
    out = []
    for display, lines, kinds in docs:
        heads = []
        for idx, (txt, k) in enumerate(zip(lines, kinds), 1):
            m = HEADING_RE.match(txt) if k == "heading" else None
            if m:
                heads.append((idx, len(m.group(1)), m.group(2)))
        for pos, (idx, level, raw) in enumerate(heads):
            end = len(lines)
            for nxt_idx, nxt_level, _r in heads[pos + 1:]:
                if nxt_level <= level:
                    end = nxt_idx - 1
                    break
            words = sum(len(lines[j].split()) for j in range(idx, end)
                        if kinds[j] == "text" and not ENTRY_RE.match(lines[j]))
            out.append({"title": norm_title(raw), "raw": raw.strip(), "display": display,
                        "line": idx, "words": words})
    return out


class DuplicateYamlKey(yaml.YAMLError):
    """YAML 映射含重复键（A3，2026-10-07 审查）。

    yaml 默认 last-wins：重复的 budget 顶层键或节名会让前一条定义被静默吞掉（配了两条、
    实检一条，而汇总里的预算项数还是诚实的，读者无从起疑）。
    """


class _NoDuplicateKeyLoader(yaml.SafeLoader):
    """安全加载器 + **任意层级**重复键检出（A3）。键名随异常上抛，由 load_budget 归 rc=2。"""

    def construct_mapping(self, node, deep=False):
        self.flatten_mapping(node)
        mapping = {}
        for key_node, value_node in node.value:
            key = self.construct_object(key_node, deep=deep)
            try:
                duplicate = key in mapping
            except TypeError:            # 不可哈希键：交给下面照常赋值（由既有 schema 校验接手）
                duplicate = False
            if duplicate:
                raise DuplicateYamlKey("重复键 %r" % (key,))
            mapping[key] = self.construct_object(value_node, deep=deep)
        return mapping


def load_budget(path):
    """--budget 的 schema 校验。返回 (budget|None, errors)；errors 非空即 rc=2。"""
    if os.path.isdir(path):
        # 不给这条就会掉进 open(dir) 的 PermissionError，被下面的兜底说成「不是合法 YAML」——
        # 那是把读者往错方向引（实测 Windows 下目录报的是 Errno 13）。
        return None, ["预算配置须是单个文件（实际是目录）：%s" % path]
    if not os.path.exists(path):
        return None, ["预算配置文件不存在：%s" % path]
    try:
        with open(path, "r", encoding="utf-8-sig") as fh:
            raw = yaml.load(fh, Loader=_NoDuplicateKeyLoader)
    except DuplicateYamlKey as exc:
        # 重复键 last-wins 属静默失效（A3）：先于通用 YAMLError 分支点名键名；与既有
        # 规范化撞车检测（Methods vs 3. Methods）互补，不覆盖其错误码。
        return None, ["预算配置含重复键：%s（yaml 默认 last-wins 会静默覆盖前一条定义，请去重）" % exc]
    except (OSError, ValueError, yaml.YAMLError) as exc:
        # 同 40 号 D-1：yaml.YAMLError 的 MRO 只有 Exception，不显式捕就变成 traceback + rc=1。
        return None, ["预算配置不是合法 YAML（%s）：%s" % (type(exc).__name__, str(exc)[:120])]
    if not isinstance(raw, dict):
        return None, ["预算配置顶层须为对象，实际为 %s" % type(raw).__name__]
    if "budget" not in raw:
        return None, ["预算配置缺 budget 键（顶层须为 budget: {节名: [lo, hi]}）"]
    body = raw["budget"]
    if not isinstance(body, dict):
        return None, ["budget 须为映射（节名 -> [lo, hi]），实际为 %s" % type(body).__name__]
    if not body:
        return None, ["budget 为空映射：写了配置却没给任何节，属门禁空转"]
    out, errors = {}, []
    for key, val in body.items():
        where = "budget[%r]" % (key,)
        if not isinstance(key, str) or not key.strip():
            errors.append("%s 的节名须为非空字符串" % where)
            continue
        if not isinstance(val, (list, tuple)) or len(val) != 2 \
                or not all(isinstance(v, int) and not isinstance(v, bool) for v in val):
            errors.append("%s 必须是 [lo, hi] 两个整数，实为 %r" % (where, val))
            continue
        if val[1] < val[0]:
            errors.append("%s 区间反序：%r" % (where, list(val)))
            continue
        normed = norm_title(key)
        if normed in out:
            # 撞车必须死在这里：静默覆盖会让「配了两条、实检一条」变成假绿，
            # 而汇总里的预算项数还是诚实的，读者无从起疑。
            errors.append("%s 与 budget[%r] 规范化后同为 %r：两条预算只有一条会参与判定"
                          % ("budget[%r]" % (out[normed][2],), key, normed))
            continue
        out[normed] = (val[0], val[1], key)
    return out, errors


def check_budget(docs, budget):
    secs = sections_of(docs)
    hits, errors = [], []
    for key in sorted(budget):
        lo, hi, shown = budget[key]
        matched = [s for s in secs if s["title"] == key]
        if not matched:
            errors.append("预算项 %r 没有对应小节（规范化标题相等才算；现有节：%s）"
                          % (shown, "、".join(sorted({s["title"] for s in secs})) or "无标题"))
            continue
        for s in matched:
            if s["words"] < lo:
                rel = "低于下界 %d" % lo
            elif s["words"] > hi:
                rel = "超出上界 %d" % hi
            else:
                continue
            hits.append((s["display"], s["line"], "word-budget",
                         "节「%s」实测 %d 词，%s（预算区间 [%d, %d]）"
                         % (s["raw"], s["words"], rel, lo, hi)))
    return hits, {"sections": len(secs), "items": len(budget)}, errors


# ---------- 装配 ----------

# ---------- 判据 5：统计报告合规（report-only 软约束，永不改退出码） ----------

def _stat_units(lines, kinds):
    """逐个文本行产出 (行号, 判定窗口)。

    p 值与它的 CI/SE 常被折行分开（「p = 0.03」一行、「(95% CI: …)」下一行），
    按单行判会全线误判，故判定域放宽到「本行 + 下一文本行」——只放宽一格，不做整节合并。
    """
    for i, k in enumerate(kinds):
        if k != "text":
            continue
        window = lines[i]
        if i + 1 < len(lines) and kinds[i + 1] == "text":
            window = lines[i] + " " + lines[i + 1]
        yield i + 1, window


def _abstract_span(lines, kinds):
    """返回摘要节行号区间 (lo, hi)（1-based 闭区间）；无摘要节返回 None。"""
    heads = []
    for i, k in enumerate(kinds):
        if k != "heading":
            continue
        m = HEADING_RE.match(lines[i])
        if m:
            heads.append((i + 1, len(m.group(1))))
    for pos, (idx, level) in enumerate(heads):
        if not ABSTRACT_HEAD_RE.match(lines[idx - 1]):
            continue
        end = len(lines)
        for nxt_idx, nxt_level in heads[pos + 1:]:
            if nxt_level <= level:
                end = nxt_idx - 1
                break
        return idx, end
    return None


def _stat_numbers(lines, rng):
    """区间内的统计数字集合：`A ± B` 与 `N%` 两种形态，按完整形态串比对。

    两组正则的 findall 返回形态不同，混用会静默错值：MEAN_SD_RE 有两个捕获组 → 返回
    tuple 列表，须 join；NUM_PCT_RE 只有一个组 → 返回**字符串**列表，元素本身就是数字，
    再取 m[0] 等于只取首字符（95% 会变成 9%、18% 变成 1%）。两条路径分开写，不共用一个 m[0]。

    CI_LEVEL_PCT 排除三个置信水平：在 % 语境下 90/95/99 最可能是「95% CI: 0.01-0.05」的
    置信水平，而置信水平不必在正文重复出现——比进去会把合规稿判成不一致。取舍是「真写
    95% of samples」的情形会漏判（少一条软提示），方向上安全（软约束宁可漏报不误报）。
    """
    got = set()
    for idx in rng:
        line = lines[idx]
        got.update("±".join(m) for m in MEAN_SD_RE.findall(line))
        got.update(m + "%" for m in NUM_PCT_RE.findall(line) if m + "%" not in CI_LEVEL_PCT)
    return got


def check_stats(docs):
    """三类统计报告合规面。返回 (hits, stats, errors)。

    report-only 口径（F17）：hits 只能进软提示通道（run_all 的 notes），**不得并入
    all_hits** —— 并入即等于把软约束变成硬门禁，是本面头号回归。
    摘要↔正文面取保守单向口径：只报「摘要有、正文无对应」，不判「两边都有但值不同」
    （那需要语义对齐，误杀率不可控），留作者与审稿人自校。
    """
    hits, errors = [], []
    n_p = n_sig = n_abs = 0
    for display, lines, kinds in docs:
        for lineno, window in _stat_units(lines, kinds):
            if P_VALUE_RE.search(window) and not CI_SE_RE.search(window):
                n_p += 1
                hits.append((display, lineno, "stats",
                             "p 值未与 CI/SE 同现（缺不确定性区间，读者无法判断效应是否稳）"))
            if SIGNIFICANT_RE.search(window) and not EFFECT_SIZE_RE.search(window):
                n_sig += 1
                hits.append((display, lineno, "stats",
                             "「显著」未同现效应量（只给 p 值不构成可复核的显著性主张）"))
        span = _abstract_span(lines, kinds)
        if not span:
            continue
        lo, hi = span
        abs_nums = _stat_numbers(lines, range(lo - 1, min(hi, len(lines))))
        body_nums = _stat_numbers(lines, (i for i in range(len(lines))
                                          if not lo <= i + 1 <= hi))
        for num in sorted(abs_nums - body_nums):
            n_abs += 1
            hits.append((display, lo, "stats",
                         "摘要数字 %s 在正文找不到对应（摘要须与正文同源，核是否正文被改漏）" % num))
    return hits, {"p_no_ci": n_p, "sig_no_effect": n_sig, "abstract_mismatch": n_abs}, errors


def run_all(paths, refs_arg, budget_arg, stats_on=False):
    files, errors = collect_inputs(paths)
    refs_display = None
    if refs_arg:
        clean = refs_arg.rstrip("/\\") or refs_arg
        if os.path.isdir(clean):
            errors.append("--refs 须是单个文件（条目源必须唯一），实为目录：%s" % refs_arg)
        else:
            ref_files, ref_err = collect_inputs([refs_arg])
            errors.extend(ref_err)
            if ref_files:
                disp, path = ref_files[0]
                rpath = os.path.realpath(path)
                # 同一物理文件可能已由位置参数收进来（display 不同）：必须复用 docs 里已有的那个名字，
                # 否则 check_refs 的 ref_only 判定对不上号，文献表会被当正文重复计入条目源。
                already = [d for d, p in files if os.path.realpath(p) == rpath]
                if already:
                    refs_display = already[0]
                else:
                    files.append((disp, path))
                    files.sort(key=lambda p: p[0])
                    refs_display = disp
    docs, read_errors = load_docs(files)
    errors.extend(read_errors)

    all_hits, all_errors, stats = list(), list(errors), {"files": len(files)}
    for fn, fn_args in ((check_refs, (docs, refs_display)),
                        (check_figures, (docs,)),
                        (check_terms, (docs,))):
        hits, st, errs = fn(*fn_args)
        all_hits.extend(hits)
        all_errors.extend(errs)
        stats[fn.__name__] = st
    if budget_arg:
        budget, errs = load_budget(budget_arg)
        if budget is None:
            all_errors.extend(errs)
            stats["check_budget"] = {"sections": 0, "items": 0}
        else:
            hits, st, errs2 = check_budget(docs, budget)
            all_hits.extend(hits)
            all_errors.extend(errs + errs2)
            stats["check_budget"] = st
    else:
        stats["check_budget"] = None

    # ⑤⑥ 软约束：notes 与 all_hits 分属两条通道——只有 all_hits 参与 rc 计算（report-only 铁律）。
    # ⑥（条目重复）常开：单条目干净输入天然无对可比，不扰民；⑤（统计报告）仍需 --stats 显式开启。
    note_hits = []
    if stats_on:
        note_hits, st5, errs5 = check_stats(docs)
        all_errors.extend(errs5)
        stats["check_stats"] = st5
    else:
        stats["check_stats"] = None
    dup_hits, dup_st, dup_errs = check_ref_entry_dups(docs, refs_display)
    note_hits.extend(dup_hits)
    all_errors.extend(dup_errs)
    stats["check_ref_dups"] = dup_st

    rendered = ["%s:%d: [%s] %s" % (d, i, c, m) for d, i, c, m in sorted(set(all_hits))]
    notes = ["%s:%d: [%s] %s" % (d, i, c, m) for d, i, c, m in sorted(set(note_hits))]
    rc = EXIT_FAIL if all_hits else (EXIT_USAGE if all_errors else EXIT_OK)
    return rc, rendered, stats, all_errors, notes


def emit(rendered, stats, errors, notes=None):
    for line in rendered:
        print(line)
    notes = notes or []
    for line in notes:
        print(line)
    if any("[stats]" in ln for ln in notes):
        print("提示：以上 [stats] 行为**软约束**（report-only）——命中不判 FAIL、不改变退出码、"
              "不进 verify manifest；统计报告合规由作者与审稿人裁定"
              "（report-only 口径见 references/60-capability-specs.md §0 退出码语义）。")
    if any("[ref-dup]" in ln for ln in notes):
        print("提示：以上 [ref-dup] 行为**软约束**（report-only）——命中只提示，不判 FAIL、"
              "不改变退出码、不进 verify manifest；是否同一文献被录两次由作者裁定"
              "（口径见本脚本 docstring 判据 6）。")
    refs = stats.get("check_refs", {})
    figs = stats.get("check_figures", {})
    terms = stats.get("check_terms", {})
    budget = stats.get("check_budget")
    print("汇总：%d 个文件；①条目 %s / 正文引用 %s（缺条目 %s、未被引用 %s）；"
          "②注 %s / 提及 %s（有注无提及 %s、有提及无注 %s）；③术语候选 %s（混用 %s）；%s"
          % (stats.get("files", 0),
             refs.get("entries", 0), refs.get("cites", 0), refs.get("missing", 0), refs.get("uncited", 0),
             figs.get("caps", 0), figs.get("mentions", 0), figs.get("uncited", 0),
             figs.get("dangling", 0),
             terms.get("candidates", 0), terms.get("mixed", 0),
             # 用 is not None 而非真值判断：给了配置但全部键不合格时 budget 是空映射，
             # 那时打「④未执行（未给 --budget）」是在说谎——它执行了，只是什么都没得查。
             "④节 %s / 预算项 %s" % (budget["sections"], budget["items"]) if budget is not None
             else "④未执行（未给 --budget）"))
    if rendered:
        print("提示：命中即不一致，不存在「保留哪一种都对」。编号与格式按 references/40-draft-to-latex.md"
              " §装配链归一到单一真源；本脚本是 pre-check 报告器，不进 verify manifest。")
    if stats.get("check_budget") is None:
        print("提示：检查④（分节字数预算）未执行——未给 --budget。**跳过不等于通过**；"
              "要判字数区间得显式给配置：budget: {节名: [lo, hi]}。")
    if stats.get("check_stats") is not None:
        st5 = stats["check_stats"]
        print("汇总：⑤统计报告（软约束 report-only）p 无 CI/SE %d、显著无效应量 %d、"
              "摘要数字无正文对应 %d；命中只提示，不改变退出码"
              % (st5.get("p_no_ci", 0), st5.get("sig_no_effect", 0),
                 st5.get("abstract_mismatch", 0)))
    dup_st = stats.get("check_ref_dups") or {}
    if dup_st.get("dup", 0) + dup_st.get("near", 0):
        # 干净输入（无重复）不打印此行：无提示即干净，汇总行不留残迹。
        print("汇总：⑥条目重复（软约束 report-only）重复 %d、近似重复 %d；命中只提示，不改变退出码"
              % (dup_st.get("dup", 0), dup_st.get("near", 0)))
    for e in errors:
        print("错误：" + e, file=sys.stderr)


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="45-consistency-check.py",
        description="合稿一致性机检：引用编号↔文献表、图表编号↔提及、术语归一、分节字数预算（只读）；"
                    "另 --stats 出统计报告软提示面（report-only，命中不改退出码）")
    ap.add_argument("paths", nargs="*", metavar="<文件或目录>...",
                    help="待检查的 md 文件或目录（目录递归收 *.md）")
    ap.add_argument("--refs", help="编号制文献表所在文件（其行首 [n] 为唯一条目源，且该文件不参与引用抽取）")
    ap.add_argument("--budget", help="字数预算 YAML：顶层 budget 映射 {节名: [lo, hi]}")
    ap.add_argument("--stats", action="store_true",
                    help="检查⑤统计报告合规（report-only 软约束：三类面命中只上屏 [stats] 提示，"
                         "不判 FAIL、不改变退出码）")
    ap.add_argument("--selftest", action="store_true", help="离线自测：合成样本 + 临时配置，用毕即删")
    args = ap.parse_args(argv)
    if args.selftest:
        return run_selftest()
    if not args.paths:
        print("用法错误：给出要检查的文件或目录（或用 --selftest）", file=sys.stderr)
        return EXIT_USAGE
    rc, rendered, stats, errors, notes = run_all(args.paths, args.refs, args.budget, args.stats)
    emit(rendered, stats, errors, notes)
    return rc


# ---------- 离线自测 ----------

def _st_capture(argv):
    """进程内跑一次检查，返回 (rc, stdout, stderr)。"""
    out, err = io.StringIO(), io.StringIO()
    old_out, old_err = sys.stdout, sys.stderr
    sys.stdout, sys.stderr = out, err
    try:
        rc = main(argv)
    finally:
        sys.stdout, sys.stderr = old_out, old_err
    return rc, out.getvalue(), err.getvalue()


def _st_write(path, lines):
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(lines) + "\n")
    return path


def _st_budget(path, mapping):
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        yaml.safe_dump({"budget": mapping}, fh, allow_unicode=True, sort_keys=False)
    return path


def _st_write_raw(path, text):
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    return path


def _st_yaml_caught(src):
    """load_budget 读配置的 try 必须捕住 yaml.YAMLError（实测它不继承 ValueError）。"""
    for node in ast.walk(ast.parse(src)):
        if not isinstance(node, ast.FunctionDef) or node.name != "load_budget":
            continue
        for sub in ast.walk(node):
            if not isinstance(sub, ast.Try):
                continue
            for handler in sub.handlers:
                t = handler.type
                names = ([ast.unparse(e) for e in t.elts] if isinstance(t, ast.Tuple)
                         else [] if t is None else [ast.unparse(t)])
                if any(n.endswith("YAMLError") for n in names):
                    return True
    return False


def _st_fenced_state_machine(src):
    """本模块必须用「同种标记 + 缩进 <=3」的状态机，而不是标记行数奇偶相消。"""
    tree = ast.parse(src)
    fn = next((n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "_line_kinds"), None)
    if fn is None:
        return False
    body = ast.unparse(fn)
    return "open_mark" in body and "lstrip()" in body and "% 2" not in body and "count(" not in body


def run_selftest():
    fails = []

    def check(name, got, want):
        if got != want:
            fails.append("%s: got %r want %r" % (name, got, want))
            print("  FAIL %s: got %r want %r" % (name, got, want))
        else:
            print("  OK   %s" % name)

    def rows(out, ident):
        return [ln for ln in out.splitlines() if ("[%s]" % ident) in ln]

    scripts_dir = os.path.dirname(os.path.abspath(__file__))
    before_listing = sorted(os.listdir(scripts_dir))
    with open(os.path.abspath(__file__), "r", encoding="utf-8-sig") as fh:
        own_src = fh.read()
    tmp = tempfile.mkdtemp(prefix="cc45-selftest-")
    old_cwd = os.getcwd()
    rcs = []

    def cap(argv):
        rc, out, errb = _st_capture(argv)
        rcs.append(rc)
        return rc, out, errb

    try:
        os.chdir(tmp)
        # ---------- AC5 基线：四类全绿的样本 ----------
        clean = _st_write("clean.md", [
            "# Paper", "", "## 1. Introduction", "The batch reached 45 MPa [1].", "",
            "## 2. Methods", "Samples were measured twice [2].", "",
            "Fig. 1. Strength of batch A.", "Figure 1 agrees with Table 1.",
            "Table 1. Composition of the batches.", "",
            "[1] A. Author, 2020.", "[2] B. Author, 2021."])
        bud_ok = _st_budget("budget_ok.yaml", {"Introduction": [4, 40], "Methods": [4, 40]})
        rc, out, errb = cap(["clean.md", "--budget", bud_ok])
        check("AC5 四类全绿样本 rc=0", (rc, errb.strip()), (0, ""))
        check("AC5 汇总行按四类分别给计数（跳过项可见）",
              ("①条目 2 / 正文引用 2" in out, "②注 2 / 提及 2" in out, "③术语候选 0" in out,
               "④节 3 / 预算项 2" in out), (True, True, True, True))
        clean_no_bud = cap(["clean.md"])[1]
        check("未给 --budget：汇总写明④未执行 + 跳过不等于通过",
              ("④未执行（未给 --budget）" in clean_no_bud, "跳过不等于通过" in clean_no_bud), (True, True))
        digest_before = open(clean, "rb").read()

        # ---------- AC1 正文引用了文献表没有的条目号 ----------
        a1 = _st_write("ac1.md", ["## 1. Introduction", "The claim holds [12]."]
                       + ["[%d] Ref %d." % (i, i) for i in range(1, 12)])
        rc, out, errb = cap(["ac1.md"])
        check("AC1 缺失条目号 12 被点名（rc=1）",
              (rc, rows(out, "ref-missing")),
              (1, ["ac1.md:2: [ref-missing] 正文引用 [12]，文献表无该条目号"]))
        a1ok = _st_write("ac1_ok.md", ["## 1. Introduction", "The claim holds [1].", "[1] Ref one."])
        check("AC1 反向对照：引用号与条目号对齐时 rc=0", cap(["ac1_ok.md"])[0], 0)

        # ---------- AC2 文献表里从未被引用的条目 ----------
        a2 = _st_write("ac2.md", ["## 1. Introduction", "Only the first is cited [1].",
                                  "[1] A.", "[2] B.", "[3] C."])
        rc, out, errb = cap(["ac2.md"])
        check("AC2 未引用条目逐条列出（rc=1）",
              (rc, rows(out, "ref-uncited")),
              (1, ["ac2.md:4: [ref-uncited] 条目 [2] 正文从未引用",
                   "ac2.md:5: [ref-uncited] 条目 [3] 正文从未引用"]))
        _st_write("ac2_ok.md", ["## 1. Introduction", "All cited [1,2] and [3].",
                                "[1] A.", "[2] B.", "[3] C."])
        check("AC2 反向对照：[n,m] 并列引用展开后逐条命中，rc=0", cap(["ac2_ok.md"])[0], 0)
        _st_write("range.md", ["See [2-5]."] + ["[%d] R." % i for i in range(2, 6)])
        rc, out, errb = cap(["range.md"])
        check("引用区间 [2-5] 展开为 4 条引用", (rc, "正文引用 4" in out), (0, True))
        _st_write("range_bad.md", ["[1] A.", "See [1] and [2-1]."])
        rc, out, errb = cap(["range_bad.md"])
        check("区间反序 → rc=2 且报出行位（不猜作者要哪个）",
              (rc, "引用区间反序：range_bad.md:2 的 [2-1]" in errb), (2, True))
        _st_write("range_wide.md", ["[1] A.", "See [1] and [1-999]."])
        rc, out, errb = cap(["range_wide.md"])
        check("区间过宽（跨度 > 500）视为笔误 → rc=2", (rc, "引用区间过宽" in errb), (2, True))
        _st_write("dup_entry.md", ["Cite [1].", "[1] A.", "[1] B."])
        rc, out, errb = cap(["dup_entry.md"])
        check("条目号重复 → rc=2 并报出两处行位", (rc, "文献表条目号重复" in errb), (2, True))
        # D-1：CITE_RE 只认三种半角形态，其余「像引用」的括号标记根本进不了解析器
        # （expand_cite 的兜底分支对 CITE_RE 全体可达输入穷举过，零命中）→ 必须另开一条面。
        for i, (mark, why) in enumerate((("[ 2 ]", "括号内空格"), ("[1,]", "悬空尾逗号"),
                                         ("[, 1]", "悬空首逗号"), ("［２］", "全角括号与数字"),
                                         ("[1、2]", "顿号分隔"), ("[1-]", "区间缺右端"))):
            _st_write("lookalike%d.md" % i, ["Body cites [1] and %s." % mark, "[1] A. Author."])
            rc, out, errb = cap(["lookalike%d.md" % i])
            check("D-1 %s 不合口径的引用标记必须上屏（不得静默 rc=0）" % why,
                  (rc, "引用标记不合口径：lookalike%d.md:1 的 %s" % (i, mark) in errb), (2, True))
        for i, (mark, why) in enumerate((("[-1, 2]", "数学区间含负号"), ("[0.5, 1.0]", "小数区间"),
                                         ("[^1]", "脚注标记"), ("[a1]", "带字母的链接标签"),
                                         ("[]", "空方括号"), ("[ ]", "任务清单复选框"))):
            _st_write("benign%d.md" % i, ["Body cites [1] as in %s." % mark, "[1] A. Author."])
            rc, out, errb = cap(["benign%d.md" % i])
            check("D-1 反向对照 %s：不判成引用笔误（%s）" % (mark, why),
                  (rc, "引用标记不合口径" in errb), (0, False))
        _st_write("no_entry.md", ["## 1. Introduction", "Nothing numbered here."])
        rc, out, errb = cap(["no_entry.md"])
        check("一个条目都没有 → rc=2 并指路 --refs（不静默按零命中通过）",
              (rc, "未找到编号制文献表条目" in errb, "--refs" in errb), (2, True, True))

        # ---------- AC3 图注 ↔ 正文提及 ----------
        a3 = _st_write("ac3.md", ["## 1. Introduction", "Fig. 1 shows the trend.",
                                  "Fig. 1. Strength of batch A.", "Table 1. Composition."])
        rc, out, errb = cap(["ac3.md"])
        check("AC3 有注无提及：列出编号与声明所在产物行号（rc=1）",
              (rc, rows(out, "fig-uncited")),
              (1, ["ac3.md:4: [fig-uncited] 表 1 有注但正文从未提及（声明于 ac3.md:4）"]))
        _st_write("ac3_ok.md", ["## 1. Introduction", "Fig. 1 shows it and Table 1 lists it, see [1].",
                                "Fig. 1. Strength.", "Table 1. Composition.", "[1] A. Author."])
        check("AC3 反向对照：两个编号都被提及则 rc=0", cap(["ac3_ok.md"])[0], 0)
        a3d = _st_write("dangling.md", ["Fig. 3 shows nothing new."])
        rc, out, errb = cap(["dangling.md"])
        check("有提及无注（悬空交叉引用）被报出",
              rows(out, "fig-dangling"),
              ["dangling.md:1: [fig-dangling] 图 3 在正文被提及，但没有该编号的图注/表注"
               "（提及于 dangling.md:1；图注须以分隔符收尾，如 Fig. 3.）"])
        _st_write("selfcap.md", ["Fig. 2. Caption text.", "Fig. 1. First caption.",
                                 "See Fig. 1, discussed in [1].", "[1] A. Author."])
        rc, out, errb = cap(["selfcap.md"])
        check("图注自身不算对自己的提及（否则本条永不触发）",
              rows(out, "fig-uncited"),
              ["selfcap.md:1: [fig-uncited] 图 2 有注但正文从未提及（声明于 selfcap.md:1）"])
        _st_write("sep.md", ["## 1. Introduction", "Table 2 不同温度下的强度见下文。"])
        rc, out, errb = cap(["sep.md"])
        check("数字后无分隔符只算提及（真图注以悬空形态上屏，不失明）",
              [ln.split("] ")[1][:12] for ln in rows(out, "fig-dangling")], ["表 2 在正文被提及，但"])
        _st_write("dup_cap.md", ["Fig. 1. A.", "see Fig. 1", "Fig. 1. B."])
        rc, out, errb = cap(["dup_cap.md"])
        check("图注编号重复 → rc=2", (rc, "图注编号重复" in errb), (2, True))
        # D-2：编号按 1–999 建模，四位以上两侧正则都收不到 → 静默 rc=0 就是「检查②绿了」的假信号
        _st_write("overlong.md", ["Fig. 1000. A four-digit caption.", "Table 9999. Another.",
                                  "Body mentions Fig. 1000 and 表 2020 的数据 [1].", "[1] A."])
        rc, out, errb = cap(["overlong.md"])
        check("D-2 四位编号不得静默免扫：声明/提及/年份三种形态全部上屏",
              (rc, errb.count("超出 1–999 口径"), "图注须以分隔符收尾" not in errb),
              (2, 4, True))
        _st_write("overlong_ok.md", ["Fig. 1. Caption.", "Mentions Fig. 1 of 2020 and 999 figures [1].",
                                     "[1] A."])
        check("D-2 反向对照：三位以内编号与裸年份不误判", cap(["overlong_ok.md"])[0], 0)

        # ---------- 术语归一（共存判据 + 两面排除） ----------
        t1 = _st_write("terms_pct.md", ["The sample is 20 wt% clean.", "Another reports 30 wt % pure."])
        rc, out, errb = cap(["terms_pct.md"])
        check("百分号空格两种写法共存 → 报未归一并给两处计数",
              (rc, len(rows(out, "terms-unnormalized")), "'wt%'（1 次" in out, "'wt %'（1 次" in out),
              (1, 1, True, True))
        _st_write("terms_pct_ok.md",
                  ["The sample is 20 wt% clean, see [1].", "Another reports 30 wt% pure.",
                   "[1] A. Author."])
        check("术语反向对照：只有闭合形一种写法时不报", cap(["terms_pct_ok.md"])[0], 0)
        _st_write("terms_sub.md", ["CO2 is a gas, see [1].", "The CO_2 partial pressure dropped.",
                                   "[1] A. Author."])
        check("下标写法共存（CO2 / CO_2）被报出", len(rows(cap(["terms_sub.md"])[1], "terms-unnormalized")), 1)
        _st_write("terms_sub_ok.md", ["The CO_2 partial pressure dropped [1].", "CO_2 flow was listed.",
                                      "[1] A. Author."])
        check("下标反向对照：统一用 CO_2 时不报", cap(["terms_sub_ok.md"])[0], 0)
        _st_write("terms_entry.md", ["The sample is 20 wt% clean and cites [1].",
                                     "[1] Study of 30 wt % alloys."])
        check("文献表条目行不参与术语面（他人题名不改）", cap(["terms_entry.md"])[0], 0)
        _st_write("terms_fence.md", ["The sample is 20 wt% clean and cites [1].", "[1] A. Study.",
                                     "```", "echo 30 wt % here", "```"])
        check("围栏内不参与术语面", cap(["terms_fence.md"])[0], 0)
        _st_write("fence_cap.md", ["```", "Fig. 9. not a real caption", "```",
                                   "Body text cites [1].", "[1] A. Author."])
        rc, out, errb = cap(["fence_cap.md"])
        check("围栏内的图注形态不算声明（也不报悬空）",
              (rc, rows(out, "fig-uncited"), rows(out, "fig-dangling")), (0, [], []))
        _st_write("prose_num.md", ["Work in 2020 and in 2019 is listed [1].", "[1] A. Author."])
        check("纯散文里的年份（带空格）不进术语面", len(rows(cap(["prose_num.md"])[1], "terms-unnormalized")), 0)
        _st_write("sub_space.md", ["The CO 2 partial pressure fell and cites [1].",
                                   "CO_2 flow was set.", "[1] A. Author."])
        rc, out, errb = cap(["sub_space.md"])
        check("下标面不含空格形：CO 2 与 CO_2 共存不报（只认 CO2/CO_2/CO_{2}）",
              (rows(out, "terms-unnormalized"), "③术语候选 1（混用 0）" in out), ([], True))
        unclosed = _st_write("unclosed.md", ["clean prose", "```", "wt % never closed"])
        rc, out, errb = cap(["unclosed.md"])
        check("未闭合围栏记账（免扫不静默）",
              (rc, "未闭合围栏：unclosed.md 第 2 行" in errb), (2, True))

        # ---------- AC4 分节字数预算 ----------
        bud = _st_write("budget.md", ["## 3. Results"]
                        + [" ".join("w%d" % i for i in range(10)) for _ in range(2)]
                        + ["## 9. References", "The points are cited [7].", "[7] A. Author."])
        b_over = _st_budget("b_over.yaml", {"Results": [4, 10]})
        rc, out, errb = cap(["budget.md", "--budget", b_over])
        check("AC4 超上界：报节名 + 实测词数 + 区间上下界",
              (rc, rows(out, "word-budget")),
              (1, ["budget.md:1: [word-budget] 节「3. Results」实测 20 词，超出上界 10（预算区间 [4, 10]）"]))
        check("AC4 反向对照：同一节放宽到 [4, 40] 即 rc=0",
              cap(["budget.md", "--budget", _st_budget("b_ok.yaml", {"Results": [4, 40]})])[0], 0)
        check("AC4 低于下界同样报并给出下界",
              rows(cap(["budget.md", "--budget", _st_budget("b_under.yaml", {"Results": [100, 200]})])[1],
                   "word-budget")[0].split("，")[1], "低于下界 100（预算区间 [100, 200]）")
        nested = _st_write("nested.md", ["## 2. Methods", "aa bb cc dd ee", "### 2.1 Details", "ff gg hh",
                                         "## 3. Results", "ii jj kk ll",
                                         "## 9. References", "The points are cited [7].", "[7] A. Author."])
        check("节区间含子节：Methods 实测 8 词（5+3）",
              cap(["nested.md", "--budget", _st_budget("b_n8.yaml", {"Methods": [9, 9]})])[1]
              .count("实测 8 词"), 1)
        check("子节自身也可单独预算：Details 实测 3 词",
              cap(["nested.md", "--budget", _st_budget("b_d3.yaml", {"Details": [4, 9]})])[1]
              .count("节「2.1 Details」实测 3 词"), 1)
        check("去编号匹配：键 Methods 对上标题「2. Methods」",
              cap(["nested.md", "--budget", _st_budget("b_nok.yaml", {"Methods": [8, 8],
                                                                      "Details": [3, 3],
                                                                      "Results": [4, 4]})])[0], 0)
        rc, out, errb = cap(["nested.md", "--budget", _st_budget("b_ghost.yaml", {"Discussion": [1, 5]})])
        check("预算项无对应小节 → rc=2 并报出该键与现有节名",
              (rc, "预算项 'Discussion' 没有对应小节" in errb, "results" in errb), (2, True, True))
        for i, (name, text, want) in enumerate((
                ("空映射", "budget: {}\n", "空映射"),
                ("缺一端", "budget: {Results: [400]}\n", "必须是 [lo, hi] 两个整数"),
                ("非整数", "budget: {Results: [\"a\", \"b\"]}\n", "必须是 [lo, hi] 两个整数"),
                ("标量值", "budget: {Results: 500}\n", "必须是 [lo, hi] 两个整数"),
                ("区间反序", "budget: {Results: [900, 400]}\n", "区间反序"),
                ("顶层非对象", "- a\n- b\n", "顶层须为对象"),
                ("缺 budget 键", "words: {Results: [1, 2]}\n", "缺 budget 键"),
                ("budget 非映射", "budget: 42\n", "须为映射"),
                ("键是数字", "budget: {1: [1, 2]}\n", "节名须为非空字符串"),
                ("不是合法 YAML", "this is not: [valid yaml\n", "不是合法 YAML"))):
            bad = _st_write_raw("bad_%d.yaml" % i, text)
            rc, out, errb = cap(["budget.md", "--budget", bad])
            check("预算配置 schema：%s → rc=2 且人类可读" % name, (rc, want in errb), (2, True))
        rc, out, errb = cap(["budget.md", "--budget", "nowhere.yaml"])
        check("预算配置不存在 → rc=2", (rc, "预算配置文件不存在" in errb), (2, True))
        os.makedirs("budget_dir", exist_ok=True)
        rc, out, errb = cap(["budget.md", "--budget", "budget_dir"])
        check("D-4 --budget 给目录：rc=2 且话说清是目录（不许说成「不是合法 YAML」）",
              (rc, "须是单个文件" in errb, "不是合法 YAML" in errb), (2, True, False))
        collide = _st_write_raw("collide.yaml", "budget:\n  Methods: [8, 8]\n  3. Methods: [1, 1]\n")
        rc, out, errb = cap(["nested.md", "--budget", collide])
        check("D-3 规范化后同名的两个预算键 → rc=2 面点名（不静默二选一）",
              (rc, "规范化后同为 'methods'" in errb), (2, True))
        check("D-3 汇总里的预算项数只数真参与判定的那条（配两条、检一条，数字不说谎）",
              "④节 4 / 预算项 1" in out, True)

        # ---------- A3（2026-10-07 审查）：重复键不得 last-wins 静默失效 ----------
        # 锚点：yaml.safe_load 默认 last-wins——重复的 budget 顶层键会静默覆盖前一条定义。
        check("A3 锚点：yaml.safe_load 对重复键 last-wins（静默覆盖，洞真实存在）",
              yaml.safe_load("budget: {Results: [1, 2]}\nbudget: {}\n") == {"budget": {}}, True)
        dup_top = _st_write_raw("dup_top.yaml",
                                "budget:\n  Methods: [8, 8]\nbudget:\n  Methods: [1, 1]\n")
        rc, out, errb = cap(["nested.md", "--budget", dup_top])
        check("A3 重复顶层键 budget -> rc=2 且点名键名",
              (rc, "重复键" in errb and "budget" in errb), (2, True))
        dup_sec = _st_write_raw("dup_sec.yaml", "budget:\n  Methods: [8, 8]\n  Methods: [1, 1]\n")
        rc, out, errb = cap(["nested.md", "--budget", dup_sec])
        check("A3 节名重复键（Methods 两遍）-> rc=2 且点名",
              (rc, "重复键" in errb and "Methods" in errb), (2, True))
        clean_b = _st_write_raw("dup_clean.yaml", "budget:\n  Methods: [8, 8]\n")
        check("A3 反向对照：去重后同一预算照常判定（Methods 实测 8 词 [8,8] -> rc=0）",
              cap(["nested.md", "--budget", clean_b])[0], 0)
        rc, out, errb = cap(["nested.md", "--budget", collide])
        check("A3 互补：规范化撞车（Methods vs 3. Methods）仍走 D-3 原码，不被重复键吞掉",
              (rc, "规范化后同为 'methods'" in errb), (2, True))

        # ---------- 检查⑤ --stats（report-only 软约束：命中永不改退出码） ----------
        # 坏样本刻意做成**四类判据全绿**：只有这样 rc=0 才能干净地证明「[stats] 命中不改退出码」，
        # 否则 rc=1 分不清是软提示升级成了硬门禁，还是本来就有的不一致。
        _st_write("stats_bad.md", [
            "# Paper", "", "## Abstract",
            "Tensile strength reached 52.4 ± 1.1 MPa.",
            "The difference was significant (p = 0.03).",
            "Adhesion improved 18%.", "", "## 1. Introduction",
            "See Fig. 1 and Table 1 [1].", "Fig. 1. Strength.", "Table 1. Composition.",
            "", "[1] A. Author, 2020."])
        rc_bad_plain, out_plain, _ = cap(["stats_bad.md"])
        rc_bad_stats, out_stats, _ = cap(["stats_bad.md", "--stats"])
        s_rows = rows(out_stats, "stats")
        check("--stats 前置：坏样本在四类判据下全绿（rc=0）", rc_bad_plain, 0)
        check("--stats 三类面命中上屏（p 无 CI / 显著无效应量 / 摘要数字无正文对应）",
              (len(s_rows) >= 3,
               any("p 值未与 CI/SE 同现" in r for r in s_rows),
               any("「显著」未同现效应量" in r for r in s_rows),
               any("在正文找不到对应" in r for r in s_rows)),
              (True, True, True, True))
        check("--stats 是软约束：命中后 rc 与不加 --stats 逐码相同（不得因提示升级成 FAIL）",
              rc_bad_stats, rc_bad_plain)
        check("--stats 缺省零上屏（不显式开启就不跑不打印）", rows(out_plain, "stats"), [])
        check("--stats 汇总行给⑤三计数且写明不改退出码",
              ("⑤统计报告" in out_stats and "不改变退出码" in out_stats), True)
        check("--stats 缺省时汇总行**不出现**⑤（逐字不变，不留残迹）",
              "⑤统计报告" in out_plain, False)
        _st_write("stats_ok.md", [
            "# Paper", "", "## Abstract",
            "Tensile strength reached 52.4 ± 1.1 MPa (n = 5).",
            "The difference was significant (p = 0.03, 95% CI: 0.01-0.05, Cohen's d = 1.4).",
            "Adhesion improved 18%.", "", "## 1. Introduction",
            "See Fig. 1 and Table 1; strength reached 52.4 ± 1.1 MPa and adhesion improved 18% [1].",
            "Fig. 1. Strength.", "Table 1. Composition.", "", "[1] A. Author, 2020."])
        rc_ok, out_ok, _ = cap(["stats_ok.md", "--stats"])
        check("--stats 合规稿零提示且 rc=0（三类面均不误杀）",
              (rc_ok, rows(out_ok, "stats")), (0, []))
        check("--stats 合规稿的⑤三计数全为 0",
              ("p 无 CI/SE 0、显著无效应量 0、摘要数字无正文对应 0" in out_ok), True)
        # 反向对照：若把 notes 并入 all_hits（软约束退化成硬门禁），上面 rc_bad_stats 会由 0 变 1 而变红。
        # 反向对照二：若 run_all 无条件调用 check_stats，缺省零上屏那条会变红。
        _st_write("stats_ci_nocd.md", [
            "# Paper", "", "## Abstract", "Adhesion improved 18%.",
            "Cited [1].", "", "## 1. Introduction", "See Fig. 1 and Table 1 [1].",
            "Fig. 1. S.", "Table 1. C.", "", "[1] A. Author, 2020."])
        rc_split, out_split, _ = cap(["stats_ci_nocd.md", "--stats"])
        check("--stats 折行窗口：CI 落在 p 值的下一行也算已同现（判域放宽一格不漏报）",
              (rc_split, [r for r in rows(out_split, "stats") if "p 值未与" in r]), (0, []))

        # ---------- 判据⑥ 条目重复/近似重复（B10/G-10，report-only 软约束） ----------
        _st_write("dup_exact.md", [
            "## 1. Introduction", "Work by Smith [1] and again by Smith [2].",
            "[1] Smith J. Deep Learning Methods, 2020.",
            "[2] Smith J. Deep Learning Methods, 2020."])
        rc, out, errb = cap(["dup_exact.md"])
        check("B10 逐字重复条目上屏 [ref-dup] 且 rc=0（软提示不判 FAIL）",
              (rc, [ln for ln in rows(out, "ref-dup") if "重复" in ln]),
              (0, ["dup_exact.md:4: [ref-dup] 条目内容与 dup_exact.md:3 重复"
                   "（归一后逐字相同，请核对是否同一文献被录两次）"]))
        check("B10 重复面进汇总⑥且写明不改退出码",
              ("⑥条目重复" in out and "不改变退出码" in out), True)
        _st_write("dup_near.md", [
            "## 1. Introduction", "Work by Smith [1] and by Smith [2].",
            "[1] Smith J. Deep Learning Methods for Vision, 2020.",
            "[2] Smith J. Deep Learning Methods for Visions, 2020."])
        rc, out, errb = cap(["dup_near.md"])
        check("B10 近似重复条目上屏且 rc=0",
              (rc, any("近似重复" in ln for ln in rows(out, "ref-dup"))), (0, True))
        _st_write("dup_clean.md", [
            "## 1. Introduction", "Work by Smith [1].",
            "[1] Smith J. Deep Learning Methods, 2020."])
        rc, out, errb = cap(["dup_clean.md"])
        check("B10 反向对照：干净单条目无 [ref-dup] 提示、无⑥汇总行",
              (rc, rows(out, "ref-dup"), "⑥条目重复" in out), (0, [], False))
        rc2, rendered2, stats2, errs2, notes2 = run_all(["dup_exact.md"], None, None, False)
        check("B10 铁律：软提示只进 notes、不进硬命中（rendered 无 ref-dup、rc=0）",
              (rc2, [h for h in rendered2 if "[ref-dup]" in h],
               [n for n in notes2 if "[ref-dup]" in n] != []),
              (0, [], True))
        check("B10 归一化纪律：连字符/大小写差异仍判重复",
              check_ref_entry_dups(
                  [("f.md", ["[1] Smith-J. Deep Learning Methods, 2020.",
                             "[2] smith j deep learning methods 2020"],
                    ["text", "text"])], None)[0] != [], True)

        # ---------- --refs 口径 ----------
        _st_write("body.md", ["## 1. Introduction", "Cited [1]. Also 20 wt% here."])
        refs = _st_write("refs.md", ["[1] A. Study of 12 alloys [12].", "[2] B. Paper on 30 wt % alloys."])
        rc, out, errb = cap(["body.md", "--refs", refs])
        check("--refs：条目源唯一化，未被引用条目报出",
              (rc, rows(out, "ref-uncited")), (1, ["refs.md:2: [ref-uncited] 条目 [2] 正文从未引用"]))
        check("--refs：文献表内他人题名的 [12] 不算本文引用",
              [ln for ln in rows(out, "ref-missing") if "[12]" in ln], [])
        check("--refs：文献表行不参与术语面（wt% 与 wt % 不判混用）",
              rows(out, "terms-unnormalized"), [])
        _st_write("body2.md", ["Cited [1].", "[9] stray numbered line."])
        rc, out, errb = cap(["body2.md", "--refs", refs])
        check("--refs：正文里的行首 [9] 按引用而非条目处理",
              (rc, [ln for ln in rows(out, "ref-missing") if "[9]" in ln]),
              (1, ["body2.md:2: [ref-missing] 正文引用 [9]，文献表无该条目号"]))
        rc, out, errb = cap(["body.md", "--refs", "nowhere.md"])
        check("--refs 路径不存在 → rc=2", (rc, "输入路径不存在" in errb), (2, True))
        rc, out, errb = cap(["body.md", "--refs", tmp])
        check("--refs 给目录 → rc=2（条目源必须唯一）", (rc, "--refs 须是单个文件" in errb), (2, True))

        # ---------- 退出码优先级与输入面 ----------
        rc, out, errb = cap(["ac2.md", "nowhere.md"])
        check("FAIL 优先：坏路径 + 有不一致 → rc=1（不一致不得被糊成 0）",
              (rc, "输入路径不存在" in errb), (1, True))
        rc, out, errb = cap(["clean.md", "nowhere.md"])
        check("全绿 + 坏路径 → rc=2", rc, 2)
        rc, out, errb = cap([])
        check("无输入 → rc=2 且打用法行", (rc, "用法错误" in errb), (2, True))
        empty_dir = os.path.join(tmp, "emptydir")
        os.makedirs(empty_dir)
        rc, out, errb = cap(["emptydir"])
        check("目录里没有 *.md → rc=2（不静默 rc=0）", (rc, "目录内没有 *.md" in errb), (2, True))
        binfile = os.path.join(tmp, "bin.md")
        with open(binfile, "wb") as fh:
            fh.write(b"\xff\xfe\x00bad bytes here [\n")
        rc, out, errb = cap(["bin.md"])
        check("解码失败 → rc=2 且点名文件（不跳过当干净）",
              (rc, "读不了 bin.md" in errb), (2, True))
        # ---------- B14（G-13/G-14）：正则输入预算 + 严格解码 ----------
        check("B14 预算常量 32KB（单行超限走截断）", REGEX_LINE_BUDGET, 32 * 1024)
        check("B14 超限行截断到预算", len(_budget_line("a" * (REGEX_LINE_BUDGET + 1))),
              REGEX_LINE_BUDGET)
        _st_write("fffd_b14.md", ["clean line", "text with \ufffd replacement here"])
        rc, out, errb = cap(["fffd_b14.md"])
        check("B14 含 U+FFFD 的文本 → rc=2 且点名文件（复用 70 号严格解码）",
              (rc, "读不了 fffd_b14.md" in errb), (2, True))
        with open("nul_b14.md", "wb") as fh:
            fh.write("abc\x00def\n".encode("utf-8"))
        rc, out, errb = cap(["nul_b14.md"])
        check("B14 含 NUL 的文本 → rc=2 且点名文件（疑二进制混入）",
              (rc, "读不了 nul_b14.md" in errb), (2, True))
        _st_write("bigcite.md", ["See work [1] plus " + "x" * 200000 + ".", "[1] A. Author."])
        rc, out, errb = cap(["bigcite.md"])
        check("B14 超长行不卡死：预算内引用照常展开（rc=0）", (rc, errb.strip()), (0, ""))
        _st_write("bigcite2.md", ["x" * 40000 + " see [1].", "[1] A. Author."])
        rc, out, errb = cap(["bigcite2.md"])
        check("B14 退化方向：引用标记只在截断尾部时按未引用报（宁可漏报行尾，不卡死）",
              (rc, rows(out, "ref-uncited")),
              (1, ["bigcite2.md:2: [ref-uncited] 条目 [1] 正文从未引用"]))
        sub = os.path.join(tmp, "sub")
        os.makedirs(sub, exist_ok=True)
        _st_write(os.path.join(sub, "deep.md"), ["Cite [1].", "[1] A."])
        rc, out, errb = cap(["sub"])
        check("目录输入：报告路径相对该目录", (rc, errb.strip()), (0, ""))
        _st_write("abs_probe.md", ["Nothing cites here.", "[1] A. Author."])
        rc, out, errb = cap([os.path.join(tmp, "abs_probe.md")])
        check("绝对路径单文件：报告只回显文件名，本机临时目录名不入报告",
              (rc, "abs_probe.md:2: [ref-uncited]" in out, tmp in (out + errb)), (1, True, False))

        # ---------- 只读承诺与卫生面 ----------
        check("只读承诺：检查不改输入文件字节", open(clean, "rb").read(), digest_before)
        check("结构面：load_budget 的 except 确实含 YAMLError", _st_yaml_caught(own_src), True)
        check("结构面：反向对照——只捕 (OSError, ValueError) 的源码判红",
              _st_yaml_caught("def load_budget():\n    try:\n        x = 1\n"
                              "    except (OSError, ValueError):\n        x = 2\n"), False)
        check("结构面：围栏走状态机而非标记数奇偶", _st_fenced_state_machine(own_src), True)
        check("结构面：反向对照——按 count 奇偶判闭合的源码判红",
              _st_fenced_state_machine("def _line_kinds(lines):\n    n = lines.count('```')\n"
                                       "    return n % 2, None\n"), False)
        check("结构面：docstring 无三引号风险且脚本可解析", bool(ast.parse(own_src)), True)
        check("退出码值域只在 0/1/2", sorted(set(rcs)), [0, 1, 2])
    finally:
        os.chdir(old_cwd)
        shutil.rmtree(tmp, ignore_errors=True)
        check("临时目录用毕即删（无常驻文件）", os.path.isdir(tmp), False)
        check("自测不在 scripts/ 留任何文件（含 __pycache__）", sorted(os.listdir(scripts_dir)), before_listing)

    if fails:
        print("CONSISTENCY-CHECK SELFTEST FAIL（%d 项）" % len(fails))
        for f in fails:
            print("  - " + f)
        return 1
    print("CONSISTENCY-CHECK SELFTEST PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())

