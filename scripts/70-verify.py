# -*- coding: utf-8 -*-
# vendor-tool: 70-verify.py version 1
"""70-verify.py — 论文任务的判据基座（manifest 驱动的结构化验收）。

用法：
    python 70-tools/70-verify.py <task-id>            # 单个任务（verify_command 的标准形态）
    python 70-tools/70-verify.py --all                # 全量（迁移/回归自检用）
    python 70-tools/70-verify.py <task-id> --json      # 机器可读判定（供审查脚本解析）
    python 70-tools/70-verify.py --schema             # 打印断言 schema（无需读源码）
    python 70-tools/70-verify.py --list               # 列出 manifest 里的任务

退出码：0 = PASS，1 = FAIL（有未满足断言），2 = 用法/manifest 问题（无该任务条目等）。
安全：只读文件与执行 manifest 中显式声明的 `run`（超时 300 s），不写任何文件。
`run` 经 **shell 解释执行**（Windows 为 cmd.exe）——manifest 属受信输入（由本 skill 生成器
或项目作者维护，done 前经审查），任何不可信来源的 manifest 一律不得直接喂给本基座。

manifest 位置（按序取第一个存在的）：`--manifest` 参数 → `70-tools/71-verify-manifest.json`
→ `scripts/verify_manifest.json` → `scripts/71-verify-manifest.json`。
`{ROOT}` = 本脚本的上级目录（即项目根）。

# 断言 schema

门禁硬化（2026-10-07 审查 A2/A3/A4，均为「假绿」方向）：
  - **文本产物严格 UTF-8 解码**：非 UTF-8 或解码结果含替换字符 U+FFFD → rc=2 并点名
    文件（旧口径 errors="replace" 会把 GBK 正文里的中文 forbid 标记吞成假绿）。
  - **manifest 重复键**：任意层级的重复键（同一 task id 两遍、条目键重复）→ rc=2
    并点名键名（旧口径 json last-wins，前一条判定被静默吞掉）。
  - **验收对象必须在项目根内**：`path` / `pattern` 为绝对路径 / 带盘符 / 含 '..' 段
    → rc=2 并点名（旧口径会照单验收项目根外的文件）。

任务条目 = {"files": [...], "json_files": [...], "globs": [...], "absent_paths": [...], "run": "..."}
（各段均可省略；四段全空即空验收，直接 PASS。）
键即契约（F4，2026-10-06）：条目级或断言项级出现未知键一律 rc=2 并点名键名——拼写错误
（如 file 少个 s）曾等效空验收静默 PASS。token_source 为合法标注键（供 78 号守卫消费）。

files[]（文本/产物文件）：
  path            必填，相对项目根
  min_bytes       文件至少这么大
  contains[]      必须出现的子串（逐条）
  forbid[]        必须不出现的子串（逐条）
  contains_regex[]  必须匹配的正则（条数不限）
  forbid_regex[]    必须不匹配的正则（条数不限）
  min_matches     {"pattern": 正则, "min": n}：匹配**总次数**下限（用于“逐条列出”类 AC）
                  两键都必填，pattern 须能编译为正则
  count_distinct  {"pattern": 正则, "min": n, "scope": "line"|"all"}：**唯一**匹配数下限
                  （同一匹配串/同一行重复 N 次只计 1——抗“同图号复制”“整列同值填充”；
                  与 min_matches 互补：填充式凑数在 min_matches 下过检、在本键下变红）
                  scope 缺省 line（数唯一匹配**行**数）；all（数唯一匹配**串**数）
                  pattern/min 必填；scope 取值或嵌套键名写错一律 rc=2（形态档）
  declare_and_count {"pattern": 正则, "declare_regex": 含捕获组的正则}：**声明与计数绑死**——
                  用 declare_regex 的捕获组从文本解析声明数 N（如「共 8 条」→8；「共 0 条」→0），
                  要求 pattern 的**实际匹配数恰好等于 N**；缺声明行或 N≠实际数即 FAIL(1) 并回显两者。
                  用于「一行声明 N 条 ⇒ 正文须有 N 个条目行」类 AC，堵住「共 999 条」幽灵声明
                  （B07，review A-6）。declare_regex 必须含至少一个捕获组且可编译，否则 rc=2；
                  多声明行时只核**第一处**命中；捕获组未捕获到整数（`共 abc 条`、可选组未命中）
                  → FAIL(1) 并回显捕获值（不得裸 traceback）。
  word_count      [lo, hi]：正文行数区间（两元数组、两端为整数，含端点）
                  ——B10（A-14）改语义：旧口径按空白切词，`|` 表格脚手架凑词数与合规
                  产物不可区分。现跳过空行/纯表格行（strip 后行首 `|`）/图注行/
                  代码围栏行（围栏标记行与围栏内——认法与 40 号 `_line_kinds` 同实现：
                  标记行缩进≤3、闭合须与开启同种标记）后再数剩下的行数；标题行计入正文。
                  图注行按 45 号检查②的图注口径（行首 `Fig./Figure/Table/图/表` + 数字 +
                  紧跟分隔符；容忍前导 `#`/`*`/`>`；`表 1 不同温度`这类数字后无分隔符的
                  只算提及、不算图注）。
                  中文口径：中英文一律按行计数（中文无空白分词，不做逐字或按空白切词
                  换算），每行非空正文计 1。

json_files[]（JSON 数据文件）：
  path            必填
  min_items / max_items   顶层长度区间（列表或对象）
  require_keys[]          列表模式下检查第 1 个元素应含的键；第 1 个元素不是对象时
                          判 FAIL 并点明实际类型（朴素 `key not in data[0]` 对标量
                          TypeError 冒充 FAIL、对 str 退化为子串判定假 PASS，审查 F-2）
  require_keys_all[]      列表模式下检查**每个**元素都应含的键（逐条校验的硬口径；
                          元素不是对象同样计入失败）
  require_values{键: 期望值}  **值判定**原语（B06a）：列表模式下检查**每个**元素的这些键
                          **等值**（布尔/字符串/数字/null 标量；值写容器即 rc=2 形态错）。
                          用于「某布尔字段必须真为 true」这类判定（如 22-refs.json 逐条
                          `two_source_verified` 必须真为 true）——只判键存在（require_keys*）
                          会把 false 当"字段在"放行，验真门因此形同虚设。对象顶层同理逐键比对。

  与 min_items 的组合语义（N-3，"逐条字段齐全"类 AC 的 fail-open 修正）：
    逐条键检查是对**已有元素**求"每条都含此键"，空列表下 0 条恒真。所以
    **空列表 + 任一 require_keys*/require_values 且未配有效 min_items（缺省或 0）判为 FAIL(1)**，
    不再静默 PASS。
    两种正确写法：配 `min_items: n`（n≥1）声明"至少 n 条"；或不写键要求（只验文件是合法 JSON）。
    判 1 而非 2 的理由：门禁现场看到的通常是"产物交了空清单"，属验收未达；若确系 manifest
    漏配，错误消息会同时点出两种补救，不必再猜。

globs[]（批量产物）：
  pattern         必填，glob 模式（相对项目根，支持 `**` 递归；`[` 等字符按通配语法解析，
                  含字面特殊字符的路径建议改用 files[].path）
  min_count       命中文件数下限
  min_bytes_each  每个命中文件的大小下限

absent_paths[]（不得存在的路径，字符串数组）：
  用于“旧目录无残留”“正文不得残留标记文件”这类否定式验收。

run（字符串，可选）：额外命令；退出码非 0 即失败。用于跑项目内的自检脚本。
  预算口径（审查 F-7）：本段超时 RUN_TIMEOUT=300s 只是基座内层上限，**实际预算受引擎
  verify_command 超时约束**（引擎默认 120s，例外通道 amend --verify-timeout-seconds
  上界 600s）——配 120-300s 的 run 命令时引擎先 E014，须走例外通道提高任务预算。

条目形态自检（N-2：形态不合一律归用法错，不许裸 traceback 冒充 FAIL）：
  条目值必须是对象；files / json_files / globs 必须是**数组 of 对象**，且每项含该段的定位键
  （前两段 `path`、globs `pattern`）；absent_paths 必须是字符串数组；run 必须是字符串。
  段内可选项的类型也有口径，写错类型同样拦在形态档：`min_bytes / min_items / max_items /
  min_count / min_bytes_each` 为整数，`min_matches / count_distinct / declare_and_count /
  require_values` 为对象，
  `word_count /
  contains / forbid / contains_regex / forbid_regex / require_keys / require_keys_all` 为数组；
  再往里一层也管：定位键须是字符串、`word_count` 须是两元整数、`min_matches / count_distinct`
  两键齐备（`count_distinct` 的 `scope` 只接受 `line|all`、嵌套未知键判错）、regex 类数组的
  每项须能编译（坏正则会以 re.error 崩，而不是"没匹配上"）。
  **null 的两种待遇是刻意的**：整段写 null（YAML `files:` 空值）等同省略该段；段内某个键写
  null（`min_bytes:` 空值）判形态错——省略整段是有意的，写半个键是笔误。
  不合时退出码 2，逐条回显「任务 id + 段名[下标] + 缺的键名或实际类型」；
  历史上这些形态都是 `AttributeError: 'str' object has no attribute 'get'` /
  `KeyError: 'path'` / `TypeError: string indices must be integers` 裸崩，rc=1 混进 FAIL 语义。

路径解析基准（2026-09-26 审查 N-5：曾把 `--root X --manifest X/子路径` 解析成 X/X/子路径，
只报 "manifest not found" 不给解析轨迹，难诊断）：

  ROOT          = `--root` 指定值（须已存在且为目录，否则 rc=2 点名；B14 G-14）；
                  未指定时 = 本脚本上级目录（项目根）。
  断言里的 path   = 相对 **ROOT** 解析；**绝对路径 / 带盘符 / 含 '..' 段一律 rc=2**（A4，
                    不得验收项目根外的文件）。
  `--manifest`   = 绝对路径原样使用；**相对路径也以 ROOT 为基准，不以当前工作目录为基准**。
                  因此从别处调用时应写 `--manifest 70-tools/71-verify-manifest.json`
                  （相对目标项目根），或干脆给绝对路径；给了带根名前缀的相对路径不会自动剥离，
                  未命中时错误消息会同时回显 `--manifest` 原值与最终解析出的绝对路径。
                  未带 `--manifest` 时按上面的候选顺序在 ROOT 下查找。
"""
from __future__ import annotations

import argparse
import glob as _glob
import json
import pathlib
import re
import subprocess
import sys

# 引擎强制的调用形态是 `python 70-verify.py <task-id>`（生成器锁死该形态，不可能带 -X utf8）。
# cp936 主机上 FAIL 明细含非 GBK 字符（✅、生僻符号）时 print 会 UnicodeEncodeError →
# traceback 截断 FAIL 与 --json 输出，rc=1 由崩溃而非断言失败给出（2026-09-26 审查 N-1）。
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

ROOT = pathlib.Path(__file__).resolve().parent.parent
MANIFEST_CANDIDATES = ("70-tools/71-verify-manifest.json", "scripts/verify_manifest.json",
                       "scripts/71-verify-manifest.json")
RUN_TIMEOUT = 300


class EncodingProblem(Exception):
    """文本产物无法严格按 UTF-8 解码（或解码后含替换字符 U+FFFD）。

    A2（2026-10-07 审查）：read_text 曾用 errors="replace"，GBK 正文里的中文 forbid
    标记被替换字符吞掉，FAIL 翻 PASS；故文本产物一律严格解码，异常/替换字符归 rc=2。
    """


class DuplicateKeyError(Exception):
    """manifest / 产物 JSON 出现重复键（A3/F-2，2026-10-07 审查）。

    json 默认 last-wins，重复的 task id / 条目键会让前一条判定被静默吞掉
    （实测 rc=0）；object_pairs_hook 检出后归 rc=2 并点名键名。
    """


class ShapeProblem(Exception):
    """产物/IO 形态问题（B03，round3）：如 files[].path 指向目录、read_text OSError。

    与 EncodingProblem 同类——归 rc=2（用法/输入面），不得并入 FAIL(1)，也不得裸 traceback。
    """


def _reject_dup_keys(pairs):
    """object_pairs_hook：任意层级重复键即抛 DuplicateKeyError（A3 / F-2）。

    A3 只护清单真源；F-2 起 check_json 读**产物** JSON 也走本 hook——产物面
    不再走默认 last-wins（此前重复 refs 键被静默吞掉、断言视形态或假绿或首键缺失）。
    """
    seen: dict = {}
    for k, v in pairs:
        if k in seen:
            raise DuplicateKeyError(k)
        seen[k] = v
    return seen


def resolve_manifest(explicit: str | None) -> pathlib.Path | None:
    if explicit:
        p = pathlib.Path(explicit)
        return p if p.is_absolute() else (ROOT / p)
    for rel in MANIFEST_CANDIDATES:
        p = ROOT / rel
        if p.exists():
            return p
    return None


def read_text(p: pathlib.Path, rel: object = None) -> str:
    # utf-8-sig：产物带 BOM 时剥掉之（否则 \ufeff 残留会影响首行 marker 与 word_count）。
    # A2（2026-10-07 审查）：文本产物改**严格 UTF-8 解码**——曾用 errors="replace"，
    # GBK 正文里的中文 forbid 标记被替换字符吞掉 → FAIL 翻 PASS（实测 GBK rc=0 /
    # UTF-8 rc=1）。非 UTF-8 或解码结果含 U+FFFD 一律抛 EncodingProblem，由 main 归 rc=2。
    where = rel if isinstance(rel, str) else str(p)
    try:
        text = p.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError as exc:
        raise EncodingProblem(
            f"{where}: 非 UTF-8 编码（{exc}）— 产物口径为 UTF-8，严格解码失败，"
            "不得退化为替换字符后按空/残缺文本判 PASS") from exc
    except OSError as exc:
        # B03（round3 G-3）：IO/权限错误归 rc=2（用法面），不裸 traceback。
        raise ShapeProblem(f"{where}: 无法读取（{exc}）——IO/权限问题，归 rc=2") from exc
    if "\ufffd" in text:
        raise EncodingProblem(
            f"{where}: 解码结果含替换字符 U+FFFD — 疑似非 UTF-8 产物混入，"
            "不得判 PASS（替换字符会吞掉 forbid/contains 标记）")
    if "\x00" in text:
        # B03（round3 G-4）：纯 ASCII 的 UTF-16LE/UCS 无 BOM 字节流是合法 UTF-8（交织 NUL、
        # 无 U+FFFD）→ forbid/contains 失明。含 NUL 一律归 rc=2 点名「疑 UTF-16/UCS 产物」。
        raise EncodingProblem(
            f"{where}: 解码结果含 NUL(\\x00) — 疑 UTF-16/UCS 产物被当 UTF-8 读入，"
            "不得判 PASS（交织 NUL 会让 forbid/contains 失明）")
    return text


def count_distinct_value(text: str, pattern: str, scope: str) -> int:
    """唯一匹配计数（F18 count_distinct）：同一匹配串 / 同一行重复 N 次只计 1。

    - ``scope="line"``：数**唯一匹配行**数（逐行 search，行文本去重）——抗“整列同值填充”；
    - ``scope="all"``：数**唯一匹配串**数（取 ``group(0)`` 去重）——抗“同图号复制”。

    与 min_matches（``re.findall`` 计**总次数**）互补：填充式凑数在 min_matches 下过检，
    在本原语下变红。scope 取值域由形态档（_knob_problems）保证；此处按缺省 line 兜底。
    """
    if scope == "all":
        return len({m.group(0) for m in re.finditer(pattern, text, flags=re.M)})
    return len({ln for ln in text.splitlines() if re.search(pattern, ln, flags=re.M)})


def _norm_ws(s: str) -> str:
    """B03（round3 G-1）：空白归一（半角空白/制表/换行/全角空格 U+3000）——forbid/contains 判前多判之一（折叠式）。"""
    return re.sub(r"[\s\u3000]+", " ", s)


_CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\u3040-\u30ff\uac00-\ud7af]")


def _has_cjk(s: str) -> bool:
    """R5（round4 R4-3）：needle 是否含 CJK 字符——全剥空白分支只对这类 needle 开放。"""
    return _CJK_RE.search(s) is not None


def _strip_ws(s: str) -> str:
    """R5（round4 R4-3）：全剥空白——中文连写 needle 无空格可插，折叠式对此失明
    （如 forbid“需作者确认”对正文“需作者\\u3000确认”旧判 rc=0）。"""
    return re.sub(r"[\s\u3000]+", "", s)


def _forbid_hit(mtext: str, norm: str, stripped: str, needle: str) -> bool:
    """R5 三判：原文命中 / 折叠式命中 /（CJK needle 才走）全剥式命中。

    全剥分支按 needle 含 CJK 门控：英文 needle（如“DATA SET”）永不进剥式——
    否则合法连写词（DATASET）会被误杀。英文词组的不误伤由该门控结构性保证，
    其行为与旧双判逐字一致（零回归）；中文连写拆词（半角/全角/换行均属 \\s 类）
    一律落入剥式。needle 同步走对应两式归一（_norm_ws / _strip_ws），单一真源。
    """
    if needle in mtext or needle in norm:
        return True
    return _has_cjk(needle) and _strip_ws(needle) in stripped


def _contains_hit(mtext: str, norm: str, stripped: str, needle: str) -> bool:
    """R5 三判之 contains 侧：与 _forbid_hit 同门控对称（缺一即判缺失）。"""
    if needle in mtext or needle in norm:
        return True
    return _has_cjk(needle) and _strip_ws(needle) in stripped


_FENCE_MARKS = ("```", "~~~")   # 与 40 号 FENCE_MARKS 同值（围栏认法同实现，见 count_body_lines）
# B14（G-13）：正则输入预算——单行超 32KB 走截断（标准库 re，不引入第三方引擎）；
# manifest 自带模式作用于超长退化行时不断言尾部命中，只保证不卡死。字数统计仍走全文。
REGEX_LINE_BUDGET = 32 * 1024


def _budget_line(s):
    """单行超预算即截断（B14 G-13）。短行原样返回，零开销。行号/行数不受影响。"""
    return s if len(s) <= REGEX_LINE_BUDGET else s[:REGEX_LINE_BUDGET]
# 图注行按 45 号检查②的图注口径：行首 Fig./Figure/Table/图/表 + 数字 + 紧跟分隔符。
# 数字后无分隔符（`表 1 不同温度……`）只算提及、不算图注（与 45 号边界一致，方向危险）。
_CAPTION_RE = re.compile(r"^(?:Fig\.|Figure|Figs\.?|Table|Tab\.?|图|表)\s*\d+\s*"
                         r"(?:[.:\-–—)：)\]]|\s*$)")
_LEAD_MARKS_RE = re.compile(r"^[\s#*>+\-]+")   # 图注判定前剥掉的前导标记（标题/加粗/引用/列表符）


def count_body_lines(text: str) -> int:
    """B10（A-14）：正文行计数——跳过空行/纯表格行/图注行/代码围栏行后剩下的行数。

    行类认法与 40 号 `_line_kinds` 同实现：围栏标记行缩进≤3、闭合须与开启同种标记
    （未闭合则其后至文末全算围栏内——少计只会把 FAIL 判出来，不会假 PASS）；
    纯表格行 = strip 后行首 `|`；图注行见 _CAPTION_RE（45 号图注口径）。
    中文口径：中英文一律按行计数（中文无空白分词，不做逐字/按空白切词换算），
    每行非空正文计 1。78 号正反控制沙箱复用本函数（单一真源，不另抄一份）。
    """
    n, open_mark = 0, None
    for ln in text.splitlines():
        s = ln.strip()
        mark = None
        if len(ln) - len(ln.lstrip()) <= 3 and s.startswith(_FENCE_MARKS):
            mark = s[0]
        if open_mark is not None:
            if mark == open_mark:
                open_mark = None      # 闭合标记行：围栏行，不计
            continue                  # 围栏内行一律不计
        if mark is not None:
            open_mark = mark          # 开启标记行：围栏行，不计
            continue
        if not s:
            continue                  # 空行
        if s.startswith("|"):
            continue                  # 纯表格行
        if _CAPTION_RE.search(_LEAD_MARKS_RE.sub("", ln)):
            continue                  # 图注行
        n += 1
    return n


def check_file(f: dict, errs: list, oks: list) -> None:
    rel = f["path"]
    p = ROOT / rel
    if not p.exists():
        errs.append(f"missing file: {rel}")
        return
    if not p.is_file():
        # B03（round3 G-3）：目录被当产物——旧版只带 min_bytes 时 rc=0「file ok」，
        # 带 contains 时 PermissionError 裸 traceback。归 rc=2（用法面，非 FAIL）。
        raise ShapeProblem(f"{rel}: 验收对象是目录而非文件（files[].path 须指向文件）")
    size = p.stat().st_size
    if "min_bytes" in f and size < f["min_bytes"]:
        errs.append(f"{rel}: {size}B < min {f['min_bytes']}B")
    needs_text = any(k in f for k in ("contains", "forbid", "contains_regex", "forbid_regex",
                                      "min_matches", "count_distinct", "declare_and_count",
                                      "word_count"))
    text = read_text(p, rel) if needs_text else ""
    # B14 输入预算：用户模式（含 manifest 自带正则）只作用于截断后的行——超长退化行
    # 不断言尾部命中，只保证不卡死；word_count 仍走全文（截断不断行，行数口径不变）。
    mtext = "\n".join(_budget_line(ln) for ln in text.splitlines())
    norm = _norm_ws(mtext)               # B03：空白归一折叠式（G-1；换行/制表/全角空格拆词即隐身）
    stripped = _strip_ws(mtext)          # R5：全剥式（R4-3；中文连写拆词即隐身）
    for needle in f.get("contains", []):
        if not _contains_hit(mtext, norm, stripped, needle):
            errs.append(f"{rel}: missing marker {needle!r}")
    for needle in f.get("forbid", []):
        if _forbid_hit(mtext, norm, stripped, needle):
            errs.append(f"{rel}: forbidden marker {needle!r} present")
    for pat in f.get("contains_regex", []):
        if not re.search(pat, mtext, flags=re.M):
            errs.append(f"{rel}: regex not matched {pat!r}")
    for pat in f.get("forbid_regex", []):
        if re.search(pat, mtext, flags=re.M):
            errs.append(f"{rel}: forbidden regex matched {pat!r}")
    if "min_matches" in f:
        mm = f["min_matches"]
        n = len(re.findall(mm["pattern"], mtext, flags=re.M))
        if n < mm["min"]:
            errs.append(f"{rel}: {n} matches of {mm['pattern']!r} < min {mm['min']}")
    if "count_distinct" in f:
        cd = f["count_distinct"]
        scope = cd.get("scope") or "line"
        n = count_distinct_value(mtext, cd["pattern"], scope)
        if n < cd["min"]:
            errs.append(f"{rel}: {n} distinct {scope} matches of {cd['pattern']!r} "
                        f"< min {cd['min']}")
    if "declare_and_count" in f:
        # B07（round3 A-6）：声明与计数绑死。形态档已保证两键齐、可编译、declare_regex 含捕获组。
        # 声明数取**第一处** declare_regex 命中（多声明行时只核第一处）。
        dc = f["declare_and_count"]
        actual = len(re.findall(dc["pattern"], mtext, flags=re.M))
        m = re.search(dc["declare_regex"], mtext, flags=re.M)
        if m is None:
            errs.append(f"{rel}: declare_and_count 未命中声明行（declare_regex="
                        f"{dc['declare_regex']!r}）——声明与计数绑死，缺声明行不得判 PASS")
        else:
            try:
                declared = int(m.group(1))
            except (TypeError, ValueError):
                # 可编译但捕获组未捕获到整数（如 `共 abc 条`、可选组未命中）——不得裸 traceback
                # 冒充；判 FAIL(1) 并回显捕获值（声明未绑死，不能判 PASS）。
                errs.append(f"{rel}: declare_and_count 的声明数无法解析为整数"
                            f"（declare_regex={dc['declare_regex']!r} 捕获到 "
                            f"{m.group(1)!r}）——声明未绑死，不得判 PASS")
            else:
                if actual != declared:
                    errs.append(f"{rel}: declared {declared} != actual {actual} "
                                f"(pattern={dc['pattern']!r})")
    if f.get("word_count"):
        lo, hi = f["word_count"]
        n = count_body_lines(text)
        if not (lo <= n <= hi):
            errs.append(f"{rel}: body lines {n} outside [{lo},{hi}]"
                        "（正文行计数：已跳过空行/纯表格行/图注行/代码围栏行）")
    oks.append(f"file ok: {rel} ({size}B)")


_MISSING = object()   # require_values：区分「键缺失」与「键值恰为 None」


def check_json(j: dict, errs: list, oks: list) -> None:
    rel = j["path"]
    p = ROOT / rel
    if not p.exists():
        errs.append(f"missing json: {rel}")
        return
    text = read_text(p, rel)            # EncodingProblem 上抛 → main 归 rc=2（不得并入 FAIL）
    try:
        # F-2（2026-10-07 二轮）：产物 JSON 也走重复键检出——默认 last-wins 会静默
        # 吞掉重复的 refs/条目键（实测 §A3 同族）。检出即上抛，main 归 rc=2 点名。
        data = json.loads(text, object_pairs_hook=_reject_dup_keys)
    except DuplicateKeyError as exc:
        raise DuplicateKeyError(f"{rel}: 产物 JSON 含重复键 {str(exc)!r}"
                                "（last-wins 会静默吞掉前一条判定）") from exc
    except Exception as exc:                                  # noqa: BLE001 — 报告原始错误
        errs.append(f"{rel}: invalid JSON: {exc}")
        return
    if not isinstance(data, (dict, list)):
        # 顶层是标量（JSON `5` / "str" / null）：长度与逐条键检查都没有意义，
        # 曾在 len(data) 处 TypeError 裸崩（N-2 同族：形态尾巴不许 traceback 冒充 FAIL）。
        errs.append(f"{rel}: JSON 顶层必须是数组或对象，实为 {type(data).__name__}"
                    "（产物形态问题，非 manifest 写法问题）")
        return
    if "min_items" in j and len(data) < j["min_items"]:
        errs.append(f"{rel}: {len(data)} items < min {j['min_items']}")
    if "max_items" in j and len(data) > j["max_items"]:
        errs.append(f"{rel}: {len(data)} items > max {j['max_items']}")
    if isinstance(data, dict):
        # dict 顶层：require_keys / require_keys_all 都按"该 dict 是否含此键"检查，
        # 不再静默跳过（曾因静默跳过导致 manifest 配错也 PASS）。
        for key in j.get("require_keys", []) + j.get("require_keys_all", []):
            if key not in data:
                errs.append(f"{rel}: dict missing key {key!r}")
        # B06a：require_values 对对象顶层逐键比对（缺失按不符处理）。
        for key, want_v in (j.get("require_values") or {}).items():
            got_v = data.get(key, _MISSING)
            if got_v != want_v:
                errs.append(f"{rel}: dict 的 {key!r} 应为 {want_v!r}，实为 "
                            f"{'<missing>' if got_v is _MISSING else repr(got_v)}")
    else:
        # N-3：曾写作 `elif isinstance(data, list) and data`，空列表整段跳过，
        # "每条都含 doi"这类 AC 在 0 条产物上恒真 → rc=0 静默放行（全仓唯一真 fail-open）。
        want = (list(j.get("require_keys") or []) + list(j.get("require_keys_all") or [])
                + list(j.get("require_values") or {}))
        if not data and want and not j.get("min_items"):
            errs.append(f"{rel}: 空列表但配了 require_keys*/require_values"
                        f"（{'、'.join(repr(k) for k in want)}）— 逐条键/值检查 0 条恒真（空转），"
                        "请补 min_items≥1 或删去键/值要求")
        # F-2（2026-09-29 审查）：首元素不一定是对象——朴素 `key not in data[0]` 对标量
        # TypeError 裸崩（rc=1 冒充 FAIL）、对 str 退化为子串判定（rc=0 假 PASS），
        # 与 N-2/N-3 同族。逐条键检查对非对象元素无意义，判 FAIL 并点明实际类型
        # （与下方 require_keys_all 的 isinstance 防御同口径）。
        req_first = list(j.get("require_keys") or [])
        if data and req_first and not isinstance(data[0], dict):
            errs.append(f"{rel}: first item is not an object (actual type "
                        f"{type(data[0]).__name__}) — require_keys 检查第 1 项键在此无意义，"
                        "请修正产物形态（列表元素应为对象）")
        else:
            for key in req_first:
                if data and key not in data[0]:
                    errs.append(f"{rel}: first item missing key {key!r}")
        for key in j.get("require_keys_all", []):
            bad = [i for i, it in enumerate(data) if not isinstance(it, dict) or key not in it]
            if bad:
                errs.append(f"{rel}: {len(bad)} item(s) missing key {key!r} "
                            f"(first at index {bad[0]})")
        # B06a：require_values 逐条硬口径（每个元素都必须等值；非对象元素计入失败）。
        for key, want_v in (j.get("require_values") or {}).items():
            bad = [i for i, it in enumerate(data)
                   if not isinstance(it, dict) or it.get(key, _MISSING) != want_v]
            if bad:
                i0 = bad[0]
                it0 = data[i0]
                got_v = it0.get(key, _MISSING) if isinstance(it0, dict) else "<non-object>"
                errs.append(f"{rel}: {len(bad)} item(s) 的 {key!r} 应为 {want_v!r} "
                            f"(first at index {i0}, actual "
                            f"{'<missing>' if got_v is _MISSING else repr(got_v)})")
    oks.append(f"json ok: {rel}")


def check_glob(g: dict, errs: list, oks: list) -> None:
    hits = [x for x in _glob.glob(str(ROOT / g["pattern"]), recursive=True)
            if pathlib.Path(x).is_file()]
    if "min_count" in g and len(hits) < g["min_count"]:
        errs.append(f"glob {g['pattern']}: {len(hits)} < min {g['min_count']}")
    if "min_bytes_each" in g:
        for h in hits:
            if pathlib.Path(h).stat().st_size < g["min_bytes_each"]:
                errs.append(f"glob {g['pattern']}: {h} smaller than {g['min_bytes_each']}B")
    oks.append(f"glob ok: {g['pattern']} ({len(hits)} files)")


def run_spec(spec: dict, errs: list, oks: list) -> None:
    for rel in spec.get("absent_paths") or []:
        if (ROOT / rel).exists():
            errs.append(f"path must not exist: {rel}")
        else:
            oks.append(f"absent ok: {rel}")
    if spec.get("run"):
        try:
            # B03（round3 B-3）：run 子进程解码改 UTF-8→GBK 回退——cp936 工具产出的中文诊断
            # 在 errors="replace" 下变 mojibake（判定只看 rc 故非假绿，但不可诊断）。
            r = subprocess.run(spec["run"], shell=True, cwd=str(ROOT),
                               capture_output=True, timeout=RUN_TIMEOUT)
        except subprocess.TimeoutExpired:
            errs.append(f"run timed out after {RUN_TIMEOUT}s: {spec['run']}")
            return

        def _decode(b) -> str:
            b = b or b""
            try:
                return b.decode("utf-8")
            except UnicodeDecodeError:
                return b.decode("gbk", errors="replace")

        out, serr = _decode(r.stdout), _decode(r.stderr)
        if out:
            print(out.rstrip())
        if r.returncode != 0:
            errs.append(f"run failed ({r.returncode}): {spec['run']}\n{serr}")
        else:
            oks.append(f"run ok: {spec['run']}")


SEGMENT_REQUIRED = (("files", "path"), ("json_files", "path"), ("globs", "pattern"))
# 段内可选项的类型口径：写错类型会在比较处 TypeError 裸崩（`len(data) < "20"`），
# 与 N-2 同族，故一并纳入形态自检。
SEGMENT_TYPED = {
    "files": {"min_bytes": int, "min_matches": dict, "count_distinct": dict,
              "declare_and_count": dict,
              "word_count": list,
              "contains": list, "forbid": list, "contains_regex": list, "forbid_regex": list},
    "json_files": {"min_items": int, "max_items": int,
                   "require_keys": list, "require_keys_all": list, "require_values": dict},
    "globs": {"min_count": int, "min_bytes_each": int},
}

# F4：合法键全集（键即契约）。条目级未知键曾被视为空段静默 PASS（file 少个 s 即空验收）；
# token_source 是 78 号出处守卫的合法标注键，70-verify 自身不消费但不拒绝。
# G-17（2026-10-07 审查）：globs 与 files 的 token_source 口径二选一，选「globs 也进白名单」
# （弃另一选项——files/json_files 的 token_source 同样 rc=2——理由：在盘 87 处标注全在
# files/json_files，白名单移除会使全部形状违规并掏空 78 号守卫，属破坏性收紧）。
# 78 号侧把 globs 纳入 TOKEN_SOURCE_SEGS：globs 条目无字面词项，带 token_source 即判冗余标注
# （与无词项 files 条目同口径），不带则放行——形状层与出处层口径一致，无 [d] 接受差异。
_ENTRY_KEYS = {"files", "json_files", "globs", "absent_paths", "run"}
_ITEM_KNOWN = {seg: {req} | set(SEGMENT_TYPED[seg]) for seg, req in SEGMENT_REQUIRED}
_ITEM_KNOWN["files"].add("token_source")
_ITEM_KNOWN["json_files"].add("token_source")
_ITEM_KNOWN["globs"].add("token_source")  # G-17：globs 也进白名单（执行层 check_glob 本就忽略多余键）


# F18：count_distinct 的嵌套键集合——「键即契约」在嵌套层同样成立（scope 拼成 scopes
# 会静默按缺省 line 判定，属拼写错误等效静默降级）。min_matches 的嵌套键保持宽松，
# 因为 70-verify 被 vendor 进论文项目、存量 frozen manifest 不得因收紧而变 rc=2。
_COUNT_DISTINCT_KEYS = frozenset({"pattern", "min", "scope"})


def _type_bad(val: object, want: type) -> bool:
    if want is int:
        return not isinstance(val, int) or isinstance(val, bool)   # True 不是计数下限
    return not isinstance(val, want)


# 内容必须是字符串的数组型可选项（正则类还要能编译）。
SEGMENT_STR_LISTS = {"files": ("contains", "forbid", "contains_regex", "forbid_regex"),
                     "json_files": ("require_keys", "require_keys_all")}


def _knob_problems(task_id: str, seg: str, i: int, it: dict) -> list:
    """段内可选项的**内部**形态（外层类型由 SEGMENT_TYPED 把关，这里管键齐不齐、元素类型）。

    这里每一条都是历史上会以 KeyError / TypeError / re.error 收场的地方：`min_matches` 少
    `min`、`word_count` 不是两元整数、定位键写成数字、字符串数组里混进数字、正则写坏。
    """
    where = f"任务 {task_id}: {seg}[{i}]"
    probs: list[str] = []
    req = dict(SEGMENT_REQUIRED)[seg]
    if req in it and not isinstance(it[req], str):
        probs.append(f"{where} 的定位键 {req!r} 必须是字符串，实为 {type(it[req]).__name__}")
    elif isinstance(it.get(req), str):
        # A4：files/json_files 的 path 与 globs 的 pattern 都不得越界（绝对路径 / '..'）。
        probs += path_problems(f"{where} 的定位键 {req!r}", it[req])
        if req == "path":
            _p = ROOT / it[req]
            if _p.exists() and not _p.is_file():
                probs.append(f"{where} 的 {req}={it[req]!r} 指向目录而非文件"
                             "（验收对象须是文件——目录形态归 rc=2）")
    mm = it.get("min_matches")
    if isinstance(mm, dict):
        if "pattern" not in mm or "min" not in mm:
            probs.append(f"{where} 的 min_matches 须同时含 pattern 与 min"
                         f"（已有键：{sorted(mm) or '无'}）")
        else:
            if _type_bad(mm["pattern"], str):
                probs.append(f"{where} 的 min_matches['pattern'] 必须是 str，"
                             f"实为 {type(mm['pattern']).__name__}")
            else:
                try:
                    re.compile(mm["pattern"])
                except re.error as exc:
                    probs.append(f"{where} 的 min_matches['pattern'] 不是合法正则"
                                 f"（{exc}）：{mm['pattern']!r}")
            if _type_bad(mm["min"], int):
                probs.append(f"{where} 的 min_matches['min'] 必须是 int，"
                             f"实为 {type(mm['min']).__name__}")
            elif mm["min"] < 1:
                probs.append(f"{where} 的 min_matches['min'] 必须 ≥1"
                             "（min:0 是空断言，形态错——与 78 号阈值同一真源）")
    cd = it.get("count_distinct")
    if isinstance(cd, dict):
        unknown = sorted(set(cd) - _COUNT_DISTINCT_KEYS)
        if unknown:
            probs.append(f"{where} 的 count_distinct 含未知键 {unknown}"
                         f"（键即契约：合法键为 {sorted(_COUNT_DISTINCT_KEYS)}）")
        if "pattern" not in cd or "min" not in cd:
            probs.append(f"{where} 的 count_distinct 须同时含 pattern 与 min"
                         f"（已有键：{sorted(cd) or '无'}）")
        else:
            if _type_bad(cd["pattern"], str):
                probs.append(f"{where} 的 count_distinct['pattern'] 必须是 str，"
                             f"实为 {type(cd['pattern']).__name__}")
            else:
                try:
                    re.compile(cd["pattern"])
                except re.error as exc:
                    probs.append(f"{where} 的 count_distinct['pattern'] 不是合法正则"
                                 f"（{exc}）：{cd['pattern']!r}")
            if _type_bad(cd["min"], int):
                probs.append(f"{where} 的 count_distinct['min'] 必须是 int，"
                             f"实为 {type(cd['min']).__name__}")
            elif cd["min"] < 1:
                probs.append(f"{where} 的 count_distinct['min'] 必须 ≥1（min:0 是空断言，形态错）")
        if "scope" in cd and cd["scope"] not in ("line", "all"):
            probs.append(f"{where} 的 count_distinct['scope'] 只接受 'line' 或 'all'，"
                         f"实为 {cd['scope']!r}")
    dc = it.get("declare_and_count")
    if isinstance(dc, dict):
        unknown = sorted(set(dc) - {"pattern", "declare_regex"})
        if unknown:
            probs.append(f"{where} 的 declare_and_count 含未知键 {unknown}"
                         f"（合法键为 pattern/declare_regex）")
        if "pattern" not in dc or "declare_regex" not in dc:
            probs.append(f"{where} 的 declare_and_count 须同时含 pattern 与 declare_regex"
                         f"（已有键：{sorted(dc) or '无'}）")
        else:
            if _type_bad(dc["pattern"], str):
                probs.append(f"{where} 的 declare_and_count['pattern'] 必须是 str，"
                             f"实为 {type(dc['pattern']).__name__}")
            else:
                try:
                    re.compile(dc["pattern"])
                except re.error as exc:
                    probs.append(f"{where} 的 declare_and_count['pattern'] 不是合法正则"
                                 f"（{exc}）：{dc['pattern']!r}")
            if _type_bad(dc["declare_regex"], str):
                probs.append(f"{where} 的 declare_and_count['declare_regex'] 必须是 str，"
                             f"实为 {type(dc['declare_regex']).__name__}")
            else:
                try:
                    cre = re.compile(dc["declare_regex"])
                except re.error as exc:
                    probs.append(f"{where} 的 declare_and_count['declare_regex'] 不是合法正则"
                                 f"（{exc}）：{dc['declare_regex']!r}")
                else:
                    if cre.groups < 1:
                        probs.append(f"{where} 的 declare_and_count['declare_regex'] 必须含"
                                     "至少一个捕获组（用于解析声明数 N）")
    wc = it.get("word_count")
    if isinstance(wc, list):
        if len(wc) != 2 or any(_type_bad(x, int) for x in wc):
            probs.append(f"{where} 的 word_count 必须是 [lo, hi] 两个整数，实为 "
                         f"{[type(x).__name__ for x in wc]}（{len(wc)} 元）")
    for key in SEGMENT_STR_LISTS.get(seg, ()):
        val = it.get(key)
        if not isinstance(val, list):
            continue
        if not val:                     # B03：键在值空即形态错（空列表=空断言，恒真）
            probs.append(f"{where} 的 {key} 是空列表——键在值空即形态错（空断言恒真）")
            continue
        for n, x in enumerate(val):
            if not isinstance(x, str):
                probs.append(f"{where} 的 {key}[{n}] 必须是字符串，实为 {type(x).__name__}")
            elif not x:                 # B03：needle 非空串
                probs.append(f"{where} 的 {key}[{n}] 是空串——needle 不得为空")
            elif key.endswith("regex"):
                try:
                    re.compile(x)
                except re.error as exc:
                    probs.append(f"{where} 的 {key}[{n}] 不是合法正则（{exc}）：{x!r}")
    # B03（round3 F-1）：globs 须配 min_count 或 min_bytes_each 之一（零命中无门槛=空转）。
    if seg == "globs" and not ("min_count" in it or "min_bytes_each" in it):
        probs.append(f"{where} 的 globs 须配 min_count 或 min_bytes_each 之一"
                     "（否则零命中静默通过=空转）")
    # B03（round3 F-1）：json_files 的 min_items 若写了必须 ≥1。
    if seg == "json_files" and "min_items" in it and not _type_bad(it["min_items"], int) \
            and it["min_items"] < 1:
        probs.append(f"{where} 的 min_items 必须 ≥1（min:0 是空断言，形态错）")
    # B06a（round3）：require_values 值判定原语——键在值空 / 值为容器即形态错
    # （外层非对象由 SEGMENT_TYPED 拦；这里管对象内部）。
    if seg == "json_files":
        rv = it.get("require_values")
        if isinstance(rv, dict):
            if not rv:
                probs.append(f"{where} 的 require_values 是空对象——键在值空即形态错（空断言恒真）")
            for k, v in rv.items():
                if not isinstance(k, str) or not k:
                    probs.append(f"{where} 的 require_values 键必须是非空字符串，实为 {k!r}")
                if isinstance(v, (dict, list)):
                    probs.append(f"{where} 的 require_values[{k!r}] 只接受标量"
                                 f"（布尔/字符串/数字/null），实为 {type(v).__name__}")
    return probs


def path_problems(label: str, rel: str) -> list:
    """A4（2026-10-07 审查）：验收对象必须落在**项目根内**——绝对路径 / 盘符 / '..' 段一律 rc=2。

    `path`/`pattern` 以 ROOT 为基准解析，但历史上不校验：`../x.md` 与绝对路径被照单
    验收（实测均 rc=0），检查的其实是项目根外的文件。定位键类型写错仍由既有口径报。
    """
    pp = pathlib.PurePath(rel)
    if pp.is_absolute():
        return [f"{label} 不得是绝对路径（验收对象须在项目根内）：{rel!r}"]
    if pp.drive:
        return [f"{label} 不得带盘符/UNC 前缀（验收对象须在项目根内）：{rel!r}"]
    if ".." in pp.parts:
        return [f"{label} 不得含 '..' 路径段（会跑到项目根外）：{rel!r}"]
    return []


def shape_problems(task_id: str, spec: object) -> list:
    """manifest 条目形态自检（N-2）。返回人可读的问题列表（空 = 形态合）。

    只判形态（值类型与该段定位键），不判断言内容：内容未达是 FAIL(1)，形态不合是用法错(2)。
    段值写 null 等同省略该段（与"四段全空 = 空验收"的既有口径一致，不额外收紧）。
    """
    if not isinstance(spec, dict):
        return [f"任务 {task_id}: 条目值必须是对象，实为 {type(spec).__name__}"]
    probs: list[str] = []
    unknown = set(spec) - _ENTRY_KEYS
    if unknown:
        probs.append(f"任务 {task_id}: 条目含未知键 {sorted(unknown)}（键即契约：合法键为 "
                     f"{sorted(_ENTRY_KEYS)}；拼错的段会被静默忽略成空验收）")
    for seg, req in SEGMENT_REQUIRED:
        items = spec.get(seg)
        if items is None:
            continue                                   # 显式写 null 等同省略该段
        if not isinstance(items, list):
            probs.append(f"任务 {task_id}: 段 {seg} 必须是数组，实为 {type(items).__name__}")
            continue
        for i, it in enumerate(items):
            if not isinstance(it, dict):
                probs.append(f"任务 {task_id}: {seg}[{i}] 必须是对象，实为 {type(it).__name__}")
                continue
            if req not in it:
                probs.append(f"任务 {task_id}: {seg}[{i}] 缺定位键 {req!r}"
                             f"（已有键：{sorted(it) or '无'}）")
            item_unknown = set(it) - _ITEM_KNOWN[seg]
            if item_unknown:
                probs.append(f"任务 {task_id}: {seg}[{i}] 含未知键 {sorted(item_unknown)}"
                             f"（键即契约：合法键为 {sorted(_ITEM_KNOWN[seg])}）")
            for k, want in SEGMENT_TYPED[seg].items():
                if k in it and _type_bad(it[k], want):
                    # 值为 null 也算形态错（YAML 里 `min_bytes:` 空值 = None → 比较处会 TypeError），
                    # 与"段值 null 等同省略"刻意不同：省略整段是有意的，写半个键是笔误。
                    probs.append(f"任务 {task_id}: {seg}[{i}] 的 {k!r} 必须是 "
                                 f"{want.__name__}，实为 {type(it[k]).__name__}")
            probs += _knob_problems(task_id, seg, i, it)
    absent = spec.get("absent_paths")
    if absent is not None:
        if not isinstance(absent, list):
            probs.append(f"任务 {task_id}: 段 absent_paths 必须是字符串数组，"
                         f"实为 {type(absent).__name__}")
        else:
            for i, rel in enumerate(absent):
                if not isinstance(rel, str):
                    probs.append(f"任务 {task_id}: absent_paths[{i}] 必须是字符串路径，"
                                 f"实为 {type(rel).__name__}")
                else:
                    probs += path_problems(f"任务 {task_id}: absent_paths[{i}]", rel)
    run = spec.get("run")
    if run is not None and not isinstance(run, str):
        probs.append(f"任务 {task_id}: run 必须是字符串命令，实为 {type(run).__name__}")
    return probs


def verify_task(spec: dict, quiet: bool = False) -> tuple[int, list, list]:
    errs: list[str] = []
    oks: list[str] = []
    for f in spec.get("files") or []:
        check_file(f, errs, oks)
    for j in spec.get("json_files") or []:
        check_json(j, errs, oks)
    for g in spec.get("globs") or []:
        check_glob(g, errs, oks)
    run_spec(spec, errs, oks)
    if not quiet:
        for o in oks:
            print("[ok]", o)
    return (1 if errs else 0), errs, oks


SCHEMA_HELP = __doc__.split("# 断言 schema", 1)[1].strip() if "# 断言 schema" in __doc__ else ""


def main() -> int:
    ap = argparse.ArgumentParser(description="论文任务判据基座（manifest 驱动）")
    ap.add_argument("task_id", nargs="?", default="")
    ap.add_argument("--manifest", help="manifest 路径（默认按约定自动查找）")
    ap.add_argument("--root", help="项目根（默认=本脚本上级目录；供审查/回归对别的项目运行）")
    ap.add_argument("--all", action="store_true", help="校验 manifest 中全部任务")
    ap.add_argument("--json", action="store_true", help="以 JSON 输出判定（供脚本解析）")
    ap.add_argument("--quiet", action="store_true", help="不打印 [ok] 明细")
    ap.add_argument("--schema", action="store_true", help="打印断言 schema")
    ap.add_argument("--list", action="store_true", help="列出 manifest 中的任务")
    a = ap.parse_args()

    if a.schema:
        print(SCHEMA_HELP)
        return 0

    if a.root:
        global ROOT
        # B14（G-14）：--root 须指向已存在的目录——不存在或指文件一律 rc=2 并点名，
        # 不得落成含糊的 "manifest not found"（旧口径信息指错方向，难诊断）。
        _rp = pathlib.Path(a.root)
        if not _rp.exists():
            print("[verify] --root 不存在：%s（须指向已存在的项目根目录）" % a.root)
            return 2
        if not _rp.is_dir():
            print("[verify] --root 须是目录而非文件：%s" % a.root)
            return 2
        ROOT = _rp.resolve()

    mp = resolve_manifest(a.manifest)
    if mp is None or not mp.exists():
        if a.manifest:
            # N-5：只报 "not found" 无法区分「相对谁解析」，故同回原值与解析结果。
            print("[verify] manifest not found: --manifest %r → %s（相对路径以 --root 为基准；"
                  "当前 --root=%s；不带 --manifest 时才试候选 %s）"
                  % (a.manifest, mp, ROOT, "、".join(MANIFEST_CANDIDATES)))
        else:
            print("[verify] manifest not found（试过 %s；--root=%s）"
                  % ("、".join("%s" % (ROOT / c) for c in MANIFEST_CANDIDATES), ROOT))
        return 2
    try:
        # utf-8-sig 同时兼容无 BOM 与带 BOM 两种形态；带 BOM 曾裸 traceback 且 rc=1
        # 混入 FAIL 语义（审查 B1），现归入 rc=2（manifest 问题）。
        manifest = json.loads(mp.read_text(encoding="utf-8-sig"),
                              object_pairs_hook=_reject_dup_keys)
    except DuplicateKeyError as exc:
        print("[verify] manifest 含重复键 %r: %s（last-wins 会静默吞掉前一条判定，"
              "请去重后再喂）" % (str(exc), mp))
        return 2
    except UnicodeDecodeError as exc:
        print("[verify] manifest 非 UTF-8 编码: %s (%s)" % (mp, exc))
        return 2
    except json.JSONDecodeError as exc:
        print("[verify] manifest invalid JSON: %s (%s)" % (mp, exc))
        return 2
    if not isinstance(manifest, dict):
        # 标量/列表顶层不是任务映射，属 manifest 结构问题（审查 B4：曾在 --all 处
        # TypeError 裸崩、rc=1 混入 FAIL 语义），显式归入 rc=2。
        print("[verify] manifest must be a JSON object of task entries, got %s"
              % type(manifest).__name__)
        return 2
    try:
        print("[verify] manifest:", mp.relative_to(ROOT))
    except ValueError:
        print("[verify] manifest:", mp)

    if a.list:
        for tid in manifest:
            print("  -", tid)
        return 0

    if a.all:
        targets = list(manifest)
        if not targets:
            # 空 manifest 下 --all 会 0 任务静默 PASS（门禁空转，审查 B2），
            # 显式报为 manifest 问题而非放行。
            print("[verify] manifest is empty（无任何任务条目）— 门禁空转 PASS，请先补断言"
                  "（参考 assets/10-verify-manifest.template.json 或 --schema）")
            return 2
        # `_` 前缀键为模板/注释专用（如 assets 模板的 _note），不是任务条目；
        # --all 若枚举它们会 AttributeError 崩溃（审查 B7）。--list 仍如实列出。
        skipped = [tid for tid in targets if tid.startswith("_")]
        if skipped:
            targets = [tid for tid in targets if not tid.startswith("_")]
            print("[verify] 跳过非任务键（_ 前缀）：%s" % "、".join(skipped))
            if not targets:
                print("[verify] manifest 仅含非任务键 — 同属空门禁，请补任务条目断言")
                return 2
    else:
        targets = [a.task_id]
    results = {}
    for tid in targets:
        if tid not in manifest:
            print(f"[verify] no manifest entry for {tid}")
            results[tid] = {"rc": 2, "errors": [f"no manifest entry for {tid}"], "oks": 0}
            continue
        spec = manifest[tid]
        probs = shape_problems(tid, spec)
        if probs:
            # N-2：以前这些形态会在这里以下三种裸崩之一结束（AttributeError / KeyError /
            # TypeError），rc=1 被当成 FAIL，且诊断只剩一行 traceback；现在归 2 并逐条定位。
            print(f"[verify] manifest 形态不合: {tid}")
            for p in probs:
                print("  -", p)
            results[tid] = {"rc": 2, "errors": probs, "oks": 0}
            continue
        try:
            rc, errs, oks = verify_task(spec, quiet=a.quiet)
        except DuplicateKeyError as exc:
            # F-2：产物 JSON 含重复键 → rc=2（写法/输入问题），不得并入 FAIL 语义。
            print(f"\n[verify] 产物 JSON 重复键: {tid}")
            print("  -", exc)
            results[tid] = {"rc": 2, "errors": [str(exc)], "oks": 0}
            continue
        except EncodingProblem as exc:
            # A2：文本产物严格解码失败（非 UTF-8 / 含 U+FFFD / 含 NUL）→ rc=2（产物问题），
            # 不得退化成替换文本后判 PASS，也不得裸 traceback。
            print(f"\n[verify] 产物编码问题: {tid}")
            print("  -", exc)
            results[tid] = {"rc": 2, "errors": [str(exc)], "oks": 0}
            continue
        except ShapeProblem as exc:
            # B03（round3 G-3）：产物形态/IO 问题（目录当文件、读失败）→ rc=2（用法面）。
            print(f"\n[verify] 产物形态问题: {tid}")
            print("  -", exc)
            results[tid] = {"rc": 2, "errors": [str(exc)], "oks": 0}
            continue
        results[tid] = {"rc": rc, "errors": errs, "oks": len(oks)}
        if rc:
            print(f"\n[verify] FAIL: {tid}")
            for e in errs:
                print("  -", e)
        else:
            print(f"\n[verify] PASS: {tid}")

    if a.json:
        print(json.dumps({"manifest": str(mp), "results": results,
                          "pass": sum(1 for r in results.values() if r["rc"] == 0),
                          "fail": sum(1 for r in results.values() if r["rc"] == 1),
                          "usage_error": sum(1 for r in results.values() if r["rc"] == 2)},
                         ensure_ascii=False, indent=2))
    elif a.all:
        ok = sum(1 for r in results.values() if r["rc"] == 0)
        print(f"\n[verify] {ok}/{len(results)} PASS（其余见上）")
    # rc 语义不因批量模式而糊：有真 FAIL → 1（验收未达是首要信号）；
    # 无 FAIL 但有 manifest/用法问题 → 2；全过 → 0。（曾用 max() 合并，
    # FAIL 会被 usage-error 掩盖成 2，2026-09-26 审查修复。）
    if any(r["rc"] == 1 for r in results.values()):
        return 1
    if any(r["rc"] == 2 for r in results.values()):
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
