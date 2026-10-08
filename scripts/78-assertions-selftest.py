#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""78-assertions-selftest.py — profile 实质断言的门禁自测（棘轮下限 + 形状守卫 + 正反控制 + 反向对照）。

用法：
    python -X utf8 78-assertions-selftest.py                     # 全量守卫（verify_command 形态）
    python -X utf8 78-assertions-selftest.py --project <项目根>  # 追加真实产物回放（假阳控制，只读）

背景（2026-09-26 审查 N-6）：profiles/*.yaml 的 verify_assertions_template 曾只有
`forbid + min_bytes` 通配，展开后没有任何一条内容判据——done 门禁形同空转。本脚本把
"含实质断言的任务条目数"做成**棘轮下限**（FLOOR，只准升不准降；自检 `FLOOR == min(各档)`），
并逐任务做正反控制：
  · 正控制：按断言反推满足的产物 → 70-verify.py 必须 rc=0（证明断言可满足、阈值没定死）；
  · 反控制：空项目 → 必须 rc=1（rc=2 说明 manifest 形状本身有问题；全过则断言是摆设）；
  · 反向对照：内存中把任一实质断言删空 → 该档实质任务数**严格递减且该任务被点名**（B6/B7：
    与 FLOOR 阈值解耦，逐档 × 逐实质任务执行，不只打最小档）；
  · --project 回放：真实已完工项目的产物必须满足断言，否则阈值是假的（假阳控制）；
  · token_source 出处白名单：每条实质断言的字面词项必须标注出处（本档 AC /
    references/NN:行 / 英文分节名枚举），守卫取对应文本验证词项真在其中，
    无 source、幽灵标注、词项不在场一律判违规（task-assertion-token-provenance）。
  · 文档任务数一致性（task-profiles-catalog-exists-to-listed；B9 2026-10-07）：SKILL.md §profiles
    表 / README 目录树行内声明的「N 任务」（单位词放宽：N 条/项/个任务均识别）必须等于生成器
    实测值；**完备门禁**——每个在盘领域档至少一条任务数声明行（旧口径三档无声明行仍 rc=0）。
  · token_source 出处白名单对**合并后**模板校验（B8 2026-10-07）：子档继承来的标注不再被
    静默跳过；每个在盘领域档的合并模板标注数须 > 0。
  · 下限断言家族（B07b 2026-10-07，F-9R 闭环）：家族识别按**首分支对合成探针的命中集合**做正则
    语义比对（`\[[0-9]+\]` ≡ `\[\d+\]`，转义竖线 `^\|\s` 不再被 `split("|")` 切成死串）；
    `min>1` 撤销「一律违规」，改须有 `declare_and_count` 声明门或 `FLOOR_SNAPSHOT` 点名的 AC 出处。
  · 下限清单棘轮（B07b）：四类下限（`min_matches.min` / `count_distinct.min` /
    `word_count.lo` / `min_items`）的 min>1
    条目全部在 `FLOOR_SNAPSHOT` 被 (档:任务:路径:键:pattern:值) 钉死并点名 AC 出处；任何增/删/
    改值未登记即违规——「变更须点名 AC 出处」，取代按字面 pattern 的识别面。
  · AC 引用路径方向（B08a 2026-10-07）：判定谓语（与…一致/按…的/以…为准/核对/只使用/落在/取自）
    支配的路径串按句提取，**并列路径**（`A`、`B`）不漏；该路径须 ∈ 任务 files_to_read∪files_to_edit。
  · 死策略键（B08a）：合并后 profile 的每个 evidence_policy 键至少被一个任务 `inject`（不留
    「文案承诺 + 键不消费」）。
  · 链上产物读者（B08a，B-5）：`10-data/<name>.md` 分析产物至少被一个任务以**精确路径** read
    （目录式 read 不掩盖），否则正文数值/样本表一致性无机检对象。
只读承诺：只写 tempfile 沙箱，绝不写技能目录与目标项目。
"""
from __future__ import annotations

import argparse
import contextlib
import copy
import io
import json
import pathlib
import re
import shlex
import subprocess
import sys
import tempfile

import yaml

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HERE = pathlib.Path(__file__).resolve().parent
VERIFY = HERE / "70-verify.py"
SKILL_ROOT = HERE.parent
PROFILES = SKILL_ROOT / "profiles"
REFS_DOC = SKILL_ROOT / "references" / "30-literature-pipeline.md"

sys.dont_write_bytecode = True                     # .pyc 内嵌本机绝对路径，是发布面污染
import importlib.util                              # noqa: E402
_spec = importlib.util.spec_from_file_location("gen30", HERE / "30-gen-proposals.py")
gen30 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gen30)                    # noqa: E402
_spec70 = importlib.util.spec_from_file_location("verify70", VERIFY)
verify70 = importlib.util.module_from_spec(_spec70)
_spec70.loader.exec_module(verify70)               # noqa: E402 — 正文行计数单一真源（70 号 B10）

# AC1 口径：实质 = 这七类之一（forbid/min_bytes/min_bytes_each 的通配不算，只拦空文件与残留标记）
# B10（B-8 试点）：count_distinct 入实质集——STROBE 22 行已从 min_matches 迁到 count_distinct，
# 不入集则该断言在实质计数/反向对照/合成沙箱三面全部隐身（与 min_matches/word_count 同列两表）。
SUBSTANTIVE = ("contains", "contains_regex", "min_matches", "count_distinct", "word_count", "json_files", "run")
FILE_SUBSTANTIVE = ("contains", "contains_regex", "min_matches", "count_distinct", "word_count")
# 棘轮下限（B6，2026-10-07 审查）：**只作下限**，不再兼作反向对照阈值——反控改为「逐档以自身
# 条数为基线、删一条须严格递减且被点名」。自检 `FLOOR == min(各档实质任务数)`（随最小档校准，
# 涨档不误伤、掉档即红）。2026-10-06：social 补 reporting-compliance 后最小档仍 20。
FLOOR = 20
WRITING_TASKS = ("task-write-introduction", "task-write-results-discussion",
                 "task-write-conclusion-abstract")
PLACEHOLDER = re.compile(r"\{(admin|data|lit|ms|fig|review|latex|nb|tool_dir|verify_tool|verify_manifest)\}")

# 正则可满足性探针：正则必须至少命中一条，否则断言永不可满足（写死在探测里，随断言演进补样本）
# F6（2026-10-06）：补 [n] 表行 / Figure 全称 / 无空格图注 三类样本，对应五档放宽后的误杀修复断言
PROBES = ["1", "12", "123", "| 1", "| 12", "| [12]", "keep", "drop", "C-1", "G1", "100kx",
          "Fig. 1", "Fig 1", "Figure 1", "**Fig. 1.**", "**Fig.1.**", "[1]", "@article{", "CRITICAL", "DOI"]


def probe_for(pattern: str):
    for p in PROBES:
        try:
            if re.search(pattern, p, flags=re.M):
                return p
        except re.error:
            return None
    return None


def domain_profiles() -> list:
    """可独立生成的领域档：编号规范里 `00-` 是抽象基类（无 verify 模板、unit_source 仍是占位），
    其余（`10-` 起）都要独立生成投喂物——故不能按"被 extends 引用"排除父档
    （那是 75 的口径，会漏掉整档覆盖）。

    B05：**跳过重复键档**——否则 gen30.load_profile 会 die(rc=2) 中止整跑；该违规由
    run_shape_guards 对 all_domain_profiles() 单独点名（跳过 ≠ 放过）。
    """
    return [p for p in all_domain_profiles() if not dup_key_violations(p)]


def all_domain_profiles() -> list:
    """磁盘上全部领域档（不过滤重复键）：重复键检测面的真源，与 gen 面同源不同滤。"""
    return sorted(p for p in PROFILES.glob("*.yaml") if not p.name.startswith("00-"))


# ── B05：profile 本体重复键检出（判据真源防护）───────────────────────────────
# `yaml.safe_load` 对重复键 last-wins：末尾再写一行同键会静默回退前一条——materials 档误粘旧行
# `min_matches:{…,min:20}` → 生效值回退 20、合规 7 帧项目 rc=1（F-9R 假杀复发），而 75/76/78 全绿。
# 与 30 号生成器（ProfileDuplicateKey / _NoDuplicateKeyLoader）同口径，本档独立实现（脚本自包含）。
class _DupKeyYaml(yaml.YAMLError):
    """profile（或其 extends 祖先）YAML 映射含重复键。"""


class _NoDupKeyLoader(yaml.SafeLoader):
    def construct_mapping(self, node, deep=False):
        self.flatten_mapping(node)
        mapping = {}
        for key_node, value_node in node.value:
            key = self.construct_object(key_node, deep=deep)
            try:
                duplicate = key in mapping
            except TypeError:            # 不可哈希键（YAML 允许序列键）：照常赋值
                duplicate = False
            if duplicate:
                raise _DupKeyYaml("重复键 %r" % (key,))
            mapping[key] = self.construct_object(value_node, deep=deep)
        return mapping


_DUP_CACHE: dict = {}


def dup_key_violations(prof: pathlib.Path) -> list:
    """本档 **及其 extends 祖先链** 的重复键检测；返回违规串列表，空 = 干净。

    祖先链一并查：子档继承自含重复键的基类时，gen30.load_profile 同样会 die，只查本档会漏。
    """
    prof = pathlib.Path(prof)
    cached = _DUP_CACHE.get(str(prof))
    if cached is not None:
        return cached
    out: list = []
    cur, depth = prof, 0
    while cur is not None and depth <= 4:
        if cur.exists():
            try:
                yaml.load(cur.read_text(encoding="utf-8-sig"), Loader=_NoDupKeyLoader)
            except _DupKeyYaml as exc:
                out.append("%s：profile 含重复键 %s（yaml last-wins 会静默回退前一条定义，"
                           "判据真源须唯一）" % (cur.name, exc))
            except (yaml.YAMLError, OSError):
                pass                     # 不可读/非法 YAML 由生成器与其它守卫点名，此处只认重复键
            parent = None
            try:
                raw = yaml.safe_load(cur.read_text(encoding="utf-8-sig"))
                if isinstance(raw, dict) and isinstance(raw.get("extends"), str):
                    parent = cur.parent / raw["extends"]
            except (yaml.YAMLError, OSError):
                parent = None
            cur = parent if (parent is not None and parent.exists()) else None
        else:
            cur = None
        depth += 1
    _DUP_CACHE[str(prof)] = out
    return out


def _load_profile_safe(prof: pathlib.Path):
    """B05b：直接读具体档处（绕不过 `domain_profiles()` 重键过滤）先查重键。

    含重复键的档直接 `gen30.load_profile` 会 die(SystemExit) 中止整跑（78 有若干硬编码具体档的
    读点：refs_required_keys / run_unit_source_guards 基类 / run_project_replay materials / merged_template）。
    此处命中即返回 None，调用方跳过该档相关判定——**跳过 ≠ 放过**：重键违规仍由
    run_shape_guards 对 all_domain_profiles() 统一点名。
    """
    if dup_key_violations(prof):
        return None
    return gen30.load_profile(prof)


_GEN_CACHE: dict = {}


def gen(profile_path: pathlib.Path):
    """生成（内存中，不落盘）：返回 (manifest 片段, 生成任务表, 生成器 problems)。

    结果按档缓存（同一进程内幂等）：九个守卫面各自取数，无缓存时 5 档被重复生成
    七轮（实测 43.4s，逼近引擎 120s 硬上限）；缓存后每档只生成一次。调用方一律
    只读——需要变异的走 copy.deepcopy / 新建 dict，故共享同一份结果安全。
    """
    key = pathlib.Path(profile_path)
    hit = _GEN_CACHE.get(key)
    if hit is not None:
        return hit
    with contextlib.redirect_stdout(io.StringIO()):
        prof = gen30.load_profile(profile_path)
        built = gen30.build(prof)
        frag = gen30.verify_fragment(prof, built["tasks"])
        rules = gen30.rules_fragment(prof)
    out = (frag, {t["id"]: t for t in built["tasks"]}, built["problems"], prof, rules)
    _GEN_CACHE[key] = out
    return out


def substantive_ids(frag: dict) -> list:
    out = []
    for tid, e in frag.items():
        kinds = [k for k in SUBSTANTIVE if k in e]
        for f in e.get("files", []):
            kinds += [k for k in FILE_SUBSTANTIVE if k in f]
        if kinds:
            out.append(tid)
    return sorted(out)


def substantive_entries(frag: dict) -> int:
    """实质断言**条目**数（一个任务可有多条）；下限门禁比的是任务数，两者都要报，
    否则读者会把 20 个任务误读成 20 条断言（实测条目 27）。"""
    n = 0
    for tid in substantive_ids(frag):
        e = frag[tid]
        n += sum(1 for f in e.get("files", []) if any(k in f for k in FILE_SUBSTANTIVE))
        n += len(e.get("json_files", []) or [])
        n += 1 if e.get("run") else 0
    return n


def floor_ok(frag: dict, floor: int = FLOOR) -> bool:
    return len(substantive_ids(frag)) >= floor


def substantive_view(frag: dict) -> dict:
    """只看实质断言部分。两档的 tool_dir 分制（scripts/ vs 70-tools/）会让通配 files 条目
    天然不同，逐字比对会误报；实质判据必须一致才算"同一套断言在两档都成立"。
    token_source 是出处元数据，不参与跨档逐字比对（不影响断言执行力）；其正确性由
    守卫 8 逐档校验（词项真含于来源文本），跨档只比执行面。"""
    def _strip(item: dict) -> dict:
        return {k: v for k, v in item.items() if k != "token_source"}

    out = {}
    for tid in substantive_ids(frag):
        e = frag[tid]
        out[tid] = {"files": [_strip(f) for f in e.get("files", [])
                              if any(k in f for k in FILE_SUBSTANTIVE)],
                    "json_files": [_strip(j) for j in e.get("json_files", [])]}
    return out


def strip_substantive(frag: dict, tid: str) -> dict:
    """把某任务的实质断言删空，保留通配（forbid/min_bytes）——模拟"删掉一条实质断言"。"""
    f = copy.deepcopy(frag)
    e = f[tid]
    for k in list(e):
        if k in SUBSTANTIVE and k != "files":
            e.pop(k)
    e["files"] = [{k: v for k, v in item.items() if k not in FILE_SUBSTANTIVE}
                  for item in e.get("files", [])]
    return f


def _entries_of(frag: dict, tid: str) -> int:
    """该任务的实质**条目**数（frag 缺该任务时记 0）。"""
    e = frag.get(tid) or {}
    n = sum(1 for f in e.get("files", []) if any(k in f for k in FILE_SUBSTANTIVE))
    n += len(e.get("json_files") or [])
    n += 1 if e.get("run") else 0
    return n


def weakened_tasks(base_frag: dict, mutated: dict) -> list:
    """形状守卫面（B6）：相比基线**实质条目严格递减**的任务清单——反向对照据此逐任务点名。

    与 FLOOR 阈值解耦：哪怕各档整体涨过 FLOOR，只要删掉某任务的一条实质断言，本函数仍点名它。
    """
    names = set(base_frag) | set(mutated)
    return sorted(tid for tid in names
                  if _entries_of(mutated, tid) < _entries_of(base_frag, tid))


# ── 守卫 1：下限 + 逐任务非空 + 生成器干净 ────────────────────────────────────────
def run_floor_guards() -> int:
    print("== 实质断言下限（棘轮 %d）==" % FLOOR)
    bad = 0
    baselines: dict = {}
    for prof in domain_profiles():
        try:
            frag, tasks, problems, _, _ = gen(prof)
        except SystemExit as exc:                     # 生成器 die 本身就是失败信号
            print("  %-28s 生成器拒绝展开（rc=%s）" % (prof.name, exc))
            bad += 1
            continue
        n = len(substantive_ids(frag))
        baselines[prof.name] = n
        empty = [tid for tid, e in frag.items()
                 if not any(e.get(k) for k in ("files", "json_files", "globs", "absent_paths"))
                 and not e.get("run")]
        ok = n >= FLOOR and not empty and not problems
        print("  %-28s 任务=%-3d 实质任务=%-3d(≥%d) 实质条目=%-3d 空断言任务=%d 生成 problems=%d  %s"
              % (prof.name, len(frag), n, FLOOR, substantive_entries(frag), len(empty),
                 len(problems), "OK" if ok else "MISMATCH"))
        for p in problems[:4]:
            print("      problem: %s" % p)
        if not ok:
            bad += 1
    # B6 自检：FLOOR 必须等于最小档实质任务数（棘轮随最小档校准；掉档没跟着调 FLOOR 即红）。
    if baselines:
        mn = min(baselines.values())
        mname = min(baselines, key=lambda k: baselines[k])
        check_ok = mn == FLOOR
        print("  %-28s FLOOR=%d == min(各档)=%d（%s）  %s"
              % ("棘轮自检", FLOOR, mn, mname, "OK" if check_ok else "MISMATCH"))
        if not check_ok:
            bad += 1
    return 1 if bad else 0


# ── 守卫 2：形状（路径字面量 / 归属 / 正则可编译 / json 必带 min_items）────────────
def run_shape_guards() -> int:
    print("== 断言形状守卫 ==")
    bad = 0
    cases = []
    for prof in domain_profiles():
        try:
            frag, tasks, _, profd, _ = gen(prof)
        except SystemExit:
            cases.append((("%s: 生成" % prof.name), "生成器 die"))
            continue
        raw = yaml_template(prof)
        for a in raw:
            tid = a.get("task", "*")
            if tid == "*":
                continue
            if tid not in tasks:
                cases.append(("%s %s: 点名了本档不存在的任务" % (prof.name, tid), "unknown task"))
                continue
            allowed = set(tasks[tid]["files_to_edit"]) | {r["path"] for r in tasks[tid]["files_to_read"]}
            for key in ("files", "json_files"):
                for item in a.get(key, []):
                    p = item.get("path", "")
                    if PLACEHOLDER.search(p) or "{" in p:
                        cases.append(("%s %s: path 含占位符" % (tid, p), "本块不做占位替换，须写字面量"))
                    elif p not in allowed:
                        cases.append(("%s %s: 不在 files_to_edit∪files_to_read" % (tid, p), "幽灵断言"))
                    if key == "json_files" and (item.get("require_keys") or item.get("require_keys_all")) \
                            and "min_items" not in item:
                        cases.append(("%s %s: require_keys* 缺 min_items" % (tid, p), "N-3 fail-open"))
                    if key in ("files", "json_files"):
                        cases += _regex_cases(tid, item)
                        wc = item.get("word_count")
                        if wc and not (isinstance(wc, list) and len(wc) == 2
                                       and all(isinstance(x, int) and x > 0 for x in wc)
                                       and wc[0] < wc[1]):
                            cases.append(("%s %s: word_count 区间" % (tid, p), str(wc)))
                        for t in (item.get("contains") or []) + (item.get("forbid") or []):
                            if not isinstance(t, str) or not t.strip():
                                cases.append(("%s %s: contains/forbid 有空或非字符串项" % (tid, p), repr(t)))
            if "run" in a:
                # B10（B-9 试点）：run 不再一律禁——social 档首挂 40/45（两文件集合比对类判据
                # 70 五类断言表达不出来，只能走 run）。真实挂接三件套：字面量（本块不做占位替换，
                # { } 进 manifest 即坏命令）、点名真实在盘检查脚本、产物参数落在该任务读写面内。
                cases += _run_cases(prof.name, tid, allowed, a["run"])
            for g in a.get("globs", []):
                # B10（B-9 试点）：globs 首挂同样验形态 + 父目录挂接（通配父目录须被该任务产物覆盖，
                # 否则是挂到别人任务的"幽灵通配"）。
                cases += _globs_cases(prof.name, tid, allowed, g)
        # 通配覆盖必须在子档存活（deep_merge 对 list 是替换：子档重定义本键会清掉通配项）。
        # 同一 path 可能有多条 files 断言（通配一条 + 点名一条），按 path 归并后判"至少一条带 forbid"。
        # 通配覆盖必须在子档存活（deep_merge 对 list 是替换：子档重定义本键会清掉通配项）。
        # 同一 path 可能有多条 files 断言（通配一条 + 点名一条），按 path 归并后判"至少一条带 forbid"。
        for tid, entry in frag.items():
            by_path: dict = {}
            for f in entry.get("files", []):
                d = by_path.setdefault(f["path"], {"forbid": set(), "bytes": 0})
                d["forbid"] |= set(f.get("forbid", []))
                d["bytes"] = max(d["bytes"], f.get("min_bytes", 0) or 0)
            for p, d in by_path.items():
                if p.replace("\\", "/") == gen30.profile_manifest_path(profd):
                    continue    # F1: manifest 本体不做文本自查，由下方专项检查兜底，不适用 forbid 通配口径
                is_text = pathlib.Path(p).suffix.lower() in gen30.TEXT_SUFFIXES
                if is_text and "TODO" not in d["forbid"]:
                    # 但若该文件有其他实质断言（contains/contains_regex/min_matches/count_distinct/word_count），
                    # 则允许无 forbid 通配（如写作分节保留 AUTHOR CONFIRM 待裁定）
                    entry = frag[tid]
                    has_other = any(
                        any(k in f for k in ("contains", "contains_regex", "min_matches",
                                             "count_distinct", "word_count"))
                        for f in entry.get("files", []) if f.get("path") == p
                    )
                    if not has_other:
                        cases.append(("%s %s: 文本产物无 forbid 通配" % (tid, p),
                                      "子档重定义了 verify_assertions_template"))
                if not is_text and d["bytes"] < 5000:
                    cases.append(("%s %s: 二进制产物无体积下限" % (tid, p), "同上"))
            # F1 专项：manifest 本体只许 {path, min_bytes}——出现任何 forbid/实质文本断言
            # 即自指死锁回归（生成物 JSON 必然含 forbid 词本身）
            mpath = gen30.profile_manifest_path(profd)
            for f in entry.get("files", []):
                if f.get("path", "").replace("\\", "/") == mpath \
                        and set(f.keys()) - {"path", "min_bytes"}:
                    cases.append(("%s %s: manifest 被文本断言覆盖" % (tid, mpath),
                                  "自指死锁（F1）：forbid 词在 manifest JSON 内必然在场"))
    # B03（round3 F-2）：与 70 号阈值**同一真源对账**——70 的 _knob_problems 必须同样拒绝
    # min_matches.min=0 / count_distinct.min=0 / 空 contains / json min_items:0
    # （否则验收侧更松，两套校验分叉）。
    import importlib.util as _ilu
    _sp = _ilu.spec_from_file_location("v70_reconcile", VERIFY)
    try:
        _v70 = _ilu.module_from_spec(_sp)
        _sp.loader.exec_module(_v70)
        for label, seg, item in (
                ("min_matches.min=0", "files",
                 {"path": "x.md", "min_matches": {"pattern": "x", "min": 0}}),
                ("count_distinct.min=0", "files",
                 {"path": "x.md", "count_distinct": {"pattern": "x", "min": 0}}),
                ("contains 空列表", "files", {"path": "x.md", "contains": []}),
                ("min_items:0", "json_files",
                 {"path": "j.json", "min_items": 0, "require_keys": ["a"]})):
            if not _v70._knob_problems("t", seg, 0, item):
                cases.append(("B03 对账：70 号 _knob_problems 未拒 %s（与 78 阈值分叉）" % label,
                              "两处阈值须逐字一致"))
    except Exception as exc:                                     # noqa: BLE001
        cases.append(("B03 对账：无法加载 70 号 _knob_problems（%s）" % exc, "加载失败"))
    # B05（round3 A-4）：profile 本体重复键——判据真源须唯一，last-wins 静默回退即违规。
    # 覆盖 all_domain_profiles()（含被 domain_profiles() 跳过的重复键档，跳过 ≠ 放过）。
    for prof in all_domain_profiles():
        for v in dup_key_violations(prof):
            cases.append((v, "profile 重复键（B05）"))
    # B05 反向对照：合成重复键档必红、干净档不红（证明检定非装饰，且不误伤合法档）。
    with tempfile.TemporaryDirectory() as _td:
        _dup = pathlib.Path(_td) / "dup.yaml"
        _dup.write_text("id: x\ntasks:\n  - id: a\n  - id: b\ntasks: []\n", encoding="utf-8")
        if not dup_key_violations(_dup):
            cases.append(("B05 反向对照：合成重复键档未被检出", "重复键检定是摆设"))
        _clean = pathlib.Path(_td) / "clean.yaml"
        _clean.write_text("id: x\ntasks:\n  - id: a\npaths:\n  ms: m\n", encoding="utf-8")
        if dup_key_violations(_clean):
            cases.append(("B05 反向对照：干净档被误报", "；".join(dup_key_violations(_clean))))
        # B05 反向对照（生成器侧）：30 号 load_profile 对重复键 profile 必 die(rc=2) 且点名键；
        # 去重后正常返回（正向对照）——证明生成器侧修的不是装饰。
        _dup30 = pathlib.Path(_td) / "dup30.yaml"
        _dup30.write_text("id: d\nmodules: []\ntasks: []\nmin_matches:\n  pattern: x\n  min: 7\n"
                          "min_matches:\n  pattern: x\n  min: 20\n", encoding="utf-8")
        _buf = io.StringIO()
        _clean30 = pathlib.Path(_td) / "clean30.yaml"
        _clean30.write_text("id: d\nmodules: []\ntasks: []\n", encoding="utf-8")
        try:
            with contextlib.redirect_stdout(_buf):
                gen30.load_profile(_dup30)
            cases.append(("B05 反向对照：30 号 load_profile 未拒重复键 profile（生成器侧是摆设）", "rc≠2"))
        except SystemExit as exc:
            if exc.code != 2 or "min_matches" not in _buf.getvalue():
                cases.append(("B05 反向对照：30 号重复键未归 rc=2 点名键（rc=%s / %r）"
                              % (exc.code, _buf.getvalue().strip()[:90]), "须 rc=2 且点名重复键"))
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                gen30.load_profile(_clean30)
        except SystemExit as exc:
            cases.append(("B05 反向对照：干净 profile 被 30 号误拒（rc=%s）" % exc.code, "误杀"))
        # B05b：直接读档安全包装——重键档返回 None（不 SystemExit），干净档正常返回。
        if _load_profile_safe(_dup30) is not None:
            cases.append(("B05b 反向对照：_load_profile_safe 未拦截重键档", "应返回 None"))
        if _load_profile_safe(_clean30) is None:
            cases.append(("B05b 反向对照：_load_profile_safe 误拦干净档", "应正常返回"))
    for name, why in cases:
        print("  MISMATCH %-56s %s" % (name, why))
        bad += 1
    print("  形状问题 %d 条" % len(cases))
    # B10 反向对照（合成正反例，内存，不落盘）：新三件（run/globs/count_distinct 形态）
    # 的守卫必须是行为级——好形态放行、坏形态逐类点名，否则是字样装饰。
    _allow = {"30-manuscript/36-draft.md", "30-manuscript/37-references.md",
              "40-figures/data/fig-descriptives.pdf"}
    _shape_ctrl = [
        ("run：合规 45 命令（脚本在盘＋参数归属）→ 放行",
         not _run_cases("syn", "t", _allow,
                        "python 70-tools/45-consistency-check.py 30-manuscript/36-draft.md"
                        " --refs 30-manuscript/37-references.md")),
        ("反向对照：run 点名不存在的脚本 → 必报",
         bool(_run_cases("syn", "t", _allow, "python 70-tools/99-nope.py 30-manuscript/36-draft.md"))),
        ("反向对照：run 含 { } 占位（manifest 侧不展开）→ 必报",
         bool(_run_cases("syn", "t", _allow,
                         "python {tool_dir}/40-style-check.py 30-manuscript/36-draft.md"))),
        ("反向对照：run 产物参数不在任务读写面 → 必报且点名路径",
         bool(_run_cases("syn", "t", _allow,
                         "python 70-tools/40-style-check.py --domain social 99-elsewhere/x.md"))),
        ("反向对照：run 空串 → 必报",
         bool(_run_cases("syn", "t", _allow, "  "))),
        ("globs：合规条目（阈值＋父目录被任务覆盖）→ 放行",
         not _globs_cases("syn", "t", _allow,
                          {"pattern": "40-figures/data/*.pdf",
                           "min_count": 2, "min_bytes_each": 5000})),
        ("反向对照：globs 无 min_count/min_bytes_each（零命中空转）→ 必报",
         bool(_globs_cases("syn", "t", _allow, {"pattern": "40-figures/data/*.pdf"}))),
        ("反向对照：globs 父目录无任务产物覆盖（幽灵通配）→ 必报",
         bool(_globs_cases("syn", "t", _allow,
                           {"pattern": "99-elsewhere/*.pdf", "min_count": 1}))),
        ("count_distinct：合规（pattern 可编译＋min≥1＋scope 合法＋探针命中）→ 放行",
         not _regex_cases("t", {"path": "x.md",
                                "count_distinct": {"pattern": "^\\|\\s*\\d+",
                                                   "min": 22, "scope": "line"}})),
        ("反向对照：count_distinct min=0（空断言）→ 必报",
         bool(_regex_cases("t", {"path": "x.md",
                                 "count_distinct": {"pattern": "^\\|\\s*\\d+", "min": 0}}))),
        ("反向对照：count_distinct scope 拼错（静默降级）→ 必报",
         bool(_regex_cases("t", {"path": "x.md",
                                 "count_distinct": {"pattern": "^\\|\\s*\\d+",
                                                    "min": 22, "scope": "lines"}}))),
        ("反向对照：count_distinct 坏正则（无探针命中）→ 必报",
         bool(_regex_cases("t", {"path": "x.md",
                                 "count_distinct": {"pattern": "[", "min": 22}}))),
        ("json min_items：合规（min_items≥1）→ 放行",
         not _regex_cases("t", {"path": "j.json", "min_items": 1})),
        ("反向对照：json min_items=0（空断言）→ 必报",
         bool(_regex_cases("t", {"path": "j.json", "min_items": 0}))),
    ]
    for name, good in _shape_ctrl:
        print("  %-52s %s" % (name, "OK" if good else "MISMATCH"))
        if not good:
            bad += 1
    # B10（B-9 试点跟进项，NOTE 不改 rc）：模板 run 点名的检查脚本若未随 vendor 进项目
    # 70-tools/（真源 = gen30.VENDOR_TOOL_NAMES ⟷ install.py vendor 清单），项目侧执行即
    # "run failed"——接线在 78/70 两侧皆为活判据。R4-tail（2026-10-08）已补 40/45 进 vendor，
    # 故此 NOTE 对 40-style-check.py / 45-consistency-check.py 应零输出（名单消音，机制不动）。
    _vendored = set(gen30.VENDOR_TOOL_NAMES)
    _unvendored_runs = set()
    for prof in domain_profiles():
        for a in yaml_template(prof):
            run = a.get("run")
            if not isinstance(run, str):
                continue
            for t in run.replace("\\", "/").split():
                base = t.rsplit("/", 1)[-1]
                if base in _RUN_SCRIPTS and base not in _vendored:
                    _unvendored_runs.add("%s:%s" % (prof.name, base))
    if _unvendored_runs:
        print("  NOTE run 引用的脚本尚未随 vendor 进项目（项目侧执行须跟进 vendor，另立任务）：%s"
              % "、".join(sorted(_unvendored_runs)))
    return 1 if bad else 0


def yaml_template(prof: pathlib.Path) -> list:
    """读本档**自己**声明的 verify_assertions_template（未合并），用于形状审查。

    B05：走重复键检出加载器——profile 本体的重复键不得静默 last-wins 回退（该违规由
    dup_key_violations() 单独点名）；此处检出即返回空模板，不打断其余守卫。
    """
    try:
        raw = yaml.load(prof.read_text(encoding="utf-8-sig"), Loader=_NoDupKeyLoader)
    except _DupKeyYaml:
        return []
    return (raw or {}).get("verify_assertions_template", []) or []


def _regex_cases(tid: str, item: dict) -> list:
    out = []
    for key in ("contains_regex", "forbid_regex"):
        for pat in item.get(key, []):
            try:
                re.compile(pat)
            except re.error as exc:
                out.append(("%s %s: %s 无法编译" % (tid, item.get("path"), key), str(exc)))
    mm = item.get("min_matches")
    if mm is not None:
        if not isinstance(mm, dict) or "pattern" not in mm or not isinstance(mm.get("min"), int) \
                or mm["min"] < 1:
            out.append(("%s %s: min_matches" % (tid, item.get("path")), "需 {pattern, min≥1}"))
        elif probe_for(mm["pattern"]) is None:
            out.append(("%s %s: min_matches 正则无任何探针命中"
                        % (tid, item.get("path")), repr(mm["pattern"])))
    cd = item.get("count_distinct")
    if cd is not None:
        # B10（B-8）：与 70 号 _knob_problems 同口径（pattern+min 齐备、min≥1、scope∈line|all；
        # scope 拼错会静默按缺省 line 判定，属拼写错误等效降级，须在此拦）。
        if not isinstance(cd, dict) or "pattern" not in cd or not isinstance(cd.get("min"), int) \
                or cd["min"] < 1:
            out.append(("%s %s: count_distinct" % (tid, item.get("path")), "需 {pattern, min≥1}"))
        else:
            if cd.get("scope", "line") not in ("line", "all"):
                out.append(("%s %s: count_distinct scope" % (tid, item.get("path")),
                            repr(cd.get("scope"))))
            if probe_for(cd["pattern"]) is None:
                out.append(("%s %s: count_distinct 正则无任何探针命中"
                            % (tid, item.get("path")), repr(cd["pattern"])))
    for pat in item.get("contains_regex", []):
        if probe_for(pat) is None:
            out.append(("%s %s: contains_regex 无任何探针命中" % (tid, item.get("path")), repr(pat)))
    if "min_items" in item:
        # F-2（round3 收口）：json min_items 写了必须 ≥1（min:0 是空断言，形态错——
        # 与 70 号 _knob_problems 同一真源；B03 对账块逐字锁定两处一致）。
        mi = item["min_items"]
        if not isinstance(mi, int) or isinstance(mi, bool) or mi < 1:
            out.append(("%s %s: min_items" % (tid, item.get("path")), "需 ≥1（min:0 是空断言）"))
    return out


# B10（B-9 试点）：模板 run / globs 的真实挂接校验（shape 段行为级，非字样级）。
_RUN_SCRIPTS = frozenset({
    "35-refs-gate.py",
    "40-style-check.py",
    "45-consistency-check.py",
    "70-verify.py",
    "72-assemble-draft.py",
    "72-compose-raster-figures.py",
    "72-latex-build-check.py",
})
_RUN_INTERP = frozenset({"python", "python3"})
_RUN_PATH_SUFFIXES = (".md", ".json", ".bib", ".tex", ".pdf", ".png",
                      ".ps1", ".yaml", ".yml", ".txt", ".csv")


def _run_cases(prof_name: str, tid: str, allowed: set, run) -> list:
    """模板 run 命令的真实挂接校验：字面量 + 点名在盘脚本 + 产物参数归属任务读写面。"""
    where = "%s %s: run" % (prof_name, tid)
    if not isinstance(run, str) or not run.strip():
        return [(where, "run 须是非空字符串命令")]
    if "{" in run or "}" in run:
        return [(where, "run 含 { } 占位（manifest 侧不做占位替换，须写字面量）")]
    try:
        toks = shlex.split(run)
    except ValueError as exc:
        return [(where, "run 无法按 shell 分词：%s" % exc)]
    script = next((t for t in toks if t.endswith(".py")), None)
    if script is None:
        return [(where, "run 未点名检查脚本（须出现 <脚本>.py，如 70-tools/45-consistency-check.py）")]
    base = script.replace("\\", "/").rsplit("/", 1)[-1]
    if base not in _RUN_SCRIPTS:
        return [(where, "run 点名的脚本 %r 不在 shipped 检查脚本表" % base)]
    if not (SKILL_ROOT / "scripts" / base).is_file():
        return [(where, "run 点名的脚本在盘不存在：scripts/%s" % base)]
    out = []
    for t in toks:
        if t in _RUN_INTERP or t.startswith("-") or t == script:
            continue
        if "/" not in t or not t.endswith(_RUN_PATH_SUFFIXES):
            continue
        if t not in allowed:
            out.append(("%s: 产物参数 %s 不在 files_to_edit∪files_to_read" % (where, t),
                        "幽灵挂接"))
    return out


def _globs_cases(prof_name: str, tid: str, allowed: set, g) -> list:
    """模板 globs 条目的形态 + 父目录挂接校验（与 70 号 _knob_problems 同口径，外加挂接面）。"""
    where = "%s %s: globs" % (prof_name, tid)
    if not isinstance(g, dict):
        return [(where, "globs 条目须是对象")]
    out = []
    pat = g.get("pattern", "")
    if not isinstance(pat, str) or not pat.strip():
        return [(where, "globs pattern 须是非空字符串")]
    if "{" in pat or "}" in pat:
        out.append((where, "globs pattern 含 { } 占位（须写字面量）"))
    elif pat.startswith("/") or re.match(r"^[A-Za-z]:", pat) or ".." in pat.replace("\\", "/").split("/"):
        out.append((where, "globs pattern 越界（绝对路径/..）：%r" % pat))
    if "min_count" not in g and "min_bytes_each" not in g:
        # 70 号 B03 同口径：零命中无门槛 = 空转。
        out.append((where, "globs 须配 min_count 或 min_bytes_each 之一（否则零命中静默通过=空转）"))
    for k in ("min_count", "min_bytes_each"):
        v = g.get(k)
        if v is not None and (not isinstance(v, int) or isinstance(v, bool) or v < 1):
            out.append((where, "globs %s 须是 ≥1 整数，实为 %r" % (k, v)))
    if "/" not in pat:
        out.append((where, "globs pattern 须含目录前缀（如 40-figures/data/*.pdf）"))
    else:
        parent = pat.rsplit("/", 1)[0]
        if not any(p == parent or p.startswith(parent + "/") for p in allowed):
            out.append(("%s: 父目录 %s 未被该任务产物覆盖" % (where, parent), "幽灵通配"))
    return out


# ── 守卫 2b：下限断言家族（F-9R 真闭环：语义基面 + min>1 门/出处）─────────────────
# 病灶（round3 A-7/A-12/E-4，亲跑）：
#   ① `pat.split("|",1)[0]` 在**转义竖线**处切断——`^\|\s` 类首分支被切出 `'^\'`，家族判定成死串；
#      且按字面串等值判基面，`\[[0-9]+\]` 等价改写即脱钩（E-4：五档同改 → 78 rc=0）。
#   ② `min>1` 一律判违规——使「达条数 或 显式声明」二选一永久无法表达，反把阈值焊死在 1。
# 修法：
#   ① 首分支切分改 `re.split(r"(?<!\\)\|", pat)[0]`；家族判定改正则**语义比对**——把首分支与家族
#      范式各自对合成探针求命中集合，集合相等即同族（`\[[0-9]+\]` ≡ `\[\d+\]`，转义竖线不再截断）。
#   ② `min>1` 允许，但须有 `declare_and_count` 声明门（B07a）或经 `FLOOR_SNAPSHOT` 点名的 AC 出处；
#      `min≤1` 一律放行。全量（含 word_count.lo / min_items）由守卫 2c 快照棘轮兜底。
_FLOOR_FAMILIES = (
    r"\[\d+\]",          # 参考文献编号 [n]
    r"@[a-z]+\{",        # bib 条目
    r"Fig\.?\s*\d+",     # 图号
    r"^\|\s*\[?\d+]?",   # 编号表格行（[n] / n）
    r"^\|\s*\d+",        # 编号表格行（数字紧跟竖线）
    r"^\|\s",            # 任意表格行
)
# 探针集：使六族两两可分。`| x` 把 `^\|\s` 与 `^\|\s*\[?\d+]?`/`^\|\s*\d+` 分开；
# `a | b`（竖线不在行首）把裸 `\|` 挡在族外。族序：更具体的编号行在前。
_FLOOR_PROBES = ("[1]", "[12]", "@article{", "Fig. 1", "Fig 1",
                 "| 1", "| x", "| [12]", "a | b")


def _floor_hit_set(pat) -> frozenset:
    """pattern 在合成探针上的命中集合；不可编译或无命中返回 None（falsy）。"""
    if not isinstance(pat, str):
        return None
    try:
        rx = re.compile(pat, flags=re.M)
    except re.error:
        return None
    return frozenset(p for p in _FLOOR_PROBES if rx.search(p)) or None


_FLOOR_FAMILY_HITS = tuple(_floor_hit_set(p) for p in _FLOOR_FAMILIES)


def floor_family(pat: str):
    r"""`pat` 是否属「领域无关计数家族」：首分支对探针的命中集合与家族范式比对（正则语义等价）。

    首分支用 `re.split(r"(?<!\\)\|", pat)[0]` 切分——转义竖线 `\|` 不再被误当分支分隔符
    （旧 `split("|")` 会把 `^\|\s` 切成 `'^\'`）。返回家族索引或 None（非家族/不可编译）。
    """
    first = re.split(r"(?<!\\)\|", pat)[0] if isinstance(pat, str) else None
    hits = _floor_hit_set(first)
    if hits is None:
        return None
    for i, fam in enumerate(_FLOOR_FAMILY_HITS):
        if hits == fam:
            return i
    return None


def _declare_gate_ok(item: dict) -> bool:
    """`declare_and_count` 声明门形态是否合规（与 70 号 `_knob_problems` 同口径）。

    合规 = 值为 dict、仅含 pattern/declare_regex、两者皆可编译的 str，且 declare_regex 含
    **≥1 捕获组**。仅凭键存在即放行是旁路——空 `declare_and_count: {}`、缺 `declare_regex`、
    无捕获组、pattern 坏正则都能骗过守卫（运行时由 70 号形态档兜底，但本守卫层存在旁路，
    与本轮「元守卫须行为级」原则不符）。
    """
    dc = item.get("declare_and_count")
    if not isinstance(dc, dict) or set(dc) - {"pattern", "declare_regex"}:
        return False
    if "pattern" not in dc or "declare_regex" not in dc:
        return False
    pat, decl = dc["pattern"], dc["declare_regex"]
    if not isinstance(pat, str) or not isinstance(decl, str):
        return False
    try:
        re.compile(pat)
    except re.error:
        return False
    try:
        cre = re.compile(decl)
    except re.error:
        return False
    return cre.groups >= 1


def _floor_escape_violations(where: str, raw: list, snapshot: dict = None) -> list:
    """家族下限断言 `min>1` 的门/出处判定（`min≤1` 一律放行）。

    违规判据：家族下限 `min_matches` 且 `min>1`，既无**形态合规**的 `declare_and_count`
    声明门，又未在 `snapshot`（FLOOR_SNAPSHOT，`{档: {(任务,路径,键,pattern): (值, 出处)}}`）
    点名 AC 出处。声明门须过 `_declare_gate_ok`（键存在不够，形态须与 70 号同口径）。
    """
    out = []
    snap = (snapshot or {}).get(where, {})
    for a in raw or []:
        tid = a.get("task", "*")
        for item in a.get("files", []) or []:
            mm = item.get("min_matches")
            if not isinstance(mm, dict):
                continue
            pat = mm.get("pattern", "")
            if floor_family(pat) is None:
                continue
            mn = mm.get("min")
            if not isinstance(mn, int) or mn <= 1:
                continue
            if "declare_and_count" in item:
                if _declare_gate_ok(item):
                    continue
                out.append("%s %s %s: 下限断言 min=%s>1 的 declare_and_count 声明门形态非法"
                           "（须 dict 且含可编译 pattern / 含 ≥1 捕获组的可编译 declare_regex）"
                           "（pattern=%r）" % (where, tid, item.get("path"), mn, pat))
                continue
            if (tid, item.get("path"), "min_matches.min", pat) in snap:
                continue
            out.append("%s %s %s: 下限断言 min=%s>1 既无合法 declare_and_count 声明门，"
                       "也未在 FLOOR_SNAPSHOT 点名 AC 出处（pattern=%r）"
                       % (where, tid, item.get("path"), mn, pat))
    return out


def _assertion_list(frag: dict) -> list:
    """生成器 frag（合并后、含继承档）→ `_floor_escape_violations` 消费的模板列表。"""
    return [{"task": tid, "files": e.get("files", []) or [],
             "json_files": e.get("json_files", []) or []}
            for tid, e in frag.items()]


def floor_escape_violations(snapshot: dict = None) -> list:
    out = []
    for prof in domain_profiles():
        try:
            frag, _, _, _, _ = gen(prof)
        except SystemExit:
            continue
        out += _floor_escape_violations(prof.name, _assertion_list(frag), snapshot)
    return out


def _scale_floor_seen() -> int:
    """家族下限命中数（空转门禁用）：只看家族识别面，值/门由其它控制行判。"""
    seen = 0
    for prof in domain_profiles():
        try:
            frag, _, _, _, _ = gen(prof)
        except SystemExit:
            continue
        for a in _assertion_list(frag):
            for item in a.get("files", []) or []:
                mm = item.get("min_matches")
                if isinstance(mm, dict) and floor_family(mm.get("pattern", "")) is not None:
                    seen += 1
    return seen


def run_floor_escape_guards() -> int:
    print("== 下限断言逃生门守卫（F-9R）==")
    bad = 0
    live = floor_escape_violations(FLOOR_SNAPSHOT)
    seen = _scale_floor_seen()
    print("  家族下限：命中 %d 条，门/出处问题 %d 条  %s"
          % (seen, len(live), "OK" if not live and seen else "MISMATCH"))
    for v in live:
        print("      MISMATCH %s" % v)
    if live or not seen:
        bad += 1
        if not seen:
            print("      MISMATCH 家族下限零命中：守卫空转（pattern 可能被变形/删净）")
    # ① 语义基面：等价改写 / 转义竖线 / 六族两两可分（AC1）。
    sem = {
        "等价改写 \\[[0-9]+\\] 仍识别为参考文献族": floor_family("\\[[0-9]+\\]") is not None,
        "转义竖线 ^\\|\\s 不再被切成死串（family 命中）": floor_family("^\\|\\s") is not None,
        "编号表格行 ^\\|\\s*\\d+ 与 ^\\|\\s 判为不同族":
            floor_family("^\\|\\s*\\d+") != floor_family("^\\|\\s"),
        "裸 \\| 不属任何族（竖线不在行首）": floor_family("\\|") is None,
        "\\d 不属任何族": floor_family("\\d") is None,
    }
    # ② 门/出处：脚本声明门**形态合规**才放行；形态非法/无门无出处必报；min≤1 放行（AC2）。
    _gate = {"path": "x.md", "min_matches": {"pattern": "\\[\\d+\\]", "min": 20},
             "declare_and_count": {"pattern": "\\[\\d+\\]", "declare_regex": "共\\s*(\\d+)\\s*条"}}
    _bare = {"path": "x.md", "min_matches": {"pattern": "\\[\\d+\\]", "min": 20}}
    _min1 = {"path": "x.md", "min_matches": {"pattern": "\\[\\d+\\]", "min": 1}}
    # AC2 反向对照：declare_and_count 仅凭键存在即放行是旁路，形态任一不合须判违规。
    _gate_empty = {"path": "x.md", "min_matches": {"pattern": "\\[\\d+\\]", "min": 20},
                   "declare_and_count": {}}
    _gate_no_regex = {"path": "x.md", "min_matches": {"pattern": "\\[\\d+\\]", "min": 20},
                      "declare_and_count": {"pattern": "\\[\\d+\\]"}}
    _gate_no_group = {"path": "x.md", "min_matches": {"pattern": "\\[\\d+\\]", "min": 20},
                      "declare_and_count": {"pattern": "\\[\\d+\\]",
                                            "declare_regex": "共\\s*\\d+\\s*条"}}
    _gate_bad_pat = {"path": "x.md", "min_matches": {"pattern": "\\[\\d+\\]", "min": 20},
                     "declare_and_count": {"pattern": "[",
                                           "declare_regex": "共\\s*(\\d+)\\s*条"}}
    snap_ok = {"gateprof": {("t", "x.md", "min_matches.min", "\\[\\d+\\]"):
                            (20, {"ac": "t", "term": "条"})}}
    ctrl_gate = [
        ("声明门：形态合规 declare_and_count → 不报", not _floor_escape_violations(
            "ok", [{"task": "t", "files": [_gate]}])),
        ("反向对照：declare_and_count 空 dict → 必报（仅凭键存在是旁路）",
         len(_floor_escape_violations("bad", [{"task": "t", "files": [_gate_empty]}])) == 1),
        ("反向对照：declare_and_count 缺 declare_regex → 必报",
         len(_floor_escape_violations("bad", [{"task": "t", "files": [_gate_no_regex]}])) == 1),
        ("反向对照：declare_regex 无捕获组 → 必报",
         len(_floor_escape_violations("bad", [{"task": "t", "files": [_gate_no_group]}])) == 1),
        ("反向对照：declare_and_count.pattern 坏正则 → 必报",
         len(_floor_escape_violations("bad", [{"task": "t", "files": [_gate_bad_pat]}])) == 1),
        ("AC 出处：FLOOR_SNAPSHOT 点名 → 不报", not _floor_escape_violations(
            "gateprof", [{"task": "t", "files": [_bare]}], snap_ok)),
        ("反向对照：min>1 无门无出处必报且点名任务/路径", len(_floor_escape_violations(
            "bad", [{"task": "t", "files": [_bare]}])) == 1),
        ("反向对照：家族下限 22→9 无门 → 必报", len(_floor_escape_violations(
            "bad", [{"task": "t", "files": [
                {"path": "x.md", "min_matches": {"pattern": "^\\|\\s*\\d+", "min": 9}}]}])) == 1),
        ("反向对照：家族下限 10→1000 无门 → 必报", len(_floor_escape_violations(
            "bad", [{"task": "t", "files": [
                {"path": "x.md", "min_matches": {"pattern": "^\\|\\s", "min": 1000}}]}])) == 1),
        ("反向对照：等价改写 + 无门 → 仍必报（语义比对不脱钩）", len(_floor_escape_violations(
            "bad", [{"task": "t", "files": [
                {"path": "x.md", "min_matches": {"pattern": "\\[[0-9]+\\]", "min": 60}}]}])) == 1),
        ("min≤1 一律放行（撤销「min>1 即违规」）", not _floor_escape_violations(
            "ok2", [{"task": "t", "files": [_min1]}])),
    ]
    for name, good in list(sem.items()) + ctrl_gate:
        print("  %-52s %s" % (name, "OK" if good else "MISMATCH"))
        if not good:
            bad += 1
    return 1 if bad else 0


# ── 守卫 2c：下限清单棘轮（FLOOR_SNAPSHOT 快照 + AC 出处）────────────────────────
# 病灶（A-7 ③）：旧守卫只认 min_matches 家族，word_count.lo / json min_items 的 min>1 全在视野外
# （实测 social:11-analysis 10→1000、reporting-checklist 22→9 → 78 rc=0）。
# 真源：每条 min>1 下限（min_matches.min / count_distinct.min / word_count.lo / min_items）在快照中被
# (档:任务:路径:键:pattern:值) 钉死，并点名 AC 出处 `{ac: 任务id, term: 词项}`（term 须真在该任务
# (档:任务:路径:键:pattern:值) 钉死，并点名 AC 出处 `{ac: 任务id, term: 词项}`（term 须真在该任务
# 的 AC 文本中，与 token_source 的 `ac`/`ac:<任务>` 口径同源）。任何增/删/改值未登记即违规——
# 「变更须点名 AC 出处」，取代按字面 pattern 的识别面。来源见 reports/00-FIX-BACKLOG-2026-10-07-round3.md B07。
# B10（A-14）语义注释：`word_count.lo` 自本轮起是**正文行数**下限（跳过空行/纯表格行/
# 图注行/代码围栏行后计数，中英文同口径按行计；口径真源见 70 号 count_body_lines）。
# R5（round4 R4-4）：阈值按每句一行（≈15 词/行）重算，AC 量纲词改行（行数预算），
# 快照数值与出处词项同步新口径（旧词口径数值见史）。
FLOOR_SNAPSHOT: dict = {
    "10-clinical.yaml": {
        ('task-assemble-draft', '30-manuscript/36-draft.md', 'word_count.lo', ''): (187, {'ac': 'task-outline-contract', 'term': '行数预算'}),
        ('task-ethics-registration', '00-admin/08-ethics-registration.md', 'min_matches.min', '^\\|\\s*\\d+'): (3, {'ac': 'task-ethics-registration', 'term': '三要素'}),
        ('task-outline-contract', '00-admin/01-meta.json', 'min_items', ''): (5, {'ac': 'task-outline-contract', 'term': '图表数'}),
        ('task-reporting-compliance', '50-review/53-reporting-checklist.md', 'min_matches.min', '^\\|\\s*\\d+'): (22, {'ac': 'task-reporting-compliance', 'term': 'STROBE 22 条'}),
        ('task-write-conclusion-abstract', '30-manuscript/30-abstract.md', 'word_count.lo', ''): (8, {'ac': 'task-outline-contract', 'term': '行数预算'}),
        ('task-write-conclusion-abstract', '30-manuscript/sections/34-conclusion.md', 'word_count.lo', ''): (13, {'ac': 'task-outline-contract', 'term': '行数预算'}),
        ('task-write-introduction', '30-manuscript/sections/31-introduction.md', 'word_count.lo', ''): (33, {'ac': 'task-outline-contract', 'term': '行数预算'}),
        ('task-write-methods', '30-manuscript/sections/32-methods.md', 'word_count.lo', ''): (47, {'ac': 'task-outline-contract', 'term': '行数预算'}),
        ('task-write-results-discussion', '30-manuscript/sections/33-results-discussion.md', 'word_count.lo', ''): (133, {'ac': 'task-outline-contract', 'term': '行数预算'}),
    },
    "10-materials-chemistry.yaml": {
        ('task-assemble-draft', '30-manuscript/36-draft.md', 'word_count.lo', ''): (187, {'ac': 'task-skeleton-contract', 'term': '行数预算'}),
        ('task-skeleton-contract', '00-admin/01-meta.json', 'min_items', ''): (5, {'ac': 'task-skeleton-contract', 'term': '图表数'}),
        ('task-write-conclusion-abstract', '30-manuscript/30-abstract.md', 'word_count.lo', ''): (8, {'ac': 'task-skeleton-contract', 'term': '行数预算'}),
        ('task-write-conclusion-abstract', '30-manuscript/sections/34-conclusion.md', 'word_count.lo', ''): (13, {'ac': 'task-skeleton-contract', 'term': '行数预算'}),
        ('task-write-experimental', '30-manuscript/sections/32-experimental.md', 'word_count.lo', ''): (27, {'ac': 'task-skeleton-contract', 'term': '行数预算'}),
        ('task-write-introduction', '30-manuscript/sections/31-introduction.md', 'word_count.lo', ''): (33, {'ac': 'task-skeleton-contract', 'term': '行数预算'}),
        ('task-write-results-discussion', '30-manuscript/sections/33-results-discussion.md', 'word_count.lo', ''): (133, {'ac': 'task-skeleton-contract', 'term': '行数预算'}),
    },
    "20-social-science.yaml": {
        ('task-assemble-draft', '30-manuscript/36-draft.md', 'word_count.lo', ''): (187, {'ac': 'task-outline-contract', 'term': '行数预算'}),
        ('task-outline-contract', '00-admin/01-meta.json', 'min_items', ''): (5, {'ac': 'task-outline-contract', 'term': '图表数'}),
        # B10（B-8 试点）：STROBE 22 行从 min_matches 迁到 count_distinct（scope=line 抗复制凑数）——
        # 旧 min_matches.min 键删除、新 count_distinct.min 键登记，出处（STROBE 22 条）不变。
        ('task-reporting-compliance', '50-review/53-reporting-checklist.md', 'count_distinct.min', '^\\|\\s*\\d+'): (22, {'ac': 'task-reporting-compliance', 'term': 'STROBE 22 条'}),
        ('task-write-conclusion-abstract', '30-manuscript/30-abstract.md', 'word_count.lo', ''): (8, {'ac': 'task-outline-contract', 'term': '行数预算'}),
        ('task-write-conclusion-abstract', '30-manuscript/sections/34-conclusion.md', 'word_count.lo', ''): (13, {'ac': 'task-outline-contract', 'term': '行数预算'}),
        ('task-write-introduction', '30-manuscript/sections/31-introduction.md', 'word_count.lo', ''): (33, {'ac': 'task-outline-contract', 'term': '行数预算'}),
        ('task-write-methods', '30-manuscript/sections/32-methods.md', 'word_count.lo', ''): (47, {'ac': 'task-outline-contract', 'term': '行数预算'}),
        ('task-write-results-discussion', '30-manuscript/sections/33-results-discussion.md', 'word_count.lo', ''): (133, {'ac': 'task-outline-contract', 'term': '行数预算'}),
    },
    "30-cs-ml.yaml": {
        ('task-analyze-baselines', '10-data/11-analysis.md', 'min_matches.min', '\\d'): (30, {'ac': 'task-analyze-baselines', 'term': '不少于 5 条'}),
        ('task-analyze-baselines', '10-data/11-analysis.md', 'min_matches.min', '\\|'): (50, {'ac': 'task-analyze-baselines', 'term': '不少于 5 条'}),
        ('task-analyze-baselines', '10-data/11-analysis.md', 'min_matches.min', '^\\|'): (7, {'ac': 'task-analyze-baselines', 'term': '不少于 5 条'}),
        ('task-analyze-baselines', '10-data/13-table-main-results.md', 'min_matches.min', '\\d'): (18, {'ac': 'task-analyze-baselines', 'term': '3 个指标行'}),
        ('task-analyze-baselines', '10-data/13-table-main-results.md', 'min_matches.min', '\\|'): (18, {'ac': 'task-analyze-baselines', 'term': '3 个指标行'}),
        ('task-analyze-baselines', '40-figures/40-figure-specs.md', 'min_matches.min', 'Fig\\. ?\\d+'): (4, {'ac': 'task-analyze-baselines', 'term': '不少于四条'}),
        ('task-assemble-draft', '30-manuscript/36-draft.md', 'word_count.lo', ''): (187, {'ac': 'task-skeleton-contract', 'term': '行数预算'}),
        ('task-declare-reproducibility', '00-admin/09-reproducibility.md', 'min_matches.min', '\\|'): (30, {'ac': 'task-declare-reproducibility', 'term': '六要素'}),
        ('task-declare-reproducibility', '00-admin/09-reproducibility.md', 'min_matches.min', '^\\|\\s*\\d+'): (6, {'ac': 'task-declare-reproducibility', 'term': '六要素'}),
        ('task-skeleton-contract', '00-admin/01-meta.json', 'min_items', ''): (5, {'ac': 'task-skeleton-contract', 'term': '图表数'}),
        ('task-tabulate-ablations', '10-data/14-table-ablations.md', 'min_matches.min', '\\d'): (15, {'ac': 'task-tabulate-ablations', 'term': '不少于 3 个消融行'}),
        ('task-tabulate-ablations', '10-data/14-table-ablations.md', 'min_matches.min', '\\|'): (25, {'ac': 'task-tabulate-ablations', 'term': '不少于 3 个消融行'}),
        ('task-tabulate-ablations', '10-data/14-table-ablations.md', 'min_matches.min', '^\\|'): (5, {'ac': 'task-tabulate-ablations', 'term': '不少于 3 个消融行'}),
        ('task-tabulate-ablations', '40-figures/40-figure-specs.md', 'min_matches.min', 'Fig\\. ?\\d+'): (4, {'ac': 'task-tabulate-ablations', 'term': '不少于四条图规格'}),
        ('task-write-conclusion-abstract', '30-manuscript/30-abstract.md', 'word_count.lo', ''): (8, {'ac': 'task-skeleton-contract', 'term': '行数预算'}),
        ('task-write-conclusion-abstract', '30-manuscript/sections/34-conclusion.md', 'word_count.lo', ''): (13, {'ac': 'task-skeleton-contract', 'term': '行数预算'}),
        ('task-write-implementation', '30-manuscript/sections/32-implementation.md', 'min_matches.min', '\\d'): (10, {'ac': 'task-write-implementation', 'term': '不少于 5 条'}),
        ('task-write-introduction', '30-manuscript/sections/31-introduction.md', 'word_count.lo', ''): (33, {'ac': 'task-skeleton-contract', 'term': '行数预算'}),
        ('task-write-results-discussion', '30-manuscript/sections/33-results-discussion.md', 'word_count.lo', ''): (133, {'ac': 'task-skeleton-contract', 'term': '行数预算'}),
    },
}


def actual_floors(frag: dict) -> dict:
    """合并后 frag → {(任务,路径,键,pattern): 值}（min>1 的四类下限）。

    B10（B-8）：第四类 count_distinct.min——复制凑数类 AC 从 min_matches 迁到 count_distinct 后，
    快照若只认旧三类，新键的增/删/改值将全部漏网（与当年 word_count.lo/min_items 入快照同理）。
    """
    out = {}
    for tid, e in frag.items():
        for item in e.get("files", []) or []:
            mm = item.get("min_matches")
            if isinstance(mm, dict) and isinstance(mm.get("min"), int) and mm["min"] > 1:
                out[(tid, item.get("path"), "min_matches.min", mm.get("pattern"))] = mm["min"]
            cd = item.get("count_distinct")
            if isinstance(cd, dict) and isinstance(cd.get("min"), int) and cd["min"] > 1:
                out[(tid, item.get("path"), "count_distinct.min", cd.get("pattern"))] = cd["min"]
            wc = item.get("word_count")
            if wc and isinstance(wc, list) and wc and wc[0] > 1:
                out[(tid, item.get("path"), "word_count.lo", "")] = wc[0]
        for item in e.get("json_files", []) or []:
            mi = item.get("min_items")
            if isinstance(mi, int) and mi > 1:
                out[(tid, item.get("path"), "min_items", "")] = mi
    return out


def floor_snapshot_violations(prof_name: str, actual: dict, snapshot: dict,
                              ac_by_task: dict) -> list:
    """快照对账（纯函数，供真实档与反向对照共用）：返回违规串（空 = 过）。"""
    out = []
    snap = snapshot.get(prof_name, {})
    for key, val in sorted(actual.items()):
        if key not in snap:
            out.append("%s %s %s: 下限 %s 变更未点名 AC 出处（新增/未登记）"
                       % (prof_name, key[0], key[1], key[2]))
        elif snap[key][0] != val:
            out.append("%s %s %s: 下限 %s 值 %s→%s 未同步快照/未点名 AC 出处"
                       % (prof_name, key[0], key[1], key[2], snap[key][0], val))
    for key in sorted(snap):
        if key not in actual:
            out.append("%s %s %s: 快照下限 %s 已消失（须同步快照）"
                       % (prof_name, key[0], key[1], key[2]))
    for key, (_val, prov) in sorted(snap.items()):
        if not isinstance(prov, dict) or set(prov) != {"ac", "term"}:
            out.append("%s %s: 快照出处形态非法 %r（须 {ac, term}）" % (prof_name, key[0], prov))
            continue
        text = ac_by_task.get(prov["ac"])
        if text is None:
            out.append("%s %s: 快照出处任务不存在 %r" % (prof_name, key[0], prov["ac"]))
        elif prov["term"] not in text:
            out.append("%s %s: 快照出处词项 %r 不在任务 %s 的 AC"
                       % (prof_name, key[0], prov["term"], prov["ac"]))
    return out


def run_floor_snapshot_guards() -> int:
    print("== 下限清单棘轮（快照 + AC 出处）==")
    bad = 0
    total = 0
    floor_by_prof: dict = {}
    for prof in domain_profiles():
        try:
            frag, tasks, _, _, _ = gen(prof)
        except SystemExit:
            continue
        actual = actual_floors(frag)
        ac_by_task = {t["id"]: "".join(t.get("acceptance_criteria") or []) for t in tasks.values()}
        floor_by_prof[prof.name] = (actual, ac_by_task)
        v = floor_snapshot_violations(prof.name, actual, FLOOR_SNAPSHOT, ac_by_task)
        total += len(actual)
        print("  %-28s 下限条目=%-3d 快照违规=%d %s"
              % (prof.name, len(actual), len(v), "OK" if not v else "MISMATCH"))
        for msg in v[:8]:
            print("      MISMATCH %s" % msg)
        if v:
            bad += 1
    if total == 0:
        print("  MISMATCH 四类下限零条目（快照守卫空转）")
        bad += 1
    # 反向对照（纯函数，内存变异，不落盘）：真实档不动 → 不报；改值/删条目/新增/出处不在 AC 必报。
    p0 = "10-clinical.yaml"
    if p0 in floor_by_prof:
        actual0, ac0 = floor_by_prof[p0]
        clean = not floor_snapshot_violations(p0, actual0, FLOOR_SNAPSHOT, ac0)
        k0 = sorted(actual0)[0]
        mut_val = dict(actual0)
        mut_val[k0] = mut_val[k0] + 1
        del_key = dict(actual0)
        del del_key[k0]
        add_key = dict(actual0)
        add_key[("task-ghost", "x.md", "min_matches.min", "Z")] = 99
        bad_prov = copy.deepcopy(FLOOR_SNAPSHOT)
        bad_prov[p0][k0] = (actual0[k0], {"ac": "task-ghost", "term": "不存在"})
        ctrl = [
            ("真实档不动 → 快照不报（正向对照）", clean),
            ("反向对照：改值未同步 → 必报", len(floor_snapshot_violations(
                p0, mut_val, FLOOR_SNAPSHOT, ac0)) == 1),
            ("反向对照：删条目 → 必报（快照有实际无）", bool(floor_snapshot_violations(
                p0, del_key, FLOOR_SNAPSHOT, ac0))),
            ("反向对照：新增下限未点名 AC 出处 → 必报", bool(floor_snapshot_violations(
                p0, add_key, FLOOR_SNAPSHOT, ac0))),
            ("反向对照：出处任务/词项不在 AC → 必报", bool(floor_snapshot_violations(
                p0, actual0, bad_prov, ac0))),
        ]
        for name, good in ctrl:
            print("  %-52s %s" % (name, "OK" if good else "MISMATCH"))
            if not good:
                bad += 1
    else:
        print("  MISMATCH 反向对照基线缺失（%s 无下限数据）" % p0)
        bad += 1
    # B10（B-8）反向对照：social 的 count_distinct.min 键同样受快照棘轮保护——
    # 迁移后该档有且仅有一条 count_distinct 下限（STROBE 22），改值未同步快照必报。
    if "20-social-science.yaml" in floor_by_prof:
        actual_s, ac_s = floor_by_prof["20-social-science.yaml"]
        cd_keys = sorted(k for k in actual_s if k[2] == "count_distinct.min")
        want_key = ("task-reporting-compliance", "50-review/53-reporting-checklist.md",
                    "count_distinct.min", "^\\|\\s*\\d+")
        soc_ctrl = [
            ("social 档 count_distinct 下限有且仅有一条（STROBE 迁移）",
             cd_keys == [want_key]),
            ("social 档快照干净（正向对照）",
             not floor_snapshot_violations("20-social-science.yaml", actual_s,
                                           FLOOR_SNAPSHOT, ac_s)),
        ]
        if cd_keys == [want_key]:
            mut_s = dict(actual_s)
            mut_s[want_key] = mut_s[want_key] + 1
            soc_ctrl.append(("反向对照：count_distinct 改值未同步快照 → 必报",
                             len(floor_snapshot_violations("20-social-science.yaml", mut_s,
                                                             FLOOR_SNAPSHOT, ac_s)) == 1))
        else:
            soc_ctrl.append(("反向对照基线：STROBE count_distinct 键缺失", False))
        for name, good in soc_ctrl:
            print("  %-52s %s" % (name, "OK" if good else "MISMATCH"))
            if not good:
                bad += 1
    else:
        print("  MISMATCH 反向对照基线缺失（20-social-science.yaml 无下限数据）")
        bad += 1
    return 1 if bad else 0


# ── 守卫 2d：word_count 量纲对账（R5 round4 R4-4）───────────────────────────
# 病灶：B10 把 word_count 换成正文行计数（70 号 count_body_lines），但四档阈值与 AC
# 量纲词仍按词——合规产物被下界假杀，且用户被迫拆行凑数（恰是反填充设计的反面）。
# 本守卫把「AC 量纲词与 word_count 语义登记一致」钉死：word_count 语义登记为**行**
# （SKILL 与 70 号 --schema 成文）。判据两条：
#   ① 凡带 word_count 断言的任务，其自身 AC 不得含词量纲（词数/字数/数字+词）；
#      刊方外部口径任务（如 select-journal 的「字数、图数」刊格式要求）无 word_count，
#      不在扫描面——外部刊方口径与本仓判据量纲互不干扰。
#   ② 骨架契约任务（skeleton/outline-contract）的 AC 须含「行数预算」（快照出处词项
#      同源；旧「字数预算」即违例）。
_WORD_DIM_RE = re.compile(r"词数|字数|\d+\s*–?\s*\d*\s*词")
_WORD_DIM_CONTRACTS = ("task-skeleton-contract", "task-outline-contract")


def wordcount_dimension_violations(prof_name: str, frag: dict, ac_by_task: dict) -> list:
    """量纲对账（纯函数，供真实档与反向对照共用）：返回违规串（空 = 过）。"""
    out = []
    wc_tasks = sorted({tid for tid, e in frag.items()
                       for f in e.get("files", []) or [] if "word_count" in f})
    if not wc_tasks:
        return []
    for tid in wc_tasks:
        text = "".join((ac_by_task.get(tid)) or [])
        m = _WORD_DIM_RE.search(text)
        if m:
            out.append("%s %s: AC 含词量纲 %r（word_count 语义登记为行）" % (prof_name, tid, m.group(0)))
    present_contracts = [c for c in _WORD_DIM_CONTRACTS if c in ac_by_task]
    if not present_contracts:
        out.append("%s: 骨架契约任务缺失（skeleton/outline-contract 均不在档）" % prof_name)
    for cid in present_contracts:
        if "行数预算" not in "".join(ac_by_task.get(cid) or []):
            out.append("%s %s: 契约 AC 缺「行数预算」（word_count 出处词项同源要求）" % (prof_name, cid))
    return out


def run_wordcount_dimension_guards() -> int:
    print("== word_count 量纲对账（AC 量纲词 = 行）==")
    bad = 0
    seen: dict = {}
    for prof in domain_profiles():
        try:
            frag, tasks, _, _, _ = gen(prof)
        except SystemExit:
            continue
        ac_by_task = {tid: (t.get("acceptance_criteria") or []) for tid, t in tasks.items()}
        v = wordcount_dimension_violations(prof.name, frag, ac_by_task)
        seen[prof.name] = (frag, ac_by_task)
        print("  %-28s word_count 任务=%-3d 量纲违规=%d %s"
              % (prof.name,
                 sum(1 for tid in frag for f in frag[tid].get("files", []) or []
                     if "word_count" in f),
                 len(v), "OK" if not v else "MISMATCH"))
        for msg in v[:8]:
            print("      MISMATCH %s" % msg)
        if v:
            bad += 1
    if not seen:
        print("  MISMATCH 无领域档数据（量纲守卫空转）")
        bad += 1
    # 反向对照（纯函数，内存变异，不落盘）：真实档不动 → 不报；AC 掺词量纲 / 契约缺行数预算必报。
    p0 = "10-materials-chemistry.yaml"
    if p0 in seen:
        frag0, ac0 = seen[p0]
        clean = not wordcount_dimension_violations(p0, frag0, ac0)
        mut_ac = {k: (list(v) if isinstance(v, list) else v) for k, v in ac0.items()}
        mut_ac["task-write-introduction"] = (
            list(mut_ac["task-write-introduction"]) + ["字数符合预算"])
        mut_contract = {k: (list(v) if isinstance(v, list) else v) for k, v in ac0.items()}
        mut_contract["task-skeleton-contract"] = ["骨架给出字数预算"]
        ctrl = [
            ("真实档不动 → 量纲不报（正向对照）", clean),
            ("反向对照：word_count 任务 AC 掺词量纲 → 必报",
             len(wordcount_dimension_violations(p0, frag0, mut_ac)) == 1),
            ("反向对照：契约 AC 缺行数预算 → 必报",
             bool(wordcount_dimension_violations(p0, frag0, mut_contract))),
        ]
        for name, good in ctrl:
            print("  %-52s %s" % (name, "OK" if good else "MISMATCH"))
            if not good:
                bad += 1
    else:
        print("  MISMATCH 反向对照基线缺失（%s 无数据）" % p0)
        bad += 1
    return 1 if bad else 0


# ── 守卫 3：规格一致性（AC2 必填字段 / AC3 三写作任务 word_count / 两档同源）─────────
def refs_required_keys() -> set:
    """22-refs.json 的必填字段集合，从两处规范文本取出（不抄常量，规范改了这里就得改）。"""
    row = next(l for l in REFS_DOC.read_text(encoding="utf-8-sig").splitlines()
               if "22-refs.json" in l and "验真" in l)
    cell = next(c for c in row.split("|") if "22-refs.json" in c)
    keys = {k for k in re.findall(r"`([a-z_]+)`", cell)}
    prof = _load_profile_safe(PROFILES / "10-materials-chemistry.yaml")
    if prof is None:
        return keys          # B05b：档含重键（形状段已点名）→ 退回规范文本侧字段集合，不中止
    ac = next(a for t in prof["tasks"] if t["id"] == "task-search-verify-refs"
              for a in t["ac"] if "字段" in a)
    m = re.search(r"字段（([^）]+)）", ac)
    keys |= {x.strip() for x in m.group(1).split("、")} if m else set()
    return keys


# F2（2026-10-07）：实质断言按**档轴**分化的任务——跨档 pairwise 逐字比对对它们不适用。
_CROSS_PROFILE_AXIS_TASKS = ("task-reporting-compliance",)


def _views_equal(a, b):
    """两视图逐字一致，但 json_files 的 require_keys 允许子档追加（父档其余保留）。"""
    if a == b:
        return True
    if len(a.get("json_files", [])) != len(b.get("json_files", [])):
        return False
    for fa, fb in zip(a.get("json_files", []), b.get("json_files", [])):
        if fa.get("path") != fb.get("path"):
            return False
        ra = set(fa.get("require_keys", []))
        rb = set(fb.get("require_keys", []))
        if ra == rb:
            continue
        if ra & rb:                                     # 有交集 → 允许追加/缩减
            if not (ra <= rb or rb <= ra):              # 非子集关系 → 真差异
                return False
        else:                                           # 无交集 → 真差异
            return False
        fa2 = dict(fa); fb2 = dict(fb)
        fa2["require_keys"] = sorted(list(ra | rb))
        fb2["require_keys"] = sorted(list(ra | rb))
        if fa2 != fb2:
            return False
    if a.get("files") != b.get("files"):
        return False
    return True


def run_spec_guards() -> int:
    print("== 规格一致性（AC2/AC3/两档同源）==")
    cases = []
    required = refs_required_keys()
    frags = {}
    for prof in domain_profiles():
        try:
            frags[prof.name], _, _, _, _ = gen(prof)
        except SystemExit:
            cases.append(("生成 %s" % prof.name, "die"))
    # AC2：task-citation-audit 的 json_files 必须逐条覆盖必填字段集合
    cit = (frags.get("10-materials-chemistry.yaml") or {}).get("task-citation-audit", {})
    refs = [j for j in cit.get("json_files", []) if j["path"].endswith("22-refs.json")]
    have = set(refs[0].get("require_keys_all", [])) if refs else set()
    cases.append(("citation-audit json_files 覆盖必填字段集合 %s" % sorted(required),
                  "" if refs and required <= have else "缺 %s" % sorted(required - have)))
    cases.append(("citation-audit json_files 带 min_items（N-3）",
                  "" if refs and "min_items" in refs[0] else "无 min_items"))
    # AC3：三个写作任务各含 word_count 正整数区间
    for tid in WRITING_TASKS:
        bands = [f["word_count"] for e in frags.values() for f in e.get(tid, {}).get("files", [])
                 if "word_count" in f]
        ok = bool(bands) and all(isinstance(b, list) and len(b) == 2
                                 and all(isinstance(x, int) and x > 0 for x in b) and b[0] < b[1]
                                 for b in bands)
        cases.append(("%s word_count 区间" % tid, "" if ok else str(bands[:2])))
    # 多档同源：任意两档的共有任务实质断言必须逐字一致（子档若重定义本键，deep_merge 的
    # list 替换会静默清掉父档实质断言，展开后形同无断言）。pairwise 比对避免新增档静默挤出
    # 旧档独有共有任务的覆盖（2026-09-27 实测：旧档间独有的 5 个任务不再
    # 做逐字比较，属新档落地带来的静默覆盖回退）。
    names = sorted(frags)
    views = {n: substantive_view(f) for n, f in frags.items()}
    pairs = [(a, b) for i, a in enumerate(names) for j, b in enumerate(names) if i < j]
    diffs = []
    for a, b in pairs:
        shared = set(views[a]) & set(views[b])
        for t in sorted(shared):
            # F2（2026-10-07）：报告规范的断言**按档轴声明走**（clinical 含 CONSORT+STROBE，
            # social 只 STROBE）——task-reporting-compliance 的实质断言本就随 axes.reporting
            # 分化，不适用「跨档逐字一致」口径（其轴自洽由 run_shape/token_source 守卫保证）。
            if t in _CROSS_PROFILE_AXIS_TASKS:
                continue
            if not _views_equal(views[a][t], views[b][t]):
                diffs.append("%s↔%s:%s" % (a, b, t))
    cases.append(("多档 pairwise 共有任务（%d 对）断言逐字一致" % len(pairs),
                  "" if not diffs else "差异 " + "、".join(diffs[:6])))
    # B8：pairwise 0 对必须判空转（否则只剩一档 / 档名漂移时「0 对全绿」= 守卫空转放行）。
    cases.append(("多档 pairwise 对数 > 0（0 对即空转）",
                  "" if pairs else "0 对可比对（档数或 gen 结果异常）"))
    bad = 0
    for name, why in cases:
        ok = not why
        print("  %-56s %s" % (name, "OK" if ok else "MISMATCH " + why))
        if not ok:
            bad += 1
    return 1 if bad else 0


# ── 守卫 6：AC 引用路径与 files_to_read 方向守卫 ──────────────────────────────
# 判定谓语支配的路径串（「与…一致/只使用/落在/取自/按…」等谓语形态取其支配的路径串，
# 须 ∈ files_to_read∪files_to_edit；pre-谓语主体不抽取）。A-13（2026-10-07）：旧实现按
# `与\s*`([^`]+)`[^`。]*?` 抽取，并列路径句「与 `A`、`B` 一致」跨不过第二个反引号 →
# 抽取为空（连第一个都不判）；且动词表缺「只使用/落在/取自/按…预算」。修法：先按句切分，
# 逐个谓语形态取其支配的路径串（并列 `A`、`B` 不漏），再校验可达性。
_AC_PATH_VERBS = (
    # 与 X（可并列 `A`、`B`）不一致 / 一致 / 一一对应 / 对应 / 相同 / 比对 / 对齐——捕获谓语
    # 支配的路径串（并列不漏）。
    r"与\s*(`[^`]+`(?:[、，,\s]*`[^`]+`)*)[^。；]*?(?:不一致|一一对应|对应|一致|相同|比对|对齐)",
    r"按\s*(`[^`]+`)\s*(?:的|预算)",
    r"以\s*(`[^`]+`)[^。；]*为准",
    r"核对[^。；]*?(`[^`]+`)",
    r"只使用[^。；]*?(`[^`]+`)",
    r"落在[^。；]*?(`[^`]+`)",
    r"取自\s*(`[^`]+`)",
)
# 指针性交叉引用（下游落点 / 交回上游 / AC 自述「可交叉核对」）不要求声明——其路径可能
# 属于下游任务产物（如 claim-map AC 的「与 00-admin/02-skeleton.md 一致（可交叉核对）」）。
_AC_PATH_CROSSREF = ("须出现在", "须回到", "可交叉核对")


def _ac_judgment_paths(ac: str) -> list:
    """该 AC 中判定谓语支配的路径串：按句切分，逐个谓语形态取其支配的路径串
    （pre-谓语主体不抽取，如「`A` 与 `B`、`C` 一致」只取谓语后的 `B`、`C`）。

    A-13：谓语支配的路径串可含并列（`A`、`B`），故用捕获组取整串再展开——旧实现用
    `与\\s*`([^`]+)`[^`。]*?` 只认紧邻的第一个路径，并列句直接抽取为空。
    """
    if any(c in ac for c in _AC_PATH_CROSSREF):
        return []
    out = []
    for sent in re.split(r"[。；;]", ac):
        for pat in _AC_PATH_VERBS:
            for run in re.findall(pat, sent):
                out += [p for p in re.findall(r"`([^`]+)`", run) if "/" in p]
    return out


def ac_path_violations(task: dict) -> list:
    """返回任务 AC 中「判定句引用的路径 ∉ files_to_read∪files_to_edit」的路径列表。

    task 为生成器产出的任务定义（键：acceptance_criteria / files_to_read / files_to_edit，
    其中路径占位符已展开）。独立成函数，既供真实档扫描，也供反向对照注入合成任务。"""
    allowed = {r["path"] for r in (task.get("files_to_read") or [])
               if isinstance(r, dict)} | set(task.get("files_to_edit") or [])
    bad = []
    for ac in task.get("acceptance_criteria") or []:
        for p in _ac_judgment_paths(ac):
            if p not in allowed:
                bad.append(p)
    return bad


def run_ac_path_guards() -> int:
    """AC 引用路径与 files_to_read 方向守卫。

    AC 规定「与某文件不一致即判 CRITICAL」「只使用某文件的已验真条目」「字数落在某文件预算
    区间」，但该文件不在同任务 files_to_read 里时，agent 按声明读取面根本拿不到比对对象。
    本守卫按判定谓语形态取其支配的路径串，校验 ∈ files_to_read∪files_to_edit；指针性
    交叉引用（「须出现在…」「须回到…」「可交叉核对」）不判红。含反向对照（声明→不红 /
    删声明→必红 / 交叉引用→不红 / 并列路径→第二个必报 / 新动词形态→必红）与空转门禁。"""
    print("== AC 引用路径方向守卫（判定动词 + 路径引用）==")
    bad = 0
    hits = 0
    for prof in domain_profiles():
        try:
            _, tasks, _, _, _ = gen(prof)
        except SystemExit:
            continue
        for tid, task in tasks.items():
            for ac in task.get("acceptance_criteria") or []:
                hits += len(_ac_judgment_paths(ac))
            for p in ac_path_violations(task):
                print("  MISMATCH %s %s: AC 引用路径不在 files_to_read∪files_to_edit: %s"
                      % (prof.name, tid, p))
                bad += 1
    # 空转门禁：真实档必须至少命中一条判定句路径，否则守卫与任务结构脱节（历史缺陷防复发）
    if hits == 0:
        print("  MISMATCH 真实档 0 条判定句命中：守卫疑与任务结构脱节（空转）")
        bad += 1

    # 反向对照（合成任务，证明守卫真咬得住且不过度判红）
    _ref = "10-data/10-audit.md"
    _ac = "与 `%s` 不一致即判 CRITICAL。" % _ref
    declared = {"files_to_read": [{"path": _ref}], "files_to_edit": [],
                "acceptance_criteria": [_ac]}
    stripped = {"files_to_read": [], "files_to_edit": [],
                "acceptance_criteria": [_ac]}
    crossref = {"files_to_read": [], "files_to_edit": [],
                "acceptance_criteria": ["数值变更须回到 `10-data/11-analysis.md` 并说明。"]}
    # F1 加宽判定动词（与…一一对应）与 AC 自述「可交叉核对」的排除，各配一条。
    _ac2 = "`20-lit/22-refs.json` 的 local_pdf 字段与 `20-lit/fulltext/` 实际文件一一对应。"
    declared2 = {"files_to_read": [{"path": "20-lit/fulltext/"}], "files_to_edit": [],
                 "acceptance_criteria": [_ac2]}
    stripped2 = {"files_to_read": [], "files_to_edit": [], "acceptance_criteria": [_ac2]}
    cross2 = {"files_to_read": [], "files_to_edit": [],
              "acceptance_criteria": ["`20-lit/20-claims-map.md` 的行与 `00-admin/02-skeleton.md` 一致（可交叉核对）。"]}
    # A-13：并列路径句——第一个已声明、第二个未声明 → 必须点名第二个（旧实现抽取为空、全不判）。
    _ac3 = "`10-data/11-analysis.md` 与 `10-data/10-audit.md`、`00-admin/00-plan.md` 一致。"
    parallel = {"files_to_read": [{"path": "10-data/11-analysis.md"}, {"path": "10-data/10-audit.md"}],
                "files_to_edit": [], "acceptance_criteria": [_ac3]}
    parallel_ok = {"files_to_read": [{"path": "10-data/11-analysis.md"},
                                     {"path": "10-data/10-audit.md"},
                                     {"path": "00-admin/00-plan.md"}],
                   "files_to_edit": [], "acceptance_criteria": [_ac3]}
    # A-13：新增动词形态——「只使用…中」「落在…预算区间」「取自」。
    verbs = {"files_to_read": [], "files_to_edit": [],
             "acceptance_criteria": [
                 "该节引用只使用 `20-lit/22-refs.json` 中已验真条目。",
                 "正文字数落在 `00-admin/01-meta.json` 的预算区间。",
                 "数值取自 `10-data/11-analysis.md`。"]}
    ctrl_ok = (not ac_path_violations(declared)
               and bool(ac_path_violations(stripped))
               and not ac_path_violations(crossref)
               and not ac_path_violations(declared2)
               and bool(ac_path_violations(stripped2))
               and not ac_path_violations(cross2)
               and ac_path_violations(parallel) == ["00-admin/00-plan.md"]
               and not ac_path_violations(parallel_ok)
               and len(ac_path_violations(verbs)) == 3)
    print("  %-56s %s" % ("反向对照：声明→不红 / 删声明→必红 / 交叉引用→不红 / 对应式→必红 / "
                          "并列第二路径→必报 / 新动词三形态→必报",
                          "OK" if ctrl_ok else "MISMATCH"))
    if not ctrl_ok:
        bad += 1

    print("  AC 路径方向问题 %d 条（判定句命中 %d）" % (bad, hits))
    return 1 if bad else 0


# ── 守卫 6b：死策略键守卫（evidence_policy 定义却零 inject）──────────────────────
# B-4（2026-10-07）：`method_citation` 文案承诺「清单见本档 domain_checklist」，但
# clinical/materials/social 的 `domain_checklist` 从未被任何任务 inject → 承诺落空；
# `axis_integrity` 在 clinical 全文零 inject → 「纵轴不从零起须图注说明」不可判。
# 口径：合并后 profile 的每个 evidence_policy 键至少被一个任务 `inject`（继承档一并算）。
def dead_policy_key_violations(profile: dict) -> list:
    """合并后 profile 中「定义却零 inject」的 evidence_policy 键（死键）清单。"""
    pol = profile.get("evidence_policy") or {}
    injected = set()
    for t in profile.get("tasks", []):
        injected |= set(t.get("inject") or [])
    return sorted(set(pol) - injected)


def dead_policy_idle(profile: dict) -> bool:
    """合并后 profile 的 evidence_policy 键数为 0 即空转（与 AC 路径 hits==0 /
    链上产物 total==0 同口径：零条目不断言通过，守卫即摆设）。"""
    return len(profile.get("evidence_policy") or {}) == 0


def run_dead_policy_key_guards() -> int:
    print("== 死策略键守卫（evidence_policy 定义却零 inject）==")
    bad = 0
    total_keys = 0
    for prof in domain_profiles():
        try:
            _, _, _, merged, _ = gen(prof)
        except SystemExit:
            continue
        pol = merged.get("evidence_policy") or {}
        total_keys += len(pol)
        if dead_policy_idle(merged):
            print("  MISMATCH %-28s evidence_policy 键=0（空转：零键不断言通过）" % prof.name)
            bad += 1
            continue
        dead = dead_policy_key_violations(merged)
        print("  %-28s evidence_policy 键=%d 零 inject=%d %s"
              % (prof.name, len(pol), len(dead),
                 "OK" if not dead else "MISMATCH " + "、".join(dead)))
        if dead:
            bad += 1
    if total_keys == 0:
        print("  MISMATCH 合并后 evidence_policy 零键（守卫空转）")
        bad += 1
    # 反向对照（合成 profile）：有死键 → 报；全被 inject → 不报；空 policy → 判空转。
    dead_prof = {"evidence_policy": {"a": "x", "b": "y"}, "tasks": [{"inject": ["a"]}]}
    live_prof = {"evidence_policy": {"a": "x", "b": "y"}, "tasks": [{"inject": ["a", "b"]}]}
    empty_prof = {"evidence_policy": {}, "tasks": []}
    ctrl = [("反向对照：定义却零 inject 的键必报", dead_policy_key_violations(dead_prof) == ["b"]),
            ("对照：全部被 inject → 不报", not dead_policy_key_violations(live_prof)),
            ("反向对照：空 policy → 判空转", dead_policy_idle(empty_prof)),
            ("对照：非空 policy → 不判空转", not dead_policy_idle(live_prof))]
    for name, ok in ctrl:
        print("  %-52s %s" % (name, "OK" if ok else "MISMATCH"))
        if not ok:
            bad += 1
    return 1 if bad else 0


# ── 守卫 6c：链上产物读者（10-data/ 分析产物必须有命名 read）────────────────────
# B-5（2026-10-07）：`13-table-main-results.md`（cs-ml）、`12-table1-sample.md`/
# `13-codebook-reliability.md`（social）等 10-data/ 分析产物全档无命名 read → 正文数值/
# 样本表/κ 一致性无机检对象。口径：分析产物（`10-data/<name>.md` 直接子件）至少被一个任务
# 以**精确路径** read（目录式 read 不掩盖；下游写作任务须显式声明其消费的分析表）。
_CHAIN_ARTIFACT_RE = re.compile(r"^10-data/[^/]+\.md$")


def chain_reader_violations(tasks: dict) -> list:
    """分析产物（10-data/ 直接子件 .md）中无任何任务以精确路径 read 的清单 [(owner, path)]。"""
    read_exact = set()
    for t in tasks.values():
        for r in t.get("files_to_read", []) or []:
            if isinstance(r, dict):
                read_exact.add(r.get("path"))
    out = []
    for tid, t in tasks.items():
        for f in t.get("files_to_edit", []) or []:
            if _CHAIN_ARTIFACT_RE.match(f) and f not in read_exact:
                out.append((tid, f))
    return out


def run_chain_reader_guards() -> int:
    print("== 链上产物读者守卫（10-data/ 分析产物须有命名 read）==")
    bad = 0
    total = 0
    for prof in domain_profiles():
        try:
            _, tasks, _, _, _ = gen(prof)
        except SystemExit:
            continue
        n = sum(1 for t in tasks.values() for f in t.get("files_to_edit", []) or []
                if _CHAIN_ARTIFACT_RE.match(f))
        v = chain_reader_violations(tasks)
        total += n
        print("  %-28s 分析产物=%-3d 无命名读者=%d %s"
              % (prof.name, n, len(v),
                 "OK" if not v else "MISMATCH " + "、".join("%s:%s" % x for x in v)))
        if v:
            bad += 1
    if total == 0:
        print("  MISMATCH 分析产物零条目（守卫空转）")
        bad += 1
    # 反向对照（合成 tasks）：产出无命名读者 → 报；有命名读者 / 非 10-data 产物 → 不报。
    orphan = {"task-a": {"files_to_edit": ["10-data/13-table-x.md"], "files_to_read": []}}
    read = {"task-a": {"files_to_edit": ["10-data/13-table-x.md"],
                       "files_to_read": [{"path": "10-data/13-table-x.md"}]}}
    terminal = {"task-a": {"files_to_edit": ["30-manuscript/36-draft.md"], "files_to_read": []}}
    ctrl = [("反向对照：分析产物无命名读者 → 必报", chain_reader_violations(orphan) == [("task-a", "10-data/13-table-x.md")]),
            ("对照：有命名读者 → 不报", not chain_reader_violations(read)),
            ("对照：非 10-data 终产物 → 不报", not chain_reader_violations(terminal))]
    for name, ok in ctrl:
        print("  %-52s %s" % (name, "OK" if ok else "MISMATCH"))
        if not ok:
            bad += 1
    return 1 if bad else 0


# ── 守卫 7：正反控制（合成沙箱跑真实 70-verify.py）─────────────────────────────
def plan_artifacts(frag: dict):
    """按断言反推一份"全部满足"的产物计划。返回 (files, jsons, globs, 不可满足问题)。"""
    texts, jsons, globs, issues = {}, {}, [], []
    for tid, e in frag.items():
        for f in e.get("files", []):
            d = texts.setdefault(f["path"], {"tokens": set(), "probes": [], "distincts": [],
                                              "bytes": 0, "lo": 0, "hi": None, "pads": []})
            d["tokens"] |= set(f.get("contains") or [])
            d["bytes"] = max(d["bytes"], f.get("min_bytes", 0) or 0)
            if "min_matches" in f:
                d["probes"].append((f["min_matches"]["pattern"], f["min_matches"]["min"]))
            if "count_distinct" in f:
                # B10（B-8）：唯一计数须合成 min 条**互异**匹配行/串——同探针复用 n 次只计 1，
                # 照 min_matches 那样重复填充会让正控制恒红（合成器未覆盖该原语即自报）。
                cd = f["count_distinct"]
                d["distincts"].append((cd["pattern"], cd["min"], cd.get("scope") or "line"))
            for pat in f.get("contains_regex", []):
                d["pads"].append(pat)
            if "word_count" in f:
                lo, hi = f["word_count"]
                d["lo"] = max(d["lo"], lo)
                d["hi"] = hi if d["hi"] is None else min(d["hi"], hi)
        for j in e.get("json_files", []):
            d = jsons.setdefault(j["path"], {"keys": set(), "min": 1, "max": None})
            d["keys"] |= set(j.get("require_keys", []) + j.get("require_keys_all", []))
            d["min"] = max(d["min"], j.get("min_items", 1))
            if "max_items" in j:
                d["max"] = j["max_items"] if d["max"] is None else min(d["max"], j["max_items"])
        for g in e.get("globs", []):
            globs.append((g["pattern"], g.get("min_count", 1), g.get("min_bytes_each", 0)))
    for path, d in sorted(texts.items()):
        lines = sorted(d["tokens"])
        for pat, n in d["probes"]:
            p = probe_for(pat)
            if p is None:
                issues.append("%s: min_matches %r 不可满足" % (path, pat))
                continue
            lines += [p] * n
        for pat, n, scope in d["distincts"]:
            p = probe_for(pat)
            if p is None:
                issues.append("%s: count_distinct %r 不可满足" % (path, pat))
                continue
            for i in range(n):
                # line 域：行尾缀序号（^ 锚模式照旧命中，行互异）；all 域：匹配串内嵌序号
                # （group(0) 互异）。通配探针 `| 1` → `| 1 #cd0` / `| 10` 两态。
                lines.append("%s #cd%d" % (p, i) if scope == "line" else "%s%d" % (p, i))
        for pat in d["pads"]:
            p = probe_for(pat)
            if p is None:
                issues.append("%s: contains_regex %r 不可满足" % (path, pat))
            else:
                lines.append(p)
        text = "".join(l + "\n" for l in lines)
        # B10：word_count 是正文行计数——补足按正文行算（探针 `| …` 表格行/图注行不计入，
        # 计数口径复用 70 号 count_body_lines，单一真源）。 filler 行取无数字无标记的 `w`。
        body = verify70.count_body_lines(text)
        need = d["lo"] - body
        if need > 0:
            text += "".join("w\n" for _ in range(need))
            body += need
        if d["hi"] is not None and body > d["hi"]:
            issues.append("%s: 满足下限后正文行 %d 超上限 %d（区间与其他断言冲突）"
                          % (path, body, d["hi"]))
        if len(text.encode("utf-8")) < d["bytes"]:
            text += "z" * (d["bytes"] - len(text.encode("utf-8")) + 8) + "\n"
        for pat, n, scope in d["distincts"]:
            # 合成后自验：填充/补齐不得吃掉互异性（否则正控制恒红，合成器先自报）。
            got = verify70.count_distinct_value(text, pat, scope)
            if got < n:
                issues.append("%s: count_distinct %r 合成后唯一计数 %d < min %d"
                              "（合成器未覆盖该原语）" % (path, pat, got, n))
        d["content"] = text
    for path, d in sorted(jsons.items()):
        n = d["min"] if d["max"] is None else min(d["min"], d["max"])
        content = json.dumps([{k: 1 for k in sorted(d["keys"])}] * max(n, 1),
                             ensure_ascii=False)
        # F-9R（2026-10-07 二轮）：min_items 条件化（20→1）后，合成小样本可能低于通配
        # `min_bytes: 200`。同路径 texts 侧（通配展开的 {path, min_bytes}）给出体积下限时，
        # 按倍数增条目数补足——保持「对象列表 + 各键」形态（不得改顶层形态或加未知键，
        # 后者会触 70 号 F4 未知键 rc=2）。
        min_b = (texts.get(path) or {}).get("bytes", 0)
        while min_b and len(content.encode("utf-8")) < min_b:
            n += 1
            content = json.dumps([{k: 1 for k in sorted(d["keys"])}] * n, ensure_ascii=False)
        d["content"] = content
    return texts, jsons, globs, issues


def write_sandbox(root: pathlib.Path, texts: dict, jsons: dict, globs: list) -> None:
    for path, d in texts.items():
        p = root / path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(d["content"], encoding="utf-8")
    for path, d in jsons.items():
        p = root / path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(d["content"], encoding="utf-8")
    for pattern, min_count, min_bytes in globs:
        if "**" in pattern:
            continue                                   # 本 skill 的 profile 未用递归 glob
        d, base = pattern.rsplit("/", 1)
        target = root / d
        target.mkdir(parents=True, exist_ok=True)
        if "*" not in base:
            (target / base).write_bytes(b"y" * max(min_bytes, 1))
            continue
        stem, suf = base.split("*", 1)
        for i in range(max(min_count, 1)):
            (target / ("%s%d%s" % (stem, i, suf))).write_bytes(b"y" * max(min_bytes, 1))


def run_verify(root: pathlib.Path, manifest: pathlib.Path, tid: str):
    # -B：conventions §2 要求跨进程调用不落 .pyc
    r = subprocess.run([sys.executable, "-B", "-X", "utf8", str(VERIFY), tid, "--quiet",
                        "--root", str(root), "--manifest", str(manifest)],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def run_wordcount_semantics_cases() -> int:
    """B10（A-14）word_count 语义 mini 控制：正文行计数（非空白切词）。

    2800 行纯 `|` 表格脚手架 / 围栏内代码 / 图注行 → 正文行 0 → rc=1（旧词数口径下
    表格脚手架约 14000 词、会落入 [2800,15000] 假过）；2800 行真实正文（中英混排，
    兼证中文按行口径）→ rc=0。由 run_synth_guards 在同一 `== 正反控制 ==` 段内调用
    （不另起段，_SEGMENT_COUNT 不变）。
    """
    cases = [
        ("纯表格脚手架 2800 行", "".join("| a | b |\n" for _ in range(2800)), 1),
        ("围栏内代码 2800 行",
         "```\n" + "".join("code line %d\n" % i for i in range(2800)) + "```\n", 1),
        ("图注行 2800 行", "".join("Fig. %d. caption text\n" % i for i in range(1, 2801)), 1),
        ("真实正文 2800 行", "".join(
            ("Body line %d with text.\n" if i % 2 == 0 else "这是第 %d 行正文内容。\n") % i
            for i in range(2800)), 0),
    ]
    bad = 0
    with tempfile.TemporaryDirectory() as td:
        tmp = pathlib.Path(td)
        mf = tmp / "manifest.json"
        mf.write_text(json.dumps(
            {"t": {"files": [{"path": "doc.md", "word_count": [2800, 15000]}]}},
            ensure_ascii=False), encoding="utf-8")
        for name, content, want in cases:
            (tmp / "doc.md").write_text(content, encoding="utf-8")
            rc, _ = run_verify(tmp, mf, "t")
            ok = rc == want
            print("  word_count %-16s rc=%d（应 %d） %s" % (name, rc, want,
                                                            "OK" if ok else "MISMATCH"))
            bad += 0 if ok else 1
    return 1 if bad else 0


def run_synth_guards() -> int:
    print("== 正反控制（合成沙箱，逐任务跑真实 70-verify.py）==")
    frags, biggest = {}, None
    for prof in domain_profiles():
        try:
            frag, _, _, _, _ = gen(prof)
        except SystemExit:
            continue
        frags[prof.name] = frag
        if biggest is None or len(frag) > len(frags[biggest]):
            biggest = prof.name
    if not frags:
        print("  MISMATCH 无可用 profile")
        return 1
    views = {n: substantive_view(f) for n, f in frags.items()}
    identical = len({json.dumps(v, ensure_ascii=False, sort_keys=True)
                     for v in views.values()}) == 1
    covers_all = all(set(frags[biggest]) >= set(f) for f in frags.values())
    targets = [biggest] if identical and covers_all else sorted(frags)
    print("  实质断言集合%s、任务集%s ⊇ 其余档 → 沙箱覆盖：%s"
          % ("一致" if identical else "不一致", "覆盖" if covers_all else "不覆盖",
             "、".join(targets)))
    bad = 0
    for name in targets:
        frag = {tid: {k: v for k, v in e.items() if k != "run"}
                for tid, e in frags[name].items()}
        with tempfile.TemporaryDirectory() as td:
            tmp = pathlib.Path(td)
            texts, jsons, globs, issues = plan_artifacts(frag)
            if issues:
                bad += 1
            for msg in issues:
                print("  MISMATCH 不可满足：%s" % msg)
            mf = tmp / "manifest.json"
            mf.write_text(json.dumps(frag, ensure_ascii=False), encoding="utf-8")
            pos, neg = tmp / "pos", tmp / "neg"
            pos.mkdir(); neg.mkdir()
            write_sandbox(pos, texts, jsons, globs)
            npass = nfail = 0
            for tid in sorted(frag):
                rc_pos, out_p = run_verify(pos, mf, tid)
                rc_neg, out_n = run_verify(neg, mf, tid)
                ok = rc_pos == 0 and rc_neg == 1
                npass += 1 if ok else 0
                nfail += 0 if ok else 1
                if not ok:
                    bad += 1
                    print("  MISMATCH %-14s %s: pos=%d(应0) neg=%d(应1)" % (name, tid, rc_pos, rc_neg))
                    print("      pos 输出：%s" % (out_p.strip().replace("\n", " | ")[:300]))
                    print("      neg 输出：%s" % (out_n.strip().replace("\n", " | ")[:300]))
            print("  %-28s 正反控制 %d/%d 通过" % (name, npass, len(frag)))
    bad += run_wordcount_semantics_cases()
    return 1 if bad else 0


# ── 守卫 5：反向对照（逐档 × 逐实质任务删空，必须严格递减且被点名）──────────────────
# B6/B7（2026-10-07 审查）：与 FLOOR 解耦——不再依赖「删一跌破下限」（各档涨过 FLOOR 即失效，
# 且旧实现只打最小档，把 social 的 reporting-compliance 摘净仍 PASS）。现改为**五档各以自身
# 条数为基线**、逐任务删空，断言「该档实质任务数严格递减 -1 且该任务被 weakened_tasks 点名」。
def run_reverse_guards() -> int:
    print("== 反向对照（逐档 × 逐实质任务删空，须严格递减且被点名）==")
    bad = 0
    total = 0
    for prof in domain_profiles():
        try:
            frag, _, _, _, _ = gen(prof)
        except SystemExit:
            continue
        ids = substantive_ids(frag)
        base_n = len(ids)
        if base_n == 0:
            print("  MISMATCH %-28s 无实质任务，反向对照空转" % prof.name)
            bad += 1
            continue
        misses = []
        for tid in ids:
            stripped = strip_substantive(frag, tid)
            dec = base_n - len(substantive_ids(stripped))
            named = tid in weakened_tasks(frag, stripped)
            still_gated = bool(stripped[tid].get("files") or stripped[tid].get("json_files"))
            total += 1
            if not (dec == 1 and named):
                misses.append("%s（递减 %d / 点名 %s）" % (tid, dec, named))
            elif not still_gated:
                # 删空后连通配兜底都不剩 → 该任务在门禁里彻底消失，属漏网
                misses.append("%s（通配未兜底）" % tid)
        ok = not misses
        print("  %-28s 实质任务=%-3d 逐条删空均严格递减且点名  %s"
              % (prof.name, base_n, "OK" if ok else "MISMATCH " + "、".join(misses[:3])))
        if not ok:
            bad += 1
    print("  逐档逐任务反向对照 %d 组（四档全覆盖）" % total)
    if total == 0:
        print("  MISMATCH 反向对照用例为 0（空转）")
        bad += 1
    return 1 if bad else 0


# ── 守卫 5.5：deep_merge 子档-only inject（父档无 inject 时子档追加必须生效）────────
def run_deep_merge_guards() -> int:
    print("== deep_merge 子档-only inject（父档无 inject 时子档追加必须生效）==")
    base = {"tasks": [{"id": "task-x", "ac": ["base"]}]}                 # 父档无 inject
    child_only = {"tasks": [{"id": "task-x", "inject": ["foo"]}]}        # 子档只写 inject
    t = {x["id"]: x for x in gen30.deep_merge(base, child_only)["tasks"]}["task-x"]
    both = gen30.deep_merge(
        {"tasks": [{"id": "task-x", "inject": ["bar"], "ac": ["base"]}]},
        {"tasks": [{"id": "task-x", "inject": ["foo", "bar"]}]})
    tb = {x["id"]: x for x in both["tasks"]}["task-x"]
    tn = {x["id"]: x for x in gen30.deep_merge(
        base, {"tasks": [{"id": "task-x", "ac": ["child"]}]})["tasks"]}["task-x"]
    am = gen30.deep_merge(
        {"verify_assertions_template": [{"task": "task-a", "files": [{"path": "p1", "contains": ["X"]}]}]},
        {"verify_assertions_template": [{"task": "task-a", "files": [{"path": "p2", "contains": ["Y"]}]}]})
    am_paths = [f["path"] for f in am["verify_assertions_template"][0]["files"]]
    ov = gen30.deep_merge(
        {"verify_assertions_template": [{"task": "task-a", "files": [{"path": "p1", "contains": ["X"]}]}]},
        {"verify_assertions_template": [{"task": "task-a", "files": [{"path": "p1", "contains": ["Z"]}]}]})
    ov_files = ov["verify_assertions_template"][0]["files"]
    add_tasks = [e["task"] for e in gen30.deep_merge(
        {"verify_assertions_template": [{"task": "task-a", "files": [{"path": "p1"}]}]},
        {"verify_assertions_template": [{"task": "task-b", "files": [{"path": "p9"}]}]}
    )["verify_assertions_template"]]
    cases = [
        ("子档-only inject 生效（父档无 inject）", t.get("inject") == ["foo"] and t.get("ac") == ["base"]),
        ("父子都有 inject 时去重追加", tb.get("inject") == ["bar", "foo"]),
        ("反向对照：子档无 inject 则不凭空生成", "inject" not in tn),
        ("assertions：同 task 子档追加 path（父档其余保留）", am_paths == ["p1", "p2"]),
        ("assertions：同名 path 子档覆盖", len(ov_files) == 1 and ov_files[0]["contains"] == ["Z"]),
        ("assertions：子档新增 task 追加、父档其余保留", add_tasks == ["task-a", "task-b"]),
    ]
    bad = 0
    for name, ok in cases:
        print("  %-50s %s" % (name, "OK" if ok else "MISMATCH"))
        if not ok:
            bad += 1
    return 1 if bad else 0


# ── 守卫 6：AC6 基类不写死字面 data/、领域档解析成规范目录 ────────────────────────
def run_unit_source_guards() -> int:
    print("== unit_source 占位与解析（AC6）==")
    base = _load_profile_safe(PROFILES / "00-base-empirical.yaml")
    cases = []
    if base is None:
        # B05b：基类含重复键（形状段已点名）→ 跳过本条，不 SystemExit 中止整跑。
        print("  跳过：基类 00-base-empirical 含重复键（B05b，已在形状段点名）")
    else:
        us = base["evidence_policy"].get("unit_source", "")
        cases.append(("基类 unit_source 不含字面 data/", " data/" not in us and "项目 data/" not in us))
        cases.append(("基类 unit_source 用 {data} 占位", "{data}" in us))
    for prof in domain_profiles():
        frag, tasks, problems, merged, rules = gen(prof)
        concrete = merged["paths"]["data"]
        line = next((l for l in rules.splitlines() if l.startswith("- **unit_source**")), "")
        cases.append(("%s rules.fragment 的 unit_source 含 %s/" % (prof.name, concrete),
                      ("%s/" % concrete) in line))
        cases.append(("%s rules.fragment 无未解析占位符" % prof.name,
                      not PLACEHOLDER.search(rules)))
    bad = 0
    for name, ok in cases:
        print("  %-52s %s" % (name, "OK" if ok else "MISMATCH"))
        if not ok:
            bad += 1
    return 1 if bad else 0


# ── 守卫 7（可选）：真实项目回放 = 假阳控制 ────────────────────────────────────────
def run_project_replay(project: pathlib.Path) -> tuple:
    """真项目回放，返回 (rc, passed, failed, skipped)（R5 T4 起元组口径，供合成守卫断言用）。

    --project 调用方只取 rc（行为零回归）；合成守卫另断言 passed/failed 防空转。
    """
    print("== 真实项目回放（假阳控制，只读）：%s ==" % project)
    if not (project / ".orchd").exists() and not (project / "20-lit").exists():
        print("  跳过：不像论文项目根")
        return (0, 0, 0, 0)
    if dup_key_violations(PROFILES / "10-materials-chemistry.yaml"):
        # B05b：materials 档含重复键（形状段已点名）→ 跳过回放，不 SystemExit。
        print("  跳过：materials 档含重复键（B05b，已在形状段点名）")
        return (0, 0, 0, 0)
    frag, _, _, merged, rules = gen(PROFILES / "10-materials-chemistry.yaml")
    concrete = merged["paths"]["data"]
    if ("%s/（含" % concrete) not in rules:
        print("  FAIL  profile 的 unit_source 未带具体数据目录 %s/（回放项目布局与领域档不一致）"
              % concrete)
        return (1, 0, 0, 0)
    # 回放口径 = 本任务新增的**实质**断言（通配 forbid/min_bytes 是 paper1 冻结前的旧口径，
    # 单独探测为 INFO，不混进本次假阳控制）
    sub = substantive_view(frag)
    with tempfile.TemporaryDirectory() as td:
        mf = pathlib.Path(td) / "manifest.json"
        mf.write_text(json.dumps(sub, ensure_ascii=False), encoding="utf-8")
        bad = skipped = passed = 0
        for tid in sorted(sub):
            paths = [f["path"] for f in sub[tid]["files"]] + \
                    [j["path"] for j in sub[tid]["json_files"]]
            missing = sorted({p for p in paths if not (project / p).exists()})
            if missing:
                skipped += 1
                print("  SKIP  %-34s 该档无此产物：%s" % (tid, "、".join(missing[:3])))
                continue
            rc, out = run_verify(project, mf, tid)
            if rc == 0:
                passed += 1
                print("  PASS  %s" % tid)
            else:
                bad += 1
                print("  FAIL  %-34s rc=%d\n        %s"
                      % (tid, rc, out.strip().replace("\n", " | ")[:400]))
        print("  实质断言回放：PASS=%d FAIL=%d SKIP=%d（共 %d 个实质任务）"
              % (passed, bad, skipped, len(sub)))
    hits = []
    for tid, e in frag.items():
        for f in e.get("files", []):
            if any(k in f for k in FILE_SUBSTANTIVE) or not f.get("forbid"):
                continue
            p = project / f["path"]
            if not p.exists():
                continue
            body = p.read_text(encoding="utf-8-sig", errors="replace")
            hits += ["%s: %s" % (f["path"], m) for m in f["forbid"] if m in body]
    print("  INFO  通配 forbid 在真实产物命中 %d 处%s"
          % (len(hits), ("：" + "、".join(hits[:4]) + ("…" if len(hits) > 4 else ""
               if hits else "")) if hits else ""))
    return ((1, passed, bad, skipped) if bad else (0, passed, bad, skipped))


# ── 守卫 7b：合成最小项目根回放（R5 round4 R4-5，E-7 拾遗）──────────────────────
# 病灶：133 条 verify_command 无一条带 --project，真项目结构回归只在自测面补偿，
# 且补偿依赖本机引擎在盘（克隆面 SKIP）——任务门禁面零覆盖。本守卫把真项目面做成
# **自含合成根**：tmp 内离线生成合规产物，走**同一** run_project_replay 真路径回放
# （非复刻判定），全程无引擎/无网络/无 paper1 实况依赖。长效点：
#   ① 产物行数取**实时** frag 区间中位（非硬编码），阈值再换算仍绿；
#   ② 反向对照走产物侧违反（截短引言）与空根 SKIP 语义双向锁定；
#   ③ 历史 133 条门禁不动——覆盖由本守卫所在 78 自测的门禁执行承担（本任务门禁即跑 78）。
_SYNTH_TASKS = ("task-write-introduction", "task-write-conclusion-abstract",
                "task-assemble-draft")


def _synth_body_lines(path: str, frag: dict) -> int:
    """该产物路径在 frag 中的首个 word_count 区间中位（无则回退 50）。"""
    for tid, e in frag.items():
        for f in e.get("files", []) or []:
            if f.get("path") == path and isinstance(f.get("word_count"), list):
                lo, hi = f["word_count"]
                return (lo + hi) // 2
    return 50


def _build_synth_root(root: pathlib.Path, frag: dict) -> None:
    """tmp 内生成最小合规项目根（只写 5 个产物 + 20-lit 标记）。"""
    (root / "20-lit").mkdir(parents=True, exist_ok=True)
    (root / "30-manuscript" / "sections").mkdir(parents=True, exist_ok=True)
    n_intro = _synth_body_lines("30-manuscript/sections/31-introduction.md", frag)
    (root / "30-manuscript" / "sections" / "31-introduction.md").write_text(
        "\n".join("Introduction background statement number %d with context [1]." % i
                  for i in range(n_intro)) + "\n", encoding="utf-8")
    n_abs = _synth_body_lines("30-manuscript/30-abstract.md", frag)
    (root / "30-manuscript" / "30-abstract.md").write_text(
        "\n".join("Abstract purpose and method sentence number %d." % i
                  for i in range(n_abs)) + "\n", encoding="utf-8")
    n_con = _synth_body_lines("30-manuscript/sections/34-conclusion.md", frag)
    (root / "30-manuscript" / "sections" / "34-conclusion.md").write_text(
        "\n".join("Conclusion finding restatement number %d." % i
                  for i in range(n_con)) + "\n", encoding="utf-8")
    n_draft = _synth_body_lines("30-manuscript/36-draft.md", frag)
    (root / "30-manuscript" / "36-draft.md").write_text(
        "**Fig. 1.** results\n**Fig. 2.** results\n"
        + "\n".join("word " * 10 for _ in range(n_draft)) + "\n", encoding="utf-8")
    (root / "30-manuscript" / "37-references.md").write_text(
        "\n".join("[%d] Author. Title. Journal. DOI:10.1/x" % i for i in range(1, 26)),
        encoding="utf-8")


def run_synthetic_project_replay() -> int:
    print("== 合成最小项目根回放（自含真项目面，离线）==")
    bad = 0
    try:
        frag, _, _, _, _ = gen(PROFILES / "10-materials-chemistry.yaml")
    except SystemExit:
        print("  MISMATCH materials 档生成失败（合成根无真源）")
        return 1
    with tempfile.TemporaryDirectory() as td:
        root = pathlib.Path(td)
        _build_synth_root(root, frag)
        rc, passed, failed, skipped = run_project_replay(root)
        ok = rc == 0 and failed == 0 and passed >= len(_SYNTH_TASKS)
        print("  合成根回放：rc=%d PASS=%d FAIL=%d SKIP=%d（目标任务 %d 个）  %s"
              % (rc, passed, failed, skipped, len(_SYNTH_TASKS),
                 "OK" if ok else "MISMATCH"))
        if not ok:
            bad += 1
        # 反向对照①：截短引言至下界之下 → 同一真路径必红（漂移可检出，非空转）。
        intro = root / "30-manuscript" / "sections" / "31-introduction.md"
        intro.write_text("Too short.\n", encoding="utf-8")
        rc2, _, failed2, _ = run_project_replay(root)
        rev = rc2 == 1 and failed2 >= 1
        print("  反向对照：合成产物违反断言 → 同一真路径必红  %s"
              % ("OK" if rev else "MISMATCH rc=%d fail=%d" % (rc2, failed2)))
        if not rev:
            bad += 1
    # 反向对照②：空目录（非项目根）→ SKIP 语义 rc=0 不假红（现行 --project 行为锁定）。
    with tempfile.TemporaryDirectory() as td2:
        rc3, p3, f3, _ = run_project_replay(pathlib.Path(td2))
        skip_ok = rc3 == 0 and p3 == 0 and f3 == 0
        print("  反向对照：非项目根输入保持 SKIP（rc=0 不假红）  %s"
              % ("OK" if skip_ok else "MISMATCH rc=%d" % rc3))
        if not skip_ok:
            bad += 1
    return 1 if bad else 0


# ── 守卫 8：token_source 出处白名单（断言词项溯源）────────────────────────────────
# AC 口径（task-assertion-token-provenance）：每条实质断言的**字面词项**（contains /
# require_keys / require_keys_all）必须带 token_source 标注，来源只有三种合法形态——
#   ac / ac:<task-id>  词项出自本档（合并基类后）该任务（或点名任务）的 AC 文本；
#                      跨任务点名用于"库字段出自建库任务 AC"（citation-audit 的 22-refs 字段
#                      出自 task-search-verify-refs / task-lit-fulltext-inventory 的 AC 清单）
#   references/<file>.md:<行号>   词项逐字出自该行（1 基）
#   sections           词项 ∈ 英文分节名枚举（SECTION_ENUM，实证类论文通行分节/后节名）
# 转写键（AC 用中文枚举字段名、断言用英文字段名，如 target_journal←「目标刊」）在值里加
# term 声明源侧词，守卫按 term 校验在场——词项↔词的对应关系由标注显式声明、可审查。
# 判违规：无 source、source 形态非法、来源任务/文件/行不存在、词项（或 term）不在来源
# 文本中、token_source 标注了断言里不存在的词项、无字面词项的条目却带 token_source。
# regex/min_matches/word_count 不在守卫范围：它们没有字面词项，可满足性由 PROBES 探针守卫
# （_regex_cases），阈值出处由各档注释与审查把关（30-cs-ml 档头「阈值的出处纪律」）。
# 守卫只读本档**自己声明**的 verify_assertions_template（标注写在声明处）；无自有条目的
# 纯继承形态随父档（materials）一并受检。
# G-17（2026-10-07 审查）裁定：globs 与 files 的 token_source 口径二选一，选「globs 也进白名单」
# （70 号 _ITEM_KNOWN["globs"] 加 token_source）；本守卫以 TOKEN_SOURCE_SEGS 覆盖三段——globs
# 条目无字面词项，带 token_source 即判冗余标注（反向对照 ⑨⑩），不带则放行。未选「接受差异」，无 [d]。
SECTION_ENUM = frozenset({
    "Abstract", "Introduction", "Background", "Related Work",
    "Materials", "Methods", "Method", "Experimental", "Experimental Section",
    "Characterization", "Results", "Discussion", "Results and Discussion",
    "Conclusion", "Conclusions", "References", "Appendix",
    "Supplementary Material", "Supplementary Materials",
    "Acknowledgements", "Funding",
})
TOKEN_SOURCE_KEYS = ("contains", "require_keys", "require_keys_all")
# G-17：token_source 形状白名单覆盖的三段（与 70 号 _ITEM_KNOWN 同口径，globs 系本任务新纳入）。
# globs 条目无字面词项，故其实质校验恒走「无词项却带标注 → 冗余」分支（见 _ts_item_violations），
# 不带则放行——70 形状层放行键存在，78 出处层只查冗余有无，两层口径一致。
TOKEN_SOURCE_SEGS = ("files", "json_files", "globs")


def _ts_check_token(where: str, tid: str, tok, src, tasks_by_id: dict) -> list:
    """校验单个词项的 source。返回违规清单（空 = 过）。"""
    if not isinstance(tok, str) or not tok.strip():
        return ["%s: 词项 %r 非字符串（形状守卫会拦，此处跳过溯源）" % (where, tok)]
    term = None
    if isinstance(src, dict):
        if set(src) - {"src", "term"} or "src" not in src:
            return ["%s: 词项 %r 的 source 形态非法 %r（需 src[/term] 两键）" % (where, tok, src)]
        term = src.get("term")
        src = src["src"]
    needle = term if term is not None else tok
    if not isinstance(needle, str) or not needle:
        return ["%s: 词项 %r 的 term 非法 %r" % (where, tok, term)]
    if src == "sections":
        if term is not None:
            return ["%s: 词项 %r 的 sections 来源不接受 term（枚举成员即词项本身）" % (where, tok)]
        if tok not in SECTION_ENUM:
            return ["%s: 词项 %r 不在英文分节名枚举" % (where, tok)]
        return []
    if isinstance(src, str) and src.startswith("references/"):
        path, _, ln = src.rpartition(":")
        if not path.startswith("references/") or not ln.isdigit():
            return ["%s: 词项 %r 的 source 形态非法 %r（需 references/<file>.md:<行号>）"
                    % (where, tok, src)]
        f = SKILL_ROOT / path
        lines = f.read_text(encoding="utf-8-sig").splitlines() if f.is_file() else []
        if not lines:
            return ["%s: 词项 %r 的来源文件缺失或为空 %s" % (where, tok, src)]
        i = int(ln)
        if not 1 <= i <= len(lines):
            return ["%s: 词项 %r 的来源行越界 %s（该文件共 %d 行）" % (where, tok, src, len(lines))]
        if needle in lines[i - 1]:
            return []
        return ["%s: 词项 %r（查 %r）不在 %s 该行" % (where, tok, needle, src)]
    if src == "ac" or isinstance(src, str) and src.startswith("ac:"):
        target = tid if src == "ac" else src[3:]
        task = tasks_by_id.get(target)
        if task is None:
            return ["%s: 词项 %r 的 source 指向本档不存在的任务 %r" % (where, tok, target)]
        text = "".join(task.get("ac") or [])
        if needle in text:
            return []
        return ["%s: 词项 %r（查 %r）不在任务 %s 的 AC 文本" % (where, tok, needle, target)]
    return ["%s: 词项 %r 的 source 形态非法 %r（合法：ac | ac:<task> | "
            "references/<file>.md:<n> | sections）" % (where, tok, src)]


def _ts_item_violations(where: str, tid: str, item: dict, tasks_by_id: dict) -> list:
    out = []
    checked = {}
    for key in TOKEN_SOURCE_KEYS:
        vals = item.get(key)
        if vals:
            checked[key] = [v for v in vals if isinstance(v, str)]
    ts = item.get("token_source")
    if not checked:
        if ts is not None:
            out.append("%s: 无字面词项（contains/require_keys*）却带 token_source" % where)
        return out
    if not isinstance(ts, dict):
        out.append("%s: 实质词项 %s 无 token_source（无 source 即违规）" % (where, sorted(checked)))
        return out
    for key, toks in checked.items():
        m = ts.get(key)
        if not isinstance(m, dict):
            for t in toks:
                out.append("%s: %s 词项 %r 无 source" % (where, key, t))
            continue
        for t in toks:
            if m.get(t) is None:
                out.append("%s: %s 词项 %r 无 source" % (where, key, t))
                continue
            out += _ts_check_token(where, tid, t, m[t], tasks_by_id)
    for key, m in ts.items():
        if key not in TOKEN_SOURCE_KEYS:
            out.append("%s: token_source 键 %r 不是字面词项断言键（合法：%s）"
                       % (where, key, "/".join(TOKEN_SOURCE_KEYS)))
            continue
        if not isinstance(m, dict):
            continue
        for t in m:
            if t not in checked.get(key, []):
                out.append("%s: token_source 标注了断言中不存在的词项 %r（%s）" % (where, t, key))
    return out


def merged_template(prof: pathlib.Path) -> list:
    """**合并后**的 verify_assertions_template（B8：含继承档注入的实质断言与 token_source）。

    旧口径读 `yaml_template(prof)`（本档未合并 raw），子档继承来的标注被静默跳过——
    本守卫对继承面零覆盖。
    """
    prof_obj = _load_profile_safe(prof)
    if prof_obj is None:
        return []            # B05b：档含重键（已点名）→ 空模板，不中止
    return prof_obj.get("verify_assertions_template") or []


def token_source_violations(prof: pathlib.Path, template_override=None) -> list:
    """本档 token_source 违规清单（空 = 过）。template_override 供反向对照注入变异。"""
    raw = template_override if template_override is not None else merged_template(prof)
    if not raw:
        return []
    merged = _load_profile_safe(prof)
    if merged is None:
        return []            # B05b：档含重键（已点名）→ 跳过，不中止
    tasks_by_id = {t["id"]: t for t in merged["tasks"]}
    out = []
    for a in raw:
        tid = a.get("task", "*")
        if tid == "*":
            continue                      # 通配条目只展开 forbid/min_bytes，无字面词项断言
        for i, item in enumerate(a.get("files") or []):
            where = "%s %s files[%d] %s" % (prof.name, tid, i, item.get("path", "?"))
            out += _ts_item_violations(where, tid, item, tasks_by_id)
        for i, item in enumerate(a.get("json_files") or []):
            where = "%s %s json_files[%d] %s" % (prof.name, tid, i, item.get("path", "?"))
            out += _ts_item_violations(where, tid, item, tasks_by_id)
        for i, item in enumerate(a.get("globs") or []):
            # G-17：globs 条目无字面词项——不带 token_source 时 _ts_item_violations
            # 直接放行（checked 空且 ts 无）；带则判冗余标注（与无词项 files 条目同口径）。
            where = "%s %s globs[%d] %s" % (prof.name, tid, i, item.get("pattern", "?"))
            out += _ts_item_violations(where, tid, item, tasks_by_id)
    return out


def _ts_annotated_count(raw: list) -> int:
    n = 0
    for a in raw:
        for seg in TOKEN_SOURCE_SEGS:
            for item in (a.get(seg) or []):
                ts = item.get("token_source")
                if isinstance(ts, dict):
                    n += sum(len(v) for v in ts.values() if isinstance(v, dict))
    return n


def _ts_first_annotated(raw: list):
    for a in raw:
        for seg in TOKEN_SOURCE_SEGS:
            for item in (a.get(seg) or []):
                ts = item.get("token_source")
                if isinstance(ts, dict) and ts:
                    return a, seg, item
    return None, None, None


def run_token_source_guards() -> int:
    print("== token_source 出处白名单（词项溯源）==")
    bad = 0
    total = 0
    zero_profiles = []
    for prof in domain_profiles():
        n = _ts_annotated_count(merged_template(prof))     # B8：读**合并后**模板（含继承注入）
        total += n
        if n == 0:
            zero_profiles.append(prof.name)
        v = token_source_violations(prof)
        print("  %-28s 标注词项=%-3d 违规=%d %s"
              % (prof.name, n, len(v), "OK" if not v else "MISMATCH"))
        for msg in v[:8]:
            print("      MISMATCH %s" % msg)
        if v:
            bad += 1
    if total == 0:
        print("  MISMATCH 四档零标注——出处白名单机检未落地（无 source 即违规的口径未生效）")
        bad += 1
    # B8 基数断言：每个在盘领域档的**合并后**模板都须含标注（继承面不得静默零覆盖）。
    if zero_profiles:
        print("  MISMATCH 领域档合并模板零标注（继承面未覆盖）：%s" % "、".join(zero_profiles))
        bad += 1
    # 反向对照：把 source 指向不含该词的位置 / 摘除标注，守卫必须变红。
    mat = PROFILES / "10-materials-chemistry.yaml"
    raw = yaml_template(mat)
    a0, _, it0 = _ts_first_annotated(raw)
    cases = []
    if it0 is None:
        cases.append(("变异基线：materials 无已标注条目", False, "无"))
    else:
        k0 = next(k for k in it0["token_source"] if isinstance(it0["token_source"][k], dict))
        t0 = next(iter(it0["token_source"][k0]))

        def viol(tpl):
            return token_source_violations(mat, template_override=tpl)

        def first_item(tpl):
            return _ts_first_annotated(tpl)[2]

        t = copy.deepcopy(raw); first_item(t)["token_source"].pop(k0)
        cases.append(("① 删整个 token_source.%s 映射 → 判无 source" % k0, bool(viol(t)), ""))
        t = copy.deepcopy(raw); first_item(t)["token_source"][k0].pop(t0)
        cases.append(("② 删词项 %r 的标注 → 判无 source" % t0, bool(viol(t)), ""))
        sec = next(((a, seg, it, k, tk) for a in raw for seg in TOKEN_SOURCE_SEGS
                    for it in (a.get(seg) or [])
                    for k, m in (it.get("token_source") or {}).items() if isinstance(m, dict)
                    for tk, s in m.items() if s == "sections"), None)
        if sec is None:
            cases.append(("③ sections 词项指错位置：无 sections 标注可变异", False, "无"))
        else:
            _, _, _, sk, stk = sec
            t = copy.deepcopy(raw)
            for a in t:
                for seg in TOKEN_SOURCE_SEGS:
                    for it in (a.get(seg) or []):
                        m = (it.get("token_source") or {}).get(sk)
                        if isinstance(m, dict) and stk in m:
                            m[stk] = "references/30-literature-pipeline.md:1"
            cases.append(("③ sections 词项 %r 指到不含它的行 → 判词项不在场" % stk,
                          bool(viol(t)), ""))
        t = copy.deepcopy(raw); first_item(t)["token_source"][k0][t0] = "sections"
        cases.append(("④ 词项 %r 改标 sections → 判不在枚举" % t0, bool(viol(t)), ""))
        t = copy.deepcopy(raw); first_item(t)["token_source"][k0][t0] = "wiki:词源"
        cases.append(("⑤ 词项 %r 改标未知形态 → 判形态非法" % t0, bool(viol(t)), ""))
        t = copy.deepcopy(raw); first_item(t)["token_source"][k0][t0] = {
            "src": "ac", "term": "绝不存在的词QQ"}
        cases.append(("⑥ 词项 %r 的 term 指到不含它的假词 → 判词项不在场" % t0,
                      bool(viol(t)), ""))
        t = copy.deepcopy(raw); first_item(t)["token_source"][k0]["幽灵词项ZZ"] = "ac"
        cases.append(("⑦ 标注断言里不存在的词项 → 判幽灵标注", bool(viol(t)), ""))
        t = copy.deepcopy(raw)
        plain = next((it for a in t for it in (a.get("files") or [])
                      if it.get("path") and not any(it.get(k) for k in TOKEN_SOURCE_KEYS)), None)
        if plain is None:
            cases.append(("⑧ 无字面词项条目带标注：无可变异对象", False, "无"))
        else:
            plain["token_source"] = {"contains": {"X": "ac"}}
            cases.append(("⑧ 无字面词项条目带标注 → 判冗余标注", bool(viol(t)), ""))
        # ⑨⑩ G-17：globs 正反用例（合成条目，内存，不落盘；在盘模板尚无 globs 条目，
        # 故不用 raw 内变异而用追加合成——变异基线与 ①—⑧ 的 materials 首标注无关）。
        t = copy.deepcopy(raw)
        t.append({"task": a0.get("task", "*"),
                  "globs": [{"pattern": "40-figures/data/*.pdf", "min_count": 1,
                             "token_source": {"contains": {"X": "ac"}}}]})
        cases.append(("⑨ globs 条目带 token_source → 判冗余标注", bool(viol(t)), ""))
        t = copy.deepcopy(raw)
        t.append({"task": a0.get("task", "*"),
                  "globs": [{"pattern": "40-figures/data/*.pdf", "min_count": 1}]})
        cases.append(("⑩ globs 条目无 token_source → 不判（形状层已白名单）",
                      not viol(t), ""))
    for name, ok, _unused in cases:
        print("  %-52s %s" % (name, "OK" if ok else "MISMATCH"))
        if not ok:
            bad += 1
    return 1 if bad else 0


# ── 守卫 9：文档行内任务数与生成器实测一致（task-profiles-catalog-exists-to-listed）──
# 口径：§profiles 表 / README 目录树的档行常以「N 任务」自我描述，档任务数变动
# （继承基类补任务、子档新增任务）时声明值会静默过期——读者据此判断工作量。
# 真源 = 生成器实测（len(gen(档)[0])），不抄数字；未声明任务数的行不参与判定
# （不强制补全口径：三档零数字仍 rc=0）。一行点名多个档时跳过（数字归属不明，
# 强判会误杀）。全文档零声明行 → 判空转失败（否则「删光数字」即可让守卫变摆设）。
# B9（2026-10-07 审查）：单位词放宽——「N 任务 / N 条任务 / N 项任务 / N 个任务」均识别。
TASK_COUNT_DECL = re.compile(r"(\d+)\s*(?:条|项|个)?\s*任务")


def count_violations(doc: str, text: str, counts: dict) -> list:
    """单文档：行内点名**唯一**领域档且声明「N 任务」时，N 须等于生成器实测值。"""
    out = []
    for i, line in enumerate(text.split("\n"), 1):
        m = TASK_COUNT_DECL.search(line)
        if m is None:
            continue
        named = sorted(n for n in counts if n in line)
        if len(named) != 1:
            continue
        got, want = int(m.group(1)), counts[named[0]]
        if got != want:
            out.append("%s:%d 行内声明 %s = %d 任务，生成器实测 %d"
                       % (doc, i, named[0], got, want))
    return out


def doc_task_count_violations(skill_text: str, readme_text: str, counts: dict) -> list:
    return (count_violations("SKILL.md", skill_text, counts)
            + count_violations("README.md", readme_text, counts))


def declared_count_lines(skill_text: str, readme_text: str, counts: dict) -> int:
    """带任务数声明且点名唯一档的行数（空转门禁用）。"""
    n = 0
    for text in (skill_text, readme_text):
        for line in text.split("\n"):
            if TASK_COUNT_DECL.search(line) and len([x for x in counts if x in line]) == 1:
                n += 1
    return n


def declared_profile_names(skill_text: str, readme_text: str, counts: dict) -> set:
    """在任务数声明行里被点名的领域档集合（B9 完备门禁真源）。

    「每个在盘领域档至少一条任务数声明行」——某档一行都没有即漏声明；旧口径只数总行数，
    三档无声明行时仍 rc=0。
    """
    names: set = set()
    for text in (skill_text, readme_text):
        for line in text.split("\n"):
            if TASK_COUNT_DECL.search(line):
                names.update(n for n in counts if n in line)
    return names


def _bump_first_decl(real_text: str, counts: dict) -> tuple:
    """真实文档定向变异：把第一条可定位的「N 任务」改成 N+1（内存，不落盘）。

    返回 (变异后文本, 命中摘要)；无可定位声明返回 (原文, None)。
    """
    for name in sorted(counts):
        decl = "%d 任务" % counts[name]
        if decl in real_text:
            return (real_text.replace(decl, "%d 任务" % (counts[name] + 1)),
                    "%s %d→%d" % (name, counts[name], counts[name] + 1))
    return real_text, None


def run_task_count_guards() -> int:
    print("== 文档任务数一致性（行内声明 vs 生成器实测）==")
    counts = {p.name: len(gen(p)[0]) for p in domain_profiles()}   # gen 已缓存，零重跑
    skill = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8-sig")
    readme = (SKILL_ROOT / "README.md").read_text(encoding="utf-8-sig")
    declared = declared_count_lines(skill, readme, counts)
    violations = doc_task_count_violations(skill, readme, counts)
    bad = 0
    print("  实测档任务数：%s" % "、".join("%s=%d" % (k, v) for k, v in sorted(counts.items())))
    print("  带任务数声明的行 %d 条、与实测不符 %d 条  %s"
          % (declared, len(violations),
             "OK" if declared and not violations else "MISMATCH"))
    for v in violations:
        print("      MISMATCH %s" % v)
    if violations:
        bad += 1
    if declared == 0:
        print("      MISMATCH 两文档零任务数声明行：守卫空转（声明全删也不会报）")
        bad += 1
    # B9 完备门禁：每个在盘领域档至少一条任务数声明行。
    declared_names = declared_profile_names(skill, readme, counts)
    missing_decl = sorted(set(counts) - declared_names)
    print("  已声明档 %d/%d，缺声明档：%s  %s"
          % (len(declared_names), len(counts), "、".join(missing_decl) or "无",
             "OK" if not missing_decl else "MISMATCH"))
    if missing_decl:
        print("      MISMATCH 领域档缺任务数声明行（完备门禁）：%s" % "、".join(missing_decl))
        bad += 1

    # 反向对照（内存文本变异，不落盘）：真实文档改错必红 / 未声明行不参与 / 多档行不强判
    skill_mut, hit_skill = _bump_first_decl(skill, counts)
    readme_mut, hit_readme = _bump_first_decl(readme, counts)
    if hit_readme is not None:
        real_v, hit = doc_task_count_violations(skill, readme_mut, counts), hit_readme
    else:
        real_v, hit = doc_task_count_violations(skill_mut, readme, counts), hit_skill
    syn = dict.fromkeys(sorted(counts), 3)
    names = sorted(syn)
    syn_over = doc_task_count_violations(
        "| `profiles/%s` | 档，4 任务 |" % names[0],
        "│   ├── %s   档（3 任务）" % names[-1], syn)
    syn_plain = doc_task_count_violations(
        "| `profiles/%s` | 档（未写数字） |" % names[0],
        "│   ├── %s   档（未写数字）" % names[-1], syn)
    syn_multi = doc_task_count_violations(
        "| `profiles/%s` 与 `profiles/%s` 共 9 任务 |" % (names[0], names[1]), "", syn)
    # B9：单位词放宽识别——「3 条任务 / 3 个任务」按 3 判（不报）；「4 项任务」对实测 3 变红。
    unit_ok = not doc_task_count_violations(
        "| `profiles/%s` | 档，3 条任务 |" % names[0],
        "│   ├── %s   档（3 个任务）" % names[-1], syn)
    unit_bad = doc_task_count_violations(
        "| `profiles/%s` | 档，4 项任务 |" % names[0], "", syn)
    ctrl = [
        ("真实文档改错声明值（%s）恰好一处变红" % (hit or "无可变异声明"),
         len(real_v) == 1 and hit is not None),
        ("未改动的行不报（无数字的两行同步比对）", not syn_plain),
        ("一行点名多档时不强判（数字归属不明）", not syn_multi),
        ("B9 单位词识别（3 条/3 个任务不报；4 项任务变红）",
         unit_ok and len(unit_bad) == 1),
    ]
    # B9 反向对照：删掉某档的声明行 → 该档从已声明集合消失（完备门禁必红）。
    dropped = None
    for line in (skill + "\n" + readme).split("\n"):
        if TASK_COUNT_DECL.search(line):
            hit_n = [n for n in counts if n in line]
            if hit_n:
                dropped = hit_n[0]
                break
    if dropped:
        s2 = "\n".join(l for l in skill.split("\n")
                       if not (TASK_COUNT_DECL.search(l) and dropped in l))
        r2 = "\n".join(l for l in readme.split("\n")
                       if not (TASK_COUNT_DECL.search(l) and dropped in l))
        ctrl.append(("删掉档 %s 的声明行 → 完备门禁点名缺失" % dropped,
                     dropped not in declared_profile_names(s2, r2, counts)))
    else:
        ctrl.append(("B9 反向对照基线：无声明行可删", False))
    for name, ok in ctrl:
        print("  %-52s %s" % (name, "OK" if ok else "MISMATCH"))
        if not ok:
            bad += 1
    if not syn_over:
        print("      MISMATCH 合成负例未变红（改错 4 vs 实测 3 却通过）→ 守卫是摆设")
        bad += 1
    return 1 if bad else 0


# B01（round3 元守卫改行为级）：守卫段接线**单一真源** + 段数棘轮 + 段头自证 + 控制行自证。
# main() 遍历本表分发（不再散列调用点）：删任一段即 _SEGMENT_COUNT 棘轮变红；段体掏空（不产
# 任何 OK/MISMATCH/FAIL 判定行）或段头漂移（不出现声明标签）同样变红——不再"删一行照打 PASS"。
_SEGMENT_COUNT = 16
_SEGMENTS = [
    ("实质断言下限", run_floor_guards),
    ("断言形状守卫", run_shape_guards),
    ("下限断言逃生门守卫", run_floor_escape_guards),
    ("下限清单棘轮", run_floor_snapshot_guards),
    ("word_count 量纲对账", run_wordcount_dimension_guards),
    ("规格一致性", run_spec_guards),
    ("AC 引用路径方向守卫", run_ac_path_guards),
    ("死策略键守卫", run_dead_policy_key_guards),
    ("链上产物读者守卫", run_chain_reader_guards),
    ("正反控制", run_synth_guards),
    ("反向对照", run_reverse_guards),
    ("deep_merge 子档-only inject", run_deep_merge_guards),
    ("unit_source 占位与解析", run_unit_source_guards),
    ("token_source 出处白名单", run_token_source_guards),
    ("文档任务数一致性", run_task_count_guards),
    ("合成最小项目根回放", run_synthetic_project_replay),
]


class _Tee:
    """Python 级 stdout 双写（真实 stdout + 缓冲）；子进程输出走真实 fd 不受影响，控制台顺序不变。

    缓冲供 :func:`_segment_selfcheck` 做段头/控制行的**行为级**自证（B01）。
    """

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
    """段头自证（预期 == 实际）+ 行为级控制行自证 + 段数棘轮；返回违规条数。"""
    bad = 0
    for label, start, end in marks:
        chunk = buf_text[start:end]
        headers = _HEADER_RE.findall(chunk)
        if not any(label in h for h in headers):
            print("  MISMATCH 段 %s 未打出声明段头（实际 %s）" % (label, headers))
            bad += 1
        body = [ln for ln in chunk.splitlines() if ln.strip() and not _HEADER_RE.match(ln)]
        if not body:
            print("  MISMATCH 段 %s 除段头外零输出（段体被掏空=死守卫）" % label)
            bad += 1
    if len(_SEGMENTS) != _SEGMENT_COUNT:
        print("  MISMATCH 段数棘轮：_SEGMENTS=%d ≠ 基线 %d（增删段必须同步基线）"
              % (len(_SEGMENTS), _SEGMENT_COUNT))
        bad += 1
    return bad


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", help="真实论文项目根（假阳控制回放，只读）")
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
            rr, _, _, _ = run_project_replay(pathlib.Path(a.project).resolve())
            rc |= rr
    rc |= 1 if _segment_selfcheck(buf.getvalue(), marks) else 0
    print("\nSELFTEST %s" % ("PASS" if rc == 0 else "FAIL"))
    return rc


if __name__ == "__main__":
    sys.exit(main())
