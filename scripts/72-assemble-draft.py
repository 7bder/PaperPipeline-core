#!/usr/bin/env python3
# -*- coding: utf-8 -*-  # noqa: UP009 — 与既有 45/70 号脚本一致，coding 声明是本仓约定
# vendor-tool: 72-assemble-draft.py version 1
# SPDX-License-Identifier: MIT
"""72-assemble-draft.py — 确定性合稿器（md 单一真源 → 单一 draft 真源）。

按 references/40-draft-to-latex.md §装配链第 1-2 步实现：标题 → 摘要 → 各节 → 图注 →
表 → 参考文献指针 → 待确认项。两项配套能力同批完成：作者确认项**上收为单一清单**
（正文零残留）、术语归一（`wt %` → `wt%`）。

用法：
    python 72-tools/72-assemble-draft.py --order order.json --out 36-draft.md
    python 72-tools/72-assemble-draft.py --order order.json --out 36-draft.md --check
    python 72-tools/72-assemble-draft.py --order order.json --inline '...'
    python 72-tools/72-assemble-draft.py --selftest

退出码：0 = 通过（--check 一致 / 生成成功），1 = 不一致或输入缺失，2 = 用法错误。
确定性：输出**不含时间戳、不含随机、不依赖 set 遍历序**——同输入必得同字节，故 --check 可作
回归门禁（幂等是本工具的存在前提；出稿时间戳会让每次重跑都判"不一致"）。

order.json schema（键全可选，除 sections 至少一项）：
    {"title": "稿件标题",
     "sections":   [{"heading": "1. Introduction", "path": "30-manuscript/…/31-intro.md"}],
     "figures":    [{"number": 1, "caption": "Strength of batch A."}],
     "tables":     [{"number": 1, "caption": "Composition of the batches."}],
     "references_pointer": "20-lit/22-refs.json",
     "todo_pointer": "00-admin/05-todos.md"}

安全：只读 order.json 与被引用节文件；写入仅限 --out 指定的那一个文件。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.dont_write_bytecode = True                            # .pyc 内嵌本机绝对路径，属发布物污染

EXIT_OK, EXIT_FAIL, EXIT_USAGE = 0, 1, 2

# 作者确认项标记：抽出上收，正文零残留。含中英文与 TODO/待核实变体。
MARKER_RE = re.compile(
    r"[ \t]*\[(?:需作者确认|待作者确认|待确认|待核实|TODO|AUTHOR[ \t]+CONFIRM)"
    r"[：:]?[ \t]*([^\]\n]*)\]", re.IGNORECASE)
# 术语归一：只做有把握的单形态（字母/数字 + 可选空白 + %），不做任何同义改写。
TERM_PCT_RE = re.compile(r"(?<=[A-Za-z0-9])[ \t]+%")


class DuplicateKeyError(Exception):
    """order JSON 出现重复键（G-9 形态档，与 70-verify 同口径）。

    json 默认 last-wins 会静默吞掉前一条（实测 title 写两遍只留后者）；
    object_pairs_hook 检出后归 rc=2 并点名键名。
    """


def _reject_dup_keys(pairs):
    """object_pairs_hook：任意层级重复键即抛 DuplicateKeyError。"""
    seen: dict = {}
    for k, v in pairs:
        if k in seen:
            raise DuplicateKeyError(k)
        seen[k] = v
    return seen


# G-9 形态档：键即契约（F4 同口径）。顶层未知键曾被照单接收（bogus_key 静默忽略）。
ORDER_KEYS = frozenset({"title", "sections", "figures", "tables",
                        "references_pointer", "todo_pointer"})
SECTION_KEYS = frozenset({"heading", "path"})
FIG_KEYS = frozenset({"number", "caption"})
TABLE_KEYS = frozenset({"number", "caption"})


def _is_int(v: object) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def order_shape_problems(order: dict) -> list:
    """order 形态自检（G-9）：类型错 / 嵌套未知键一律回问题列表，不抛 traceback。"""
    probs: list = []
    t = order.get("title")
    if "title" in order and t is not None and not isinstance(t, str):
        probs.append(f"order['title'] 必须是字符串，实为 {type(t).__name__}")
    secs = order.get("sections")
    if isinstance(secs, list):
        for i, s in enumerate(secs):
            if not isinstance(s, dict):
                probs.append(f"order.sections[{i}] 必须是对象，实为 {type(s).__name__}")
                continue
            unknown = sorted(set(s) - SECTION_KEYS)
            if unknown:
                probs.append(f"order.sections[{i}] 含未知键 {unknown}"
                             f"（合法键为 {sorted(SECTION_KEYS)}）")
            if "heading" in s and s["heading"] is not None \
                    and not isinstance(s["heading"], str):
                probs.append(f"order.sections[{i}]['heading'] 必须是字符串，"
                             f"实为 {type(s['heading']).__name__}")
            if "path" in s and not isinstance(s["path"], str):
                probs.append(f"order.sections[{i}]['path'] 必须是字符串，"
                             f"实为 {type(s['path']).__name__}")
    for key, item_keys in (("figures", FIG_KEYS), ("tables", TABLE_KEYS)):
        items = order.get(key)
        if items is None:
            continue
        if not isinstance(items, list):
            probs.append(f"order['{key}'] 必须是数组，实为 {type(items).__name__}")
            continue
        for i, it in enumerate(items):
            if not isinstance(it, dict):
                probs.append(f"order.{key}[{i}] 必须是对象，实为 {type(it).__name__}")
                continue
            unknown = sorted(set(it) - item_keys)
            if unknown:
                probs.append(f"order.{key}[{i}] 含未知键 {unknown}"
                             f"（合法键为 {sorted(item_keys)}）")
            if "number" in it and it["number"] is not None and not _is_int(it["number"]):
                probs.append(f"order.{key}[{i}]['number'] 必须是整数，"
                             f"实为 {type(it['number']).__name__}")
            if "caption" in it and it["caption"] is not None \
                    and not isinstance(it["caption"], str):
                probs.append(f"order.{key}[{i}]['caption'] 必须是字符串，"
                             f"实为 {type(it['caption']).__name__}")
    for key in ("references_pointer", "todo_pointer"):
        v = order.get(key)
        if key in order and v is not None and not isinstance(v, str):
            probs.append(f"order['{key}'] 必须是字符串，实为 {type(v).__name__}")
    return probs


def die(msg: str) -> int:
    print(f"用法错误：{msg}", file=sys.stderr)
    return EXIT_USAGE


def load_order(args) -> tuple:
    """返回 (order_dict, errors)。--inline 与 --order 互斥但后者优先。"""
    if args.order:
        p = args.order
        if not os.path.isfile(p):
            return None, [f"order 文件不存在：{p}"]
        try:
            with open(p, "r", encoding="utf-8-sig") as fh:
                raw = json.loads(fh.read(), object_pairs_hook=_reject_dup_keys)
        except DuplicateKeyError as exc:
            return None, [f"order 含重复键 {str(exc)!r}（last-wins 会静默吞掉前一条）"]
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            return None, [f"order 文件读不了（{type(exc).__name__}：{str(exc)[:80]}）"]
    elif args.inline:
        try:
            raw = json.loads(args.inline, object_pairs_hook=_reject_dup_keys)
        except DuplicateKeyError as exc:
            return None, [f"order 含重复键 {str(exc)!r}（last-wins 会静默吞掉前一条）"]
        except json.JSONDecodeError as exc:
            return None, [f"--inline 不是合法 JSON：{str(exc)[:80]}"]
    else:
        return None, []
    if not isinstance(raw, dict):
        return None, ["order 顶层须是对象"]
    unknown = sorted(set(raw) - ORDER_KEYS)
    if unknown:
        return None, [f"order 含未知键 {unknown}（合法键为 {sorted(ORDER_KEYS)}）"]
    probs = order_shape_problems(raw)
    if probs:
        return None, probs
    secs = raw.get("sections") or []
    if not isinstance(secs, list) or not secs:
        return None, ["order.sections 至少要一项（合稿没有输入就是空稿）"]
    for i, s in enumerate(secs):
        if not isinstance(s, dict) or not s.get("path"):
            return None, ["sections[%d] 缺 path" % i]
    return raw, []


def read_section(path: str) -> tuple:
    """读一节正文，返回 (行列表, errors)。路径不存在一律记错，不静默跳过。"""
    if not os.path.isfile(path):
        return None, [f"节文件不在盘：{path}"]
    try:
        with open(path, "r", encoding="utf-8-sig") as fh:
            return fh.read().splitlines(), []
    except (OSError, UnicodeDecodeError) as exc:
        return None, [f"节文件读不了 {path}（{type(exc).__name__}：{str(exc)[:80]}）"]


def render(order: dict, root: str) -> tuple:
    """渲染 draft 正文。返回 (文本, errors)。确定性：无时间戳、无随机。"""
    errors, todos = [], []
    if not isinstance(order, dict):
        return "", [f"order 顶层须是对象，实为 {type(order).__name__}"]
    shape = order_shape_problems(order)
    if shape:
        return "", shape
    secs_top = order.get("sections")
    if not isinstance(secs_top, list) or not secs_top:
        return "", ["order.sections 至少要一项（合稿没有输入就是空稿）"]

    def rel(p: str) -> str:
        return p if os.path.isabs(p) else os.path.join(root, p)

    out = []
    raw_title = order.get("title")
    title = (raw_title or "Untitled").strip() if isinstance(raw_title, str) \
        else "Untitled"
    out.append(f"# {title}")
    out.append("")

    for i, sec in enumerate(order.get("sections") or [], 1):
        if not isinstance(sec, dict) or not sec.get("path"):
            errors.append("sections[%d] 缺 path" % (i - 1))
            continue
        raw_heading = sec.get("heading")
        heading = raw_heading.strip() if isinstance(raw_heading, str) else ""
        lines, errs = read_section(rel(sec["path"]))
        errors += errs
        if lines is None:
            continue
        if heading:
            out.append(f"## {heading}")
            out.append("")
        body = []
        for lineno, raw in enumerate(lines, 1):
            marks = MARKER_RE.findall(raw)
            if marks:
                for txt in marks:
                    todos.append("%s:%d  %s" % (sec["path"], lineno, (txt or "(空标记)").strip()))
                raw = MARKER_RE.sub("", raw)          # 上收：正文零残留
                if raw.strip() == "":
                    continue
            body.append(TERM_PCT_RE.sub("%", raw).rstrip())
        while body and body[0].strip() == "":
            body.pop(0)
        while body and body[-1].strip() == "":
            body.pop()
        out.extend(body)
        out.append("")

    figs = order.get("figures") or []
    if figs:
        out.append("## Figures")
        out.append("")
        for f in sorted(figs, key=lambda x: x.get("number")
                        if isinstance(x, dict) and _is_int(x.get("number")) else 0):
            if not isinstance(f, dict):
                continue
            num = f.get("number")
            cap = f.get("caption")
            out.append("Fig. {}. {}".format(
                num, cap.strip() if isinstance(cap, str) else ""))
        out.append("")

    tabs = order.get("tables") or []
    if tabs:
        out.append("## Tables")
        out.append("")
        for t in sorted(tabs, key=lambda x: x.get("number")
                        if isinstance(x, dict) and _is_int(x.get("number")) else 0):
            if not isinstance(t, dict):
                continue
            num = t.get("number")
            cap = t.get("caption")
            out.append("Table {}. {}".format(
                num, cap.strip() if isinstance(cap, str) else ""))
        out.append("")

    ref = order.get("references_pointer")
    if isinstance(ref, str) and ref:
        out.append("## References")
        out.append("")
        out.append(f"见 `{ref}`（编号制文献表为唯一真源；LaTeX 侧走 \\citep，不手写文献表）。")
        out.append("")

    if todos:
        out.append("## 待确认项（单一清单）")
        out.append("")
        for i, t in enumerate(sorted(set(todos)), 1):
            out.append("%d. %s" % (i, t))
        out.append("")

    # 末尾恰好一个换行：拼接结果以 "\n" join 再补尾换行，字节稳定。
    return "\n".join(out).rstrip("\n") + "\n", errors


def selftest() -> int:
    fails = []

    def check(name, got, want):
        if got != want:
            fails.append(f"{name}: got {got!r} want {want!r}")
            print(f"  FAIL {name}: got {got!r} want {want!r}")
        else:
            print(f"  OK   {name}")

    here = os.path.dirname(os.path.abspath(__file__))
    before = sorted(os.listdir(here))
    old_cwd = os.getcwd()
    tmp = tempfile.mkdtemp(prefix="cc72a-selftest-")

    def w(path, text, mode="w"):
        """写文件必走 with：Windows 上未关闭的句柄会让临时目录清理失败。"""
        with open(path, mode, encoding="utf-8", newline="\n") as fh:
            fh.write(text)
        return path

    try:
        os.chdir(tmp)
        w("s1.md",
          "# 1. Introduction\n\nWe measured 20 wt% and 5 wt % batches [1].\n"
          "The result was significant (p = 0.03).\n[需作者确认: 补齐批次编号]\n")
        w("s2.md", "## Methods\n\nSamples were measured twice.\n")
        order = {"title": "Demo Paper",
                 "sections": [{"heading": "1. Introduction", "path": "s1.md"},
                              {"heading": "2. Methods", "path": "s2.md"}],
                 "figures": [{"number": 2, "caption": "Second."}, {"number": 1, "caption": "First."}],
                 "tables": [{"number": 1, "caption": "Composition."}],
                 "references_pointer": "20-lit/22-refs.json"}
        with open("order.json", "w", encoding="utf-8") as fh:
            json.dump(order, fh, ensure_ascii=False, indent=2)

        text, errs = render(order, tmp)
        check("渲染无错误", errs, [])
        check("标题在首行", text.splitlines()[0], "# Demo Paper")
        check("图注按编号排序（输入乱序）",
              [l for l in text.splitlines() if l.startswith("Fig. ")],
              ["Fig. 1. First.", "Fig. 2. Second."])
        check("术语归一 wt % -> wt%", "5 wt% batches" in text, True)
        check("待确认项上收到单一清单", "## 待确认项（单一清单）" in text, True)
        check("清单含来源位置与内容（节内行号）",
              "s1.md:5  补齐批次编号" in text, True)
        check("正文零残留（标记已删）", "[需作者确认" in text, False)
        check("参考文献指针在盘位", "## References" in text, True)

        # 幂等：同输入两次渲染字节一致
        again, _ = render(order, tmp)
        check("幂等：同输入字节一致", again.encode("utf-8"), text.encode("utf-8"))
        check("幂等：无时间戳类内容", "20" in text and "Generated" not in text, True)

        # --check 语义
        check("--check 在 out 不存在时 rc=1",
              subprocess_rc(["--order", "order.json", "--out", "d.md", "--check"]), 1)
        w("d.md", text)
        check("--check 一致时 rc=0",
              subprocess_rc(["--order", "order.json", "--out", "d.md", "--check"]), 0)
        w("s1.md", "\nchanged\n", "a")
        check("--check 不一致时 rc=1（可作回归门禁）",
              subprocess_rc(["--order", "order.json", "--out", "d.md", "--check"]), 1)

        # 缺输入一律报错，不静默出空稿
        bad = dict(order, sections=[{"heading": "X", "path": "nope.md"}])
        _, e2 = render(bad, tmp)
        check("节文件缺失记错", (e2 and "nope.md" in e2[0]), True)

        # order schema 守卫
        check("order 顶层非对象 → 用法错",
              subprocess_rc(["--inline", "[1,2]", "--out", "x.md"]), EXIT_USAGE)
        check("order 无 sections → 用法错",
              subprocess_rc(["--inline", '{"title":"t"}', "--out", "x.md"]), EXIT_USAGE)
        check("order 文件不存在 → 用法错",
              subprocess_rc(["--order", "nope.json", "--out", "x.md"]), EXIT_USAGE)

        # G-9 形态档：目录 out / 未知键 / 重复键 / 类型错（每条配正反用例）
        os.mkdir("outdir")
        check("--out 指目录 → 用法错 rc=2",
              subprocess_rc(["--order", "order.json", "--out", "outdir"]), EXIT_USAGE)
        check("--out 指目录（--check） → 用法错 rc=2",
              subprocess_rc(["--order", "order.json", "--out", "outdir",
                             "--check"]), EXIT_USAGE)
        check("合法 out 可写出 rc=0",
              subprocess_rc(["--order", "order.json", "--out", "ok.md"]), EXIT_OK)
        with open("ok.md", "r", encoding="utf-8") as _fh:
            _ok_text = _fh.read()
        _fresh, _ = render(order, tmp)
        check("合法 out 写出字节与渲染一致", _ok_text, _fresh)

        bad_unknown = dict(order, bogus_key=1)
        check("order 未知键 → 用法错 rc=2",
              subprocess_rc(["--inline", json.dumps(bad_unknown, ensure_ascii=False),
                             "--out", "x.md"]), EXIT_USAGE)
        bad_nested = dict(order, sections=[{"heading": "H", "path": "s1.md",
                                            "bogus": 1}])
        check("order 节条目未知键 → 用法错 rc=2",
              subprocess_rc(["--inline", json.dumps(bad_nested, ensure_ascii=False),
                             "--out", "x.md"]), EXIT_USAGE)
        check("合法 order 无未知键可跑 rc=0",
              subprocess_rc(["--inline", json.dumps(order, ensure_ascii=False),
                             "--out", "ok2.md"]), EXIT_OK)

        dup_inline = ('{"title":"t","title":"t2",'
                      '"sections":[{"heading":"H","path":"s1.md"}]}')
        check("order 内重复键（inline）→ 用法错 rc=2",
              subprocess_rc(["--inline", dup_inline, "--out", "x.md"]), EXIT_USAGE)
        w("dup.json", dup_inline)
        check("order 内重复键（文件）→ 用法错 rc=2",
              subprocess_rc(["--order", "dup.json", "--out", "x.md"]), EXIT_USAGE)
        check("干净 order 无重复键可跑 rc=0",
              subprocess_rc(["--order", "order.json", "--out", "ok3.md"]), EXIT_OK)

        bad_title = {"title": 123,
                     "sections": [{"heading": "H", "path": "s1.md"}]}
        check("类型错 title=123 → 用法错 rc=2",
              subprocess_rc(["--inline", json.dumps(bad_title), "--out", "x.md"]),
              EXIT_USAGE)
        bad_fig = {"title": "t",
                   "sections": [{"heading": "H", "path": "s1.md"}],
                   "figures": [{"number": 1, "caption": 123}]}
        check("类型错 caption=123 → 用法错 rc=2",
              subprocess_rc(["--inline", json.dumps(bad_fig), "--out", "x.md"]),
              EXIT_USAGE)
        bad_sec = {"title": "t",
                   "sections": [{"heading": 123, "path": "s1.md"}]}
        check("类型错 heading=123 → 用法错 rc=2",
              subprocess_rc(["--inline", json.dumps(bad_sec), "--out", "x.md"]),
              EXIT_USAGE)
        txt_bad, err_bad = render(bad_title, tmp)
        check("类型错直接调 render 不裸崩（回 errors）",
              (isinstance(err_bad, list) and len(err_bad) > 0), True)
        check("合法类型直接调 render 无错",
              render(order, tmp)[1], [])
    finally:
        os.chdir(old_cwd)
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)
        check("临时目录用毕即删", os.path.isdir(tmp), False)
        check("自测不在 scripts/ 留任何文件（含 __pycache__）", sorted(os.listdir(here)), before)
    if fails:
        print("ASSEMBLE-DRAFT SELFTEST FAIL（%d 项）" % len(fails))
        for f in fails:
            print("  - " + f)
        return 1
    print("ASSEMBLE-DRAFT SELFTEST PASS")
    return 0


def subprocess_rc(argv) -> int:
    """自测内跑一次 CLI（进程内捕获退出码，避免额外依赖）。"""
    import io
    out, err = io.StringIO(), io.StringIO()
    old_o, old_e = sys.stdout, sys.stderr
    sys.stdout, sys.stderr = out, err
    try:
        return main(argv)
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else EXIT_USAGE
    finally:
        sys.stdout, sys.stderr = old_o, old_e


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog="72-assemble-draft.py",
        description="确定性合稿器：md 单一真源 → 单一 draft（作者确认项上收 + 术语归一）")
    ap.add_argument("--order", help="order.json 路径")
    ap.add_argument("--inline", help="内联 order JSON（--order 优先）")
    ap.add_argument("--out", help="draft 输出路径（写入仅限此文件）")
    ap.add_argument("--root", default=".", help="节文件相对根（默认当前目录）")
    ap.add_argument("--check", action="store_true",
                    help="只校验不改写：out 与将生成的内容不一致即 rc=1（回归门禁）")
    ap.add_argument("--selftest", action="store_true", help="离线自测：合成样本 + 临时目录")
    args = ap.parse_args(argv)

    if args.selftest:
        return selftest()
    if not args.order and not args.inline:
        return die("给出 --order 或 --inline（或用 --selftest）")
    if not args.out:
        return die("给出 --out")
    if os.path.isdir(args.out):
        return die(f"--out 指向目录而非文件：{args.out}（须给出文件路径）")
    order, errs = load_order(args)
    if order is None:
        for e in errs:
            print(f"用法错误：{e}", file=sys.stderr)
        return EXIT_USAGE

    text, errs = render(order, args.root)
    if errs:
        for e in errs:
            print(f"错误：{e}", file=sys.stderr)
        return EXIT_FAIL

    if args.check:
        if not os.path.isfile(args.out):
            print(f"不一致：{args.out} 不存在（先不带 --check 生成一次）")
            return EXIT_FAIL
        with open(args.out, "r", encoding="utf-8-sig") as fh:
            cur = fh.read()
        if cur != text:
            a, b = cur.splitlines(), text.splitlines()
            for i in range(max(len(a), len(b))):
                x = a[i] if i < len(a) else "<缺行>"
                y = b[i] if i < len(b) else "<缺行>"
                if x != y:
                    print("不一致：第 %d 行\n  盘上：%s\n  将生成：%s" % (i + 1, x[:100], y[:100]))
                    break
            return EXIT_FAIL
        print("一致：%s 与 order 逐字节相同（%d 字节 / %d 行）"
              % (args.out, len(text.encode("utf-8")), len(text.splitlines())))
        return EXIT_OK

    parent = os.path.dirname(os.path.abspath(args.out))
    try:
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(args.out, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
    except (OSError, TypeError, ValueError) as exc:
        return die(f"--out 写不了 {args.out}（{type(exc).__name__}：{str(exc)[:80]}）")
    print("已写出 %s（%d 字节 / %d 行）；作者确认项上收至「待确认项」清单。"
          % (args.out, len(text.encode("utf-8")), len(text.splitlines())))
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
