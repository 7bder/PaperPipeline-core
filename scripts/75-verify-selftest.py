#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""75-verify-selftest.py — 判据基座的自测（parity + 每个断言类型的正反控制 + 生成器断言守卫）。

用法：
    python -X utf8 75-verify-selftest.py                    # 合成控制套件 + manifest guards + 生成器守卫
    python -X utf8 75-verify-selftest.py --project <项目根>   # 追加与该项目自带 verify 脚本的 parity 比对

设计：合成一个临时项目，把**每个断言类型**都放一对“应当通过 / 应当失败”的用例；
只接受"该通过的全过、该失败的全败"——单边干净（全过或全败）视为该断言未被真正检查。
parity 模式用真实项目的历史 manifest 比对两个实现的判定是否逐任务一致。
生成器守卫（2026-09-26 审查后新增）：断言展开为空的任务必须被 30-gen-proposals.py 拒绝，
真实 profile 的生成物每个任务必须至少有一条断言——防止 done 门禁空转回归。
碎片守卫（规格 §3 能力建成后新增）：未声明 fragments 时生成物与改动前逐字节一致且完全不读
manifest、声明后按声明顺序原样注入（marker + 正文不折叠）、未知 id 必须非零退出且不落半份生成物。
注册表守卫（task-capability-registry-resync 新增）：SKILL.md 能力注册表状态位与磁盘实测一致
（available 行路径在盘、planned 行路径不在盘），含 available→planned 与幽灵路径双向内存反向对照；
状态格闭集校验（B8，2026-10-07 审查：取值只能 available/planned，写成 done 之类不再被静默忽略）。
B12（D-1/D-11）：注册表切列前 `\\|` 先占位转义（40 号行实证，旧口径 7/8 漏行），加
“肉眼行数 == 解析行数 == 期望 8”自证（删/增一行即红）与 40 号行翻牌/删行双反向对照。
基数断言（B8）：合成矩阵用例数钉在 SUITE_CASES（缩小即红）；引擎端到端守卫的 SKIP 归 rc=2
（引擎件缺失 / 正路用例 0 条不静默放行）。
判定硬化守卫（2026-10-07 审查 A2/A3/A4 落地）：非 UTF-8 产物严格解码 → rc=2、manifest
重复键 → rc=2、越界路径（绝对 / '..'）→ rc=2，三组各带锚点与干净对照。
vendor 豁免守卫（2026-10-07 审查 A1 落地）：通配 forbid 不落到随技能发货的 vendor 工具
（install.py 清单），逐档生成物 + 端到端 rc=0 + 摘除豁免反向对照 + 与 install.py 交叉核对。
require_values 值判定守卫（B06a，round3）：json_files 的 `require_values` 逐条等值判定（布尔/
字符串），反向对照 `two_source_verified:false` → rc=1 点名键与实测值，含正控制 / 形态档 /
空断言四类；补上「只判键存在」把 false 放行的验真门空转。
生成器形态档守卫（B13/A-11/B-7，round3）：build 入口集中校验 read/edit/inject/ac
须 list、read 项须 dict 含 path、edit 项须真实路径形态、axes 键值须在闭集/词汇内，
违规归 problems → CLI rc=2 并点名 `档:任务:键`；含标量/char-split 双锚点与合规档正向对照。
豁免差集守卫（B13/B-6/G-15，round3）：exclude/forbid 通配统一走 fill()（占位符与字面同命中，
`{ms}/skip.md` 对展开后路径生效）、vendor 豁免全路径匹配、strip 只剥 forbid/forbid_regex、
空命中 exclude 上报；每处配正反用例。
"""
from __future__ import annotations

import argparse
import contextlib
import copy
import io
import json
import os
import pathlib
import re
import subprocess
import sys
import tempfile

# 与 70-verify.py 同一口径（conventions §2）：cp936 主机上打印 ✅/中文明细不得崩溃。
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

HERE = pathlib.Path(__file__).resolve().parent
VERIFY = HERE / "70-verify.py"
sys.path.insert(0, str(HERE))
import importlib.util                                  # noqa: E402
# 本文件以 importlib 直接加载生成器，会在 scripts/ 落下 .pyc；.pyc 内嵌本机绝对路径，
# 是发布物污染（.gitignore 也拦不住已被删过一次又再生的情况），故在加载前关闭写字节码。
sys.dont_write_bytecode = True
_spec = importlib.util.spec_from_file_location("gen30", HERE / "30-gen-proposals.py")
gen30 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gen30)                        # noqa: E402


def build_case_root(root: pathlib.Path) -> dict:
    """造临时项目 + 覆盖全部断言类型的 manifest，返回 {task_id: 期望 rc}。"""
    (root / "70-tools").mkdir(parents=True, exist_ok=True)
    (root / "docs").mkdir(exist_ok=True)
    (root / "big.txt").write_text("hello world " * 40, encoding="utf-8")          # ~480 B
    (root / "mid.txt").write_text("needle here\nforbidden\n" + "w " * 50, encoding="utf-8")
    (root / "clean.txt").write_text("needle here\n" + "w " * 50, encoding="utf-8")
    (root / "words.txt").write_text("\n".join(["w"] * 100), encoding="utf-8")
    (root / "many.txt").write_text("\n".join(["[x] item"] * 5), encoding="utf-8")
    (root / "one.txt").write_text("[x] item\n", encoding="utf-8")
    # F18 count_distinct 夹具：3 行彼此不同（唯一行=唯一串=3）；many.txt 的 5 行**完全相同**
    # （"[x] item"），是「同图号复制 / 整列同值填充」的最小复现样本——min_matches 计 5 次过检，
    # count_distinct 数唯一只得 1。
    (root / "distinct.md").write_text("[x] 1\n[x] 2\n[x] 3\n@kw1 @kw2 @kw3\n", encoding="utf-8")
    (root / "items_ok.json").write_text(json.dumps([{"a": 1, "b": 2}] * 3), encoding="utf-8")
    (root / "items_bad.json").write_text(json.dumps([{"a": 1}, {"a": 1, "b": 2}]), encoding="utf-8")
    (root / "99-batch").mkdir(exist_ok=True)
    for i in range(3):
        (root / "99-batch" / f"f{i}.png").write_bytes(b"x" * 300)
    (root / "deep" / "nest").mkdir(parents=True)
    for name in ("a.rr", "b.rr"):
        (root / "deep" / "nest" / name).write_text("rr", encoding="utf-8")
    (root / "residual").mkdir(exist_ok=True)
    (root / "residual" / "old.md").write_text("old", encoding="utf-8")

    M = {
        # files / min_bytes
        "c-min-bytes-ok":   {"files": [{"path": "big.txt", "min_bytes": 100}]},
        "c-min-bytes-bad":  {"files": [{"path": "big.txt", "min_bytes": 99999}]},
        "c-missing-file":   {"files": [{"path": "nope.md"}]},
        # files / contains
        "c-contains-ok":    {"files": [{"path": "clean.txt", "contains": ["needle here"]}]},
        "c-contains-bad":   {"files": [{"path": "clean.txt", "contains": ["absent tk"]}]},
        # files / forbid
        "c-forbid-ok":      {"files": [{"path": "clean.txt", "forbid": ["forbidden"]}]},
        "c-forbid-bad":     {"files": [{"path": "mid.txt", "forbid": ["forbidden"]}]},
        # files / word_count（B10 行计数语义：words.txt 为 100 正文行，
        # [90,110] 绿、[1,10] 红——count_body_lines 口径）
        "c-words-ok":       {"files": [{"path": "words.txt", "word_count": [90, 110]}]},
        "c-words-bad":      {"files": [{"path": "words.txt", "word_count": [1, 10]}]},
        # files / contains_regex
        "c-re-ok":          {"files": [{"path": "many.txt", "contains_regex": [r"^\[x\] item$"]}]},
        "c-re-bad":         {"files": [{"path": "many.txt", "contains_regex": [r"^\[y\] item$"]}]},
        # files / forbid_regex
        "c-nore-ok":        {"files": [{"path": "clean.txt", "forbid_regex": [r"forbidden"]}]},
        "c-nore-bad":       {"files": [{"path": "mid.txt", "forbid_regex": [r"forbidden"]}]},
        # files / min_matches
        "c-matches-ok":     {"files": [{"path": "many.txt", "min_matches": {"pattern": r"\[x\]", "min": 5}}]},
        "c-matches-bad":    {"files": [{"path": "many.txt", "min_matches": {"pattern": r"\[x\]", "min": 6}}]},
        # files / count_distinct（F18 唯一计数；line/all 两模式正反控制）
        "c-cdist-line-ok":  {"files": [{"path": "distinct.md",
                                        "count_distinct": {"pattern": r"^\[x\] \d+$", "min": 3}}]},
        "c-cdist-line-bad": {"files": [{"path": "distinct.md",
                                        "count_distinct": {"pattern": r"^\[x\] \d+$", "min": 4}}]},
        "c-cdist-all-ok":   {"files": [{"path": "distinct.md",
                                        "count_distinct": {"pattern": r"@kw\d+", "min": 3,
                                                           "scope": "all"}}]},
        "c-cdist-all-bad":  {"files": [{"path": "distinct.md",
                                        "count_distinct": {"pattern": r"@kw\d+", "min": 4,
                                                           "scope": "all"}}]},
        # 同串填充欺骗对照（同一份 many.txt）：-ok 走 min_matches 计总次数 5≥5 仍绿，
        # -bad 走 count_distinct 数唯一只得 1<5 变红——本原语存在的理由即此对照。
        "c-cdist-fill-ok":  {"files": [{"path": "many.txt",
                                        "min_matches": {"pattern": r"\[x\] item", "min": 5}}]},
        "c-cdist-fill-bad": {"files": [{"path": "many.txt",
                                        "count_distinct": {"pattern": r"\[x\] item", "min": 5}}]},
        "c-cdist-fillall-bad": {"files": [{"path": "many.txt",
                                           "count_distinct": {"pattern": r"\[x\] item",
                                                              "min": 5, "scope": "all"}}]},
        # json_files
        "c-json-items-ok":  {"json_files": [{"path": "items_ok.json", "min_items": 1, "max_items": 5}]},
        "c-json-items-bad": {"json_files": [{"path": "items_ok.json", "min_items": 9}]},
        "c-json-max-bad":   {"json_files": [{"path": "items_ok.json", "max_items": 2}]},
        "c-json-keys-ok":   {"json_files": [{"path": "items_ok.json", "require_keys": ["a", "b"]}]},
        "c-json-keys-bad":  {"json_files": [{"path": "items_ok.json", "require_keys": ["zz"]}]},
        "c-json-keysall-ok":  {"json_files": [{"path": "items_ok.json", "require_keys_all": ["a", "b"]}]},
        "c-json-keysall-bad": {"json_files": [{"path": "items_bad.json", "require_keys_all": ["a", "b"]}]},
        # globs
        "c-glob-ok":        {"globs": [{"pattern": "99-batch/*.png", "min_count": 3, "min_bytes_each": 100}]},
        "c-glob-count-bad": {"globs": [{"pattern": "99-batch/*.png", "min_count": 9}]},
        "c-glob-bytes-bad": {"globs": [{"pattern": "99-batch/*.png", "min_bytes_each": 9999}]},
        # globs / ** 递归（审查：曾未传 recursive=True，`**` 静默 0 命中）
        "c-glob-rr-ok":     {"globs": [{"pattern": "**/*.rr", "min_count": 2}]},
        "c-glob-rr-bad":    {"globs": [{"pattern": "**/*.zz", "min_count": 1}]},
        # absent_paths
        "c-absent-ok":      {"absent_paths": ["nothing-here/"]},
        "c-absent-bad":     {"absent_paths": ["residual/old.md"]},
        # run
        "c-run-ok":         {"run": 'python -c "import sys; sys.exit(0)"'},
        "c-run-bad":        {"run": 'python -c "import sys; sys.exit(1)"'},
    }
    expected = {tid: (0 if "-ok" in tid else 1) for tid in M}
    (root / "70-tools" / "71-verify-manifest.json").write_text(
        json.dumps(M, ensure_ascii=False, indent=2), encoding="utf-8")
    return expected


# B8（2026-10-07 审查）基数断言：合成控制矩阵的用例数下限。用例矩阵整体缩小（删掉整类
# 断言的正反控制）时，旧的「N/N 一致」仍会全绿——本常量把「矩阵规模」本身钉住，缩小即红。
SUITE_CASES = 38


def run_suite() -> int:
    with tempfile.TemporaryDirectory() as td:
        root = pathlib.Path(td)
        expected = build_case_root(root)
        r = subprocess.run([sys.executable, "-B", "-X", "utf8", str(VERIFY), "--all", "--quiet",
                            "--json", "--root", str(root)],
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
        text = r.stdout or ""
        try:
            got = json.loads(text[text.index("{"):])["results"]
        except Exception as exc:                                   # noqa: BLE001
            print("无法解析自测输出：%s\n%s" % (exc, text[:800]))
            return 1
        bad = []
        # B8 基数断言：用例矩阵不得整体缩小（源码字面量集对应 SUITE_CASES，缩小即红）。
        if len(expected) != SUITE_CASES:
            bad.append(("suite-cardinality", SUITE_CASES, len(expected)))
        for tid, want in expected.items():
            have = got.get(tid, {}).get("rc")
            if have != want:
                bad.append((tid, want, have))
        # missing-entry 用例：manifest 里没有的任务应返回 rc=2
        r2 = subprocess.run([sys.executable, "-B", "-X", "utf8", str(VERIFY), "no-such-task",
                             "--quiet", "--json", "--root", str(root)],
                            capture_output=True, text=True, encoding="utf-8", errors="replace")
        rc2 = r2.returncode
        print("== 合成控制套件 ==")
        print("  用例 %d，期望与实际一致 %d，不一致 %d" % (len(expected), len(expected) - len(bad),
                                                        len(bad)))
        for tid, want, have in bad:
            print("   MISMATCH %-22s want=%s got=%s" % (tid, want, have))
        ok_missing = (rc2 == 2)
        print("  %-22s want=2 got=%s" % ("c-missing-entry", rc2))
        return 0 if not bad and ok_missing else 1


def run_manifest_guards() -> int:
    """BOM manifest 与空 manifest 都应返回 rc=2（manifest 问题），而非崩溃或静默 PASS。

    对应审查 B1（带 BOM manifest 曾裸 traceback 且 rc=1 混入 FAIL 语义）与
    B2（空 manifest 下 --all 曾 0 任务静默 PASS，门禁空转）。
    """
    cases: list[tuple[str, int]] = []
    with tempfile.TemporaryDirectory() as td:
        root = pathlib.Path(td)
        (root / "70-tools").mkdir(parents=True)
        mp = root / "70-tools" / "71-verify-manifest.json"
        mp.write_text("{}", encoding="utf-8-sig")   # 带 BOM 的空对象（沙盒实际出现过）
        cases.append(("bom-empty-manifest", subprocess.run(
            [sys.executable, "-B", "-X", "utf8", str(VERIFY), "--all", "--quiet", "--json",
             "--root", str(root)],
            capture_output=True, text=True, encoding="utf-8", errors="replace").returncode))
        mp.write_text("{}", encoding="utf-8")        # 无 BOM 纯空对象
        cases.append(("empty-manifest", subprocess.run(
            [sys.executable, "-B", "-X", "utf8", str(VERIFY), "--all", "--quiet", "--json",
             "--root", str(root)],
            capture_output=True, text=True, encoding="utf-8", errors="replace").returncode))
    print("== manifest guards（B1/B2）==")
    bad = 0
    for name, rc in cases:
        print("  %-24s want=2 got=%s  %s" % (name, rc, "OK" if rc == 2 else "MISMATCH"))
        if rc != 2:
            bad += 1
    return 1 if bad else 0


def run_rc_semantics_guards() -> int:
    """--all 的退出码合成规则（2026-09-26 审查：曾用 max() 把真 FAIL 掩盖成 2）。

    口径：有 rc=1 的断言失败 → 整体 1（首要信号）；无失败但有 rc=2（缺条目/manifest
    问题）→ 整体 2；全过 → 0。单任务 missing-entry 仍 2。
    """
    def rc_all(root: pathlib.Path, manifest_text: str) -> int:
        mp = root / "70-tools" / "71-verify-manifest.json"
        mp.write_text(manifest_text, encoding="utf-8")
        return subprocess.run([sys.executable, "-B", "-X", "utf8", str(VERIFY), "--all",
                               "--quiet", "--root", str(root)],
                              capture_output=True, text=True, encoding="utf-8",
                              errors="replace").returncode

    cases = []
    with tempfile.TemporaryDirectory() as td:
        root = pathlib.Path(td)
        (root / "70-tools").mkdir(parents=True)
        (root / "ok.txt").write_text("hello", encoding="utf-8")
        m_mix = json.dumps({"t-ok": {"files": [{"path": "ok.txt"}]},
                            "t-fail": {"files": [{"path": "nope.md"}]},
                            "t-empty": {"files": []}})
        # 混合批：真 FAIL 必须把整体判成 1（旧 max() 语义下若批内再混入 rc=2 会被掩盖；
        # per-task rc=2 在 --all 里构不出——missing-entry 只能来自单任务模式，见后一例）。
        cases.append(("all: mixed batch FAIL -> 1", rc_all(root, m_mix)))
        m_usage = json.dumps([])                                     # 顶层非 dict → 2
        cases.append(("all: non-dict manifest -> 2", rc_all(root, m_usage)))
        m_badjson = "{ not json"
        cases.append(("all: invalid JSON -> 2", rc_all(root, m_badjson)))
        m_ok = json.dumps({"t-ok": {"files": [{"path": "ok.txt"}]}})
        cases.append(("all: all pass -> 0", rc_all(root, m_ok)))
        # missing-entry 单任务
        (root / "70-tools" / "71-verify-manifest.json").write_text(m_ok, encoding="utf-8")
        r = subprocess.run([sys.executable, "-B", "-X", "utf8", str(VERIFY), "ghost-task",
                            "--quiet", "--root", str(root)],
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
        cases.append(("single: missing entry -> 2", r.returncode))
    want = {0: 1, 1: 2, 2: 2, 3: 0, 4: 2}
    print("== 退出码语义守卫 ==")
    bad = 0
    for i, (name, got) in enumerate(cases):
        exp = want[i]
        print("  %-30s want=%d got=%d  %s" % (name, exp, got, "OK" if got == exp else "MISMATCH"))
        if got != exp:
            bad += 1
    return 1 if bad else 0


def pick_profile_fixture(profiles_dir: pathlib.Path, prefer_child: bool = True) -> pathlib.Path | None:
    """运行时选取 CLI 守卫的夹具档（task-selftest-fixture-decouple）：不写死任何领域档文件名。

    prefer_child=True 优先 extends 非空的**子档**（保住"子档继承/deep_merge"类守卫的测试语义）；
    无子档退化任一非 00- 基类档；全缺返回 None——调用方必须显式 SKIP，不得静默判 PASS。
    """
    try:
        files = sorted(p for p in profiles_dir.glob("*.yaml") if not p.name.startswith("00-"))
    except OSError:
        return None
    if not files:
        return None
    if prefer_child:
        for p in files:
            try:
                head = p.read_text(encoding="utf-8-sig")
            except OSError:
                continue
            if re.search(r"^extends:\s*\S", head, re.M):
                return p
    return files[0]


def _generator_required_missing(cases: list, required) -> list:
    """生成器守卫必有用例缺失清单（纯函数，供真实 cases 与反向对照共用）。

    具名棘轮：删任一必有用例即判缺失（E-2 同族：B08b 五例可被静默删除仍全绿）。
    """
    names = {name for name, _ in cases}
    return sorted(n for n in required if n not in names)


# 生成器断言守卫必有用例名集合（B08b 五例 + 关键既有）：段内断言其全部在场。
_GENERATOR_REQUIRED_CASES = frozenset({
    "B08b 路径 token 提取（反引号/标点/非路径均不误收）",
    "B08b 路径 token 幂等去重",
    "B08b 无已知前缀目录 → 不误收（RR/OR/HR 等非路径）",
    "B08b 注入路径自动并入 read（合成档正向）",
    "B08b 反向对照：关闭自动并入 → 该路径不在 read（行为级）",
    "empty-expansion-rejected",
    "binary-covered-nonempty",
})


def run_generator_guards() -> int:
    """断言展开为空 = done 门禁空转，生成器必须拒绝（2026-09-26 审查：redraw/draw-schematics
    曾因通配模板只覆盖文本文件而生成 `{}`）。正反控制：无二进制模板必须 die，有则必须非空。
    """
    tasks = [{"id": "task-fig-only", "files_to_edit": ["40-figures/x.pdf", "40-figures/x.png"]}]
    prof_text_only = {"verify_assertions_template": [
        {"task": "*", "apply_to": "edit_files_text", "forbid": ["TODO"]}]}
    prof_with_bin = {"verify_assertions_template": [
        {"task": "*", "apply_to": "edit_files_text", "forbid": ["TODO"]},
        {"task": "*", "apply_to": "edit_files_binary", "min_bytes_each": 5000}]}
    cases = []
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            gen30.verify_fragment(prof_text_only, tasks)
        cases.append(("empty-expansion-rejected", False))          # 没抛 die = 失败
    except SystemExit:
        cases.append(("empty-expansion-rejected", True))
    frag = gen30.verify_fragment(prof_with_bin, tasks)
    entry = frag["task-fig-only"]
    cases.append(("binary-covered-nonempty",
                  len(entry.get("files", [])) == 2
                  and all(f.get("min_bytes") == 5000 for f in entry["files"])))
    # F1（2026-10-06 审查）：manifest 本体不做文本自查——通配 forbid 落到 verify manifest
    # 上是自指死锁（生成的 manifest JSON 必然含 AUTHOR CONFIRM/TODO 词本身），两制路径都验。
    def _manifest_clean(frag_: dict, mpath: str) -> bool:
        for e_ in frag_.values():
            for f_ in e_.get("files", []):
                if f_.get("path", "").replace("\\", "/") == mpath \
                        and set(f_.keys()) - {"path", "min_bytes"}:
                    return False
        return True
    for prof_name in ("10-materials-chemistry.yaml",):
        prof_m = gen30.load_profile(HERE.parent / "profiles" / prof_name)
        with contextlib.redirect_stdout(io.StringIO()):
            built_m = gen30.build(prof_m)
            frag_m = gen30.verify_fragment(prof_m, built_m["tasks"])
        mpath = gen30.profile_manifest_path(prof_m)
        touched = any(f.get("path", "").replace("\\", "/") == mpath
                      for e in frag_m.values() for f in e.get("files", []))
        cases.append(("manifest-self-forbid:%s" % prof_name,
                      touched and _manifest_clean(frag_m, mpath)))
        # 反向对照：把判定拆掉（给 manifest 塞回 forbid 词）→ 探针必须变红
        dirty = json.loads(json.dumps(frag_m))
        for e in dirty.values():
            for f in e.get("files", []):
                if f.get("path", "").replace("\\", "/") == mpath:
                    f["forbid"] = ["TODO"]
        cases.append(("manifest-self-forbid-reversed:%s" % prof_name,
                      not _manifest_clean(dirty, mpath)))
    # 真实 profile 全量：每个任务展开后至少一条断言。抽象父档（被任何 extends 引用的）
    # 从不独立生成，不适用此口径，跳过。
    parents = set()
    for prof in (HERE.parent / "profiles").glob("*.yaml"):
        for line in prof.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith("extends:"):
                parents.add(line.split(":", 1)[1].strip())
    for prof in sorted((HERE.parent / "profiles").glob("*.yaml")):
        if prof.name in parents:
            continue
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                built = gen30.build(gen30.load_profile(prof))
            f = gen30.verify_fragment(gen30.load_profile(prof), built["tasks"])
            cases.append(("real:%s" % prof.name,
                          bool(built["tasks"]) and all(
                              any(e.get(k) for k in ("files", "json_files", "globs", "absent_paths"))
                              or e.get("run") for e in f.values())))
        except SystemExit:
            cases.append(("real:%s" % prof.name, False))
    # emit 幂等：profile 删任务后，陈旧 task-*.json 必须被清理（审查：曾只增不删）
    with tempfile.TemporaryDirectory() as td:
        out = pathlib.Path(td) / "build"
        fixture = pick_profile_fixture(HERE.parent / "profiles")
        if fixture is None:
            print("  SKIP  emit-stale-proposal-pruned（profiles 无可生成领域档，不判 PASS）")
        else:
            prof = gen30.load_profile(fixture)
            built = gen30.build(prof)
            with contextlib.redirect_stdout(io.StringIO()):
                gen30.emit(built, prof, out)
            stale = out / "proposals" / "task-zz-stale.json"
            stale.write_text("{}", encoding="utf-8")
            with contextlib.redirect_stdout(io.StringIO()):
                gen30.emit(built, prof, out)
            cases.append(("emit-stale-proposal-pruned", not stale.exists()))
    # B06 收尾：fulltext_gate.mode 的真消费——声明 strict 必须有终局机器门（缺门=生成期 problems）。
    cl_prof = gen30.load_profile(HERE.parent / "profiles" / "10-clinical.yaml")
    cases.append(("fulltext-gate:clinical 合规 → 无该问题",
                  not gen30._fulltext_gate_problems(cl_prof)))
    mut_prof = copy.deepcopy(cl_prof)
    mut_prof["verify_assertions_template"] = [
        a for a in mut_prof["verify_assertions_template"]
        if not (a.get("task") == "task-finalize-manuscript"
                and any(str(i.get("path", "")).endswith("22-refs.json")
                        for i in (a.get("json_files") or [])))]
    with contextlib.redirect_stdout(io.StringIO()):
        built_mut = gen30.build(mut_prof)
    cases.append(("fulltext-gate:clinical 摘掉终局门 → build problems 点名（CLI rc=1）",
                  any("fulltext_gate.mode=strict" in p for p in built_mut["problems"])))
    cases.append(("fulltext-gate:advisory 不要求门（防过度收紧）",
                  gen30._fulltext_gate_problems(
                      {"id": "x", "tasks": [{"id": "task-finalize-manuscript"}],
                       "citation_policy": {"fulltext_gate": {"mode": "advisory"}}}) == []))
    cases.append(("fulltext-gate:无终局任务的模板档不适用",
                  gen30._fulltext_gate_problems(
                      {"id": "x", "tasks": [{"id": "task-back-matter"}],
                       "citation_policy": {"fulltext_gate": {"mode": "strict"}}}) == []))
    # B08b：域口径注入文案里的路径形态 token 自动并入该任务 read（一处集中，免逐档手写）。
    _pprof = {"paths": {"data": "10-data", "lit": "20-lit"}, "tool_dir": "70-tools"}
    cases.append(("B08b 路径 token 提取（反引号/标点/非路径均不误收）",
                  gen30.policy_path_tokens(_pprof, [
                      "数值取自 10-data/11-analysis.md；源 20-lit/x.json；划分 train/val/test；"
                      "RR/OR/HR=1；PDF/doc；significantly/outperforms；取 `10-data/b.md` 尾句点 10-data/c.md."
                  ]) == ["10-data/11-analysis.md", "20-lit/x.json", "10-data/b.md", "10-data/c.md"]))
    cases.append(("B08b 路径 token 幂等去重",
                  gen30.policy_path_tokens(_pprof, ["10-data/a.md 与 10-data/a.md"]) == ["10-data/a.md"]))
    cases.append(("B08b 无已知前缀目录 → 不误收（RR/OR/HR 等非路径）",
                  gen30.policy_path_tokens({"paths": {"data": "10-data"}},
                                           ["RR/OR/HR=1；train/val/test；significantly/outperforms"]) == []))
    _min_prof = {
        "id": "b08", "version": "1", "tool_dir": "70-tools",
        "paths": {"data": "10-data"},
        "project": {"name": "x", "brief": "b", "review_mode": "unified"},
        "modules": [{"id": "m", "name": "m", "role": "r"}],
        "evidence_policy": {"p": "数值取自 10-data/11-analysis.md 逐值核对"},
        "tasks": [{"id": "task-x", "module": "m", "name": "n", "brief": "b",
                   "ac": ["`10-data/out.md` 逐值核对。", "不得臆造。", "结论落边界。"],
                   "inject": ["p"], "read": [], "edit": ["10-data/out.md"],
                   "verify": "python {verify_tool} task-x"}],
        "verify_assertions_template": [{"task": "*", "apply_to": "edit_files_text",
                                        "forbid": ["TODO"]}],
    }

    def _min_reads():
        with contextlib.redirect_stdout(io.StringIO()):
            b = gen30.build(_min_prof)
        return {r["path"] for r in {t["id"]: t for t in b["tasks"]}["task-x"]["files_to_read"]}

    cases.append(("B08b 注入路径自动并入 read（合成档正向）",
                  "10-data/11-analysis.md" in _min_reads()))
    # 反向对照（行为级）：关闭自动并入（monkeypatch 提取函数返回空）→ 该路径不在 read。
    _orig_ppt = gen30.policy_path_tokens
    gen30.policy_path_tokens = lambda *a, **k: []
    try:
        _off = "10-data/11-analysis.md" not in _min_reads()
    finally:
        gen30.policy_path_tokens = _orig_ppt
    cases.append(("B08b 反向对照：关闭自动并入 → 该路径不在 read（行为级）", _off))
    # 具名必有用例棘轮：必有用例名须全部在场；删任一即判缺失。反向对照用从未在案例中
    # 的假名走同一函数，证明缺失判定真咬得住（行为级）。
    _missing_required = _generator_required_missing(cases, _GENERATOR_REQUIRED_CASES)
    _ghost = "__ghost-generator-case从未在案例中__"
    _ghost_missing = _generator_required_missing(cases, _GENERATOR_REQUIRED_CASES | {_ghost})
    _ghost_ok = _ghost_missing == [_ghost]
    print("== 生成器断言守卫 ==")
    bad = 0
    for name, ok in cases:
        print("  %-44s %s" % (name, "OK" if ok else "MISMATCH"))
        if not ok:
            bad += 1
    print("  %-44s %s" % ("具名必有用例棘轮（%d 例全在场）" % len(_GENERATOR_REQUIRED_CASES),
                          "OK" if not _missing_required else "MISMATCH 缺失 %s" % _missing_required))
    if _missing_required:
        bad += 1
    print("  %-44s %s" % ("反向对照：假名（从未在案例中）→ 判缺失", "OK" if _ghost_ok else "MISMATCH"))
    if not _ghost_ok:
        bad += 1
    return 1 if bad else 0


def run_gen_cli_guards() -> int:
    """N-4（--check/--regress 缺 --project 静默走 emit 落盘）与 N-10（P-1 注入假设）的守卫。

    每类各带一条**锚点**：把旧的口径本身放进子进程跑，证明故障条件真实存在（旧控制流确实
    rc=0 且落了文件 / 旧注入循环在缺锚任务时静默），否则守卫只是陪着修复变绿的装饰。
    """
    cases: list[tuple[str, bool, str]] = []
    gen = HERE / "30-gen-proposals.py"
    profiles = HERE.parent / "profiles"
    mat = profiles / "10-materials-chemistry.yaml"
    fx = pick_profile_fixture(profiles)
    if fx is None:
        print("  SKIP  CLI 夹具档缺失（profiles 无可生成领域档）——相关用例显式跳过，不判 PASS")

    def call(*args, cwd: pathlib.Path | None = None) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, "-B", "-X", "utf8", str(gen), *args],
                              capture_output=True, text=True, encoding="utf-8",
                              errors="replace", cwd=str(cwd) if cwd else None)

    def snippet(code: str, *argv) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, "-B", "-c", code, *argv], capture_output=True,
                              text=True, encoding="utf-8", errors="replace")

    def emptied(d: pathlib.Path) -> bool:
        return not d.exists() or not any(d.rglob("*"))

    with tempfile.TemporaryDirectory() as td:
        base = pathlib.Path(td)

        # ==== 类 1：缺 --project 的口径（N-4）====
        anchor = snippet(
            "import pathlib,sys\n"
            "out = pathlib.Path(sys.argv[1])\n"
            "(out / 'proposals').mkdir(parents=True)         # 旧口径：emit 无条件先跑\n"
            "(out / '_master.fragment.json').write_text('{}')\n"
            "project = ''                                    # 未给 --project\n"
            "rc = 0\n"
            "if project:                                     # 旧口径：核对整段被包在这里\n"
            "    rc |= 1\n"
            "sys.exit(rc)\n",
            str(base / "anchor"))
        files = list((base / "anchor").rglob("*")) if (base / "anchor").exists() else []
        cases.append(("锚点：旧控制流缺项目仍 rc=0 且落文件",
                      anchor.returncode == 0 and len(files) >= 2,
                      "rc=%d files=%d" % (anchor.returncode, len(files))))
        if fx is not None:
            for flag in ("--check", "--regress"):
                outdir = base / flag.lstrip("-")
                r = call("--profile", str(fx), flag, "--out", str(outdir))
                cases.append(("%s 缺 --project → rc=2（非静默 0）" % flag, r.returncode == 2,
                              "rc=%d %s" % (r.returncode, (r.stdout or r.stderr)[-90:])))
                cases.append(("%s 的消息点名参数 project" % flag,
                              "project" in (r.stdout + r.stderr),
                              "stdout=%r" % (r.stdout or "")[-120:]))
                left = [x.name for x in outdir.rglob("*")] if outdir.exists() else []
                cases.append(("%s 缺 --project 不落任何生成物" % flag, not left, "落了 %s" % left))
            plain = call("--profile", str(fx), "--out", str(base / "plain"))
            cases.append(("纯生成路径仍 rc=0 且落盘（防过度收紧）",
                          plain.returncode == 0 and not emptied(base / "plain"),
                          "rc=%d %s" % (plain.returncode, (plain.stdout or plain.stderr)[-90:])))
            both = call("--profile", str(fx), "--check",
                        "--project", str(base / "noparam"), "--out", str(base / "withproj"))
        # 这里不要求 rc=0（那个"项目"没有 .orchd/，引擎侧当然会报），只要求**不是**被
        # 本任务新增的参数守卫拦下——否则等于把正路也堵了。
            cases.append(("给了 --project 就不被新守卫拦下（不误伤正路）",
                          "必须同时给" not in (both.stdout + both.stderr),
                          "rc=%d %s" % (both.returncode, (both.stdout or both.stderr)[-140:])))

        # ==== 类 2：docstring 与 argparse 的旗标口径（N-4 文档面）====
        h = call("--help")
        declared = set(re.findall(r"(?<!\w)--[a-z][a-z0-9-]*", h.stdout or ""))
        doc = gen.read_text(encoding="utf-8").split('"""')[1]
        usage = [ln.strip() for ln in doc.splitlines()
                 if ln.strip().startswith("python") and "30-gen-proposals.py" in ln]
        documented = set()
        for ln in usage:
            documented |= set(re.findall(r"--[a-z][a-z0-9-]*", ln))
        cases.append(("docstring 用法条数 = 3（生成/check/regress）", len(usage) == 3,
                      "实为 %d：%s" % (len(usage), usage)))
        cases.append(("docstring 旗标全部为 argparse 实际接受项",
                      bool(documented) and documented <= declared,
                      "多出 %s" % sorted(documented - declared)))
        cases.append(("核对类用法行一律带 --project",
                      all(("--project" in ln) for ln in usage if "--check" in ln or "--regress" in ln),
                      "缺 --project 的用法行见上"))
        pos = re.findall(r"--(?:check|regress)\s+<", doc)
        cases.append(("位置参数写法 --regress <项目> 命中 0", not pos, "命中 %s" % pos))
        if fx is not None:
            legacy = call("--profile", str(fx), "--regress", str(HERE.parent))
            cases.append(("锚点：位置参数写法必被 argparse 拒（rc=2）",
                          legacy.returncode == 2 and "unrecognized" in (legacy.stderr or ""),
                          "rc=%d %s" % (legacy.returncode, (legacy.stderr or "")[-90:])))

        # ==== 类 3：multi-paper 的 P-1 注入假设（N-10）====
        anchor = snippet(
            "tasks = [{'id': 'task-audit-dataX', 'depends_on': []}]\n"
            "for t in tasks:                                  # 旧口径：只遍历，不校验锚任务在不在\n"
            "    if t['id'] == 'task-audit-data':\n"
            "        t['depends_on'].append('task-data-asset-mapping')\n"
            "print('silent-ok')\n")
        cases.append(("锚点：旧注入循环缺锚任务时静默无报错",
                      anchor.returncode == 0 and "silent-ok" in (anchor.stdout or ""),
                      "rc=%d %s" % (anchor.returncode, (anchor.stderr or "")[-90:])))
        prof = gen30.load_profile(mat)
        prof.setdefault("entry", {})["mode"] = "multi-paper"
        prof["tasks"] = [t for t in prof["tasks"] if t.get("id") != "task-audit-data"]
        # 把 depends 里对它的引用一并摘掉：否则通用「未知依赖」检查会先报错，
        # 看不出 P-1 守卫本身有没有生效。
        prof["depends"] = {k: [d for d in v if d != "task-audit-data"]
                           for k, v in (prof.get("depends") or {}).items()}
        built = gen30.build(prof)
        hit = [p for p in built["problems"] if "task-data-asset-mapping" in p
               and "task-audit-data" in p]
        cases.append(("删 task-audit-data 后 multi-paper 生成必报错（含两个任务名）",
                      bool(hit), "problems=%s" % built["problems"][:2]))
        cases.append(("报错不靠通用未知依赖检查兜底",
                      not any("depends_on unknown task" in p for p in built["problems"]),
                      "见 %s" % built["problems"][:2]))
        kept = gen30.load_profile(mat)
        kept.setdefault("entry", {})["mode"] = "multi-paper"
        bk = gen30.build(kept)
        ad = [t for t in bk["tasks"] if t["id"] == "task-audit-data"]
        cases.append(("保留 task-audit-data 时 0 问题且 P-1 有人依赖",
                      not bk["problems"] and ad
                      and "task-data-asset-mapping" in ad[0]["depends_on"],
                      "problems=%s" % bk["problems"][:2]))
        datafirst = gen30.build(gen30.load_profile(mat))
        cases.append(("data-first 模式不注册 P-1（默认档不误伤）",
                      not any(t["id"] == "task-data-asset-mapping" for t in datafirst["tasks"])
                      and not datafirst["problems"],
                      "problems=%s" % datafirst["problems"][:2]))
        zero_pairs = [("materials", mat)] + ([(fx.stem, fx)] if fx is not None else [])
        for name, path in zero_pairs:
            b = gen30.build(gen30.load_profile(path))
            cases.append(("%s 档生成期 0 问题（零回归）" % name, not b["problems"],
                          "problems=%s" % b["problems"][:2]))

        # ==== 类 3b：基类模板档单独生成（F-4，2026-09-29 审查）====
        # 基类的任务依赖仅在领域子档定义（task-back-matter → task-finalize-manuscript），
        # 旧口径以 rc=1「depends_on unknown task」收场且不说明原因。新口径：die() 归
        # rc=2 用法错，消息点明 extends 模板语义并指路领域子档；build() 在 emit 之前
        # die，不落任何生成物。子档不受影响的反向对照即上方"生成期 0 问题"组。
        base_prof = profiles / "00-base-empirical.yaml"
        if base_prof.exists():
            rbase = call("--profile", str(base_prof), "--out", str(base / "basetpl"))
            cases.append(("基类单独生成 → rc=2（不再 rc=1 自检未过）",
                          rbase.returncode == 2,
                          "rc=%d out=%r" % (rbase.returncode, (rbase.stdout or "")[-110:])))
            cases.append(("基类诊断消息含「extends 模板」与「领域子档」指引",
                          "extends 模板" in (rbase.stdout + rbase.stderr)
                          and "领域子档" in (rbase.stdout + rbase.stderr),
                          "out=%r" % (rbase.stdout or "")[-160:]))
            cases.append(("基类诊断不落任何生成物（先拒后写）",
                          not (base / "basetpl").exists() or not any((base / "basetpl").rglob("*")),
                          "rc=%d" % rbase.returncode))

        # ==== 夹具选取函数反向对照（合成 profiles 目录，不落盘真文件）====
        with tempfile.TemporaryDirectory() as tp:
            pdir = pathlib.Path(tp) / "profiles"
            pdir.mkdir()
            (pdir / "00-base.yaml").write_text("id: base\n", encoding="utf-8")
            cases.append(("夹具选取：仅基类（00- 排除）→ None（SKIP 语义）",
                          pick_profile_fixture(pdir) is None, ""))
            (pdir / "10-child.yaml").write_text("id: child\nextends: 00-base.yaml\n", encoding="utf-8")
            picked = pick_profile_fixture(pdir)
            cases.append(("夹具选取：基类+子档→选中子档（继承语义保留）",
                          picked is not None and picked.name == "10-child.yaml", ""))
            (pdir / "20-plain.yaml").write_text("id: plain\n", encoding="utf-8")
            picked2 = pick_profile_fixture(pdir)
            cases.append(("夹具选取：子档优先于普通档",
                          picked2 is not None and picked2.name == "10-child.yaml", ""))
            (pdir / "10-child.yaml").unlink()
            picked3 = pick_profile_fixture(pdir)
            cases.append(("夹具选取：无子档退化任一非基类档",
                          picked3 is not None and picked3.name == "20-plain.yaml", ""))

    print("== 生成器 CLI 与 P-1 注入守卫（N-4/N-10）==")
    bad = 0
    for name, ok, detail in cases:
        print("  %-44s %s%s" % (name, "OK" if ok else "MISMATCH",
                                "" if ok or not detail else "  " + detail))
        if not ok:
            bad += 1
    return 1 if bad else 0


def _legacy_rules_fragment(profile: dict) -> str:
    """**改动前**（尚无碎片能力时）的 `rules_fragment` 逐字冻结副本，含它依赖的 `_render_scalar`。

    零回归守卫拿它比对 sha256。副本刻意不调用 gen30 的实现——否则本体改了基线跟着改，
    守卫就成了陪跑。基线变了要显式改这里，这是有意的摩擦。
    """
    # F8（2026-10-07 审查）：rules_fragment 现对 policy 文案走 {paths} 占位替换——冻结副本
    # 同步该行为（否则新源 {data} 经旧副本渲染成未解析占位符，与生成物必然不一致）。
    ctx = dict(profile.get("paths") or {})
    if profile.get("tool_dir"):
        ctx["tool_dir"] = profile["tool_dir"]

    def fmt(s):
        try:
            return s.format(**ctx)
        except (KeyError, IndexError, ValueError):
            return s

    def render(v):
        if isinstance(v, dict):
            return "；".join("%s=%s" % (k, render(x)) for k, x in v.items())
        if isinstance(v, list):
            return "；".join(render(x) for x in v)
        return fmt(str(v))

    pol = profile["evidence_policy"]
    lines = ["# 域口径规则片段（由 profiles/%s 生成，请并入项目 `rules/`）" % profile["id"], ""]
    for k, v in pol.items():
        lines.append("- **%s**：%s" % (k, render(v)))
    for key in ("figure_policy", "citation_policy"):
        if key in profile:
            lines += ["", "## %s" % key]
            for k, v in profile[key].items():
                lines.append("- **%s**：%s" % (k, render(v)))
    return "\n".join(lines) + "\n"


def run_fragment_guards() -> int:
    """static/ 规则碎片能力（规格 `references/60-capability-specs.md` §3）的守卫。

    §3.5 点名的三条里有两条是**否定条件**：未声明零回归、未知 id 必须 die。缺任一条，
    「注入」这件事就等于没检查——正则没覆盖到不等于检查过且干净。另加 manifest 结构守卫，
    把 AC1（≥3 条目、axes ≥2 键、碎片文件在盘）钉成机检而不是靠人看。
    每条正向守卫都配反向对照（把故障条件真造出来一次），否则守卫会陪着修复一起空转变绿。
    """
    import hashlib
    import yaml

    cases: list[tuple[str, bool, str]] = []
    static = HERE.parent / "static"
    gen = HERE / "30-gen-proposals.py"
    profiles = HERE.parent / "profiles"

    # ---- AC1：manifest 结构与碎片文件在盘 ----
    mpath = static / "manifest.yaml"
    idx: dict = {}
    try:
        data = yaml.safe_load(mpath.read_text(encoding="utf-8-sig"))
    except Exception as exc:                                       # noqa: BLE001
        data = None
        cases.append(("manifest.yaml 可读且是合法 YAML", False, repr(exc)))
    if data:
        entries = data.get("fragments")
        ids = [e.get("id") for e in entries or [] if isinstance(e, dict)]
        idx = {e.get("id"): e for e in entries or [] if isinstance(e, dict)}
        cases.append(("碎片条目数 ≥3", isinstance(entries, list) and len(entries) >= 3,
                      "实际 %s" % (len(entries) if isinstance(entries, list) else entries)))
        cases.append(("首条为 elsevier-numbered", bool(ids) and ids[0] == "elsevier-numbered",
                      "首条=%s" % (ids[:1])))
        cases.append(("id 无重复", len(ids) == len(set(ids)), str(ids)))
        cases.append(("version 为 1", str(data.get("version")) == "1", repr(data.get("version"))))
        thin = [i for i, e in idx.items()
                if not isinstance(e.get("axes"), dict) or len(e.get("axes")) < 2]
        cases.append(("每条 axes ≥2 键", not thin, str(thin)))
        allowed = set(gen30.FRAGMENT_AXES_KEYS)
        stray = {i: sorted(set(e.get("axes", {})) - allowed) for i, e in idx.items()
                 if isinstance(e.get("axes"), dict)}
        cases.append(("axes 键 ⊆ 允许集合", not [k for k, v in stray.items() if v],
                      str({k: v for k, v in stray.items() if v})))
        gone = [i for i, e in idx.items()
                if not e.get("fragment") or not (static / str(e["fragment"])).exists()]
        cases.append(("每条 fragment 文件在盘", not gone, str(gone)))
        asciiish = [i for i, e in idx.items()
                    if not re.fullmatch(r"[A-Za-z0-9._-]+\.md", str(e.get("fragment", "")))]
        cases.append(("碎片文件名为平铺 ASCII kebab-case", not asciiish, str(asciiish)))

    # ---- AC2：零回归（未声明档）+ 激活白名单（F7，2026-10-06）----
    # materials 档已真实激活三碎片——白名单对账取代原「零激活判负」；
    # 其余档维持未声明零回归（与 _legacy 冻结实现 sha256 对拍 + 「完全不读 manifest」证明）。
    # 这里**不**沿用 run_generator_guards 的「跳过被 extends 引用的父档」口径：那条排除的是
    # 断言展开为空的抽象档，而规则片段本体对任何档都成立，父档恰恰是最可能被声明碎片的一档。
    ACTIVATED = {"10-materials-chemistry.yaml": ["elsevier-numbered", "md-single-source",
                                                "lab-experimental-reporting"]}
    with tempfile.TemporaryDirectory() as td:
        empty_static = pathlib.Path(td) / "no-such-static"
        empty_static.mkdir()
        for prof_path in sorted(profiles.glob("*.yaml")):
            prof = gen30.load_profile(prof_path)
            declared = list(prof.get("fragments") or [])
            if prof_path.name in ACTIVATED:
                want = ACTIVATED[prof_path.name]
                cases.append(("%s 激活白名单对账" % prof_path.name, declared == want,
                              "declared=%s want=%s" % (declared, want)))
                out = gen30.rules_fragment(prof)
                got_ids = [ln[len("<!-- fragment: "):-len(" -->")]
                           for ln in out.splitlines() if ln.startswith("<!-- fragment: ")]
                cases.append(("%s 注入 marker 齐且按声明序" % prof_path.name, got_ids == want,
                              str(got_ids)))
                legacy = _legacy_rules_fragment(prof)
                cases.append(("%s 碎片正文真实注入（输出 ≠ 冻结旧实现）" % prof_path.name,
                              out != legacy,
                              "sha256 %s vs %s" % (hashlib.sha256(out.encode()).hexdigest()[:12],
                                                   hashlib.sha256(legacy.encode()).hexdigest()[:12])))
                # 反向对照：声明缺一件 → marker 序不再等于白名单（判定真咬得住）
                try:
                    with contextlib.redirect_stdout(io.StringIO()):
                        broken = gen30.rules_fragment({**prof, "fragments": want[:2]})
                    got2 = [ln[len("<!-- fragment: "):-len(" -->")]
                            for ln in broken.splitlines() if ln.startswith("<!-- fragment: ")]
                    cases.append(("%s 反向对照：声明缺失即判不齐" % prof_path.name,
                                  got2 != want, str(got2)))
                except SystemExit:
                    cases.append(("%s 反向对照：声明缺失即判不齐" % prof_path.name,
                                  True, "die 亦算咬住"))
                continue
            if declared:
                cases.append(("未激活档 %s 声明了 fragments" % prof_path.name, False,
                              "白名单外声明 → 零回归基线失守"))
                continue
            new = hashlib.sha256(gen30.rules_fragment(prof).encode("utf-8")).hexdigest()
            old = hashlib.sha256(_legacy_rules_fragment(prof).encode("utf-8")).hexdigest()
            cases.append(("%s 未声明：与改动前逐字节一致" % prof_path.name, new == old,
                          "sha256 %s vs %s" % (new[:12], old[:12])))
            blank = hashlib.sha256(
                gen30.rules_fragment(prof, empty_static).encode("utf-8")).hexdigest()
            cases.append(("%s 未声明：manifest 不在也不影响（不读）" % prof_path.name,
                          blank == new, "sha256 %s vs %s" % (blank[:12], new[:12])))
            # 反向对照：同一份空目录下**声明**碎片必须 die，证明上一条的绿不是恒真
            try:
                with contextlib.redirect_stdout(io.StringIO()):
                    gen30.rules_fragment({**prof, "fragments": ["elsevier-numbered"]}, empty_static)
                cases.append(("%s 反向对照：声明后空目录要 die" % prof_path.name, False,
                              "没抛 SystemExit → 「不读」那条守卫是空转"))
            except SystemExit as exc:
                cases.append(("%s 反向对照：声明后空目录要 die" % prof_path.name,
                              exc.code not in (0, None), "rc=%s" % exc.code))

    # ---- AC3：声明后 marker + 正文原样 + 顺序 = 声明顺序 ----
    with tempfile.TemporaryDirectory() as td:
        tmp = pathlib.Path(td)
        sdir = tmp / "static"
        sdir.mkdir()
        body_a = "    首行带四格缩进\n\n下一段前有空的行\n末行\n"
        (sdir / "aa-first.md").write_text(body_a + "\n\n", encoding="utf-8")
        (sdir / "bb-second.md").write_text("# 第二片\n\ntext\n", encoding="utf-8")
        (sdir / "manifest.yaml").write_text(
            "version: 1\nfragments:\n"
            "  - id: bb-second\n    fragment: bb-second.md\n"
            "    axes: {publisher: springer, language: en}\n"
            "  - id: aa-first\n    fragment: aa-first.md\n"
            "    axes: {publisher: elsevier, language: en}\n", encoding="utf-8")
        prof = gen30.load_profile(profiles / "10-materials-chemistry.yaml")
        prof = {**prof, "fragments": ["aa-first", "bb-second"]}   # 声明顺序与 manifest 相反
        cap = io.StringIO()
        with contextlib.redirect_stdout(cap):
            out = gen30.rules_fragment(prof, sdir)
        exp_a = "<!-- fragment: aa-first -->\n" + body_a.rstrip("\n") + "\n"
        exp_b = "<!-- fragment: bb-second -->\n# 第二片\n\ntext\n"
        cases.append(("AC3 顺序=声明顺序且逐字节块（缩进/空行/标记全原样）",
                      out.endswith(exp_a + "\n" + exp_b), repr(out[-90:])))
        cases.append(("AC3 marker 行独占一行", out.count("<!-- fragment: ") == 2
                      and "\n<!-- fragment: aa-first -->\n" in out, ""))
        cases.append(("AC3 axes 不符只 warn 不改判定",
                      "warn" in cap.getvalue() and "bb-second" in cap.getvalue(), ""))
        cases.append(("AC3 未声明时输出无 marker",
                      "<!-- fragment:" not in gen30.rules_fragment(
                          {k: v for k, v in prof.items() if k != "fragments"}, sdir), ""))

    # ---- AC4/AC5：未知 id 走子进程真实退出码，且不得留下半份生成物 ----
    with tempfile.TemporaryDirectory() as td:
        tmp = pathlib.Path(td)
        prof = gen30.load_profile(profiles / "10-materials-chemistry.yaml")
        ghost = "ghost-fragment-9k2"
        pf = tmp / "ghost-profile.yaml"
        pf.write_text(yaml.safe_dump({**prof, "fragments": [ghost]}, allow_unicode=True),
                      encoding="utf-8")
        build = tmp / "build"
        r = subprocess.run([sys.executable, "-B", "-X", "utf8", str(gen),
                            "--profile", str(pf), "--out", str(build)],
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
        born = (r.stdout or "") + (r.stderr or "")
        cases.append(("AC4 未知 id：子进程 rc≠0", r.returncode != 0, "rc=%d" % r.returncode))
        cases.append(("AC4 未知 id：消息含该 id", ghost in born, born[:120]))
        cases.append(("AC4 未知 id：消息列出已知 id",
                      "elsevier-numbered" in born and "md-single-source" in born, ""))
        cases.append(("AC4 未知 id：消息不含本机绝对路径",
                      not re.search(r"[A-Za-z]:[\\/]|\\\\Users\\\\", born), ""))
        leftovers = sorted(p.name for p in build.rglob("*")) if build.exists() else []
        cases.append(("AC4 未知 id：先拒后写（不留半份生成物）", not leftovers, str(leftovers)[:120]))
        # 反向对照：同一条命令去掉 ghost 声明必须 rc=0 且落盘，证明上一条的「空」是拒绝而非崩溃
        pf.write_text(yaml.safe_dump(prof, allow_unicode=True), encoding="utf-8")
        r2 = subprocess.run([sys.executable, "-B", "-X", "utf8", str(gen),
                             "--profile", str(pf), "--out", str(build)],
                            capture_output=True, text=True, encoding="utf-8", errors="replace")
        cases.append(("AC4 反向对照：去掉声明后正常落盘 rc=0",
                      r2.returncode == 0 and (build / "rules.fragment.md").exists(),
                      "rc=%d" % r2.returncode))

    # ---- D1–D4：索引字段形态与正文编码的强制点（2026-09-27 code 审查返工）----
    # 这组判据测的是"规格写了没强制"：`../`、绝对路径、子目录、非 .md、非字符串字段、
    # 非 UTF-8 正文都必须 rc=2 明拒。缺任一条，索引里一个笔误就会把**别的文件**当规则静默注入。
    with tempfile.TemporaryDirectory() as td:
        tmp = pathlib.Path(td)
        sdir = tmp / "static"
        sdir.mkdir()
        good_manifest = ("version: 1\nfragments:\n  - id: good\n    fragment: good.md\n"
                         "    axes: {publisher: elsevier, language: en}\n")
        (sdir / "good.md").write_text("# 好片\n\n正文\n", encoding="utf-8")
        (tmp / "outside.md").write_text("包外正文\n", encoding="utf-8")
        (sdir / "sub").mkdir()
        (sdir / "sub" / "nested.md").write_text("嵌套正文\n", encoding="utf-8")
        (sdir / "good.txt").write_text("非 md 正文\n", encoding="utf-8")
        (sdir / "gbk.md").write_bytes("# 好片\n\n中文正文在此\n".encode("gbk"))
        (sdir / "marker.md").write_text("正文\n\n<!-- fragment: fake -->\n冒名 marker\n",
                                         encoding="utf-8")
        prof0 = gen30.load_profile(profiles / "10-materials-chemistry.yaml")

        def reject(tag, manifest_text, declared=("good",), needle=""):
            """把故障真造一次：期望 die(rc=2) + 有 ERROR: + 不回显本机绝对路径。"""
            (sdir / "manifest.yaml").write_text(manifest_text, encoding="utf-8")
            cap = io.StringIO()
            code, crashed = None, None
            try:
                with contextlib.redirect_stdout(cap):
                    gen30.fragment_blocks({**prof0, "fragments": list(declared)}, sdir)
            except SystemExit as exc:
                code = exc.code
            except Exception as exc:                                   # noqa: BLE001
                crashed = repr(exc)                                    # 期望 die，不接受 traceback
            msg = cap.getvalue()
            if crashed:
                cases.append((tag, False, "以崩代拒：%s" % crashed))
            elif code is None:
                cases.append((tag, False, "未 die → 该失败面静默放过"))
            else:
                cases.append((tag, code == 2 and "ERROR:" in msg
                              and not re.search(r"[A-Za-z]:[\\/]", msg)
                              and (needle in msg if needle else True),
                              "rc=%s %s" % (code, msg.strip()[-140:] or "无输出")))

        def one(kind_frag, kind_id=None):
            return ("version: 1\nfragments:\n  - id: %s\n    fragment: %s\n"
                    "    axes: {publisher: elsevier, language: en}\n"
                    % (kind_id or "good", kind_frag))

        reject("D1 fragment 为列表 → rc=2 明拒", one("[good.md]"))
        reject("D1 fragment 为整数 → rc=2 明拒", one("123"))
        reject("D1 id 为整数 → rc=2（含报错消息构造本身不崩）", one("good.md", kind_id="1"),
               declared=("1",))
        reject("D1 id 为空串 → rc=2", one("good.md", kind_id='""'))
        reject("D3 fragment 越界 ../ → rc=2（不得把包外文件当规则）",
               one("../outside.md"))
        reject("D3 fragment 带子目录 → rc=2（§3.1 平铺）", one("sub/nested.md"))
        reject("D3 fragment 非 .md → rc=2", one("good.txt"))
        reject("D3 fragment 为绝对路径 → rc=2", one('"%s"' % str(tmp / "outside.md").replace("\\", "/")))
        reject("D3 axes 非映射 → rc=2 且不回显本体",
               "version: 1\nfragments:\n  - id: good\n    fragment: good.md\n"
               "    axes: [publisher, elsevier]\n")
        reject("D4 正文非 UTF-8 → rc=2（不得乱码注入/不得崩）", one("gbk.md"))
        reject("O2 正文含注入标记 → rc=2（marker 由拼接层独占）", one("marker.md"))
        reject("O1 声明重复 → rc=2（与索引侧重复 id 对称）", good_manifest,
               declared=("good", "good"))
        reject("D1 声明元素非字符串 → rc=2", good_manifest, declared=("good", 1))
        # 反向对照：以上全部故障条件都不在时，必须逐字节注入成功
        (sdir / "manifest.yaml").write_text(good_manifest, encoding="utf-8")
        cap_ok = io.StringIO()
        with contextlib.redirect_stdout(cap_ok):
            ok_out = gen30.fragment_blocks({**prof0, "fragments": ["good"]}, sdir)
        cases.append(("D1–D4 反向对照：合法索引逐字节注入成功",
                      ok_out == "<!-- fragment: good -->\n# 好片\n\n正文\n", repr(ok_out[:120])))
        # 反向对照：新校验不得把「未声明」拖进失败面——索引坏成非 UTF-8 也要原样返回空串
        (sdir / "manifest.yaml").write_bytes("version: 1\nfragments: [ ]\n".encode("gbk")
                                             + b"\xff\xfe garbage")
        cases.append(("D1–D4 反向对照：未声明时坏索引仍零回归（不读）",
                      gen30.fragment_blocks({**prof0, "fragments": []}, sdir) == "", "返回非空"))
        # 子进程级：越界声明必须 rc=2、无 traceback、零残留（先拒后写没被新校验破坏）。
        # STATIC_DIR 由脚本自身的 __file__ 推出，所以要把生成器复制到临时包里跑，
        # 否则它读的还是仓库真 static/，这条判据测不到我造的坏索引。
        script_dir = tmp / "scripts"
        script_dir.mkdir(exist_ok=True)
        gen_copy = script_dir / gen.name
        gen_copy.write_bytes(gen.read_bytes())
        (sdir / "manifest.yaml").write_text(one("../outside.md"), encoding="utf-8")
        pf2 = tmp / "esc-profile.yaml"
        pf2.write_text(yaml.safe_dump({**prof0, "fragments": ["good"]}, allow_unicode=True),
                       encoding="utf-8")
        build2 = tmp / "build-esc"
        r3 = subprocess.run([sys.executable, "-B", "-X", "utf8", str(gen_copy),
                             "--profile", str(pf2), "--out", str(build2)],
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
        born3 = (r3.stdout or "") + (r3.stderr or "")
        cases.append(("D3 子进程级：越界声明 rc=2（非 traceback）",
                      r3.returncode == 2 and "Traceback" not in born3,
                      "rc=%d %s" % (r3.returncode, born3.strip()[-160:])))
        cases.append(("D3 子进程级：先拒后写（零残留）",
                      not (build2.exists() and any(build2.rglob("*"))),
                      str(sorted(p.name for p in build2.rglob("*"))[:3]) if build2.exists() else ""))
        # 反向对照：把索引修好，同一个临时包必须 rc=0 并落下 rules.fragment.md
        (sdir / "manifest.yaml").write_text(good_manifest, encoding="utf-8")
        r4 = subprocess.run([sys.executable, "-B", "-X", "utf8", str(gen_copy),
                             "--profile", str(pf2), "--out", str(tmp / "build-ok")],
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
        cases.append(("D3 子进程级反向对照：好索引 rc=0 且产物在盘",
                      r4.returncode == 0 and (tmp / "build-ok" / "rules.fragment.md").exists(),
                      "rc=%d %s" % (r4.returncode, born3.strip()[-120:])))

    print("== 规则碎片守卫（规格 §3）==")
    bad = 0
    for name, ok, detail in cases:
        print("  %-46s %s%s" % (name, "OK" if ok else "MISMATCH",
                                "" if ok or not detail else "  " + detail))
        if not ok:
            bad += 1
    return 1 if bad else 0


# ── 能力注册表状态位守卫（task-capability-registry-resync）───────────────────────
# 口径（SKILL.md §能力注册表）：「是否可用」由磁盘决定——标 available 的行路径必须存在，
# 标 planned 的行路径必须不存在，任一违反即 rc=1；registry-flip 漏翻或能力文件被误删都会在此变红。
#
# B12（task-r4-b12-registry-pipe，D-1）：转义竖线先占位再切列——40 号行用途格含
# `--domain material\|clinical\|social\|csml`（markdown 转义写法，渲染为字面 `|`），
# 旧 `[^|]+` 切列把行内转义竖线当成分隔符，该行列数对不上被静默丢弃（实测 7/8）。
# 切列前统一把 `\|` 换成占位符，切完再换回；肉眼行数/解析行数/期望 8 三方对账，
# 删一行（7≠8）或行内竖线未转义（肉眼≠解析）即红。
REGISTRY_STATUSES = ("available", "planned")
# B12 自证基线：SKILL.md 能力注册表数据行数（增删行须同步改基线，有意的摩擦；
# 同族：SUITE_CASES、_SEGMENT_COUNT）。
REGISTRY_EXPECTED_ROWS = 8
_REGISTRY_PIPE_TOKEN = "\x00ESCAPED_PIPE\x00"


def _registry_body(text: str) -> str:
    _, sep, body = text.partition("## 能力注册表")
    if not sep:
        return ""
    return body.split("**建好后的动作**")[0]


def _registry_cells(line: str) -> list | None:
    """单行转义感知切列：`\\|` 先占位（不参与分隔），切完还原。

    返回 [名称, 路径格, 用途格, 状态格]；非 4 列（表头/分隔行/损坏行）返回 None。
    """
    tmp = line.strip().replace("\\|", _REGISTRY_PIPE_TOKEN)
    if not (tmp.startswith("|") and tmp.endswith("|")):
        return None
    cells = [c.replace(_REGISTRY_PIPE_TOKEN, "|").strip() for c in tmp[1:-1].split("|")]
    if len(cells) != 4:
        return None
    return cells


def _is_registry_header_or_sep(cells: list) -> bool:
    return cells[0] == "能力" or set(cells[3]) <= set("-: ")


def registry_rows(text: str) -> list:
    """解析 SKILL.md 能力注册表 → [(名称, 检查路径, 状态)]。

    碎片行的 `static/` + `manifest.yaml` 双反引号格归一为 static/manifest.yaml
    （目录与索引同时在盘才算可用）；其余行取路径单元格第一个反引号路径。
    状态格不在闭集的行不在此出现（由 registry_status_violations 点名）。
    """
    rows = []
    for line in _registry_body(text).split("\n"):
        cells = _registry_cells(line)
        if cells is None or _is_registry_header_or_sep(cells):
            continue
        name, cell, _, status = cells
        if status not in REGISTRY_STATUSES:
            continue
        if "manifest.yaml" in cell:
            path = "static/manifest.yaml"
        else:
            m = re.search(r"`([^`]+)`", cell)
            if not m:
                continue
            path = m.group(1).rstrip("/")
        rows.append((name.strip(), path, status))
    return rows


def registry_visual_rows(text: str) -> int:
    """肉眼行数：注册表节内 4 列数据行条数（表头/分隔行除外），与 registry_rows
    同一切列口径——转义不断列，故「肉眼 8 ≠ 解析 8」只可能是解析漏行。"""
    n = 0
    for line in _registry_body(text).split("\n"):
        cells = _registry_cells(line)
        if cells is None or _is_registry_header_or_sep(cells):
            continue
        n += 1
    return n


def registry_count_ok(text: str) -> bool:
    """B12 自证断言（单一判据）：肉眼行数 == 解析行数 == 期望行数。"""
    return registry_visual_rows(text) == len(registry_rows(text)) == REGISTRY_EXPECTED_ROWS


def registry_status_violations(text: str) -> list:
    """注册表状态格闭集校验（B8）：4 列数据行的第 4 格必须 ∈ REGISTRY_STATUSES。

    跳过表头与分隔行；未知状态值即违反（旧口径下这种行被 regex 静默忽略）。"""
    if "## 能力注册表" not in text:
        return ["能力注册表节缺失"]
    out = []
    for line in _registry_body(text).split("\n"):
        cells = _registry_cells(line)
        if cells is None or _is_registry_header_or_sep(cells):
            continue
        status = cells[3]
        if status not in REGISTRY_STATUSES:
            out.append("注册表行「%s」状态格 %r 不在闭集 %s（旧口径静默忽略该行）"
                       % (cells[0], status, list(REGISTRY_STATUSES)))
    return out


def registry_violations(text: str, root: pathlib.Path) -> list:
    rows = registry_rows(text)
    status_bad = registry_status_violations(text)
    if not rows:
        return ["能力注册表未解析到任何行（节缺失或表结构变更）"] + status_bad
    out = list(status_bad)
    for name, path, status in rows:
        exists = (root / path).exists()
        if status == "available" and not exists:
            out.append("标 available 但路径不在盘：%s（%s）" % (path, name))
        if status == "planned" and exists:
            out.append("标 planned 但路径已在盘（应翻牌 available）：%s（%s）" % (path, name))
    return out


def run_registry_guards() -> int:
    print("== 能力注册表状态位守卫（SKILL.md）==")
    text = (HERE.parent / "SKILL.md").read_text(encoding="utf-8-sig")
    root = HERE.parent
    violations = registry_violations(text, root)
    bad = 1 if violations else 0
    for v in violations:
        print("  MISMATCH %s" % v)
    rows = registry_rows(text)
    visual = registry_visual_rows(text)
    print("  注册表解析 %d 行 / 肉眼 %d 行 / 期望 %d 行，状态位与磁盘%s" % (
        len(rows), visual, REGISTRY_EXPECTED_ROWS,
        "一致" if not violations else "不一致"))
    # B12 自证断言：肉眼 == 解析（转义漏行即红）且解析 == 期望（删/增一行即红）。
    ok_count = registry_count_ok(text)
    print("  %-46s %s" % ("自证：肉眼行数 == 解析行数 == 期望 %d 行" % REGISTRY_EXPECTED_ROWS,
                          "OK" if ok_count else
                          "MISMATCH（肉眼 %d / 解析 %d）" % (visual, len(rows))))
    bad = bad or (0 if ok_count else 1)
    if violations or not ok_count:
        print("  SKIP  反向对照（当前注册表本身不一致，先修复再对照）")
        return bad
    # 反向对照（内存变异，不落盘、不动真文件）：改错任一行状态位，守卫必须变红。
    m = re.search(r"^(\|[^|]+\|[^|]+\|[^|]+\|)\s*available(\s*\|)", text, re.M)
    flip = text[:m.start()] + m.group(1) + " planned" + m.group(2) + text[m.end():] if m else None
    ok1 = bool(flip) and bool(registry_violations(flip, root))
    print("  %-46s %s" % ("反向对照：available→planned（路径已在盘）被判违反",
                          "OK" if ok1 else "MISMATCH"))
    m2 = re.search(r"^(\|[^|]+\| `)[^`]+(` \|[^|]+\|)\s*available(\s*\|)", text, re.M)
    flip2 = (text[:m2.start()] + m2.group(1) + "scripts/00-ghost-capability.py" + m2.group(2)
             + " available" + m2.group(3) + text[m2.end():]) if m2 else None
    ok2 = bool(flip2) and any("00-ghost-capability.py" in v
                              for v in registry_violations(flip2, root))
    print("  %-46s %s" % ("反向对照：available 行指向不在盘路径被判违反",
                          "OK" if ok2 else "MISMATCH"))
    # B8 反向对照：状态格写成闭集外的值（done）→ 闭集校验变红（旧口径静默忽略该行）。
    status_mut = re.sub(r"(\|[^|]+\|[^|]+\|[^|]+\|\s*)available(\s*\|)", r"\1done\2",
                        text, count=1)
    ok3 = (status_mut != text) and any("不在闭集" in v
                                       for v in registry_violations(status_mut, root))
    print("  %-46s %s" % ("反向对照：状态格写成闭集外值（done）被判违反",
                          "OK" if ok3 else "MISMATCH"))
    # B12 反向对照：40 号行（转义竖线行）翻牌 planned → 必须变红（旧口径下该行
    # 根本未被解析，翻牌 violations=[] 空转）。行内含 `\|`，不用 `[^|]+` 定位，
    # 直接按行找 40-style-check。
    tbl = text.split("\n")
    i40 = next((i for i, ln in enumerate(tbl)
                if "40-style-check" in ln and "available" in ln), None)
    flip40 = ("\n".join(tbl[:i40] + [tbl[i40].replace("available", "planned", 1)]
                         + tbl[i40 + 1:]) if i40 is not None else None)
    ok4 = bool(flip40) and any("40-style-check.py" in v
                               for v in registry_violations(flip40, root))
    print("  %-46s %s" % ("反向对照：40 号行翻牌 planned 被判违反",
                          "OK" if ok4 else "MISMATCH"))
    # B12 反向对照：删一行 → 自证断言变红（证明判据真咬得住，不是恒真）。
    drop40 = "\n".join(tbl[:i40] + tbl[i40 + 1:]) if i40 is not None else None
    ok5 = bool(drop40) and registry_count_ok(text) and not registry_count_ok(drop40)
    print("  %-46s %s" % ("反向对照：删一行即自证变红（7≠8）",
                          "OK" if ok5 else "MISMATCH"))
    return bad or (0 if ok1 and ok2 and ok3 and ok4 and ok5 else 1)


def run_encoding_and_path_guards() -> int:
    """N-1（cp936 下 FAIL 打印崩溃）与 N-5（--manifest 相对路径解析基准）的守卫。

    调用形态刻意用**引擎强制**的那一种：`python 70-verify.py <task>`（不带 -X utf8，
    生成器 :211 的正则锁死了这个形态），并以 `PYTHONIOENCODING=gbk` + 剥掉 `PYTHONUTF8`
    模拟纯 cp936 主机——本机设了 PYTHONUTF8=1 会完全掩盖这个 bug。
    反向对照两层：①同一段 ✅ print 放在不带 reconfigure 的子进程里必须崩（证明环境真的
    复现了故障条件，守卫不是空转）；②✅ 必须确实不能被 GBK 编码（证明用例有牙）。
    """
    env = dict(os.environ, PYTHONIOENCODING="gbk")
    env.pop("PYTHONUTF8", None)
    cases: list[tuple[str, bool, str]] = []

    def call(*args) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, "-B", str(VERIFY), *args], capture_output=True,
                              text=True, encoding="utf-8", errors="replace", env=env)

    with tempfile.TemporaryDirectory() as td:
        root = pathlib.Path(td)
        (root / "70-tools").mkdir(parents=True)
        (root / "a.md").write_text("nothing here", encoding="utf-8")
        (root / "70-tools" / "71-verify-manifest.json").write_text(
            json.dumps({"c-emoji-fail": {"files": [{"path": "a.md",
                                                   "contains": ["✅ 已完成"]}]}},
                       ensure_ascii=False), encoding="utf-8")
        try:
            "✅".encode("gbk")
            cases.append(("用例有牙：✅ 不可被 GBK 编码", False, "该字符在 gbk 下可编码，用例失去复现力"))
        except UnicodeEncodeError:
            cases.append(("用例有牙：✅ 不可被 GBK 编码", True, ""))
        old = subprocess.run([sys.executable, "-c",
                              "print('  - missing marker %r' % '\\u2705 已完成')"],
                             capture_output=True, text=True, encoding="utf-8",
                             errors="replace", env=env)
        cases.append(("反向对照：旧行为（无 reconfigure）必崩",
                      old.returncode != 0 and "UnicodeEncodeError" in (old.stderr or ""),
                      "rc=%d stderr=%s" % (old.returncode, (old.stderr or "")[-80:])))
        # N-1 修复后的三条正向断言：rc 语义、明细完整、--json 可整份解析
        r = call("c-emoji-fail", "--root", str(root))
        cases.append(("gbk 下 FAIL 退出码 = 1", r.returncode == 1, "rc=%d" % r.returncode))
        cases.append(("FAIL 明细打全（含 ✅ 原文）",
                      "missing marker" in r.stdout and "✅ 已完成" in r.stdout,
                      "stdout 尾部=%r" % r.stdout[-60:]))
        cases.append(("stderr 无 UnicodeEncodeError",
                      "UnicodeEncodeError" not in (r.stderr or ""),
                      (r.stderr or "")[-120:]))
        rj = call("c-emoji-fail", "--json", "--root", str(root))
        try:
            parsed = json.loads(rj.stdout[rj.stdout.index("{"):])
            got_rc = parsed["results"]["c-emoji-fail"]["rc"]
            cases.append(("gbk 下 --json 可完整解析", got_rc == 1, "内层 rc=%s" % got_rc))
        except Exception as exc:                                    # noqa: BLE001
            cases.append(("gbk 下 --json 可完整解析", False,
                          "%s：%r" % (type(exc).__name__, (rj.stdout or "")[-80:])))
        # N-5：相对 --manifest 以 --root 为基准（文档化语义的正/反两面）
        rel = "70-tools/71-verify-manifest.json"
        rpos = call("c-emoji-fail", "--root", str(root), "--manifest", rel)
        cases.append(("相对 --manifest 按 --root 命中",
                      "manifest not found" not in rpos.stdout and rpos.returncode == 1,
                      "rc=%d %s" % (rpos.returncode, rpos.stdout[-80:])))
        wrong = "%s/%s" % (root.name, rel)                           # 带根名前缀的 cwd 视角写法
        rneg = call("c-emoji-fail", "--root", str(root), "--manifest", wrong)
        joined = str(root / wrong)
        cases.append(("二次拼接未命中 → rc=2", rneg.returncode == 2, "rc=%d" % rneg.returncode))
        cases.append(("未命中消息回显原值+解析后绝对路径+基准",
                      wrong in rneg.stdout and joined in rneg.stdout
                      and "--root" in rneg.stdout,
                      "stdout=%r" % rneg.stdout[-160:]))
        rschema = call("--schema")
        cases.append(("--schema 写明解析基准",
                      "--manifest" in rschema.stdout and "--root" in rschema.stdout,
                      ""))
    print("== 编码与 manifest 路径守卫（N-1/N-5）==")
    bad = 0
    for name, ok, detail in cases:
        print("  %-38s %s%s" % (name, "OK" if ok else "MISMATCH",
                                "" if ok or not detail else "  " + detail))
        if not ok:
            bad += 1
    return 1 if bad else 0


def run_manifest_shape_guards() -> int:
    """N-3（空列表逐条键检查恒真 = fail-open）与 N-2（manifest 形态裸崩）的守卫。

    三类各带一条**锚点**：锚点不复用 70 的代码，而是把出问题的判据表达式本身放进子进程跑，
    证明该形态在朴素写法下确实恒真（类 1）/确实抛异常（类 2、3）。没有锚点的话，守卫可能只是
    陪着修复一起变绿的空转装饰——AC5 要求的反向对照口径就是"把判据拆掉后测试要变红"。
    """
    cases: list[tuple[str, bool, str]] = []

    def call(root: pathlib.Path, *args) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, "-B", str(VERIFY), *args, "--root", str(root)],
                              capture_output=True, text=True, encoding="utf-8", errors="replace")

    def snippet(code: str) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, "-B", "-c", code], capture_output=True,
                              text=True, encoding="utf-8", errors="replace")

    def mk(name: str, manifest: dict, files: dict | None = None) -> pathlib.Path:
        root = base / name
        (root / "70-tools").mkdir(parents=True, exist_ok=True)
        (root / "70-tools" / "71-verify-manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
        for rel, content in (files or {}).items():
            p = root / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")
        return root

    def crashed(r: subprocess.CompletedProcess) -> str:
        err = r.stderr or ""
        return err.splitlines()[-1].strip() if err.strip() else ""

    with tempfile.TemporaryDirectory() as td:
        base = pathlib.Path(td)

        # ==== 类 1：json_files 空列表（N-3，本仓唯一真 fail-open）====
        anchor = snippet("import sys;sys.exit(0 if all('doi' in it for it in []) else 1)")
        cases.append(("锚点：空列表下逐条键检查恒真", anchor.returncode == 0,
                      "rc=%d" % anchor.returncode))
        req_all = {"t": {"json_files": [{"path": "e.json", "require_keys_all": ["doi"]}]}}
        r = mk("empty-all", req_all, {"e.json": "[]"})
        p1 = call(r, "t")
        cases.append(("空列表 + require_keys_all 不再 rc=0", p1.returncode == 1,
                      "rc=%d %s" % (p1.returncode, crashed(p1) or p1.stdout[-90:])))
        cases.append(("空转消息含 path 与「空列表」",
                      "e.json" in p1.stdout and "空列表" in p1.stdout,
                      "stdout=%r" % p1.stdout[-160:]))
        r = mk("empty-keys", {"t": {"json_files": [{"path": "e.json",
                                                   "require_keys": ["doi"]}]}},
               {"e.json": "[]"})
        p2 = call(r, "t")
        cases.append(("空列表 + require_keys 不 IndexError",
                      p2.returncode == 1 and not crashed(p2),
                      "rc=%d %s" % (p2.returncode, crashed(p2))))
        r = mk("empty-min", {"t": {"json_files": [{"path": "e.json", "require_keys_all": ["doi"],
                                                  "min_items": 1}]}}, {"e.json": "[]"})
        p3 = call(r, "t")
        cases.append(("配 min_items=1 时原口径不回退",
                      p3.returncode == 1 and "min 1" in p3.stdout, "rc=%d" % p3.returncode))
        r = mk("nonempty", req_all, {"e.json": json.dumps([{"doi": "1"}])})
        p4 = call(r, "t")
        cases.append(("非空且字段齐全仍 PASS（防过度收紧）", p4.returncode == 0,
                      "rc=%d %s" % (p4.returncode, p4.stdout[-90:])))
        rschema = call(base / "empty-all", "--schema")
        cases.append(("--schema 写明 require_keys* 与 min_items 组合语义",
                      "require_keys_all" in rschema.stdout and "min_items" in rschema.stdout
                      and "空列表" in rschema.stdout, "rc=%d" % rschema.returncode))

        # ==== 类 1b：require_keys 对非 dict 首元素（审查 F-2，2026-09-29 实锤）====
        # 朴素 `key not in data[0]`：int 首元素 TypeError 裸崩（rc=1 冒充 FAIL）、
        # str 首元素退化为子串判定（rc=0 假 PASS）。两条锚点证明朴素写法确实错，
        # 行为断言在防御被摘除时分别以 traceback 痕迹 / rc=0 变红。
        anchor = snippet("d=[1,2,3]\n"
                         "try:\n"
                         "    'doi' not in d[0]\n"
                         "except TypeError:\n"
                         "    import sys;sys.exit(3)\n"
                         "sys.exit(0)")
        cases.append(("锚点：int 首元素下 `key not in data[0]` 必 TypeError",
                      anchor.returncode == 3, "rc=%d" % anchor.returncode))
        anchor = snippet("import sys;sys.exit(0 if 'doi' in 'doi is here' else 1)")
        cases.append(("锚点：str 首元素下 `not in` 退化为子串判定（假 PASS 源）",
                      anchor.returncode == 0, "rc=%d" % anchor.returncode))
        r = mk("int-first", {"t": {"json_files": [{"path": "e.json",
                                                   "require_keys": ["doi"]}]}},
               {"e.json": "[1, 2, 3]"})
        q1 = call(r, "t")
        cases.append(("int 首元素 + require_keys → rc=1 FAIL 且无 traceback",
                      q1.returncode == 1 and not crashed(q1),
                      "rc=%d %s" % (q1.returncode, crashed(q1) or q1.stdout[-120:])))
        cases.append(("FAIL 消息点明首元素实际类型 int",
                      "not an object" in q1.stdout and "int" in q1.stdout,
                      "stdout=%r" % q1.stdout[-160:]))
        r = mk("str-first", {"t": {"json_files": [{"path": "e.json",
                                                   "require_keys": ["doi"]}]}},
               {"e.json": json.dumps(["doi is here", {"x": 1}])})
        q2 = call(r, "t")
        cases.append(("str 首元素 + require_keys → rc=1（子串假 PASS 已堵）",
                      q2.returncode == 1 and "str" in q2.stdout,
                      "rc=%d %s" % (q2.returncode, q2.stdout[-120:])))
        r = mk("obj-missing", {"t": {"json_files": [{"path": "e.json",
                                                     "require_keys": ["doi"]}]}},
               {"e.json": json.dumps([{"title": "x"}])})
        q3 = call(r, "t")
        cases.append(("对照组：对象列表缺键仍 rc=1（口径不糊）",
                      q3.returncode == 1 and "first item missing key 'doi'" in q3.stdout,
                      "rc=%d %s" % (q3.returncode, q3.stdout[-120:])))
        r = mk("obj-ok", {"t": {"json_files": [{"path": "e.json",
                                                "require_keys": ["doi"]}]}},
               {"e.json": json.dumps([{"doi": "10.1/x"}])})
        q4 = call(r, "t")
        cases.append(("对照组：对象列表含键仍 rc=0（防过度收紧）",
                      q4.returncode == 0, "rc=%d %s" % (q4.returncode, q4.stdout[-120:])))

        # ==== 类 2：条目值形态（N-2，曾以 AttributeError 裸崩冒充 FAIL）====
        anchor = snippet("s='oops';s.get('files')")
        cases.append(("锚点：朴素 spec.get 对字符串必崩",
                      anchor.returncode != 0 and "AttributeError" in (anchor.stderr or ""),
                      "rc=%d %s" % (anchor.returncode, crashed(anchor))))
        r = mk("str-entry", {"t-str": "oops"})
        s1 = call(r, "--all")
        cases.append(("条目值为字符串 --all → rc=2", s1.returncode == 2, "rc=%d" % s1.returncode))
        cases.append(("形态消息含任务 id 与定位说明",
                      "t-str" in s1.stdout and "条目值必须是对象" in s1.stdout
                      and "str" in s1.stdout, "stdout=%r" % s1.stdout[-160:]))
        cases.append(("无 AttributeError 裸 traceback", "AttributeError" not in (s1.stderr or ""),
                      crashed(s1)))
        s2 = call(r, "t-str")
        cases.append(("单任务形态同样 rc=2", s2.returncode == 2, "rc=%d" % s2.returncode))
        r = mk("null-entry", {"t-null": None})
        s3 = call(r, "--all")
        cases.append(("null 条目值报形态错而非「无条目」",
                      s3.returncode == 2 and "NoneType" in s3.stdout
                      and "no manifest entry" not in s3.stdout, "rc=%d" % s3.returncode))
        r = mk("mixed", {"ok-entry": {"files": [{"path": "a.md", "contains": ["x"]}]},
                         "t-str": "oops"}, {"a.md": "x"})
        s4 = call(r, "--all")
        cases.append(("混合 manifest：坏条目不吞好条目判定",
                      s4.returncode == 2 and "PASS: ok-entry" in s4.stdout
                      and "形态不合: t-str" in s4.stdout,
                      "rc=%d %s" % (s4.returncode, s4.stdout[-200:])))

        # ==== 类 3：段内项形态（缺定位键 / 段或键类型不合）====
        anchor = snippet("{}['path']")
        cases.append(("锚点：缺 path 的朴素取键必 KeyError",
                      anchor.returncode != 0 and "KeyError" in (anchor.stderr or ""),
                      "rc=%d %s" % (anchor.returncode, crashed(anchor))))
        r = mk("no-path", {"t": {"files": [{"min_bytes": 10}]}}, {"a.md": "x"})
        f1 = call(r, "t")
        cases.append(("files[0] 缺 path → rc=2", f1.returncode == 2, "rc=%d" % f1.returncode))
        cases.append(("缺键消息含段名[下标]与键名",
                      "files[0]" in f1.stdout and "path" in f1.stdout
                      and "min_bytes" in f1.stdout, "stdout=%r" % f1.stdout[-160:]))
        r = mk("json-no-path", {"t": {"json_files": [{"min_items": 1}]}}, {"e.json": "[]"})
        f2 = call(r, "t")
        cases.append(("json_files[0] 缺 path → rc=2", f2.returncode == 2, "rc=%d" % f2.returncode))
        r = mk("glob-no-pattern", {"t": {"globs": [{"min_count": 1}]}}, {})
        f3 = call(r, "t")
        cases.append(("globs[0] 缺 pattern → rc=2 且点名 pattern",
                      f3.returncode == 2 and "pattern" in f3.stdout,
                      "rc=%d %s" % (f3.returncode, f3.stdout[-120:])))
        r = mk("bad-type", {"t": {"json_files": [{"path": "e.json", "min_items": "20"}]}},
               {"e.json": "[]"})
        f4 = call(r, "t")
        cases.append(("min_items 写成字符串 → rc=2 而非 TypeError",
                      f4.returncode == 2 and "必须是 int" in f4.stdout and not crashed(f4),
                      "rc=%d %s" % (f4.returncode, crashed(f4) or f4.stdout[-120:])))
        r = mk("null-knob", {"t": {"files": [{"path": "a.md", "min_bytes": None}]}},
               {"a.md": "x"})
        f5 = call(r, "t")
        cases.append(("段内键值为 null → rc=2（笔误不当省略）",
                      f5.returncode == 2 and "NoneType" in f5.stdout, "rc=%d" % f5.returncode))
        r = mk("null-seg", {"t": {"files": None, "json_files": None, "globs": None,
                                  "absent_paths": None}}, {})
        f6 = call(r, "t")
        cases.append(("整段写 null 等同省略（宽容不回退）", f6.returncode == 0,
                      "rc=%d %s" % (f6.returncode, f6.stdout[-120:])))
        r = mk("scalar-json", {"t": {"json_files": [{"path": "e.json", "min_items": 1}]}},
               {"e.json": "5"})
        f7 = call(r, "t")
        cases.append(("产物 JSON 顶层标量 → rc=1 且无 TypeError",
                      f7.returncode == 1 and "顶层必须是数组或对象" in f7.stdout
                      and not crashed(f7),
                      "rc=%d %s" % (f7.returncode, crashed(f7) or f7.stdout[-120:])))

        # ==== 类 3 续：可选项的**内部**形态（少键 / 元素类型 / 坏正则）====
        anchor = snippet("m={'pattern':'x'};m['min']")
        cases.append(("锚点：min_matches 少 min 必 KeyError",
                      anchor.returncode != 0 and "KeyError" in (anchor.stderr or ""),
                      "rc=%d %s" % (anchor.returncode, crashed(anchor))))
        r = mk("mm-nomin", {"t": {"files": [{"path": "a.md",
                                            "min_matches": {"pattern": "Fig"}}]}}, {"a.md": "Fig 1"})
        k1 = call(r, "t")
        cases.append(("min_matches 少 min → rc=2 且点名 min",
                      k1.returncode == 2 and "min" in k1.stdout and not crashed(k1),
                      "rc=%d %s" % (k1.returncode, crashed(k1) or k1.stdout[-120:])))
        r = mk("mm-badre", {"t": {"files": [{"path": "a.md",
                                             "min_matches": {"pattern": "(", "min": 1}}]}},
               {"a.md": "x"})
        k2 = call(r, "t")
        cases.append(("坏正则（min_matches）→ rc=2 而非 re.error",
                      k2.returncode == 2 and "不是合法正则" in k2.stdout and not crashed(k2),
                      "rc=%d %s" % (k2.returncode, crashed(k2) or k2.stdout[-120:])))
        r = mk("fr-badre", {"t": {"files": [{"path": "a.md", "forbid_regex": ["("]}]}},
               {"a.md": "x"})
        k3 = call(r, "t")
        cases.append(("坏正则（forbid_regex）→ rc=2", k3.returncode == 2
                      and "不是合法正则" in k3.stdout, "rc=%d" % k3.returncode))
        r = mk("wc-str", {"t": {"files": [{"path": "a.md", "word_count": ["10", 20]}]}},
               {"a.md": "x"})
        k4 = call(r, "t")
        cases.append(("word_count 端点非整数 → rc=2",
                      k4.returncode == 2 and "两个整数" in k4.stdout and not crashed(k4),
                      "rc=%d %s" % (k4.returncode, crashed(k4) or k4.stdout[-120:])))
        r = mk("wc-len", {"t": {"files": [{"path": "a.md", "word_count": [10]}]}}, {"a.md": "x"})
        k5 = call(r, "t")
        cases.append(("word_count 非两元 → rc=2", k5.returncode == 2, "rc=%d" % k5.returncode))
        r = mk("path-int", {"t": {"files": [{"path": 12}]}}, {})
        k6 = call(r, "t")
        cases.append(("定位键写成数字 → rc=2 且点名定位键",
                      k6.returncode == 2 and "定位键" in k6.stdout, "rc=%d" % k6.returncode))
        r = mk("contains-int", {"t": {"files": [{"path": "a.md", "contains": ["x", 3]}]}},
               {"a.md": "x"})
        k7 = call(r, "t")
        cases.append(("contains 混入数字 → rc=2 而非 TypeError",
                      k7.returncode == 2 and "contains[1]" in k7.stdout and not crashed(k7),
                      "rc=%d %s" % (k7.returncode, crashed(k7) or k7.stdout[-120:])))
        r = mk("reqkey-int", {"t": {"json_files": [{"path": "e.json",
                                                    "require_keys_all": [7]}]}},
               {"e.json": '[{"doi": "1"}]'})
        k8 = call(r, "t")
        cases.append(("require_keys_all 混入数字 → rc=2", k8.returncode == 2,
                      "rc=%d" % k8.returncode))

        # ==== 类 3 续：count_distinct 的嵌套形态（F18；scope 值 / 键名写错都属形态档）====
        r = mk("cdist-scope-val", {"t": {"files": [{"path": "a.md",
                                                    "count_distinct": {"pattern": "x", "min": 1,
                                                                       "scope": "lines"}}]}},
               {"a.md": "x"})
        k9 = call(r, "t")
        cases.append(("count_distinct scope 值非法（lines）→ rc=2 且点名取值域",
                      k9.returncode == 2 and "scope" in k9.stdout and "line" in k9.stdout
                      and not crashed(k9),
                      "rc=%d %s" % (k9.returncode, crashed(k9) or k9.stdout[-120:])))
        r = mk("cdist-scope-key", {"t": {"files": [{"path": "a.md",
                                                    "count_distinct": {"pattern": "x", "min": 1,
                                                                       "scopes": "line"}}]}},
               {"a.md": "x"})
        k10 = call(r, "t")
        cases.append(("count_distinct 嵌套键拼错（scopes）→ rc=2 且点名未知键",
                      k10.returncode == 2 and "scopes" in k10.stdout and not crashed(k10),
                      "rc=%d %s" % (k10.returncode, crashed(k10) or k10.stdout[-120:])))
        r = mk("cdist-nomin", {"t": {"files": [{"path": "a.md",
                                                "count_distinct": {"pattern": "x"}}]}},
               {"a.md": "x"})
        k11 = call(r, "t")
        cases.append(("count_distinct 少 min → rc=2 且点名 min",
                      k11.returncode == 2 and "min" in k11.stdout and not crashed(k11),
                      "rc=%d %s" % (k11.returncode, crashed(k11) or k11.stdout[-120:])))

    print("== manifest 形态守卫（N-2/N-3）==")
    bad = 0
    for name, ok, detail in cases:
        print("  %-38s %s%s" % (name, "OK" if ok else "MISMATCH",
                                "" if ok or not detail else "  " + detail))
        if not ok:
            bad += 1
    return 1 if bad else 0


def run_engine_e2e_guard() -> int:
    """--check 正路端到端守卫（审查 F-3，2026-09-29）：生成器产物 → 真实引擎 validate。

    既有「给了 --project 不被新守卫拦下」用例拿不存在的空目录当 project（引擎侧必然失败，
    注释自述不要求 rc=0），--check 的正路（生成 → cwd=project 执行 .orchd/__main__.py validate
    合成 master）在自测中从未真正执行；引擎升级后 master fragment 与引擎 schema 的兼容性
    无自动回归（此前最近一次人工验证停留在 CHANGELOG D-8/D-11）。本守卫以**本仓自身**为
    --project（.orchd/ 引擎在盘），对在盘领域档跑真实 --check 断言 PASS；并以坏 master
    反向对照证明 validate 结果真的被解析（防断言空转假绿）。沙盒全在系统临时目录：
    --out 指临时目录，check() 对 --project 只读且子进程带 -B，不触发布局面。
    """
    cases: list[tuple[str, bool, str]] = []
    gen = HERE / "30-gen-proposals.py"
    profiles = HERE.parent / "profiles"
    engine_entry = HERE.parent / ".orchd" / "__main__.py"

    # B02（round3 A-3）：引擎可用性必须**真探测**——发货面含 `.orchd/__main__.py` 但**不含**
    # `.orchd/orchd/` 引擎包（AGENTS 要求另装），只看 `__main__.py` 在盘与否会把干净克隆误判成
    # 「引擎已接入」，退化为 ModuleNotFoundError 的 traceback-as-FAIL（克隆内 rc=1）。故子进程
    # 实跑 `--version` 探活；失败即**显式 SKIP**（克隆面 rc=0，不判 FAIL / 不裸 traceback）。
    def engine_available() -> bool:
        if not engine_entry.exists():
            return False
        try:
            r = subprocess.run([sys.executable, "-B", "-X", "utf8", str(engine_entry), "--version"],
                               cwd=str(HERE.parent), capture_output=True, text=True,
                               encoding="utf-8", errors="replace", timeout=60)
        except (OSError, subprocess.SubprocessError):
            return False
        return r.returncode == 0

    def call(*args) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, "-B", "-X", "utf8", str(gen), *args],
                              capture_output=True, text=True, encoding="utf-8",
                              errors="replace")

    def validate(master: pathlib.Path) -> subprocess.CompletedProcess:
        # 与 30-gen-proposals.py check() 同形态：cwd=项目根、-B、master 传绝对路径、timeout=120
        # （P2，2026-10-05：产品侧 check() 已带超时，此处同步，防自测无限挂起）。
        # 失败时的退出码语义随引擎版本而变（E-13 修复前 rc=0，v1.5.0-1 起非法 master
        # 返回 rc=1）——判定锚一律以 JSON 的 valid 字段为准，退出码只作辅助断言。
        return subprocess.run([sys.executable, "-B", "-X", "utf8", ".orchd/__main__.py", "validate",
                               str(master)], cwd=str(HERE.parent), capture_output=True,
                              text=True, encoding="utf-8", errors="replace", timeout=120)

    with tempfile.TemporaryDirectory() as td:
        base = pathlib.Path(td)
        if not engine_available():
            # B02（round3 A-3）：真探测判定——引擎包不在盘/不可导入时显式 SKIP（rc=0，不静默、
            # 不判 FAIL）。判据不再用「.orchd/__main__.py 在盘与否」（发货面含它不含引擎包）。
            print("== 引擎端到端守卫（F-3）==\n"
                  "  SKIP  引擎未接入（真探测 .orchd/__main__.py --version 失败）——"
                  "克隆面/未装引擎时显式跳过本段，不判 FAIL；接入见 AGENTS.md："
                  "git clone https://github.com/7bder/orchd-core.git && "
                  "python orchd-core/install.py . --agent")
            return 0
        # 锚点：坏 master（depends_on 指向不存在任务）经引擎 validate 必 valid:false——
        # 证明本段对 validate JSON 的解析路径真的能区分 PASS/FAIL，而非陪着好 master 空转。
        bad = {"schema_version": 1,
               "project": {"name": "e2e-anchor", "brief": "anchor"},
               "modules": [],
               "tasks": [{"id": "task-anchor-a", "name": "a", "brief": "a", "module": "m",
                          "depends_on": ["task-not-registered-anywhere"],
                          "acceptance_criteria": ["AC 必须含 00-admin/00-plan.md（锚点占位）"],
                          "files_to_edit": ["00-admin/00-plan.md"],
                          "verify_command": "python x task-anchor-a"}]}
        badp = base / "bad-master.json"
        badp.write_text(json.dumps(bad, ensure_ascii=False), encoding="utf-8")
        vbad = validate(badp)
        try:
            bad_valid = bool(json.loads((vbad.stdout or "").lstrip("\ufeff")).get("valid"))
        except json.JSONDecodeError:
            bad_valid = None
        cases.append(("锚点：坏 master（未知 depends_on）经引擎 validate 报失败且 valid:false",
                      vbad.returncode != 0 and bad_valid is False,
                      "rc=%d valid=%r out=%r" % (vbad.returncode, bad_valid,
                                                 (vbad.stdout or "")[-90:])))

        # 正路：以本仓为 --project 对两档代表跑真实 --check（最小子档 clinical + 回归基线档 materials）。
        checked = 0
        for prof in (profiles / "10-clinical.yaml", profiles / "10-materials-chemistry.yaml"):
            if not prof.exists():
                continue
            outdir = base / ("e2e-" + prof.stem)
            r = call("--profile", str(prof), "--check", "--project", str(HERE.parent),
                     "--out", str(outdir))
            cases.append(("--check 正路（%s）：生成 → 引擎 validate PASS" % prof.name,
                          r.returncode == 0 and "orchd validate -> PASS" in (r.stdout or ""),
                          "rc=%d out=%r" % (r.returncode, (r.stdout or "")[-110:])))
            emitted = list(outdir.rglob("*")) if outdir.exists() else []
            cases.append(("--check 生成物全部落 --out（临时目录，含 _validate.proposed.json）",
                          r.returncode == 0 and any(p.name == "_validate.proposed.json"
                                                    for p in emitted),
                          "files=%d" % len(emitted)))
            checked += 1
        if checked == 0:
            # B8：正路用例 0 条 = 空转，SKIP 归 rc=2（不静默放行；锚点结论另由 main 的回归兜底）。
            print("== 引擎端到端守卫（F-3）==\n"
                  "  FAIL  profiles 无在盘领域档——正路用例 0 条（SKIP 不静默放行，rc=2）")
            return 2

    print("== 引擎端到端守卫（F-3）==")
    bad = 0
    for name, ok, detail in cases:
        print("  %-52s %s%s" % (name, "OK" if ok else "MISMATCH",
                                "" if ok or not detail else "  " + detail))
        if not ok:
            bad += 1
    return 1 if bad else 0


def run_parity(project: pathlib.Path) -> int:
    """与项目自带 verify 脚本逐任务比对判定（rc 必须一致）。"""
    script = project / "scripts" / "verify.py"
    if not script.exists():
        print("== parity ==\n  跳过：%s 不存在" % script)
        return 0
    r = subprocess.run([sys.executable, "-B", "-X", "utf8", str(VERIFY), "--all", "--quiet", "--json",
                        "--root", str(project), "--manifest", str(project / "scripts" / "verify_manifest.json")],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    text = r.stdout or ""
    try:
        got = json.loads(text[text.index("{"):])["results"]
    except Exception as exc:                                   # noqa: BLE001 — parity 也要有兜底（审查：曾裸崩）
        print("== parity ==\n  无法解析基座输出：%s\n%s" % (exc, text[:800]))
        return 1
    print("== parity（vs %s）==" % script)
    mism = []
    for tid in sorted(got):
        p = subprocess.run([sys.executable, "-B", str(script), tid], cwd=str(project),
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
        if p.returncode != got[tid]["rc"]:
            mism.append((tid, p.returncode, got[tid]["rc"]))
        print("  %-34s 项目脚本 rc=%d / 基座 rc=%d  %s"
              % (tid, p.returncode, got[tid]["rc"], "OK" if p.returncode == got[tid]["rc"] else "DIFF"))
    print("  不一致 %d 个" % len(mism))
    return 1 if mism else 0


def run_verify_layout_guards() -> int:
    """F2（2026-10-06 审查）：--verify-layout 两制切换。

    materials 档 verify_tool 冻结在 paper1 scripts/ 侧，新项目 vendor 在 70-tools/——
    缺省（legacy）必须保持 --regress A 类 parity；standard 必须把 verify_command、
    verify_manifest 断言路径与 tool_dir 声明整体重写到 70-tools/；emit 模式缺省跑
    scripts/ 侧档案时 stderr 必须打双制警告（显式给旗标即静默）。"""
    print("== --verify-layout 两制守卫 ==")
    bad = 0
    gen = HERE / "30-gen-proposals.py"
    mat = HERE.parent / "profiles" / "10-materials-chemistry.yaml"

    def call(*args) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, "-B", "-X", "utf8", str(gen), *args],
                              capture_output=True, text=True, encoding="utf-8", errors="replace")

    def read_probe(outdir: pathlib.Path):
        prop = outdir / "proposals" / "task-citation-audit.json"
        frag = json.loads((outdir / "verify_manifest.fragment.json").read_text(encoding="utf-8-sig"))
        p = json.loads(prop.read_text(encoding="utf-8-sig"))
        mpaths = sorted({f["path"].replace("\\", "/") for e in frag.values()
                         for f in e.get("files", []) if "verify" in str(f.get("path", ""))})
        return p["verify_command"], mpaths

    cases: list[tuple[str, bool, str]] = []
    with tempfile.TemporaryDirectory() as td:
        base = pathlib.Path(td)
        # 1) standard 重写
        r_std = call("--profile", str(mat), "--out", str(base / "std"), "--verify-layout", "standard")
        std_cmd, std_mp = read_probe(base / "std") if r_std.returncode == 0 else ("", [])
        all_std = all(json.loads(x.read_text(encoding="utf-8-sig"))["verify_command"]
                      .startswith("python 70-tools/70-verify.py ")
                      for x in (base / "std" / "proposals").glob("task-*.json")) if r_std.returncode == 0 else False
        cases.append(("standard: 全部 verify_command 指向 70-tools/70-verify.py",
                      r_std.returncode == 0 and all_std,
                      "rc=%d cmd=%r" % (r_std.returncode, std_cmd)))
        cases.append(("standard: manifest 断言路径落 70-tools/",
                      std_mp == ["70-tools/71-verify-manifest.json"], "mpaths=%r" % std_mp))
        # 2) 缺省维持 legacy（--regress A 类 parity 锚点）+ emit 打警告
        r_def = call("--profile", str(mat), "--out", str(base / "def"))
        def_cmd, def_mp = read_probe(base / "def") if r_def.returncode == 0 else ("", [])
        cases.append(("缺省: verify_command 维持 scripts/verify.py（回归 parity 不变）",
                      def_cmd == "python scripts/verify.py task-citation-audit", "cmd=%r" % def_cmd))
        cases.append(("缺省 emit: stderr 打双制警告",
                      "--verify-layout standard" in (r_def.stderr or ""), (r_def.stderr or "")[-90:]))
        # 3) 反向对照：standard 与 legacy 产物必须真不同（旗标不是装饰）
        cases.append(("反向对照: standard 产物与缺省产物不同（旗标真生效）",
                      bool(std_cmd) and std_cmd != def_cmd and std_mp != def_mp,
                      "std=%r def=%r" % (std_cmd, def_cmd)))
        # 4) 显式旗标静默（standard / legacy 都不再警告）
        r_s = call("--profile", str(mat), "--out", str(base / "s2"), "--verify-layout", "standard")
        r_l = call("--profile", str(mat), "--out", str(base / "l2"), "--verify-layout", "legacy")
        cases.append(("显式 standard: 静默", "--verify-layout standard" not in (r_s.stderr or ""),
                      (r_s.stderr or "")[-60:]))
        cases.append(("显式 legacy: 静默且输出同缺省",
                      "--verify-layout standard" not in (r_l.stderr or "")
                      and read_probe(base / "l2")[0] == def_cmd, (r_l.stderr or "")[-60:]))
        # 5) materials 零回归：缺省与 legacy 逐字节一致
        r_w0 = call("--profile", str(mat), "--out", str(base / "w0"))
        r_wl = call("--profile", str(mat), "--out", str(base / "wl"), "--verify-layout", "legacy")
        same = r_w0.returncode == 0 and r_wl.returncode == 0 and all(
            (base / "w0" / n).read_bytes() == (base / "wl" / n).read_bytes()
            for n in ("verify_manifest.fragment.json", "_master.fragment.json", "rules.fragment.md"))
        cases.append(("materials: 缺省与 legacy 逐字节一致（零回归）", same, "rc=%d/%d" % (r_w0.returncode, r_wl.returncode)))
    for name, ok, ev in cases:
        print("  %-52s %s  %s" % (name, "OK" if ok else "MISMATCH", "" if ok else ev))
        if not ok:
            bad += 1
    return 1 if bad else 0


def run_inherited_direction_guards() -> int:
    """F8（2026-10-06 审查）：inherited 模式方向约束按档映射。

    direction 字典曾硬编码 task-analyze-data——clinical/social/cs-ml 三档分析任务已改名，
    inherited 入口对它们静默不注入。修后按 `task-analyze-` 前缀从任务图探测，锚不定显式 problems。"""
    print("== inherited 方向映射守卫 ==")
    bad = 0
    cases = []
    for name in ("10-materials-chemistry", "10-clinical", "20-social-science", "30-cs-ml"):
        prof = gen30.load_profile(HERE.parent / "profiles" / ("%s.yaml" % name))
        prof.setdefault("entry", {})["mode"] = "inherited"
        with contextlib.redirect_stdout(io.StringIO()):
            built = gen30.build(prof)
        ids = [x["id"] for x in built["tasks"] if x["id"].startswith("task-analyze-")]
        inj = 0
        if ids:
            task = [x for x in built["tasks"] if x["id"] == ids[0]][0]
            inj = sum(1 for a in task["acceptance_criteria"] if "07-paper-roadmap" in a)
        cases.append(("%s: 分析任务 %s 注入方向约束" % (name, ids[0] if ids else "无"),
                      len(ids) == 1 and inj >= 1 and not built["problems"],
                      "ids=%s inj=%d problems=%d" % (ids, inj, len(built["problems"]))))
    synth = {"id": "synth", "version": "1", "entry": {"mode": "inherited"},
             "paths": {"admin": "00-admin"}, "tool_dir": "70-tools",
             "evidence_policy": {}, "modules": [], "depends": {},
             "tasks": [{"id": "task-audit-data", "name": "a", "brief": "b", "module": "m",
                        "acceptance_criteria": ["x"],
                        "files_to_edit": ["10-data/10-audit.md"], "verify": "python t task-audit-data"}]}
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            built2 = gen30.build(synth)
        cases.append(("反向对照: 无 task-analyze-* 时 problems 显式报错",
                      any("inherited" in p for p in built2["problems"]),
                      str(built2["problems"])[:90]))
    except SystemExit:
        cases.append(("反向对照: 无 task-analyze-* 时 problems 显式报错", True, "die 亦算咬住"))
    old_direction = {"task-analyze-data": "hint"}
    cases.append(("锚点: 旧字典对 task-analyze-outcomes 取 hint 得 None（静默不注入）",
                  old_direction.get("task-analyze-outcomes") is None, ""))
    for name_, ok, ev in cases:
        print("  %-56s %s  %s" % (name_, "OK" if ok else "MISMATCH", "" if ok else ev))
        if not ok:
            bad += 1
    return 1 if bad else 0


def run_hardening_guards() -> int:
    """A2/A3/A4（2026-10-07 审查）：严格解码 / 重复键 / 越界路径，三组正反控制。

    三组都是「假绿」方向——旧口径下 GBK 正文的中文 forbid 标记被替换字符吞成 rc=0、
    manifest 重复键 last-wins 吞掉前一条判定（rc=0）、`../x.md` 与绝对路径照单验收
    （rc=0）。每组配一条**锚点**（把旧写法放进子进程复现其洞，证明守卫不是陪跑）与
    干净对照；摘掉任一守卫后对应用例必红（GBK→0、重复键→0、越界→0/1）。
    """
    print("== 判定硬化守卫（A2/A3/A4）==")
    cases: list[tuple[str, bool, str]] = []
    bad = 0

    def call(root: pathlib.Path, *args) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, "-B", "-X", "utf8", str(VERIFY), *args,
                               "--root", str(root)], capture_output=True, text=True,
                              encoding="utf-8", errors="replace")

    def snippet(code: str) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, "-B", "-c", code], capture_output=True,
                              text=True, encoding="utf-8", errors="replace")

    def put_manifest(root: pathlib.Path, text: str) -> None:
        (root / "70-tools").mkdir(parents=True, exist_ok=True)
        (root / "70-tools" / "71-verify-manifest.json").write_text(text, encoding="utf-8")

    with tempfile.TemporaryDirectory() as td:
        base = pathlib.Path(td)

        # ==== A2：文本产物严格 UTF-8 解码 ====
        root = base / "a2"
        (root / "70-tools").mkdir(parents=True)
        marker = "占位符"
        (root / "gbk.md").write_bytes(("正文 TODO %s\n" % marker).encode("gbk"))
        (root / "u8.md").write_bytes(("正文 TODO %s\n" % marker).encode("utf-8"))
        (root / "clean.md").write_text("nothing here", encoding="utf-8")
        (root / "repl.md").write_text("bad \ufffd char", encoding="utf-8")
        # 锚点：旧口径 errors="replace" 下 GBK 标记被替换字符吞掉 → 找不到（洞真实存在）。
        # 子进程代码保持纯 ASCII（中文用 \\uXXXX 转义），规避 cp936 主机 -c 源码编码问题。
        marker_esc = "".join("\\u%04x" % ord(c) for c in marker)
        anchor = snippet(
            "import pathlib,sys\n"
            "t=pathlib.Path(%r).read_text(encoding='utf-8-sig',errors='replace')\n"
            "sys.exit(0 if '%s' not in t else 1)" % (str(root / "gbk.md"), marker_esc))
        cases.append(("锚点：旧 errors=replace 吞掉 GBK 中文标记（找不到）",
                      anchor.returncode == 0, "rc=%d" % anchor.returncode))
        put_manifest(root, json.dumps({"t-gbk": {"files": [
            {"path": "gbk.md", "forbid": [marker]}]}}, ensure_ascii=False))
        r = call(root, "t-gbk")
        cases.append(("A2 非 UTF-8 产物 + forbid → rc=2（不再假绿）", r.returncode == 2,
                      "rc=%d %s" % (r.returncode, r.stdout[-90:])))
        cases.append(("A2 报错点名文件与「UTF-8」",
                      "gbk.md" in r.stdout and "UTF-8" in r.stdout, r.stdout[-120:]))
        put_manifest(root, json.dumps({"t-u8": {"files": [
            {"path": "u8.md", "forbid": [marker]}]}}, ensure_ascii=False))
        r = call(root, "t-u8")
        cases.append(("A2 对照：UTF-8 同内容 forbid 命中 → rc=1（不回退）",
                      r.returncode == 1 and "forbidden marker" in r.stdout,
                      "rc=%d %s" % (r.returncode, r.stdout[-90:])))
        put_manifest(root, json.dumps({"t-clean": {"files": [
            {"path": "clean.md", "forbid": [marker]}]}}, ensure_ascii=False))
        r = call(root, "t-clean")
        cases.append(("A2 对照：干净 UTF-8 无标记 → rc=0", r.returncode == 0,
                      "rc=%d" % r.returncode))
        put_manifest(root, json.dumps({"t-repl": {"files": [
            {"path": "repl.md", "forbid": ["xyz"]}]}}))
        r = call(root, "t-repl")
        cases.append(("A2 解码结果含 U+FFFD 不得判 PASS（rc=2）", r.returncode == 2,
                      "rc=%d" % r.returncode))

        # ==== A3：manifest 重复键（任意层级）====
        root = base / "a3"
        (root / "70-tools").mkdir(parents=True)
        (root / "ok.txt").write_text("body", encoding="utf-8")
        anchor = snippet("import json,sys\n"
                         "sys.exit(0 if json.loads('{\"a\":1,\"a\":2}')['a']==2 else 1)")
        cases.append(("锚点：json 默认 last-wins 静默覆盖重复键", anchor.returncode == 0,
                      "rc=%d" % anchor.returncode))
        # 首条 FAIL（缺文件）、次条 PASS（ok.txt）：旧口径 last-wins 取次条 → rc=0 假绿
        put_manifest(root, '{"t-dup":{"files":[{"path":"nope.md"}]},'
                           '"t-dup":{"files":[{"path":"ok.txt"}]}}')
        r = call(root, "t-dup")
        cases.append(("A3 重复 task id → rc=2（不再 last-wins 假绿）", r.returncode == 2,
                      "rc=%d %s" % (r.returncode, r.stdout[-90:])))
        cases.append(("A3 重复键报错点名键名", "t-dup" in r.stdout, r.stdout[-120:]))
        put_manifest(root, '{"t-item":{"files":[{"path":"ok.txt","min_bytes":1,'
                           '"min_bytes":99999}]}}')
        r = call(root, "t-item")
        cases.append(("A3 条目级重复键（min_bytes 两遍）→ rc=2", r.returncode == 2,
                      "rc=%d" % r.returncode))
        put_manifest(root, '{"t-ok":{"files":[{"path":"ok.txt","min_bytes":1}]}}')
        r = call(root, "t-ok")
        cases.append(("A3 对照：无重复键的单键 manifest → rc=0", r.returncode == 0,
                      "rc=%d" % r.returncode))

        # ==== A3b / F-2（2026-10-07 二轮）：**产物** JSON 重复键（不止 manifest 真源）====
        root = base / "a3b"
        (root / "70-tools").mkdir(parents=True)
        anchor = snippet("import json,sys\n"
                         "sys.exit(0 if json.loads('{\"refs\":[1],\"refs\":[2]}')['refs']==[2] else 1)")
        cases.append(("锚点：产物 JSON 默认 last-wins 静默覆盖重复键", anchor.returncode == 0,
                      "rc=%d" % anchor.returncode))
        (root / "refs.json").write_text(
            '{"refs": [{"doi": "10.1/a"}], "refs": [{"doi": "10.1/b"}]}', encoding="utf-8")
        put_manifest(root, json.dumps({"t-pdup": {"json_files": [
            {"path": "refs.json", "require_keys": ["refs"]}]}}, ensure_ascii=False))
        r = call(root, "t-pdup")
        cases.append(("F-2 产物 JSON 重复键 → rc=2（不再 last-wins 假绿）", r.returncode == 2,
                      "rc=%d %s" % (r.returncode, r.stdout[-90:])))
        cases.append(("F-2 产物重复键报错点名键/文件",
                      "refs" in r.stdout and "refs.json" in r.stdout, r.stdout[-120:]))
        (root / "ok.json").write_text('{"refs": [{"doi": "10.1/a"}]}', encoding="utf-8")
        put_manifest(root, json.dumps({"t-pok": {"json_files": [
            {"path": "ok.json", "require_keys": ["refs"]}]}}, ensure_ascii=False))
        r = call(root, "t-pok")
        cases.append(("F-2 对照：无重复键产物 JSON → rc=0", r.returncode == 0,
                      "rc=%d" % r.returncode))

        # ==== A4：验收对象必须在项目根内 ====
        root = base / "a4" / "proj"
        (root / "70-tools").mkdir(parents=True)
        outside = base / "a4" / "secret.md"
        outside.write_text("ok body", encoding="utf-8")
        (base / "a4" / "secret.json").write_text('{"a": 1}', encoding="utf-8")
        (root / "ok.txt").write_text("clean body", encoding="utf-8")
        anchor = snippet("import pathlib,sys\n"
                         "p=pathlib.PurePath('../x.md')\n"
                         "sys.exit(0 if ('..' in p.parts and not p.is_absolute()) else 1)")
        cases.append(("锚点：'..' 段非绝对、is_absolute 独自拦不下",
                      anchor.returncode == 0, "rc=%d" % anchor.returncode))
        put_manifest(root, json.dumps({"t-dotdot": {"files": [
            {"path": "../secret.md", "contains": ["ok body"]}]}}, ensure_ascii=False))
        r = call(root, "t-dotdot")
        cases.append(("A4 files 含 '..' → rc=2（不验收根外文件）", r.returncode == 2,
                      "rc=%d %s" % (r.returncode, r.stdout[-90:])))
        put_manifest(root, json.dumps({"t-abs": {"files": [
            {"path": str(outside), "contains": ["ok body"]}]}}, ensure_ascii=False))
        r = call(root, "t-abs")
        cases.append(("A4 files 绝对路径 → rc=2", r.returncode == 2, "rc=%d" % r.returncode))
        put_manifest(root, json.dumps({"t-glob": {"globs": [
            {"pattern": "../*.md", "min_count": 1}]}}))
        r = call(root, "t-glob")
        cases.append(("A4 globs pattern 含 '..' → rc=2", r.returncode == 2,
                      "rc=%d" % r.returncode))
        put_manifest(root, json.dumps({"t-jdot": {"json_files": [
            {"path": "../secret.json", "min_items": 1}]}}))
        r = call(root, "t-jdot")
        cases.append(("A4 json_files path 含 '..' → rc=2", r.returncode == 2,
                      "rc=%d" % r.returncode))
        put_manifest(root, json.dumps({"t-absent": {"absent_paths": ["../secret.md"]}}))
        r = call(root, "t-absent")
        cases.append(("A4 absent_paths 含 '..' → rc=2", r.returncode == 2,
                      "rc=%d" % r.returncode))
        put_manifest(root, json.dumps({"t-clean": {"files": [
            {"path": "ok.txt", "contains": ["clean body"]}]}}))
        r = call(root, "t-clean")
        cases.append(("A4 对照：合法相对路径 → rc=0（不误杀）", r.returncode == 0,
                      "rc=%d" % r.returncode))

    for name, ok, ev in cases:
        print("  %-52s %s  %s" % (name, "OK" if ok else "MISMATCH", "" if ok else ev))
        if not ok:
            bad += 1
    return 1 if bad else 0


def run_b03_hardening_guards() -> int:
    """B03（round3）：判据核硬化——空白归一 / 目录归 rc=2 / NUL 编码 / 空断言形态档。"""
    print("== B03 判定核硬化守卫（空白归一/目录/NUL/空断言）==")
    bad = 0
    cases: list[tuple[str, bool, str]] = []

    def call(root: pathlib.Path, *args) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, "-B", "-X", "utf8", str(VERIFY), *args,
                               "--root", str(root)], capture_output=True, text=True,
                              encoding="utf-8", errors="replace")

    def put(root: pathlib.Path, obj) -> str:
        (root / "70-tools").mkdir(parents=True, exist_ok=True)
        (root / "70-tools" / "71-verify-manifest.json").write_text(
            json.dumps(obj, ensure_ascii=False), encoding="utf-8")
        return next(iter(obj))

    with tempfile.TemporaryDirectory() as td:
        base = pathlib.Path(td)
        root = base / "core"
        root.mkdir()
        # G-1 空白归一：'AUTHOR CONFIRM' 被换行 / 全角空格拆开 → 仍须命中 forbid
        (root / "x.md").write_text("AUTHOR\nCONFIRM\n", encoding="utf-8")
        cases.append(("G-1 forbid 换行拆分（AUTHOR\\nCONFIRM）→ rc=1",
                      call(root, put(root, {"t-nl": {"files": [
                          {"path": "x.md", "forbid": ["AUTHOR CONFIRM"]}]}})).returncode == 1, ""))
        (root / "y.md").write_text("需作者\u3000确认\n", encoding="utf-8")
        cases.append(("G-1 forbid 全角空格（需作者\\u3000确认）→ rc=1",
                      call(root, put(root, {"t-fw": {"files": [
                          {"path": "y.md", "forbid": ["需作者 确认"]}]}})).returncode == 1, ""))
        # R5（round4 R4-3）：中文连写 needle 对拆词结构性失明——旧双判下以下两例 rc=0。
        # 三判（原文/折叠/全剥，剥式仅 CJK needle 开放）后必须 rc=1 点名。
        (root / "cjk1.md").write_text("需作者\u3000确认\n", encoding="utf-8")
        cases.append(("R4-3 中文连写 needle + 全角拆词（需作者\\u3000确认）→ rc=1",
                      call(root, put(root, {"t-cjk1": {"files": [
                          {"path": "cjk1.md", "forbid": ["需作者确认"]}]}})).returncode == 1, ""))
        (root / "cjk2.md").write_text("需作者 确认\n", encoding="utf-8")
        cases.append(("R4-3 中文连写 needle + 半角拆词 → rc=1",
                      call(root, put(root, {"t-cjk2": {"files": [
                          {"path": "cjk2.md", "forbid": ["需作者确认"]}]}})).returncode == 1, ""))
        (root / "cjk3.md").write_text("本节需作者\n确认后投稿\n", encoding="utf-8")
        cases.append(("R4-3 中文连写 needle + 换行拆词 → rc=1",
                      call(root, put(root, {"t-cjk3": {"files": [
                          {"path": "cjk3.md", "forbid": ["需作者确认"]}]}})).returncode == 1, ""))
        cases.append(("R4-3 contains 侧对称：全角拆词正文仍命中中文 needle → rc=0",
                      call(root, put(root, {"t-cjk4": {"files": [
                          {"path": "cjk1.md", "contains": ["需作者确认"]}]}})).returncode == 0, ""))
        # R5 英文防退化与不误伤：NBSP/原文拆词仍红；剥式被 CJK 门控挡在英文之外，
        # 合法连写词 DATASET 对 forbid "DATA SET" 必须 rc=0（旧版同为 rc=0）。
        (root / "en1.md").write_text("AUTHOR\u00a0CONFIRM\n", encoding="utf-8")
        cases.append(("R4-3 英文 NBSP 拆词 → rc=1（防退化）",
                      call(root, put(root, {"t-en1": {"files": [
                          {"path": "en1.md", "forbid": ["AUTHOR CONFIRM"]}]}})).returncode == 1, ""))
        (root / "en2.md").write_text("AUTHOR CONFIRM\n", encoding="utf-8")
        cases.append(("R4-3 英文原文命中 → rc=1（防退化）",
                      call(root, put(root, {"t-en2": {"files": [
                          {"path": "en2.md", "forbid": ["AUTHOR CONFIRM"]}]}})).returncode == 1, ""))
        (root / "en3.md").write_text("DATASET release\n", encoding="utf-8")
        cases.append(("R4-3 英文合法连写词不误伤（DATASET vs 'DATA SET'）→ rc=0",
                      call(root, put(root, {"t-en3": {"files": [
                          {"path": "en3.md", "forbid": ["DATA SET"]}]}})).returncode == 0, ""))
        # G-3 目录当产物 → rc=2
        (root / "adir").mkdir()
        cases.append(("G-3 files[].path 指目录 → rc=2（不 rc=0/PermissionError）",
                      call(root, put(root, {"t-dir": {"files": [
                          {"path": "adir", "min_bytes": 1}]}})).returncode == 2, ""))
        # G-4 UTF-16LE 无 BOM（含 NUL）→ rc=2
        (root / "u16.md").write_bytes("TODO item".encode("utf-16-le"))
        cases.append(("G-4 UTF-16LE 无 BOM（含 NUL）→ rc=2（forbid 不失明）",
                      call(root, put(root, {"t-u16": {"files": [
                          {"path": "u16.md", "forbid": ["TODO"]}]}})).returncode == 2, ""))
        # F-1 空断言形态档 → rc=2
        (root / "z.md").write_text("body", encoding="utf-8")
        (root / "j.json").write_text('[{"a": 1}]', encoding="utf-8")
        for name, tid, item in (
                ("contains 空列表", "t-c0", {"files": [{"path": "z.md", "contains": []}]}),
                ("contains 空串", "t-c1", {"files": [{"path": "z.md", "contains": [""]}]}),
                ("min_matches.min=0", "t-mm0", {"files": [{"path": "z.md",
                                                           "min_matches": {"pattern": "x", "min": 0}}]}),
                ("forbid 空列表", "t-f0", {"files": [{"path": "z.md", "forbid": []}]}),
                ("contains_regex 空串", "t-cr0", {"files": [{"path": "z.md",
                                                            "contains_regex": [""]}]}),
                ("require_keys 空表", "t-rk0", {"json_files": [{"path": "j.json",
                                                                "min_items": 1,
                                                                "require_keys": []}]}),
                ("min_items:0", "t-mi0", {"json_files": [{"path": "j.json",
                                                          "min_items": 0,
                                                          "require_keys": ["a"]}]}),
                ("globs 无 min_count/min_bytes_each", "t-g0", {"globs": [{"pattern": "*.md"}]})):
            cases.append(("F-1 %s → rc=2" % name,
                          call(root, put(root, {tid: item})).returncode == 2, ""))
        # 干净对照：正常 forbid 命中仍 rc=1；合法条目 rc=0
        (root / "hit.md").write_text("TODO here\n", encoding="utf-8")
        cases.append(("对照：正常 forbid 命中 → rc=1（不误升 rc=2）",
                      call(root, put(root, {"t-hit": {"files": [
                          {"path": "hit.md", "forbid": ["TODO"]}]}})).returncode == 1, ""))
        cases.append(("对照：合法条目 → rc=0",
                      call(root, put(root, {"t-ok": {"files": [
                          {"path": "hit.md", "min_bytes": 1}]}})).returncode == 0, ""))

    for name, ok, ev in cases:
        print("  %-56s %s  %s" % (name, "OK" if ok else "MISMATCH", "" if ok else ev))
        if not ok:
            bad += 1
    return 1 if bad else 0


def run_b06_require_values_guards() -> int:
    """B06a（round3）：70 的值判定原语 `require_values`——布尔/字符串等值的逐条硬口径。

    背景：json 面只有 require_keys*（键存在）时，`two_source_verified: false` 会被当"字段在"
    放行（验真门形同虚设）。本守卫经真实 70-verify.py 子进程做正反控制：
    - 反向：`two_source_verified:false` → rc=1 且点名键与实测值（真拦）；
    - 正向：全等值 → rc=0；对象顶层等值 → rc=0；
    - 形态档：非对象 / 空对象 / 值为容器 → rc=2；
    - 空断言：空列表 + require_values 无 min_items → rc=1（不静默放绿）。
    """
    print("== B06a require_values 值判定守卫 ==")
    bad = 0
    cases: list[tuple[str, bool, str]] = []

    def call(root: pathlib.Path, tid: str) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, "-B", "-X", "utf8", str(VERIFY), tid,
                               "--root", str(root)], capture_output=True, text=True,
                              encoding="utf-8", errors="replace")

    def put(root: pathlib.Path, obj) -> None:
        (root / "70-tools").mkdir(parents=True, exist_ok=True)
        (root / "70-tools" / "71-verify-manifest.json").write_text(
            json.dumps(obj, ensure_ascii=False), encoding="utf-8")

    with tempfile.TemporaryDirectory() as td:
        root = pathlib.Path(td) / "rv"
        root.mkdir()
        (root / "70-tools").mkdir()
        (root / "good.json").write_text(json.dumps(
            [{"doi": "10.1/a", "two_source_verified": True},
             {"doi": "10.1/b", "two_source_verified": True}]), encoding="utf-8")
        (root / "bad.json").write_text(json.dumps(
            [{"doi": "10.1/a", "two_source_verified": True},
             {"doi": "10.1/b", "two_source_verified": False}]), encoding="utf-8")
        (root / "empty.json").write_text("[]", encoding="utf-8")
        (root / "obj.json").write_text(json.dumps({"gate": True}), encoding="utf-8")

        put(root, {"t-rv-ok": {"json_files": [
            {"path": "good.json", "min_items": 1,
             "require_values": {"two_source_verified": True}}]}})
        r = call(root, "t-rv-ok")
        cases.append(("require_values 全等值 → rc=0（正控制）", r.returncode == 0,
                      "rc=%d %s" % (r.returncode, r.stdout[-90:])))

        put(root, {"t-rv-bad": {"json_files": [
            {"path": "bad.json", "min_items": 1,
             "require_values": {"two_source_verified": True}}]}})
        r = call(root, "t-rv-bad")
        cases.append(("two_source_verified:false → rc=1（真拦）", r.returncode == 1,
                      "rc=%d" % r.returncode))
        cases.append(("反向对照点名键与实测值",
                      "two_source_verified" in r.stdout and "False" in r.stdout,
                      r.stdout[-140:]))

        put(root, {"t-rv-empty": {"json_files": [
            {"path": "empty.json", "require_values": {"two_source_verified": True}}]}})
        r = call(root, "t-rv-empty")
        cases.append(("空列表 + require_values 无 min_items → 不静默放绿（rc=1）",
                      r.returncode == 1, "rc=%d %s" % (r.returncode, r.stdout[-90:])))

        put(root, {"t-rv-nondict": {"json_files": [
            {"path": "good.json", "min_items": 1,
             "require_values": ["two_source_verified"]}]}})
        cases.append(("require_values 非对象 → rc=2（形态档）",
                      call(root, "t-rv-nondict").returncode == 2, ""))
        put(root, {"t-rv-emptyobj": {"json_files": [
            {"path": "good.json", "min_items": 1, "require_values": {}}]}})
        cases.append(("require_values 空对象 → rc=2（空断言形态错）",
                      call(root, "t-rv-emptyobj").returncode == 2, ""))
        put(root, {"t-rv-containerval": {"json_files": [
            {"path": "good.json", "min_items": 1,
             "require_values": {"two_source_verified": [True]}}]}})
        cases.append(("require_values 值为容器 → rc=2（只接受标量）",
                      call(root, "t-rv-containerval").returncode == 2, ""))

        put(root, {"t-rv-obj-ok": {"json_files": [
            {"path": "obj.json", "require_values": {"gate": True}}]}})
        cases.append(("对象顶层 require_values 等值 → rc=0",
                      call(root, "t-rv-obj-ok").returncode == 0, ""))
        put(root, {"t-rv-obj-bad": {"json_files": [
            {"path": "obj.json", "require_values": {"gate": False}}]}})
        cases.append(("对象顶层 require_values 不等 → rc=1",
                      call(root, "t-rv-obj-bad").returncode == 1, ""))

    for name, ok, ev in cases:
        print("  %-52s %s  %s" % (name, "OK" if ok else "MISMATCH", "" if ok else ev))
        if not ok:
            bad += 1
    return 1 if bad else 0


def run_b07_declare_and_count_guards() -> int:
    """B07a（round3）：70 计数绑死原语 declare_and_count——「声明 N 条 ⇒ 实际须 N 条」。

    背景（review A-6，亲跑）：F-9R 的「共 N 条」逃生门不核 N 与正文条目数，`共 999 条` 零条目
    即放行。本守卫经真实 70-verify.py 子进程做正反控制：999/0 → rc=1；0/0、8/8 → rc=0；
    8/7 → rc=1；缺声明行 → rc=1；四类形态错 → rc=2。
    """
    print("== B07a declare_and_count 声明绑死守卫 ==")
    bad = 0
    cases: list[tuple[str, bool, str]] = []

    def call(root: pathlib.Path, tid: str) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, "-B", "-X", "utf8", str(VERIFY), tid,
                               "--root", str(root)], capture_output=True, text=True,
                              encoding="utf-8", errors="replace")

    def put(root: pathlib.Path, item) -> None:
        (root / "70-tools").mkdir(parents=True, exist_ok=True)
        (root / "70-tools" / "71-verify-manifest.json").write_text(
            json.dumps({"t-dc": {"files": [{"path": "refs.md", "declare_and_count": item}]}},
                       ensure_ascii=False), encoding="utf-8")

    _item = {"pattern": r"\[\d+\]", "declare_regex": r"共\s*(\d+)\s*条"}
    _8 = "\n".join("[%d] entry" % i for i in range(1, 9))

    with tempfile.TemporaryDirectory() as td:
        root = pathlib.Path(td) / "dc"
        root.mkdir()
        (root / "70-tools").mkdir()

        def refs(text):
            (root / "refs.md").write_text(text, encoding="utf-8")

        refs("参考文献共 999 条\n")
        put(root, _item)
        r = call(root, "t-dc")
        cases.append(("共 999 条 + 0 条目 → rc=1（幽灵声明被拦）", r.returncode == 1,
                      "rc=%d" % r.returncode))
        cases.append(("反向对照点名 declared/actual",
                      "declared 999 != actual 0" in r.stdout, r.stdout[-140:]))

        refs("参考文献共 0 条\n")
        put(root, _item)
        cases.append(("共 0 条 + 0 条目 → rc=0",
                      call(root, "t-dc").returncode == 0, ""))
        refs("参考文献共 8 条\n" + _8 + "\n")
        put(root, _item)
        cases.append(("共 8 条 + 8 个 [n] → rc=0",
                      call(root, "t-dc").returncode == 0, ""))
        refs("参考文献共 8 条\n" + "\n".join("[%d] e" % i for i in range(1, 8)) + "\n")
        put(root, _item)
        r = call(root, "t-dc")
        cases.append(("共 8 条 + 7 个 → rc=1", r.returncode == 1, "rc=%d" % r.returncode))
        cases.append(("差 1 也点名 declared 8 != actual 7",
                      "declared 8 != actual 7" in r.stdout, r.stdout[-140:]))
        refs("没有声明行\n" + _8 + "\n")
        put(root, _item)
        r = call(root, "t-dc")
        cases.append(("缺声明行 → rc=1（不得判 PASS）", r.returncode == 1, "rc=%d" % r.returncode))

        # 可编译但捕获组非整数 / 未捕获（不裸 traceback）
        refs("参考文献共 abc 条\n" + _8 + "\n")
        put(root, {"pattern": r"\[\d+\]", "declare_regex": r"共\s*(\D+)\s*条"})
        r = call(root, "t-dc")
        cases.append(("捕获组非整数 → rc=1 不裸 traceback",
                      r.returncode == 1 and "Traceback" not in (r.stdout + r.stderr),
                      "rc=%d tail=%s" % (r.returncode, (r.stdout + r.stderr)[-80:])))
        refs("参考文献共 条\n" + _8 + "\n")
        put(root, {"pattern": r"\[\d+\]", "declare_regex": r"共(?:\s*(\d+))?\s*条"})
        r = call(root, "t-dc")
        cases.append(("可选捕获组未捕获 → rc=1 不裸 traceback",
                      r.returncode == 1 and "Traceback" not in (r.stdout + r.stderr),
                      "rc=%d tail=%s" % (r.returncode, (r.stdout + r.stderr)[-80:])))

        for name, item in (
                ("非对象", ["x"]),
                ("缺 declare_regex", {"pattern": r"\[\d+\]"}),
                ("declare_regex 无捕获组", {"pattern": r"\[\d+\]",
                                          "declare_regex": r"共\s*\d+\s*条"}),
                ("pattern 非法正则", {"pattern": "[", "declare_regex": r"共\s*(\d+)\s*条"})):
            put(root, item)
            cases.append(("形态错：%s → rc=2" % name, call(root, "t-dc").returncode == 2, ""))

    for name, ok, ev in cases:
        print("  %-52s %s  %s" % (name, "OK" if ok else "MISMATCH", "" if ok else ev))
        if not ok:
            bad += 1
    return 1 if bad else 0


def run_gen_shape_guards() -> int:
    """B13（round3 A-11/B-7）：build 入口集中形態檔。

    背景（亲跑）：任务四键写成标量时，`list(标量)` 把字符串逐字拆散——edit 短标量
    无声落盘成单字文件表（problems=0），read 标量在 `r["path"]` 抛裸 TypeError
    （rc=1 冒充 FAIL）；profile 轴值拼错只在 emit 期打 warn（无 fragments 更全程
    静默）。修后：四键須 list、read 項須 dict 含非空 path、edit 項須真實路徑形態、
    axes 键在闭集且值在词汇内；违规记 problems（[shape] 前缀 → CLI rc=2）并点名
    `档:任务:键`。本守卫配双锚点（旧习语确实 char-split/确实 TypeError）+ 合规档
    正向对照 + 00 基类不误伤对照。
    """
    print("== 生成器形態檔守衛（B13/A-11/B-7）==")
    bad = 0
    cases: list[tuple[str, bool, str]] = []

    def snippet(code: str) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, "-B", "-c", code], capture_output=True,
                              text=True, encoding="utf-8", errors="replace")

    # ==== 锚点：旧习语确实有洞（守卫不是陪跑）====
    anchor = snippet("import sys;sys.exit(0 if list('ab')==['a','b'] else 1)")
    cases.append(("锚点A-11a：旧 `list(短标量)` 确实 char-split", anchor.returncode == 0,
                  "rc=%d" % anchor.returncode))
    anchor = snippet("try:\n    'x'['path']\nexcept TypeError:\n    import sys;sys.exit(3)\n")
    cases.append(("锚点A-11b：旧 `标量[\"path\"]` 确实裸 TypeError", anchor.returncode == 3,
                  "rc=%d" % anchor.returncode))

    def min_prof() -> dict:
        return {
            "id": "shape", "version": "1", "tool_dir": "70-tools",
            "paths": {"admin": "00-admin"},
            "project": {"name": "x", "brief": "b", "review_mode": "unified"},
            "modules": [{"id": "m", "name": "m", "role": "r"}],
            "evidence_policy": {},
            "tasks": [{"id": "task-x", "module": "m", "name": "n", "brief": "b",
                       "ac": ["`10-data/out.md` 逐值核对。", "不得臆造。", "结论落边界。"],
                       "inject": [], "read": [], "edit": ["10-data/out.md"],
                       "verify": "python {verify_tool} task-x"}],
            "verify_assertions_template": [{"task": "*", "apply_to": "edit_files_text",
                                            "forbid": ["TODO"]}],
        }

    def build_quiet(prof: dict):
        with contextlib.redirect_stdout(io.StringIO()):
            return gen30.build(prof)

    def shape_of(prof: dict) -> list:
        try:
            b = build_quiet(prof)
        except Exception as exc:                               # noqa: BLE001
            return ["<EXC %s: %s>" % (type(exc).__name__, exc)]
        return [p for p in b["problems"] if p.startswith(gen30.SHAPE_PREFIX)]

    def mutate(task_mut: dict | None = None, axes: dict | str | None = "keep"):
        p = min_prof()
        if task_mut:
            p["tasks"][0].update(task_mut)
        if axes != "keep":
            if axes is None:
                p.pop("axes", None)
            else:
                p["axes"] = axes
        return p

    # ==== 合规正向对照：合成最小档 0 problems ====
    cases.append(("正向：合规合成档 build 0 problems（含 0 shape）",
                  build_quiet(min_prof())["problems"] == [],
                  str(build_quiet(min_prof())["problems"])[:90]))

    # ==== A-11：四键标量 → problems 点名（不再裸崩/char-split）====
    for label, mut, needle in (
            ("read 标量 → rc=2 点名（不再裸 TypeError）", {"read": "10-data/a.md"},
             "shape:task-x:read"),
            ("edit 短标量 → rc=2 点名（不再 char-split）", {"edit": "ab"},
             "shape:task-x:edit"),
            ("inject 标量 → rc=2 点名", {"inject": "somekey"}, "shape:task-x:inject"),
            ("ac 标量 → rc=2 点名", {"ac": "do something"}, "shape:task-x:ac")):
        hit = shape_of(mutate(mut))
        cases.append((label, len(hit) == 1 and needle in hit[0], str(hit)[:110]))

    # ==== 项级形态：read 须 dict 含 path、edit 须真实路径、inject/ac 项须串 ====
    for label, mut, needle in (
            ("read 项为字符串 → 点名 read[0]", {"read": ["10-data/a.md"]},
             "shape:task-x:read[0]"),
            ("read 项缺 path → 点名 read[0]", {"read": [{"priority": "must_read"}]},
             "shape:task-x:read[0]"),
            ("read 项 path 非串 → 点名 read[0]", {"read": [{"path": 123}]},
             "shape:task-x:read[0]"),
            ("edit 项非串 → 点名 edit[1]",
             {"edit": ["10-data/out.md", 123]}, "shape:task-x:edit[1]"),
            ("edit 目录式 → 点名（非真实路径）", {"edit": ["10-data/"]},
             "shape:task-x:edit[0]"),
            ("edit 通配符 → 点名（非真实路径）", {"edit": ["10-data/*.csv"]},
             "shape:task-x:edit[0]"),
            ("inject 项非串 → 点名 inject[0]", {"inject": [7]},
             "shape:task-x:inject[0]"),
            ("ac 项非串 → 点名 ac[0]", {"ac": [7, "不得臆造。", "结论落边界。"]},
             "shape:task-x:ac[0]")):
        hit = shape_of(mutate(mut))
        cases.append((label, len(hit) == 1 and needle in hit[0], str(hit)[:110]))

    # ==== B-7：axes 键/值形态 → rc=2 点名 ====
    for label, axes, needle in (
            ("axes 未知键 → 点名 axes:键", {"publishre": "elsevier"},
             "shape:axes:publishre"),
            ("axes 拼错值 → 点名 axes:键=值", {"publisher": "elsevire"},
             "shape:axes:publisher=elsevire"),
            ("axes 本体非映射 → 点名 axes", "oops", "shape:axes "),
            ("axes 值非串 → 点名 axes:键", {"publisher": 123},
             "shape:axes:publisher")):
        hit = shape_of(mutate(None, axes))
        cases.append((label, len(hit) == 1 and needle in hit[0], str(hit)[:110]))

    # ==== B-7 正向：4 档逐档 build 0 problems（改后无新增）+ 词汇闭包 ====
    for prof_name in ("10-materials-chemistry.yaml", "10-clinical.yaml",
                      "20-social-science.yaml", "30-cs-ml.yaml"):
        prof = gen30.load_profile(HERE.parent / "profiles" / prof_name)
        axes = prof.get("axes") or {}
        vocab_ok = (set(axes) <= set(gen30.FRAGMENT_AXES_KEYS)
                    and all((x in gen30.PROFILE_AXES_VALUES.get(k, set()))
                                for k, vs in axes.items()
                                for x in (vs if isinstance(vs, list) else [vs])))
        with contextlib.redirect_stdout(io.StringIO()):
            b = gen30.build(prof)
        cases.append(("%s 合规：词汇闭包且 0 problems" % prof_name,
                      vocab_ok and b["problems"] == [],
                      "problems=%s" % b["problems"][:1]))
    # evidence_form 变体值在词汇内：合法变体不被当拼错（形态档只拦真错）
    cases.append(("evidence_form 变体 lab-experimental-with-eis 在词汇内（变体≠拼错）",
                  "lab-experimental-with-eis"
                  in gen30.PROFILE_AXES_VALUES.get("evidence_form", set()), ""))
    # materials 派生变体 mismatch 仍只 warn（emit 期提示保留，不升级）且 build 无 shape
    _mat_var = gen30.load_profile(HERE.parent / "profiles" / "10-materials-chemistry.yaml")
    _mat_var["axes"] = {**(_mat_var.get("axes") or {}),
                        "evidence_form": "lab-experimental-with-eis"}
    cap = io.StringIO()
    with contextlib.redirect_stdout(cap):
        gen30.rules_fragment(_mat_var)
    with contextlib.redirect_stdout(io.StringIO()):
        bw = gen30.build(_mat_var)
    cases.append(("materials 变体：warn 保留且 build 0 shape（不误伤）",
                  "warn" in cap.getvalue()
                  and not [p for p in bw["problems"]
                           if p.startswith(gen30.SHAPE_PREFIX)], cap.getvalue()[:90]))

    # ==== 反向对照：摘除形态档 → 同一坏档 shape 消失（旧路裸崩/静默）====
    saved_task, saved_axes = gen30._task_shape_problems, gen30._axes_shape_problems
    gen30._task_shape_problems = lambda *a, **k: []
    gen30._axes_shape_problems = lambda *a, **k: []
    try:
        off_axes = shape_of(mutate(None, {"publisher": "elsevire"}))
        with contextlib.redirect_stdout(io.StringIO()):
            gen30.build(mutate({"read": "10-data/a.md"}))
        crashed, crashed_ok = "未抛异常（旧路应裸 TypeError）", False
    except TypeError:
        crashed, crashed_ok = "旧路裸 TypeError（洞真实）", True
    finally:
        gen30._task_shape_problems, gen30._axes_shape_problems = saved_task, saved_axes
    cases.append(("反向对照：摘除任务形态档 → read 标量走旧路裸崩（非 shape）",
                  crashed_ok, crashed))
    cases.append(("反向对照：摘除 axes 形态档 → 拼错值 shape 消失", off_axes == [],
                  str(off_axes)[:80]))

    # ==== CLI 级：rc 语义 + 先拒后写 + 00 基类不误伤 ====
    gen = HERE / "30-gen-proposals.py"

    def cli(prof_dict: dict):
        import yaml
        with tempfile.TemporaryDirectory() as td:
            pf = pathlib.Path(td) / "shape-profile.yaml"
            pf.write_text(yaml.safe_dump(prof_dict, allow_unicode=True), encoding="utf-8")
            out = pathlib.Path(td) / "build"
            r = subprocess.run([sys.executable, "-B", "-X", "utf8", str(gen),
                                "--profile", str(pf), "--out", str(out)],
                               capture_output=True, text=True, encoding="utf-8",
                               errors="replace")
            born = (r.stdout or "") + (r.stderr or "")
            left = sorted(p.name for p in out.rglob("*")) if out.exists() else []
            return r.returncode, born, left

    rc, born, left = cli(mutate({"read": "10-data/a.md"}))
    cases.append(("CLI：read 标量 rc=2 且点名（无 Traceback）",
                  rc == 2 and "shape:task-x:read" in born and "Traceback" not in born,
                  "rc=%d %s" % (rc, born.strip()[-90:])))
    rc, born, left = cli(mutate({"edit": "ab"}))
    cases.append(("CLI：edit 短标量 rc=2、不落生成物（char-split 不再落盘）",
                  rc == 2 and "shape:task-x:edit" in born and not left,
                  "rc=%d left=%s" % (rc, left)))
    rc, born, left = cli(mutate(None, {"publisher": "elsevire"}))
    cases.append(("CLI：axes 拼错 rc=2 且点名", rc == 2 and "shape:axes:publisher=elsevire" in born,
                  "rc=%d %s" % (rc, born.strip()[-90:])))
    rc, born, left = cli(min_prof())
    cases.append(("CLI：合规合成档 rc=0 且落盘（防过度收紧）",
                  rc == 0 and len(left) >= 4,
                  "rc=%d files=%d" % (rc, len(left))))
    bad_content = min_prof()
    bad_content["tasks"][0]["ac"] = ["第一条行为描述。", "第二条行为描述。", "第三条行为描述。"]
    rc, born, left = cli(bad_content)
    cases.append(("CLI：纯内容类 problems 仍 rc=1（映射不扩大）",
                  rc == 1 and "[shape]" not in born, "rc=%d" % rc))
    with tempfile.TemporaryDirectory() as td:
        r = subprocess.run([sys.executable, "-B", "-X", "utf8", str(gen),
                            "--profile", str(HERE.parent / "profiles" / "00-base-empirical.yaml"),
                            "--out", str(pathlib.Path(td) / "base")],
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
        born = (r.stdout or "") + (r.stderr or "")
    cases.append(("00 基类：仍走 extends 模板通道 rc=2、无 [shape]（不误伤）",
                  r.returncode == 2 and "extends 模板" in born and "[shape]" not in born,
                  "rc=%d %s" % (r.returncode, born.strip()[-110:])))

    for name, ok, ev in cases:
        print("  %-52s %s  %s" % (name, "OK" if ok else "MISMATCH", "" if ok else ev))
        if not ok:
            bad += 1
    return 1 if bad else 0


def run_exclude_exempt_guards() -> int:
    """B13（B-6/G-15，round3）：exclude/forbid 通配 fill 统一与豁免差集收口。

    背景：通配模板的 exclude/forbid 从未走 fill()——`{ms}/…` 占位符形态与展开后路径
    静默失配；vendor 豁免只看 basename（发货目录外的同名文件被误豁免）；strip 把
    manifest 项下 contains/min_matches 连 forbid 一起删；拼错/过期 exclude 零命中也
    无声通过。修后：forbid/exclude 先 fill 再展开；vendor 按全路径判；strip 只剥
    forbid/forbid_regex；空命中 exclude die 点名。本守卫四组正反控制。
    """
    print("== exclude 豁免差集守卫（B13/B-6/G-15）==")
    cases: list[tuple[str, bool, str]] = []
    bad = 0

    def xprof(exclude, forbid=("TODO",),
              edit=("30-manuscript/sections/a.md", "30-manuscript/skip.md",
                    "30-manuscript/36-draft.md")):
        return ({
            "id": "x", "version": "1", "tool_dir": "70-tools",
            "paths": {"ms": "30-manuscript"},
            "verify_assertions_template": [
                {"task": "*", "apply_to": "edit_files_text",
                 "forbid": list(forbid), "exclude": list(exclude)}],
        }, [{"id": "task-x", "files_to_edit": list(edit)}])

    def expand(prof, tasks):
        with contextlib.redirect_stdout(io.StringIO()):
            return gen30.verify_fragment(prof, tasks)

    def dies(prof, tasks):
        cap = io.StringIO()
        try:
            with contextlib.redirect_stdout(cap):
                gen30.verify_fragment(prof, tasks)
        except SystemExit as exc:
            return exc.code, cap.getvalue()
        return None, cap.getvalue()

    # 锚点：占位符未展开时确实与展开后路径失配（fill 的必要性证明，非陪跑）。
    cases.append(("锚点：未展开占位符与展开后路径失配",
                  not gen30._matches_exclude("30-manuscript/x.md", ["{ms}/x.md"])
                  and gen30._matches_exclude("30-manuscript/x.md",
                                             ["30-manuscript/x.md"]), ""))

    # ==== F-fill：占位符与字面同命中 ====
    got = sorted(f["path"] for f in
                 expand(*xprof(["{ms}/sections/*", "{ms}/skip.md"]))["task-x"].get("files", []))
    cases.append(("F-占位符 exclude 命中展开后路径（分节+skip 豁免，draft 保留）",
                  got == ["30-manuscript/36-draft.md"], str(got)))
    prof_lit, tasks_lit = xprof(["30-manuscript/sections/*", "30-manuscript/skip.md"])
    got_lit = sorted(f["path"] for f in
                     expand(prof_lit, tasks_lit)["task-x"].get("files", []))
    cases.append(("F-字面与占位符展开结果一致（同命中）", got_lit == got, str(got_lit)))
    prof_f, tasks_f = xprof([], ("{ms}", "A { B"))
    fb = expand(prof_f, tasks_f)["task-x"]["files"][0]["forbid"]
    cases.append(("F-forbid 占位符展开、字面花括号保留（不裸崩）",
                  fb == ["30-manuscript", "A { B"], str(fb)))
    _saved_fill = gen30._fill_str_list
    gen30._fill_str_list = lambda items, ctx: list(items or [])
    try:
        rc_off, _ = dies(*xprof(["{ms}/sections/*"]))
    finally:
        gen30._fill_str_list = _saved_fill
    cases.append(("F-反向：摘除 fill 后占位符 exclude 零命中即 die（旧路静默失配被堵）",
                  rc_off == 2, "rc=%r" % rc_off))

    # ==== V-vendor：全路径匹配 ====
    def vprof(edit):
        return ({"id": "x", "tool_dir": "70-tools", "paths": {},
                 "verify_assertions_template": [
                     {"task": "*", "apply_to": "edit_files_text", "forbid": ["TODO"]}]},
                [{"id": "task-x", "files_to_edit": list(edit)}])

    got_v = sorted(f["path"] for f in
                   expand(*vprof(["70-tools/72-assemble-draft.py",
                                  "30-manuscript/36-draft.md"]))["task-x"].get("files", []))
    cases.append(("V-发货目录全路径豁免（工具无条目，draft 保留）",
                  got_v == ["30-manuscript/36-draft.md"], str(got_v)))
    got_b = expand(*vprof(["10-data/70-verify.py"]))["task-x"].get("files", [])
    cases.append(("V-同名不同目录不豁免（basename 旁路消除）",
                  len(got_b) == 1 and got_b[0]["forbid"] == ["TODO"], str(got_b)))
    got_d = expand(*vprof(["scripts/72-assemble-draft.py"]))["task-x"].get("files", [])
    cases.append(("V-目录错不豁免（tool_dir 对不上）",
                  len(got_d) == 1 and got_d[0]["forbid"] == ["TODO"], str(got_d)))
    cases.append(("V-直调：裸名/缺 tool_dir 不豁免",
                  gen30.is_vendor_tool("70-tools/72-assemble-draft.py", "70-tools") is True
                  and gen30.is_vendor_tool("72-assemble-draft.py", "70-tools") is False
                  and gen30.is_vendor_tool("70-tools/72-assemble-draft.py", None) is False, ""))

    # ==== S-strip：只剥缺席类 ====
    mpath = "70-tools/71-verify-manifest.json"
    item = {"path": mpath, "forbid": ["TODO"], "forbid_regex": ["x+"],
            "contains": ["a"], "min_matches": {"pattern": "x", "min": 1}, "min_bytes": 5}
    other = {"path": "other.md", "forbid": ["TODO"]}
    out = {"t": {"files": [dict(item), dict(other)]}}
    gen30.strip_manifest_text_assertions(
        out, {"tool_dir": "70-tools", "verify_manifest": mpath})
    cases.append(("S-manifest 只剥 forbid/forbid_regex，contains/min_matches 保留",
                  out["t"]["files"][0] == {"path": mpath, "contains": ["a"],
                                           "min_matches": {"pattern": "x", "min": 1},
                                           "min_bytes": 5},
                  str(out["t"]["files"][0])))
    cases.append(("S-反向：非 manifest 路径不动（forbid 保留，防过度剥离）",
                  out["t"]["files"][1] == other, str(out["t"]["files"][1])))
    again = {"t": {"files": [dict(f) for f in out["t"]["files"]]}}
    gen30.strip_manifest_text_assertions(
        again, {"tool_dir": "70-tools", "verify_manifest": mpath})
    cases.append(("S-幂等：strip 两次结果一致", again == out, ""))

    # ==== E-上报：空命中 die ====
    rc_ghost, out_ghost = dies(*xprof(["30-manuscript/no-such-dir/*"]))
    cases.append(("E-幽灵 exclude 上报（rc=2 且点名模式）",
                  rc_ghost == 2 and "no-such-dir" in out_ghost,
                  "rc=%r %s" % (rc_ghost, out_ghost.strip()[-80:])))
    rc_vo, _ = dies(*xprof(["70-tools/*"],
                            edit=("70-tools/72-assemble-draft.py",
                                  "30-manuscript/36-draft.md")))
    cases.append(("E-只命中范围外（vendor）的 exclude 上报",
                  rc_vo == 2, "rc=%r" % rc_vo))
    rc_wt, _ = dies(*xprof(["40-figures/*.png"],
                            edit=("40-figures/x.png", "30-manuscript/36-draft.md")))
    cases.append(("E-放错模板的 exclude 上报（二进制模式写进文本模板）",
                  rc_wt == 2, "rc=%r" % rc_wt))
    prof_b, tasks_b = xprof([], ("TODO",),
                            ("40-figures/x.png", "30-manuscript/36-draft.md"))
    prof_b["verify_assertions_template"].append(
        {"task": "*", "apply_to": "edit_files_binary",
         "min_bytes_each": 5000, "exclude": ["40-figures/*"]})
    rc_ok, _ = dies(prof_b, tasks_b)
    fb_ok = sorted(f["path"] for f in
                   expand(prof_b, tasks_b)["task-x"].get("files", []))
    cases.append(("E-正向：命中生效路径的 exclude 不误报（二进制豁免生效）",
                  rc_ok is None and fb_ok == ["30-manuscript/36-draft.md"], str(fb_ok)))

    for name, ok, ev in cases:
        print("  %-52s %s  %s" % (name, "OK" if ok else "MISMATCH", "" if ok else ev))
        if not ok:
            bad += 1
    return 1 if bad else 0


def run_vendor_exempt_guards() -> int:
    """A1（2026-10-07 审查）：vendor 发货工具豁免通配 forbid。

    真源 = install.py::install_project 的 vendor 清单；生成器展开 apply_to: edit_files_text
    时必须排除这些工具（否则其源码里的字面 TODO 被 forbid 咬成 task-assemble-draft 永久
    rc=1）。守卫四面：① 逐档生成物中 vendor 路径不带文本断言；② 端到端 materials
    task-assemble-draft 在合规产物下 rc=0；③ 反向对照——内存摘除豁免后同一路径必须重新
    长出 forbid 且 rc=1；④ VENDOR_TOOL_NAMES 与 install.py 实际清单交叉核对（防两处漂移）。
    B09（C-3）：⑤ 件头版本戳 × PROVENANCE 逐件 sha 两端一致（实装后已装件逐件对账，
    空清单=一致）+ ⑥ 反向对照——真实改动一件已装件内容后同一断言变红且只点名该件。
    """
    print("== vendor 发货工具豁免守卫（A1）==")
    cases: list[tuple[str, bool, str]] = []
    bad = 0
    text_keys = ("forbid", "contains", "contains_regex", "forbid_regex")
    profiles = sorted(p for p in (HERE.parent / "profiles").glob("*.yaml")
                      if not p.name.startswith("00-"))
    e2e_prof = HERE.parent / "profiles" / "10-materials-chemistry.yaml"

    def gen(profile_path: pathlib.Path) -> tuple[dict, dict, dict]:
        with contextlib.redirect_stdout(io.StringIO()):
            prof = gen30.load_profile(profile_path)
            built = gen30.build(prof)
            return (gen30.verify_fragment(prof, built["tasks"]),
                    {t["id"]: t for t in built["tasks"]}, prof)

    def run_v70(root: pathlib.Path, frag: pathlib.Path, tid: str) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, "-B", "-X", "utf8", str(VERIFY),
                               "--manifest", str(frag), "--root", str(root), tid],
                              capture_output=True, text=True, encoding="utf-8", errors="replace")

    # ④ 真源交叉核对：install.py 的 _PROJECT_FILES (src_rel, dst_name) 第二列 == VENDOR_TOOL_NAMES
    install_src = (HERE.parent / "install.py").read_text(encoding="utf-8-sig")
    m = re.search(r"_PROJECT_FILES = \((.*?)\n\n", install_src, re.S)
    declared = set(re.findall(r'\(\s*"[^"]+"\s*,\s*"([^"]+)"\s*\)', m.group(1))) if m else set()
    cases.append(("VENDOR_TOOL_NAMES 与 install.py vendor 清单逐项一致",
                  bool(declared) and declared == set(gen30.VENDOR_TOOL_NAMES),
                  "install=%s tool=%s" % (sorted(declared), sorted(gen30.VENDOR_TOOL_NAMES))))

    # ① 逐档生成物：vendor 路径不带任何文本断言；并确认守卫非空转（确有任务声明 vendor 工具）
    offenders: list[str] = []
    vendor_in_frag = 0
    tasks_with_vendor = 0
    for p in profiles:
        frag, tasks, prof = gen(p)
        _td = prof.get("tool_dir")
        for t in tasks.values():
            if any(gen30.is_vendor_tool(x, _td) for x in t.get("files_to_edit", [])):
                tasks_with_vendor += 1
        for tid, e in frag.items():
            for f in e.get("files", []):
                if not gen30.is_vendor_tool(f.get("path", ""), _td):
                    continue
                vendor_in_frag += 1
                hit = [k for k in text_keys if k in f]
                if hit:
                    offenders.append("%s/%s %s %s" % (p.stem, tid, f["path"], hit))
    cases.append(("逐档生成物: vendor 路径不带 forbid/contains*（豁免生效）",
                  not offenders, "; ".join(offenders[:4])))
    cases.append(("守卫非空转: 至少一个任务的 files_to_edit 含 vendor 工具",
                  tasks_with_vendor >= 1,
                  "tasks_with_vendor=%d" % tasks_with_vendor))
    cases.append(("豁免为「整体排除」而非仅摘 forbid（vendor 路径不出现在生成物）",
                  vendor_in_frag == 0, "vendor_in_frag=%d" % vendor_in_frag))

    # ③ 反向对照：内存摘除豁免 → vendor 路径重新长出 forbid
    saved = gen30.VENDOR_TOOL_NAMES
    frag_no_exempt: dict = {}
    try:
        gen30.VENDOR_TOOL_NAMES = frozenset()
        frag_no_exempt, _, _ = gen(e2e_prof)
    finally:
        gen30.VENDOR_TOOL_NAMES = saved
    revoked = [f for f in frag_no_exempt.get("task-assemble-draft", {}).get("files", [])
               if f.get("path", "").endswith("72-assemble-draft.py")]
    cases.append(("反向对照: 摘除豁免后 vendor 路径重新长出 forbid",
                  bool(revoked) and "forbid" in revoked[0],
                  "revoked=%r" % (revoked[:1] or None)))

    # ② 端到端：materials task-assemble-draft 合规产物 → rc=0；反向（含豁免摘除 + TODO 工具）→ rc=1
    frag_mat, _, _mat_prof = gen(e2e_prof)
    _manifest_rel = str(_mat_prof.get("verify_manifest") or "70-tools/71-verify-manifest.json").replace("\\", "/")
    _tool_rel = "%s/72-assemble-draft.py" % str(_mat_prof.get("tool_dir") or "70-tools").replace("\\", "/")
    with tempfile.TemporaryDirectory() as td:
        root = pathlib.Path(td)
        (root / "30-manuscript").mkdir(parents=True)
        (root / _manifest_rel).parent.mkdir(parents=True, exist_ok=True)
        # R5（round4 R4-4）：draft 区间按每句一行重算为 [187,1000] 后，旧 3000 行
        # 夹具超上界（合规产物定义随口径走）。取 500 行（区间中位），仍覆盖
        # Fig 两态 + min 1 形态，不碰其他断言。
        (root / "30-manuscript" / "36-draft.md").write_text(
            "**Fig. 1.** results\n**Fig. 2.** results\n"
            + "\n".join(["word " * 10] * 500), encoding="utf-8")
        (root / "30-manuscript" / "37-references.md").write_text(
            "\n".join("[%d] Author. Title. Journal. DOI:10.1/x" % i for i in range(1, 26)),
            encoding="utf-8")
        (root / _manifest_rel).write_text(
            "{}" + " " * 250, encoding="utf-8")
        f1 = root / "frag.json"
        f1.write_text(json.dumps(frag_mat, ensure_ascii=False), encoding="utf-8")
        r1 = run_v70(root, f1, "task-assemble-draft")
        cases.append(("端到端: 合规产物 + 含豁免生成物 → rc=0（修复前永久 rc=1）",
                      r1.returncode == 0,
                      "rc=%d %s" % (r1.returncode, (r1.stdout or "")[-110:])))
        # 反向：无豁免生成物 + 含 TODO 的 vendor 工具 → rc=1（证明原故障真被豁免消除）
        (root / _tool_rel).parent.mkdir(parents=True, exist_ok=True)
        (root / _tool_rel).write_text(
            "# TODO placeholder\n" + "# pad\n" * 40, encoding="utf-8")
        f2 = root / "frag-noexempt.json"
        f2.write_text(json.dumps(frag_no_exempt, ensure_ascii=False), encoding="utf-8")
        r2 = run_v70(root, f2, "task-assemble-draft")
        cases.append(("端到端反向: 摘除豁免 + 含 TODO 工具 → rc=1（原故障复现）",
                      r2.returncode == 1 and "72-assemble-draft.py" in (r2.stdout or ""),
                      "rc=%d %s" % (r2.returncode, (r2.stdout or "")[-110:])))

    # ── B09（C-3）：件头版本戳 × PROVENANCE 逐件 sha 两端一致 + 改一件即红 ──
    # 真源：vendor 六件文件头 `# vendor-tool: <件名> version <版本>`（解析口径与
    # install.py::vendor_tool_stamp 同形）；install.py::provenance() 把逐件
    # {version, sha256} 写进目标 PROVENANCE.json。同一函数 `_prov_problems` 既判正
    # （实装后已装件逐件对账→空清单）又判反（改一件内容→点名该件）：正反同一口径，
    # 反向若另起口径，对照只是陪跑。
    import hashlib as _hashlib
    _VENDOR_SRC = ("70-verify.py", "72-assemble-draft.py",
                   "72-compose-raster-figures.py", "72-latex-build-check.py",
                   "40-style-check.py", "45-consistency-check.py")

    def _vendor_stamp_of(data: bytes, name: str) -> str:
        for ln in data.decode("utf-8-sig").splitlines()[:12]:
            m = re.match(r"^# vendor-tool:\s*(\S+)\s+version\s+(\S+)\s*$", ln.strip())
            if m and m.group(1) == name:
                return m.group(2)
        return ""

    def _vendor_prov_problems(tools_dir: pathlib.Path, prov_vendor) -> list:
        """已装 70-tools/ 六件逐件对账 PROVENANCE 记录；返回点名清单（空=两端一致）。"""
        if not isinstance(prov_vendor, dict):
            prov_vendor = {}
        problems = []
        for _name in _VENDOR_SRC:
            try:
                _data = (tools_dir / _name).read_bytes()
            except OSError:
                problems.append("%s: 工具不在盘" % _name)
                continue
            _have = prov_vendor.get(_name)
            if not isinstance(_have, dict):
                problems.append("%s: PROVENANCE 缺该件记录" % _name)
                continue
            _ver = _vendor_stamp_of(_data, _name)
            if _have.get("version") != _ver or not _ver:
                problems.append("%s: 版本不一致（件头=%r PROVENANCE=%r）"
                                % (_name, _ver, _have.get("version")))
            elif _have.get("sha256") != _hashlib.sha256(_data).hexdigest():
                problems.append("%s: sha 不一致（内容已改动或装配过期）" % _name)
        return problems

    with tempfile.TemporaryDirectory() as _td:
        _t = pathlib.Path(_td) / "prov-target"
        _t.mkdir()
        _r = subprocess.run([sys.executable, "-B", "-X", "utf8", str(HERE.parent / "install.py"),
                             str(_t), "--mode", "project"],
                            capture_output=True, text=True, encoding="utf-8",
                            errors="replace", timeout=120)
        try:
            _prov = json.loads((_t / "PROVENANCE.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            _prov = {}
        _tools = _t / "70-tools"
        _ok_problems = _vendor_prov_problems(_tools, _prov.get("vendor_tools"))
        cases.append(("两端一致: 件头版本戳与 PROVENANCE 逐件 sha 一致",
                      _r.returncode == 0 and _ok_problems == [],
                      "rc=%d problems=%s" % (_r.returncode, _ok_problems[:2])))
        # 反向对照：真实改动一件已装件内容（尾部追加一字节）→ 同一断言变红且只点名该件
        _tamper = _tools / "72-assemble-draft.py"
        if _tamper.is_file():
            _tamper.write_bytes(_tamper.read_bytes() + b"\n# B09-tamper\n")
            _back = _vendor_prov_problems(_tools, _prov.get("vendor_tools"))
        else:
            _back = ["<installed 72-assemble-draft.py missing: 正向安装已失败>"]
        cases.append(("反向对照: 改一件已装件内容 → 同一断言变红并点名该件",
                      _back == ["72-assemble-draft.py: sha 不一致（内容已改动或装配过期）"],
                      "problems=%s" % (_back,)))

    for name, ok, ev in cases:
        print("  %-52s %s  %s" % (name, "OK" if ok else "MISMATCH", "" if ok else ev))
        if not ok:
            bad += 1
    return 1 if bad else 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", help="真实项目根（做 parity 比对）")
    a = ap.parse_args()
    rc = 0
    buf = io.StringIO()
    marks: list = []
    with contextlib.redirect_stdout(_Tee(sys.stdout, buf)):
        for label, fn in _SEGMENTS:
            start = buf.tell()
            rc |= fn()
            marks.append((label, start, buf.tell()))
        if a.project:
            rc |= run_parity(pathlib.Path(a.project).resolve())
    rc |= 1 if _segment_selfcheck(buf.getvalue(), marks) else 0
    print("\nSELFTEST %s" % ("PASS" if rc == 0 else "FAIL"))
    return rc


def run_unknown_key_guards() -> int:
    """F4（2026-10-06 审查）：manifest 未知键 fail-open 收口。

    shape_problems 曾只认五个段名与已知键类型——条目段名拼错（file 少个 s）被 .get()
    静默忽略成空段，等效"四段全空"直接 PASS（实测同缺失文件正确键 rc=1、拼错键 rc=0）。
    修后：条目级/项级未知键一律 rc=2 并点名键名；token_source 为合法标注键。"""
    print("== manifest 未知键守卫 ==")
    bad = 0
    verify = HERE / "70-verify.py"
    _spec = importlib.util.spec_from_file_location("v70", verify)
    v70 = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(v70)
    cases: list[tuple[str, bool, str]] = []
    ok_entry = {"files": [{"path": "ghost.md", "min_bytes": 10}]}
    typo_entry = {"file": [{"path": "ghost.md", "min_bytes": 10}]}
    item_typo = {"files": [{"path": "ghost.md", "min_bytes": 10, "min_lenght": 5}]}
    ts_entry = {"files": [{"path": "ghost.md", "min_bytes": 10,
                           "token_source": {"contains": {"X": "ac"}}}]}
    cases.append(("对照: 正确键+缺失文件 shape 无形态问题（FAIL 语义不变）",
                  v70.shape_problems("t-ok", ok_entry) == [], ""))
    p1 = v70.shape_problems("t-typo", typo_entry)
    cases.append(("条目级未知键（file 少 s）→ 形态问题点名 'file'",
                  any("'file'" in x for x in p1), repr(p1)[:90]))
    p2 = v70.shape_problems("t-item", item_typo)
    cases.append(("项级未知键 → 形态问题点名 'min_lenght'",
                  any("'min_lenght'" in x for x in p2), repr(p2)[:90]))
    cases.append(("token_source 仍为合法键（78 号标注不受影响）",
                  v70.shape_problems("t-ts", ts_entry) == [], ""))
    # 锚点：旧口径 verify_task 以 spec.get(seg) or [] 取段——拼错键确实取到空列表
    #（洞真实存在，修复不是陪跑装饰）
    cases.append(("锚点: 旧取段方式对拼错键得到空列表（等效空验收）",
                  (typo_entry.get("files") or []) == [], ""))
    with tempfile.TemporaryDirectory() as td:
        mp = pathlib.Path(td) / "m.json"
        mp.write_text(json.dumps({"task-demo-typo": typo_entry, "task-demo-ok": ok_entry}),
                      encoding="utf-8")
        r = subprocess.run([sys.executable, "-X", "utf8", str(verify), "--manifest", str(mp),
                            "--root", str(td), "task-demo-typo"], capture_output=True,
                           text=True, encoding="utf-8", errors="replace")
        cases.append(("CLI: 未知键 rc=2", r.returncode == 2,
                      "rc=%d out=%r" % (r.returncode, (r.stdout + r.stderr)[-90:])))
        r2 = subprocess.run([sys.executable, "-X", "utf8", str(verify), "--manifest", str(mp),
                             "--root", str(td), "task-demo-ok"], capture_output=True,
                            text=True, encoding="utf-8", errors="replace")
        cases.append(("CLI: 正确键 rc=1（缺失文件 FAIL 不变）", r2.returncode == 1,
                      "rc=%d" % r2.returncode))
    for name, ok, ev in cases:
        print("  %-52s %s  %s" % (name, "OK" if ok else "MISMATCH", "" if ok else ev))
        if not ok:
            bad += 1
    return 1 if bad else 0


# B01（round3 元守卫改行为级）：守卫段接线**单一真源** + 段数棘轮 + 段头自证 + 段体非空自证。
# main() 遍历本表分发：删任一段即 _SEGMENT_COUNT 棘轮变红；段体掏空或段头漂移同样变红。
_SEGMENT_COUNT = 20
_SEGMENTS = [
    ("合成控制套件", run_suite),
    ("manifest guards", run_manifest_guards),
    ("退出码语义守卫", run_rc_semantics_guards),
    ("生成器断言守卫", run_generator_guards),
    ("生成器 CLI 与 P-1 注入守卫", run_gen_cli_guards),
    ("生成器形態檔守衛", run_gen_shape_guards),
    ("--verify-layout 两制守卫", run_verify_layout_guards),
    ("引擎端到端守卫", run_engine_e2e_guard),
    ("规则碎片守卫", run_fragment_guards),
    ("能力注册表状态位守卫", run_registry_guards),
    ("编码与 manifest 路径守卫", run_encoding_and_path_guards),
    ("manifest 形态守卫", run_manifest_shape_guards),
    ("inherited 方向映射守卫", run_inherited_direction_guards),
    ("manifest 未知键守卫", run_unknown_key_guards),
    ("判定硬化守卫", run_hardening_guards),
    ("B03 判定核硬化守卫", run_b03_hardening_guards),
    ("B06a require_values 值判定守卫", run_b06_require_values_guards),
    ("B07a declare_and_count 声明绑死守卫", run_b07_declare_and_count_guards),
    ("exclude 豁免差集守卫", run_exclude_exempt_guards),
    ("vendor 发货工具豁免守卫", run_vendor_exempt_guards),
]


class _Tee:
    """Python 级 stdout 双写（真实 stdout + 缓冲）；子进程输出走真实 fd 不受影响，控制台顺序不变。"""

    def __init__(self, real, buf):
        self.real, self.buf = real, buf

    def write(self, s):
        self.real.write(s)
        self.buf.write(s)
        return len(s)

    def flush(self):
        self.real.flush()


_HEADER_RE = re.compile(r"^==\s*(.+?)\s*==$", re.M)


def _segment_selfcheck(buf_text: str, marks: list) -> int:
    """段头自证（预期 == 实际）+ 段体非空自证 + 段数棘轮；返回违规条数。"""
    bad = 0
    for label, start, end in marks:
        chunk = buf_text[start:end]
        headers = _HEADER_RE.findall(chunk)
        if not any(label in h for h in headers):
            print("  MISMATCH 段 %s 未打出声明段头（实际 %s）" % (label, headers))
            bad += 1
        if not [ln for ln in chunk.splitlines() if ln.strip() and not _HEADER_RE.match(ln)]:
            print("  MISMATCH 段 %s 除段头外零输出（段体被掏空=死守卫）" % label)
            bad += 1
    if len(_SEGMENTS) != _SEGMENT_COUNT:
        print("  MISMATCH 段数棘轮：_SEGMENTS=%d ≠ 基线 %d（增删段必须同步基线）"
              % (len(_SEGMENTS), _SEGMENT_COUNT))
        bad += 1
    return bad


if __name__ == "__main__":
    sys.exit(main())
