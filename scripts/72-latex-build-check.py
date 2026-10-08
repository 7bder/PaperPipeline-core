#!/usr/bin/env python3
# -*- coding: utf-8 -*-  # noqa: UP009 — 与既有 45/70 号脚本一致，coding 声明是本仓约定
# vendor-tool: 72-latex-build-check.py version 1
# SPDX-License-Identifier: MIT
"""72-latex-build-check.py — LaTeX 装配回读校验（派生物体检）。

按 references/40-draft-to-latex.md §装配链第 4 步实现：`.tex` 生成后回读校验四件事——
① 头部 GENERATED 标注在位（单一真源铁律的护栏）；② 无 TODO / [需作者确认] 残留；
③ `\\bibliography{X}` 的 X.bib 与 `\\includegraphics` 的图件在盘；④ `\\citep{}` 的
key 在 bib 里有对应条目（引用↔文献表一致性，防 .bst 重编号后与真源分叉）。

PDF 页数用 pypdf：**在盘则核**（可给 --min-pages），**不在盘降级提示且不判 FAIL**——
本工具不该因构建工具缺席而阻断 LaTeX 侧体检。

用法：
    python 70-tools/72-latex-build-check.py main.tex
    python 70-tools/72-latex-build-check.py main.tex --pdf main.pdf --min-pages 8
    python 70-tools/72-latex-build-check.py --selftest

退出码：0 = 全部通过；1 = 有命中项（含引用一致性判据未执行）；2 = 用法错
（文件不在盘、非 UTF-8/含 U+FFFD/NUL、--min-pages 缺 --pdf 等）。
安全：全程只读，不改 .tex、不跑构建。
"""
from __future__ import annotations

import argparse
import os
import re
import sys
import tempfile

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.dont_write_bytecode = True

EXIT_OK, EXIT_FAIL, EXIT_USAGE = 0, 1, 2

# ① 单一真源铁律：.tex 是派生物，头部必须带该标注（措辞可变，含 GENERATED 即可）。
GENERATED_RE = re.compile(r"^\s*%.*\bGENERATED\b", re.IGNORECASE | re.MULTILINE)
# ② 待办残留：TODO / AUTHOR CONFIRM / 中文待确认三族（大小写不敏感）。
TODO_RE = re.compile(r"TODO|AUTHOR[ \t]+CONFIRM|需作者确认|待作者确认|待核实", re.IGNORECASE)
# ③ 资源引用（\bibliography 是 BibTeX 口径；\addbibresource 是 biblatex 口径，一并覆盖）
BIB_RE = re.compile(r"\\bibliography\s*\{([^}]*)\}")
ADD_BIBRESOURCE_RE = re.compile(r"\\addbibresource\s*(?:\[[^\]]*\])?\s*\{([^}]*)\}")
GRAPHICS_RE = re.compile(r"\\includegraphics\s*(?:\[[^\]]*\])?\s*\{([^}]*)\}")
THEBIB_RE = re.compile(r"\\begin\{thebibliography\}")
# ④ 引用 key（Elsevier cas-sc 口径用 \citep；\cite/\citet 一并覆盖）
CITE_RE = re.compile(r"\\(?:cite|citep|citet|citealp|citealt|citeyear|citeyearpar)\s*\{([^}]*)\}")
BIB_ENTRY_RE = re.compile(r"@\s*\w+\s*\{\s*([^,\s}]+)\s*,")

PYPDF_HINT = ("未装 pypdf → PDF 页数核验降级（不影响 rc）。安装：pip install pypdf"
              "（国内镜像示例：pip install -i https://mirrors.aliyun.com/pypi/simple/ pypdf）")


def need_pypdf():
    try:
        import pypdf
        return pypdf, None
    except ImportError:
        return None, PYPDF_HINT


class EncodingProblem(Exception):
    """tex/bib 无法严格按 UTF-8 解码（或解码结果含 U+FFFD/NUL）。

    与 70-verify A2 同一条纪律：曾用 errors="replace"，GBK 正文里的中文待确认
    标记被替换字符吞掉 → FAIL 翻 PASS。故一律严格解码，异常/替换字符/NUL 归 rc=2。
    """


def read_text(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8-sig") as fh:
            text = fh.read()
    except UnicodeDecodeError as exc:
        raise EncodingProblem(
            f"{path}：非 UTF-8 编码（{exc}）——产物口径为 UTF-8，严格解码失败，"
            "不得退化为替换字符后判 PASS（替换字符会吞掉中文待确认标记）") from exc
    if "�" in text:
        raise EncodingProblem(
            f"{path}：解码结果含替换字符 U+FFFD——疑似非 UTF-8 产物混入，"
            "不得判 PASS（替换字符会吞掉待确认标记）")
    if "\x00" in text:
        raise EncodingProblem(
            f"{path}：解码结果含 NUL(\\x00)——疑 UTF-16/UCS 产物被当 UTF-8 读入，"
            "不得判 PASS（交织 NUL 会让待确认/引用标记失明）")
    return text


def bib_paths_for(text: str, base: str) -> list:
    """从 \\bibliography{X,Y} 与 \\addbibresource{F.bib} 推出 bib 路径列表（相对 .tex 所在目录）。

    \\bibliography{X} 按 BibTeX 口径补 .bib；\\addbibresource 通常自带扩展名，
    缺扩展名才补 .bib。改用 biblatex 口径后引用一致性照样核，不再整体免跑。
    """
    paths = [os.path.join(base, n.strip() + ".bib")
             for names in BIB_RE.findall(text)
             for n in names.split(",") if n.strip()]
    for names in ADD_BIBRESOURCE_RE.findall(text):
        for n in [x.strip() for x in names.split(",") if x.strip()]:
            if not n.lower().endswith(".bib"):
                n += ".bib"
            paths.append(os.path.join(base, n))
    return paths


def cite_keys_in(tex: str) -> list:
    """tex 内全部 \\cite 系引用 key（去重排序）。"""
    keys = set()
    for group in CITE_RE.findall(tex):
        for key in [k.strip() for k in group.split(",") if k.strip()]:
            keys.add(key)
    return sorted(keys)


def bib_known_entries(bib_paths: list) -> tuple:
    """收集各 bib 的条目 key。返回 (known, bib_errors)。

    bib 侧同样严格解码：读失败/解码失败记入 bib_errors（调用方归 rc=2），
    不在盘的 bib 跳过（由 bib-missing 命中项覆盖，不在此重复点名）。
    """
    known, bib_errors = set(), []
    for bp in bib_paths:
        if not os.path.isfile(bp):
            continue
        try:
            known.update(BIB_ENTRY_RE.findall(read_text(bp)))
        except EncodingProblem as exc:
            bib_errors.append(str(exc))
        except OSError as exc:
            bib_errors.append(f"{bp}：bib 读不了（{type(exc).__name__}：{str(exc)[:80]}）")
    return known, bib_errors


def check_cites(tex: str, bib_paths: list) -> tuple:
    """引用 key ↔ bib entry 一致性。返回 (missing, verifiable, bib_errors)。

    verifiable=False 表示无可核条目（未声明 bib / bib 全不在盘 / 空 .bib）——
    调用方判 rc=1「判据未执行」并点名，不得整体免跑 rc=0。
    bib_errors 为 bib 严格解码/读入失败明细（调用方归 rc=2）。
    """
    keys = cite_keys_in(tex)
    if not keys:
        return [], True, []
    known, bib_errors = bib_known_entries(bib_paths)
    if not known:
        return [], False, bib_errors
    return sorted(k for k in keys if k not in known), True, bib_errors


def check_tex(path: str) -> tuple:
    """对 .tex 做四件套体检。返回 (hits, notes, errors)；errors 非空属读入失败。"""
    hits, notes, errors = [], [], []
    if not os.path.isfile(path):
        return hits, notes, [f"tex 文件不在盘：{path}"]
    try:
        text = read_text(path)
    except EncodingProblem as exc:
        return hits, notes, [str(exc)]
    except OSError as exc:
        return hits, notes, [f"tex 读不了（{type(exc).__name__}：{str(exc)[:80]}）"]

    base = os.path.dirname(os.path.abspath(path))

    if not GENERATED_RE.search(text):
        hits.append(("generated-missing",
                     ("头部缺 GENERATED 标注——.tex 是派生物，缺这行护栏就会被人手改；"
                     "应是 `%% GENERATED — do not edit; change manuscript/*.md and re-run`")))

    for i, line in enumerate(text.splitlines(), 1):
        m = TODO_RE.search(line)
        if m:
            # 消息带该行原文（截断）：只报匹配到的 "TODO" 三个字，作者无从判断该改哪一处。
            hits.append(("todo-residual", "第 %d 行残留 %r，原文：%s（作者确认项应上收为单一清单，"
                                         "排版层不得出现）"
                         % (i, m.group(0), line.strip()[:80])))

    for n in bib_paths_for(text, base):
        if not os.path.isfile(n):
            hits.append(("bib-missing", f"\\bibliography 引用的 {os.path.basename(n)} 不在盘"))

    for names in GRAPHICS_RE.findall(text):
        for n in [x.strip() for x in names.split(",") if x.strip()]:
            if not os.path.isfile(os.path.join(base, n)):
                hits.append(("graphic-missing", f"\\includegraphics{{{n}}} 引用的文件不在盘"))

    if THEBIB_RE.search(text):
        notes.append("检测到 thebibliography（手写文献表）。多数出版社口径（Elsevier cas-sc）要求 "
                     "\\citep + \\bibliography——手写文献表会让 .bst 编号与 md 真源的 [n] 分叉。"
                     "本工具按提示处理（不判 FAIL），是否禁用由目标刊碎片决定。")

    missing, verifiable, bib_errors = check_cites(text, bib_paths_for(text, base))
    errors.extend(bib_errors)
    if cite_keys_in(text) and not verifiable and not THEBIB_RE.search(text):
        declared = [os.path.basename(p) for p in bib_paths_for(text, base)]
        detail = ("已声明：" + "、".join(declared)) if declared else \
            "未声明 \\bibliography/\\addbibresource"
        hits.append(("cite-unchecked",
                     f"引用一致性判据未执行：{os.path.basename(path)} 含 \\cite 引用但无可核条目"
                     f"（{detail}；空 .bib / 声明文件不在盘均属此类）——跳过不得判 PASS"))
    else:
        for key in missing:
            hits.append(("cite-missing", f"\\citep{{{key}}} 在 .bib 里没有对应条目"))

    return hits, notes, errors


def check_pdf(pdf: str, min_pages: int, pypdf_mod) -> tuple:
    """PDF 页数核验。返回 (hits, notes)。"""
    if not pdf:
        return [], []
    if not os.path.isfile(pdf):
        return [("pdf-missing", f"PDF 不在盘：{pdf}（Tectonic 未构建或构建失败）")], []
    if pypdf_mod is None:
        return [], [PYPDF_HINT]
    try:
        n = len(pypdf_mod.PdfReader(pdf).pages)
    except Exception as exc:                      # noqa: BLE001 — pypdf 对损坏 PDF 会抛自定义与内建多种异常，窄捕获必漏
        return [("pdf-unreadable", f"PDF 读不了（{type(exc).__name__}：{str(exc)[:80]}）")], []
    if n < min_pages:
        return [("pdf-pages", "PDF 只有 %d 页，少于下限 %d 页——多半是图件或章节没插进去"
                             % (n, min_pages))], []
    return [], ["PDF %d 页（≥ 下限 %d）" % (n, min_pages)]


def selftest() -> int:
    fails = []

    def check(name, got, want):
        if got != want:
            fails.append(f"{name}: got {got!r} want {want!r}")
            print(f"  FAIL {name}: got {got!r} want {want!r}")
        else:
            print(f"  OK   {name}")

    pypdf_mod, _ = need_pypdf()
    here = os.path.dirname(os.path.abspath(__file__))
    before = sorted(os.listdir(here))
    old_cwd = os.getcwd()
    tmp = tempfile.mkdtemp(prefix="cc72b-selftest-")
    try:
        os.chdir(tmp)
        with open("refs.bib", "w", encoding="utf-8") as fh:
            fh.write("@article{smith2020,\n  title={A},\n}\n@book{jones2021,\n  title={B},\n}\n")
        with open("fig1.pdf", "w", encoding="utf-8") as fh:
            fh.write("%PDF-1.4\n")
        good = ("% GENERATED — do not edit; change manuscript/*.md and re-run\n"
                "\\documentclass{cas-sc}\n"
                "\\begin{document}\n"
                "\\citep{smith2020,jones2021}\n"
                "\\bibliographystyle{cas-model2-names}\n"
                "\\bibliography{refs}\n"
                "\\includegraphics[width=\\linewidth]{fig1.pdf}\n"
                "\\end{document}\n")
        with open("good.tex", "w", encoding="utf-8") as fh:
            fh.write(good)

        hits, _, errors = check_tex("good.tex")
        check("合规 tex 零命中", ([h[0] for h in hits], errors), ([], []))
        check("合规 tex 引用 key 全在 bib 内", check_cites(good, ["refs.bib"])[0], [])

        with open("nogen.tex", "w", encoding="utf-8") as fh:
            fh.write(good.replace("% GENERATED — do not edit", "% hand written"))
        check("缺 GENERATED 标注 → 判 FAIL",
              "generated-missing" in [h[0] for h in check_tex("nogen.tex")[0]], True)

        with open("todo.tex", "w", encoding="utf-8") as fh:
            fh.write(good.replace("\\citep{smith2020,jones2021}",
                                  "\\citep{smith2020} % TODO: 补 jones"))
        h_todo = check_tex("todo.tex")[0]
        check("TODO 残留 → 判 FAIL 且给行号与内容",
              ("todo-residual" in [h[0] for h in h_todo],
               any("补 jones" in h[1] for h in h_todo)), (True, True))
        with open("cn.tex", "w", encoding="utf-8") as fh:
            fh.write(good.replace("\\citep{smith2020,jones2021}",
                                  "\\citep{smith2020} [需作者确认: 核 X]"))
        check("中文待确认残留 → 判 FAIL",
              "todo-residual" in [h[0] for h in check_tex("cn.tex")[0]], True)

        # 「引用了但文件不在盘」必须测：若整条删掉 \bibliography / \includegraphics，
        # 就变成「无引用 → 无命中」，测不到 bib-missing / graphic-missing 两支。
        with open("nobib.tex", "w", encoding="utf-8") as fh:
            fh.write(good.replace("\\bibliography{refs}", "\\bibliography{nobib}"))
        check("bib 不在盘 → 判 FAIL",
              "bib-missing" in [h[0] for h in check_tex("nobib.tex")[0]], True)

        with open("nopic.tex", "w", encoding="utf-8") as fh:
            fh.write(good.replace("{fig1.pdf}", "{missing.pdf}"))
        check("图件不在盘 → 判 FAIL",
              "graphic-missing" in [h[0] for h in check_tex("nopic.tex")[0]], True)

        with open("badkey.tex", "w", encoding="utf-8") as fh:
            fh.write(good.replace("\\citep{smith2020,jones2021}", "\\citep{smith2020,ghost2022}"))
        check("引用 key 不在 bib → 判出来",
              check_cites(read_text("badkey.tex"), ["refs.bib"])[0], ["ghost2022"])
        check("引用 key 缺失走主流程也判 FAIL",
              "cite-missing" in [h[0] for h in check_tex("badkey.tex")[0]], True)

        with open("thebib.tex", "w", encoding="utf-8") as fh:
            fh.write(good.replace("\\bibliography{refs}",
                                  "\\begin{thebibliography}{9}\\bibitem{a} x \\end{thebibliography}"))
        h_tb, n_tb, _ = check_tex("thebib.tex")
        check("thebibliography 只提示不判 FAIL（编号体系分叉风险交人工裁）",
              (any("thebibliography" in n for n in n_tb),
               "bib-missing" not in [h[0] for h in h_tb],
               "cite-unchecked" not in [h[0] for h in h_tb]), (True, True, True))

        # G-5：严格解码（与 70 A2 同口径）——GBK 含中文待确认标记不得被吞成 rc=0。
        cn_utf8 = good.replace("\\citep{smith2020,jones2021}",
                               "\\citep{smith2020} [需作者确认: 核 X]")
        with open("gbk.tex", "wb") as fh:
            fh.write(cn_utf8.encode("gbk"))
        e_gbk = check_tex("gbk.tex")[2]
        check("GBK tex 含中文待确认标记 → 读入失败归 rc=2 并点名文件与 UTF-8",
              (e_gbk != [],
               any("gbk.tex" in e for e in e_gbk),
               any("UTF-8" in e for e in e_gbk),
               "todo-residual" not in [h[0] for h in check_tex("gbk.tex")[0]]),
              (True, True, True, True))
        check("main：GBK tex 归 rc=2", main(["gbk.tex"]), 2)
        h_cn, _, e_cn = check_tex("cn.tex")
        check("UTF-8 同内容命中仍 rc=1、不误升",
              ([h[0] for h in h_cn], e_cn, main(["cn.tex"])), (["todo-residual"], [], 1))
        with open("gbk-clean.tex", "wb") as fh:
            fh.write(good.encode("gbk"))
        check("GBK tex 无标记同样 rc=2（严格解码与内容无关）",
              check_tex("gbk-clean.tex")[2] != [], True)
        with open("nul.tex", "w", encoding="utf-8") as fh:
            fh.write(good + "\x00\n")
        check("tex 含 NUL → rc=2（疑 UTF-16/UCS）", check_tex("nul.tex")[2] != [], True)
        with open("fffd.tex", "w", encoding="utf-8") as fh:
            fh.write(good.replace("\\citep{smith2020,jones2021}", "\\citep{smith2020} �"))
        check("tex 含 U+FFFD → rc=2", check_tex("fffd.tex")[2] != [], True)
        with open("gbk.bib", "wb") as fh:
            fh.write("@article{smith2020,\n  title={中文标题},\n}\n".encode("gbk"))
        with open("gbkbib.tex", "w", encoding="utf-8") as fh:
            fh.write(good.replace("\\bibliography{refs}", "\\bibliography{gbk}"))
        check("GBK .bib → rc=2（bib 侧同样严格解码）",
              check_tex("gbkbib.tex")[2] != [], True)

        # G-6：空集合免跑一律改 rc=1「判据未执行」；\\addbibresource 改口径后照样核。
        with open("empty.bib", "w", encoding="utf-8") as fh:
            fh.write("% empty — no entries\n")
        with open("emptybib.tex", "w", encoding="utf-8") as fh:
            fh.write(good.replace("\\bibliography{refs}", "\\bibliography{empty}"))
        h_eb = check_tex("emptybib.tex")[0]
        check("空 .bib + 有引用 → rc=1 判据未执行并点名",
              ("cite-unchecked" in [h[0] for h in h_eb],
               any("判据未执行" in h[1] for h in h_eb),
               main(["emptybib.tex"])), (True, True, 1))
        with open("bl.tex", "w", encoding="utf-8") as fh:
            fh.write(good.replace("\\bibliography{refs}", "\\addbibresource{refs.bib}"))
        check("addbibresource 正常识别 → 零命中",
              [h[0] for h in check_tex("bl.tex")[0]], [])
        with open("bl-empty.tex", "w", encoding="utf-8") as fh:
            fh.write(good.replace("\\bibliography{refs}", "\\addbibresource{empty.bib}"))
        check("addbibresource 指空 .bib → 判据未执行 rc=1",
              ("cite-unchecked" in [h[0] for h in check_tex("bl-empty.tex")[0]],
               main(["bl-empty.tex"])), (True, 1))
        with open("nodecl.tex", "w", encoding="utf-8") as fh:
            fh.write(good.replace("\\bibliography{refs}\n", ""))
        check("有引用无 bib 声明 → 判据未执行 rc=1",
              ("cite-unchecked" in [h[0] for h in check_tex("nodecl.tex")[0]],
               main(["nodecl.tex"])), (True, 1))
        with open("nocite.tex", "w", encoding="utf-8") as fh:
            fh.write(good.replace("\\citep{smith2020,jones2021}\n", "")
                        .replace("\\bibliography{refs}\n", ""))
        check("无引用无声明 → 无事可核仍 rc=0",
              ([h[0] for h in check_tex("nocite.tex")[0]], main(["nocite.tex"])), ([], 0))
        check("main：合规 tex 归 rc=0", main(["good.tex"]), 0)

        # 缺参：--min-pages 无 --pdf 不再静默 rc=0，归 rc=2 点名参数。
        check("main：--min-pages 缺 --pdf → rc=2", main(["good.tex", "--min-pages", "8"]), 2)

        if pypdf_mod is not None:
            try:
                w = pypdf_mod.PdfWriter()
                for _i in range(3):
                    w.add_blank_page(width=200, height=200)
                with open("three.pdf", "wb") as fh:
                    w.write(fh)
                h_p, n_p = check_pdf("three.pdf", 3, pypdf_mod)
                check("PDF 页数达标 → 零命中 + 给计数", ([h[0] for h in h_p], len(n_p)), ([], 1))
                check("PDF 页数不足 → 判 FAIL",
                      "pdf-pages" in [h[0] for h in check_pdf("three.pdf", 8, pypdf_mod)[0]], True)
                check("main：--min-pages + --pdf 正常跑（3 页 ≥ 3 → rc=0）",
                      main(["good.tex", "--pdf", "three.pdf", "--min-pages", "3"]), 0)
                check("main：--min-pages + --pdf 页数不足 → rc=1",
                      main(["good.tex", "--pdf", "three.pdf", "--min-pages", "8"]), 1)
            except Exception as exc:              # noqa: BLE001 — pypdf 版本差异 → 降级说明，不掩盖
                print(f"  SKIP  PDF 侧自测（本机 pypdf 生成样本失败：{str(exc)[:60]}）")
        # R5-1：样本用无条件创建的 fig1.pdf（:245-246），不依赖 pypdf 在场生成 three.pdf；
        # pypdf 缺席时 three.pdf 不在盘 → 误判 pdf-missing（假红）。pypdf 有/无两态均须绿。
        h_none, n_none = check_pdf("fig1.pdf", 3, None)
        check("pypdf 缺席 → 降级提示且不判 FAIL", ([h[0] for h in h_none], len(n_none)), ([], 1))
        check("PDF 不在盘 → 判 FAIL",
              "pdf-missing" in [h[0] for h in check_pdf("nope.pdf", 1, pypdf_mod)[0]], True)
        check("tex 不在盘 → 用法错", check_tex("nope.tex")[2] != [], True)
    finally:
        os.chdir(old_cwd)
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)
        check("临时目录用毕即删", os.path.isdir(tmp), False)
        check("自测不在 scripts/ 留任何文件（含 __pycache__）", sorted(os.listdir(here)), before)
    if fails:
        print("LATEX-BUILD-CHECK SELFTEST FAIL（%d 项）" % len(fails))
        for f in fails:
            print("  - " + f)
        return 1
    print("LATEX-BUILD-CHECK SELFTEST PASS")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog="72-latex-build-check.py",
        description="LaTeX 装配回读校验：GENERATED 标注 / 待办残留 / bib 与图件在盘 / 引用 key 一致性 / PDF 页数")
    ap.add_argument("tex", nargs="?", help="待校验的 .tex 路径")
    ap.add_argument("--pdf", help="对应 PDF 路径（给出才核页数）")
    ap.add_argument("--min-pages", type=int, default=0,
                    help="PDF 页数下限（须与 --pdf 联用；缺 --pdf 时给出归 rc=2）")
    ap.add_argument("--selftest", action="store_true", help="离线自测：合成 tex + bib + PDF")
    args = ap.parse_args(argv)

    if args.selftest:
        return selftest()
    if not args.tex:
        print("用法错误：给出待校验的 .tex（或用 --selftest）", file=sys.stderr)
        return EXIT_USAGE
    if args.min_pages and not args.pdf:
        print("用法错误：--min-pages 需与 --pdf 联用（缺 --pdf 时页数下限无核验对象，"
              "不得静默跳过）", file=sys.stderr)
        return EXIT_USAGE

    hits, notes, errors = check_tex(args.tex)
    if errors:
        for e in errors:
            print(f"错误：{e}", file=sys.stderr)
        return EXIT_USAGE

    pypdf_mod, _ = need_pypdf()
    if args.pdf:
        ph, pn = check_pdf(args.pdf, args.min_pages, pypdf_mod)
        hits += ph
        notes += pn

    for n in notes:
        print("提示：" + n)
    for tag, msg in hits:
        print(f"{tag}:{msg}")
    print("检查：%d 命中 / %d 提示（%s）" % (len(hits), len(notes), args.tex))
    return EXIT_FAIL if hits else EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
