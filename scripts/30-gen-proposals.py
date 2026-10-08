#!/usr/bin/env python3
"""30-gen-proposals.py — 域档（profile）→ orchd 原生投喂物。

产出（默认写入 <out>/）：
  proposals/task-<id>.json        单任务提案（字段与 orchd `amend --register` 逐字对齐）
  _master.fragment.json           {project, modules, tasks} 片段，可并入 _master.json
  rules.fragment.md               域口径规则片段（evidence_policy → 可读规则）+ profile
                                  `fragments:` 声明的 static/ 碎片原样注入（未声明则零改动）
  verify_manifest.fragment.json   本域建议的 verify 断言（按任务分组）

用法（三条旗标形态与 argparse 一致，改 CLI 必同步此处，守卫见 75-verify-selftest.py）：
  python -X utf8 30-gen-proposals.py --profile profiles/10-materials-chemistry.yaml --out ./build
  python -X utf8 30-gen-proposals.py --profile profiles/<x>.yaml --check --project <目标项目>    # 生成 master 并跑 orchd validate
  python -X utf8 30-gen-proposals.py --profile profiles/<x>.yaml --regress --project <目标项目>  # 与该项目真实任务结构对比

`--check` 与 `--regress` 都必须同时给 `--project`：二者是"对某个真实项目核对"的动作，缺项目时无从核对。
曾的做法是 `if a.project:` 把整段跳过 → 缺 `--project` 时 rc=0 静默走 emit 写出 `--out`（默认 `./build/`），
门禁现场看起来像"跑过了"（2026-09-26 审查 N-4 实测 M6）。现在缺 `--project` 归 rc=2 且先拒后写，不落生成物。

设计约束（全部来自引擎实测，违反即被拒）：
  1. `source` 必须匹配 ^(idea|roadmap|debug):[a-z0-9-]+$ —— 本脚本用 `debug:<profile>-v<version>`；
     技能名不能直接出现在 source 里（E003）。
  2. 注册期禁目录式/通配符声明：read/edit 必须是具体文件路径，不得以 "/" 结尾。
  3. 单任务 files_to_edit ≤5（超出触发 E029 告警）；确需超出者在 profile 里显式登记 exceptions。
  4. AC 仅 pending 可改，故生成即须可判定：每条 AC 必须提到具体产物路径或可机检口径。
  5. B13 生成器形态档（build 入口集中）：任务四键 read/edit/inject/ac 須 list、
     read 項須 dict 含非空 path、edit 項須真實路徑形態（非空串、无尾随 `/`、无 `*`），
     profile 顶层 axes 键须在闭集内且取值须在已知词汇内；违规记 problems（[shape]
     前缀 → CLI rc=2）并点名 `档:任务:键`。
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

import yaml

SCHEMA_SOURCE = re.compile(r"^(idea|roadmap|debug):[a-z0-9-]+$")
AC_ARTIFACT = re.compile(r"(`[^`]+\.(md|json|py|csv|toml|yaml|tex|bib|pdf)`|\d\d-[a-z]+/|"
                         r"70-tools/|\d\d-[a-z]+\.(py|json|md))")
CHECKABLE = re.compile(r"(不得|须|必须|一致|逐条|覆盖|字段|标注|零占位符|可回指|可判定|写明|"
                       r"区间|上限|下限|无重复|一一对应|显式|禁止|至少|不得超出)")
# B6：本 skill 的稿件是英文稿，AC 允许英文表述；CHECKABLE 只含中文词会把
# language: en 轴的合法 AC（must/only/at least…）一律误拒。词表只收**硬约束词**，
# 不收形近虚词（with/within 类由 at most/between 等限定短语覆盖），避免模糊句被误放行；
# 用 \b 定界防止 "must" 命中 "adjust" 之类子串。
CHECKABLE_EN = re.compile(
    r"\b(must|shall|required|only|at least|at most|no more than|no fewer than|"
    r"no less than|no greater than|no later than|no earlier than|between|"
    r"exactly|consisten\w*|identical|match(?:es|ed)?|cover(?:s|ed|age)?|"
    r"explicitly?|forbid(?:den)?|prohibit(?:ed)?|absent|"
    r"unique|continuous|unambiguous|verifiable|reproducib\w+|traceab\w+)\b", re.I)


def die(msg: str) -> None:
    print("ERROR: %s" % msg)
    sys.exit(2)


# ---------- 判据真源防护：YAML 重复键检出（B05，2026-10-07 三轮）------------------
# `yaml.safe_load` 对重复键 **last-wins**：末尾再写一行同键会静默回退前一条，生效值被覆盖而
# 不报错（实测 materials 档误粘旧行 `min_matches:{…,min:20}` → 合规 7 帧项目 rc=1，四套自测全绿）。
# profiles 本体（本函数的 load_profile / load_fragment_manifest）曾漏检，故此处补上；同族成员的
# 穷举守卫见 scripts/76-doc-refs-selftest.py G12。
class ProfileDuplicateKey(yaml.YAMLError):
    """profile（或碎片索引）YAML 映射含重复键。"""


class _NoDuplicateKeyLoader(yaml.SafeLoader):
    """安全加载器 + **任意层级**重复键检出（键名随异常上抛，由 load_* 归 rc=2 点名）。"""

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
                raise ProfileDuplicateKey("重复键 %r" % (key,))
            mapping[key] = self.construct_object(value_node, deep=deep)
        return mapping


def load_yaml_strict(text: str):
    """按重复键检出加载 YAML（B05）：重复键 → ProfileDuplicateKey（键名随异常上抛）。"""
    return yaml.load(text, Loader=_NoDuplicateKeyLoader)


def _merge_path_items(base_items, child_items):
    """按 item['path'] 归并：同名 path 子档覆盖、父档其余保留；无 path 项各自保留。"""
    by_path = {}
    order = []
    passthrough = []
    for it in base_items or []:
        p = it.get("path") if isinstance(it, dict) else None
        if p:
            if p not in by_path:
                order.append(p)
            by_path[p] = it
        else:
            passthrough.append(it)
    for it in child_items or []:
        p = it.get("path") if isinstance(it, dict) else None
        if p:
            if p not in order:
                order.append(p)
            by_path[p] = it
        else:
            passthrough.append(it)
    return passthrough + [by_path[p] for p in order]


def _merge_assertions(base_list, child_list):
    """按条目 task 键归并 verify_assertions_template：同 task 时 files/json_files 按 path 归并，
    其余键子档整体覆盖；子档新增 task 追加、父档其余 task 保留。
    通配条目（task="*"）按 (task, apply_to) 组合键归并，避免不同 apply_to 的通配互相覆盖。"""
    by_key = {}
    order = []
    passthrough = []
    for e in base_list or []:
        if isinstance(e, dict) and "task" in e:
            key = (e["task"], e.get("apply_to"))
            if key not in by_key:
                order.append(key)
            by_key[key] = e
        else:
            passthrough.append(e)
    for e in child_list or []:
        if not (isinstance(e, dict) and "task" in e):
            passthrough.append(e)
            continue
        key = (e["task"], e.get("apply_to"))
        if key not in by_key:
            by_key[key] = e
            order.append(key)
            continue
        parent = dict(by_key[key])
        for k2, v2 in e.items():
            if k2 in ("files", "json_files"):
                parent[k2] = _merge_path_items(parent.get(k2) or [], v2)
            else:
                parent[k2] = v2
        by_key[key] = parent
    return passthrough + [by_key[k] for k in order]


def deep_merge(base: dict, child: dict) -> dict:
    """child 覆盖 base；tasks 按 id 合并（同 id 覆盖、新增追加）；depends 逐键合并。

    tasks 深度合并规则：子档同名任务的 `inject` 列表**追加合并**（去重）——子档只要写了
    `inject` 即生效，父档无 `inject` 键时按空列表处理（deep-merge-child-only-inject）；
    其余字段子档整体覆盖。这样子档（如 paper2）可以只写
    `- id: task-write-results-discussion\n  inject: [impedance_rule]`
    来给继承任务追加学科特有口径，而不必重写整个任务。
    """
    out = dict(base)
    for k, v in child.items():
        if k == "tasks":
            by_id = {t["id"]: t for t in out.get("tasks", [])}
            order = [t["id"] for t in out.get("tasks", [])]
            for t in v:
                if t["id"] in by_id:
                    parent_t = dict(by_id[t["id"]])
                    if "inject" in t:
                        merged_inject = list(parent_t.get("inject") or [])
                        for x in t["inject"]:
                            if x not in merged_inject:
                                merged_inject.append(x)
                        parent_t["inject"] = merged_inject
                    for k2, v2 in t.items():
                        if k2 != "inject":
                            parent_t[k2] = v2
                    by_id[t["id"]] = parent_t
                else:
                    by_id[t["id"]] = t
                    order.append(t["id"])
            out["tasks"] = [by_id[i] for i in order]
        elif k == "depends" and isinstance(v, dict):
            out["depends"] = {**out.get("depends", {}), **v}
        elif k == "verify_assertions_template":
            out[k] = _merge_assertions(out.get(k, []), v)
        elif isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = {**out[k], **v}
        else:
            out[k] = v
    return out


def load_profile(path: Path, _depth: int = 0) -> dict:
    if _depth > 3:
        die("profile extends chain too deep (or cyclic): %s" % path)
    if not path.exists():
        die("profile not found: %s" % path)
    try:
        p = load_yaml_strict(path.read_text(encoding="utf-8-sig"))
    except ProfileDuplicateKey as exc:
        # B05：重复键 last-wins 会静默回退前一条定义（生效值被旧值覆盖）——先于通用 YAMLError
        # 分支点名「档:路径:键」，归 rc=2（判据真源不唯一时不得生成）。
        die("profile %s 含重复键：%s（yaml 默认 last-wins 会静默回退前一条定义，判据生效值被覆盖，"
            "请去重后再生成）" % (_disp(path), exc))
    except yaml.YAMLError as exc:
        die("profile %s: invalid YAML: %s" % (path, exc))
    if not isinstance(p, dict):
        die("profile %s: top-level must be a mapping" % path)
    parent = p.pop("extends", None)
    # F-4（2026-09-29 审查）：顶层档且无 extends = 模板/基类档。该标记供 build() 判定
    # "未知依赖"是预期形态（依赖目标由领域子档补齐）还是真配错，最终不进任何生成物。
    p["_is_template"] = parent is None and _depth == 0
    if parent:
        p = deep_merge(load_profile(path.parent / parent, _depth + 1), p)
    for key in ("id", "modules", "tasks"):
        if key not in p:
            die("profile missing key: %s" % key)
    p.setdefault("version", "1")
    p.setdefault("tool_dir", "scripts")
    p.setdefault("paths", {})
    p.setdefault("evidence_policy", {})
    p.setdefault("verify_assertions_template", [])
    return p


def fill(value, ctx: dict):
    """占位符替换：{admin} {data} {lit} {ms} {fig} {review} {latex} {nb} {tool_dir} {profile}"""
    if isinstance(value, str):
        return value.format(**ctx)
    if isinstance(value, list):
        return [fill(v, ctx) for v in value]
    if isinstance(value, dict):
        return {k: fill(v, ctx) for k, v in value.items()}
    return value


def policy_lines(profile: dict, inject: list, ctx: dict | None = None) -> list:
    """把 evidence_policy 的域口径渲染成 AC 行（只取任务声明的 inject 键）。

    F8（2026-10-07 审查）：注入出的 AC 也须走 `fill()`——否则 evidence_policy 里写的
    `{data}/…`/`{ms}/…` 占位不会展开（旧版只对任务 spec 做 fill），策略文案硬编码
    `10-data/…` 时 inject 出的 AC 就是死路径、绕过 profile 的 paths 口径。
    """
    pol, out = profile["evidence_policy"], []
    for key in inject or []:
        val = pol.get(key)
        if val is None:
            die("task injects unknown evidence_policy key: %s" % key)
        if ctx is not None:
            try:
                val = fill(val, ctx)
            except (KeyError, IndexError, ValueError):
                pass          # 字面花括号：保留原值（与任务 spec 的 fill 失败口径一致，不裸崩）
        if isinstance(val, list):
            out.append("域口径约束：%s。" % "；".join(str(v) for v in val))
        else:
            out.append("域口径约束：%s。" % val)
    return out


def _profile_path_prefixes(profile: dict) -> list:
    """档内已知路径前缀（paths.* 的具体目录 + tool_dir），长者优先。"""
    dirs = {str(v) for v in (profile.get("paths") or {}).values()
            if isinstance(v, str) and v}
    td = profile.get("tool_dir")
    if isinstance(td, str) and td:
        dirs.add(td)
    return sorted(dirs, key=len, reverse=True)


def policy_path_tokens(profile: dict, lines: list) -> list:
    """B08b：域口径注入文案里**路径形态 token**（已知编号目录前缀），按出现序去重。

    只认档内 paths.* 与 tool_dir 的前缀——`RR/OR/HR`、`train/val/test`、
    `significantly/outperforms` 等非路径 token 天然不命中（前缀不在已知集合）。
    """
    prefixes = _profile_path_prefixes(profile)
    if not prefixes:
        return []
    # 路径字符类只收 [A-Za-z0-9._/-]——反引号/ASCII 标点/中日韩标点/空白一律为边界，
    # 避免把 `` `00-admin/x.md` `` 的尾反引号、句末句点、逗号并入路径。
    rx = re.compile(r"(?:%s)/[A-Za-z0-9._/-]*"
                    % "|".join(re.escape(d) for d in prefixes))
    out = []
    for line in lines:
        for m in rx.findall(line):
            tok = m.rstrip(".")          # 句末句点不算路径（`.md` 的 `.` 在中间，不受影响）
            if tok and tok not in out:
                out.append(tok)
    return out


def _fulltext_gate_problems(profile: dict) -> list:
    """B06 收尾：`citation_policy.fulltext_gate.mode` 的**真消费**——声明 strict 就必须有机器门。

    规则：`mode == "strict"` 时，终局任务（`task-finalize-manuscript`，缺则
    `task-presubmit-review`）必须挂一条对 `…/22-refs.json` 的
    `require_values{two_source_verified: true}` 断言（B06b 落地的形态）。缺门即判生成期
    问题并点名 `<档>:<任务>:fulltext_gate.mode=strict`——把「声明 strict 但无门」从
    「渲染进 rules.fragment 的无人读文字」变成机器可拦（review A-5④ 的收尾）。
    无终局任务的档（基类/模板）与 `mode != strict` 的档不适用，返回 []。
    """
    gate = (profile.get("citation_policy") or {}).get("fulltext_gate") or {}
    if gate.get("mode") != "strict":
        return []
    ids = {t.get("id") for t in profile.get("tasks", [])}
    terminal = ("task-finalize-manuscript" if "task-finalize-manuscript" in ids
                else "task-presubmit-review" if "task-presubmit-review" in ids else None)
    if terminal is None:
        return []
    for a in profile.get("verify_assertions_template", []):
        if a.get("task") != terminal:
            continue
        for item in a.get("json_files") or []:
            rv = item.get("require_values") or {}
            if str(item.get("path", "")).endswith("22-refs.json") \
                    and rv.get("two_source_verified") is True:
                return []
    return ["%s: %s:fulltext_gate.mode=strict 但终局任务未挂 `22-refs.json` 的 "
            "require_values{two_source_verified: true} 机器门（声明 strict 必须有门，"
            "否则文献验真在自动化面上仍是装饰）" % (profile.get("id", "?"), terminal)]


def _expand_ctx(profile: dict) -> dict:
    """通配展开用占位符上下文（build/verify_fragment 同源，防两处漂移）。

    与 build() 主循环所用 ctx 同构：paths 口径 + tool_dir/verify_tool/
    verify_manifest/profile 四键。verify_fragment 的 exclude/forbid 展开走此上下文，
    占位符形态（`{ms}/…`）与字面路径同命中。
    """
    ctx = dict(profile.get("paths") or {})
    ctx["tool_dir"] = profile.get("tool_dir")
    # verify 脚本名分两制：新项目 70-tools/70-verify.py（编号规范）；paper1 冻结为 scripts/verify.py
    # （22 条历史 verify_command 不可改），由 profile 的 verify_tool 指定。
    ctx["verify_tool"] = profile.get("verify_tool") or ("%s/70-verify.py" % profile.get("tool_dir"))
    # manifest 名同样分两制：新项目 70-tools/71-verify-manifest.json；paper1 冻结 verify_manifest.json
    ctx["verify_manifest"] = profile_manifest_path(profile)
    ctx["profile"] = profile.get("id")
    return ctx


def _fill_str_list(items, ctx: dict) -> list:
    """对字符串列表逐项走 fill()：占位符展开，字面花括号保留原值不裸崩。

    与 policy_lines 的失败口径一致（KeyError/IndexError/ValueError → 保留原值），
    非字符串项原样透传（形态问题由下游守卫点名，不在此裸崩）。
    """
    out = []
    for it in items or []:
        if isinstance(it, str):
            try:
                out.append(fill(it, ctx))
            except (KeyError, IndexError, ValueError):
                out.append(it)
        else:
            out.append(it)
    return out


def build(profile: dict, project_override: dict | None = None) -> dict:
    ctx = _expand_ctx(profile)
    src = "debug:%s-v%s" % (profile["id"].replace("_", "-"), str(profile["version"]))
    if not SCHEMA_SOURCE.match(src):
        # 设计约束 #1 的机械化：违约的 profile id/version 会经 E003 在注册期才炸，这里前置拒绝。
        die("generated source '%s' violates orchd schema %s" % (src, SCHEMA_SOURCE.pattern))

    deps = profile.get("depends", {})
    tasks, problems = [], []
    problems.extend(_axes_shape_problems(profile))
    seen = set()
    for spec in profile["tasks"]:
        try:
            t = fill(spec, ctx)
        except (KeyError, IndexError, ValueError) as exc:
            # B5：AC/brief 里的字面花括号（JSON/LaTeX 示例）会破坏占位符替换。
            # 报为生成期问题并继续检查其余任务，避免裸 traceback 且不指明任务。
            problems.append("%s: text breaks placeholder fill: %s "
                            "(字面 { } 请双写为 {{ }}，或避免在 AC/brief 中放 JSON/LaTeX 示例)"
                            % (spec.get("id", "?"), exc))
            continue
        tid = t["id"]
        # B13：四键形状集中档——违规记 problems（shape 前缀 → CLI rc=2）并跳过该任务，
        # 避免标量 char-split 落盘或下游裸 TypeError/KeyError/AttributeError。
        shape = _task_shape_problems(profile.get("id", "?"), tid, t)
        if shape:
            problems.extend(shape)
            continue
        # 依赖图集中在 profile 的 depends: 块（便于逐条审阅），任务条目里可覆盖。
        if "depends_on" not in t:
            t["depends_on"] = deps.get(tid, [])
        if tid in seen:
            problems.append("duplicate task id: %s" % tid)
        seen.add(tid)
        if not re.match(r"^task-[a-z0-9-]+$", tid):
            problems.append("bad task id: %s" % tid)

        pol_lines = policy_lines(profile, t.get("inject") or [], ctx)
        ac = list(t.get("ac") or []) + pol_lines
        if len(ac) < 3:
            problems.append("%s: fewer than 3 acceptance criteria" % tid)
        if len(ac) > 6 and not t.get("ac_exception"):
            problems.append("%s: %d acceptance criteria (>6, needs ac_exception)" % (tid, len(ac)))
        # AC 可判定性口径（对齐 paper1 真实 AC 的形态）：
        #   ① 至少一条 AC 锚定具体产物路径；② 至少一条 AC 给出可判定约束（不得/须/一致/逐条/覆盖…）。
        # 不要求每条 AC 都带路径——真实的 AC 里大量是行为与口径约束。
        if not any(AC_ARTIFACT.search(a) for a in ac):
            problems.append("%s: no AC anchors a concrete artifact path" % tid)
        if not any(CHECKABLE.search(a) or CHECKABLE_EN.search(a) for a in ac):
            problems.append("%s: no AC states a checkable constraint" % tid)

        edit = list(t.get("edit") or [])
        if not edit:
            problems.append("%s: empty files_to_edit" % tid)
        if len(edit) > 5 and not t.get("fte_exception"):
            problems.append("%s: %d files_to_edit (>5, needs fte_exception)" % (tid, len(edit)))
        # files_to_read 允许目录与通配符（paper1 实际即用 `data/`、`../data/*.csv`）。
        # files_to_edit 的目录式/通配符检查已收口进 _task_shape_problems（B13，同归 shape）。
        # B08b：域口径注入文案里的路径形态 token 自动并入该任务 read（一处集中，免逐档手写；
        # 幂等去重——已声明的路径不重复登记）。
        read = list(t.get("read") or [])
        known_paths = {r.get("path") for r in read if isinstance(r, dict)} | set(edit)
        for p in policy_path_tokens(profile, pol_lines):
            if p not in known_paths:
                read.append({"path": p, "priority": "reference",
                             "hint": "域口径注入点名（B08b 自动并入）"})
                known_paths.add(p)
        try:
            verify_cmd = t["verify"].format(**ctx)
        except (KeyError, IndexError, ValueError) as exc:
            problems.append("%s: format error in verify: %s" % (tid, exc))
            continue
        if not re.match(r"^python \S+ task-%s$" % re.escape(tid[5:]), verify_cmd):
            problems.append("%s: verify_command must be 'python <script> %s'" % (tid, tid))

        tasks.append({
            "id": tid,
            "name": t["name"],
            "brief": t["brief"],
            "module": t["module"],
            "depends_on": sorted(set(t.get("depends_on", []))),
            "estimated_hours": t.get("hours", 2),
            "difficulty": t.get("difficulty", "medium"),
            "requires": t.get("requires", ["python"]),
            "acceptance_criteria": ac,
            "files_to_read": [{"path": r["path"], "priority": r.get("priority", "must_read"),
                               "hint": r.get("hint", "")} for r in read],
            "files_to_edit": edit,
            "exempt_files": [],
            "verify_command": verify_cmd,
            "source": src,
            "stage": t.get("stage", ""),
        })

    entry_mode = profile.get("entry", {}).get("mode", "data-first")
    # multi-paper 模式才激活 P-1 资产规划任务；其余模式它不进任务图。
    # inherited 模式不额外过滤任务——它的差异在于 audit-data 的 AC 来源
    # （外部路线图已给定故事线），由领域 profile 在任务 AC 里体现，不在这里删任务。
    if entry_mode != "multi-paper":
        tasks = [t for t in tasks if t["id"] != "task-data-asset-mapping"]
    else:
        # N-10：P-1 注入只挂在 task-audit-data 上。该任务被领域档删掉时，注入循环静默零命中，
        # P-1 仍进任务图却无人依赖（生成期 problems 也抓不到——它不依赖任何未知任务），
        # 注册出去就是一个孤儿前置任务。故在注入点显式校验这条假设。
        if not any(t["id"] == "task-audit-data" for t in tasks):
            problems.append("entry.mode=multi-paper 需要 task-audit-data 承载 P-1 注入："
                            "该任务不在任务图里，task-data-asset-mapping 将成为无人依赖的孤儿前置")
        for t in tasks:
            if t["id"] == "task-audit-data" and "task-data-asset-mapping" not in t["depends_on"]:
                t["depends_on"].append("task-data-asset-mapping")
                t["depends_on"] = sorted(set(t["depends_on"]))

    # inherited 模式：P-1 路线图已定故事线，任务按路线图方向执行，不重复探索。
    if entry_mode == "inherited":
        # F8（2026-10-06 审查）：分析任务名按档改名（analyze-data/outcomes/survey/baselines），
        # 硬编码单任务名会让 inherited 对 clinical/social/cs-ml 静默不注入方向约束。
        # 改为按 `task-analyze-` 前缀从任务图内探测；锚不定（0 个或多个）显式报 problems。
        direction = {
            "task-audit-data": "按 `{admin}/07-paper-roadmap.md` 指定的数据子集逐值核对，不盘点全量数据。",
            "task-claim-map": "按 `{admin}/07-paper-roadmap.md` 指定的 claim 建需求单，不空泛收敛研究问题。",
        }
        analyze_ids = sorted(t["id"] for t in tasks if t["id"].startswith("task-analyze-"))
        if len(analyze_ids) != 1:
            problems.append(
                "entry.mode=inherited 需要恰好一个 task-analyze-* 承载方向约束：实测 %s"
                % (analyze_ids or "无"))
        for tid in analyze_ids:
            direction[tid] = "按 `{admin}/07-paper-roadmap.md` 指定的故事线定量分析，不探索其他方向。"
        for t in tasks:
            hint = direction.get(t["id"])
            if hint:
                t["acceptance_criteria"].append(hint.format(**ctx))

    ids = {t["id"] for t in tasks}
    unknown = [(t["id"], d) for t in tasks for d in t["depends_on"] if d not in ids]
    if unknown and profile.get("_is_template"):
        # F-4（2026-09-29 审查）：基类/模板档单独生成——其任务的 depends_on 指向仅在
        # 领域子档中定义的任务（实测：task-back-matter → task-finalize-manuscript），
        # 属 extends 机制的预期形态而非配错。给出定位诊断并整档拒绝（rc=2 用法错），
        # 不再以 rc=1「depends_on unknown task」收场让使用者猜。_is_template 由
        # load_profile 标注（顶层且无 extends），不进任何生成物。
        sample_tid, sample_dep = unknown[0]
        die("profile '%s' 是 extends 模板（基类）：其任务依赖仅在领域子档定义的任务"
            "（如 %s → %s，共 %d 处未知依赖）。请改用领域子档生成（子档 extends 本档），"
            "或对子档跑 --check / --regress 做整体核对"
            % (profile["id"], sample_tid, sample_dep, len(unknown)))
    for tid, d in unknown:
        problems.append("%s: depends_on unknown task %s" % (tid, d))

    project = dict(profile.get("project", {}))
    if project_override:
        project.update(project_override)
    master = {
        "schema_version": 1,          # 必须是整数（schema: "1.0" 被拒）
        "project": project,
        "modules": [{"id": m["id"], "name": m["name"], "role": m["role"]}
                    for m in profile["modules"]],
        "tasks": [{k: v for k, v in t.items() if k != "stage"} for t in tasks],
    }
    problems += _fulltext_gate_problems(profile)
    return {"tasks": tasks, "master": master, "problems": problems, "source": src}


def _render_scalar(v) -> str:
    """把 policy 值渲染成可读文本（dict/list 递归展平，避免 Python repr）。"""
    if isinstance(v, dict):
        return "；".join("%s=%s" % (k, _render_scalar(x)) for k, x in v.items())
    if isinstance(v, list):
        return "；".join(_render_scalar(x) for x in v)
    return str(v)


# ---------- 规则碎片：static/manifest.yaml + static/<轴值>-<主题>.md ----------
# 规格真源 references/60-capability-specs.md §3：声明才注入、未声明零回归（连 manifest 都不读）、
# 未知 id 即 die、注入正文原样不折叠。axes 只做一致性提示，自动匹配不是本能力的激活路径。

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
FRAGMENT_AXES_KEYS = {"paper_type", "evidence_form", "publisher",
                      "citation_style", "language", "reporting"}

# B13（2026-10-08）：build 入口集中形態檔。
# profile 顶层 axes 各轴的已知合法取值（由在盘 4 档 + 碎片索引的实际取值收敛；
# 新增合法值时在此登记——未知值一律按"拼错"归 shape problems → rc=2）。
# 注意与碎片 mismatch warn 的分工：此表拦的是"真错"（拼错/未知值），而档内合法特化
# （如已删档 wbpu 的 lab-experimental-with-eis：删档前的档内合法特化，值仍在表内、保持绿）。
PROFILE_AXES_VALUES = {
    "paper_type": {"research-article"},
    "evidence_form": {"lab-experimental", "lab-experimental-with-eis",
                      "clinical-study", "survey-observational",
                      "computational-study"},
    "publisher": {"elsevier", "acm"},
    "citation_style": {"numbered"},
    "language": {"en"},
    "reporting": {"consort", "strobe", "reproducibility-checklist"},
}

# 形态类 problems 的统一前缀：main() 据此前缀把"用法错"判成 rc=2（内容类 problems
# 仍 rc=1）；消息本体按 `档:任务:键` 点名。
SHAPE_PREFIX = "[shape]"


def _task_shape_problems(profile_id: str, tid: str, t: dict) -> list:
    """B13：单任务四键（read/edit/inject/ac）的形状集中校验。

    拦三类真错（A-11 实锤）：① 四键須 list——标量在此前经 `list(v)` 会 char-split
    （edit 短标量无声落盘成单字文件表）或在下游 `r["path"]` 抛裸 TypeError；
    ② read 項須 dict 含非空 path 字符串（缺键此前抛裸 KeyError）；③ edit 項須
    真實路徑形態（非空串、无尾随 `/`、无 `*`）。缺键/显式 null 按省略处理（下游
    内容检查照旧报 empty/ac 不足，不在此升级），只拦"写了但写错"。
    返回 problems 条目（调用方 extend 后跳过该任务，避免级联裸崩）。
    """
    out = []
    for key in ("read", "edit", "inject", "ac"):
        v = t.get(key)
        if v is None:
            continue                  # 缺键/显式 null = 省略，下游内容检查照旧
        if not isinstance(v, list):
            out.append("%s %s:%s:%s 须是列表（实际类型 %s）——标量会被 list() 逐字拆散"
                       % (SHAPE_PREFIX, profile_id, tid, key, type(v).__name__))
            continue
        if key == "read":
            for i, it in enumerate(v):
                if not isinstance(it, dict) or not isinstance(it.get("path"), str) \
                        or not it.get("path").strip():
                    out.append("%s %s:%s:read[%d] 须是含非空 path 字符串的映射（实际 %r）"
                               % (SHAPE_PREFIX, profile_id, tid, i, it))
        elif key == "edit":
            for i, it in enumerate(v):
                if not isinstance(it, str) or not it.strip():
                    out.append("%s %s:%s:edit[%d] 须是非空路径字符串（实际类型 %s）"
                               % (SHAPE_PREFIX, profile_id, tid, i, type(it).__name__))
                elif it.endswith("/") or "*" in it:
                    # 原分散在 build 主循环的目录/通配符检查收口至此（同为"非真实
                    # 路径形态"，与类型错同归 shape → rc=2）。
                    out.append("%s %s:%s:edit[%d] 非真实路径形态"
                               "（目录式/通配符不得进 files_to_edit）：%s"
                               % (SHAPE_PREFIX, profile_id, tid, i, it))
        elif key == "inject":
            for i, it in enumerate(v):
                if not isinstance(it, str) or not it.strip():
                    out.append("%s %s:%s:inject[%d] 须是非空口径键字符串（实际 %r）"
                               % (SHAPE_PREFIX, profile_id, tid, i, it))
        elif key == "ac":
            for i, it in enumerate(v):
                if not isinstance(it, str):
                    out.append("%s %s:%s:ac[%d] 须是字符串（实际类型 %s）"
                               % (SHAPE_PREFIX, profile_id, tid, i, type(it).__name__))
    return out


def _axes_shape_problems(profile: dict) -> list:
    """B13 B-7：profile 顶层 axes 的形状与取值校验（build 入口一处集中）。

    拦三类：① axes 本体須映射；② 轴键须在 FRAGMENT_AXES_KEYS 闭集内（拼错键此前
    被 _axes_mismatch 静默跳过）；③ 轴值須标量/标量列表且落在 PROFILE_AXES_VALUES
    词汇内（拼错值此前只在 emit 期打 warn、不改退出码——B-7 改为 rc=2）。
    未声明 axes 的档（基类/合成档）不适用，返回 []。空列表值 = 该轴不适用，不校验。
    """
    pid = profile.get("id", "?")
    axes = profile.get("axes")
    if axes is None:
        return []
    if not isinstance(axes, dict):
        return ["%s %s:axes 须是映射（实际类型 %s）"
                % (SHAPE_PREFIX, pid, type(axes).__name__)]
    out = []
    for key in sorted(axes, key=str):
        if key not in FRAGMENT_AXES_KEYS:
            out.append("%s %s:axes:%s 未知轴键（允许：%s）"
                       % (SHAPE_PREFIX, pid, key, sorted(FRAGMENT_AXES_KEYS)))
            continue
        v = axes[key]
        vals = v if isinstance(v, list) else [v]
        if not isinstance(v, list) and not isinstance(v, str):
            out.append("%s %s:axes:%s 轴值须是字符串或字符串列表（实际类型 %s）"
                       % (SHAPE_PREFIX, pid, key, type(v).__name__))
            continue
        for x in vals:
            if not isinstance(x, str) or not x.strip():
                out.append("%s %s:axes:%s 轴值须是非空字符串（实际 %r）"
                           % (SHAPE_PREFIX, pid, key, x))
            elif x not in PROFILE_AXES_VALUES.get(key, set()):
                out.append("%s %s:axes:%s=%s 未知轴值（允许：%s）——拼错请修正，"
                           "合法新值请在 PROFILE_AXES_VALUES 登记"
                           % (SHAPE_PREFIX, pid, key, x,
                              sorted(PROFILE_AXES_VALUES.get(key, set()))))
    return out


def _disp(path: Path) -> str:
    """诊断里的路径只取末两段（`static/manifest.yaml`）：STATIC_DIR 由 __file__ 推出，
    整条回显会把本机绝对路径写进出生输出（40 号脚本同口径，CHANGELOG D-14 同族）。"""
    return "/".join(path.parts[-2:])


def load_fragment_manifest(static_dir: Path) -> dict:
    """读并校验碎片索引，返回 {id: {"path": 碎片文件, "axes": dict}}。

    只在 profile 声明了 `fragments:` 时被调用：未声明的项目不得因这份文件坏掉而新增失败面。
    """
    index = static_dir / "manifest.yaml"
    if not index.exists():
        die("profile 声明了 fragments 但碎片索引不存在: %s" % _disp(index))
    try:
        data = load_yaml_strict(index.read_text(encoding="utf-8-sig"))
    except ProfileDuplicateKey as exc:
        # B05：碎片索引同属判据真源，重复键同样不得静默 last-wins。
        die("碎片索引 %s 含重复键：%s（last-wins 会静默吞掉前一条，请去重）" % (_disp(index), exc))
    except yaml.YAMLError as exc:
        die("碎片索引 %s 不是合法 YAML: %s" % (_disp(index), exc))
    if not isinstance(data, dict) or not isinstance(data.get("fragments"), list):
        die("碎片索引 %s 须是含顶层列表键 `fragments:` 的映射" % _disp(index))
    if str(data.get("version")) != "1":
        die("碎片索引 %s 的 version 须为 1（实际 %r）" % (_disp(index), data.get("version")))
    out: dict[str, dict] = {}
    for pos, entry in enumerate(data["fragments"], 1):
        if not isinstance(entry, dict):
            die("碎片索引 %s 第 %d 条不是映射（实际类型 %s）"
                % (_disp(index), pos, type(entry).__name__))
        fid, frag = entry.get("id"), entry.get("fragment")
        if not fid or not frag:
            # 不回显条目本体：里面可能有绝对路径，回显等于把本机路径写进出生输出。
            die("碎片索引 %s 第 %d 条须同时有非空 id 与 fragment（该条目键：%s）"
                % (_disp(index), pos,
                   sorted(map(str, entry)) if isinstance(entry, dict) else "?"))
        # 类型先于一切：非字符串会在 `static_dir / frag` 抛 TypeError，非字符串 id 会让
        # 下面"未知 id"消息里的 sorted(index) 崩在报错当场（2026-09-27 code 审查 D1/D2）。
        if not isinstance(fid, str) or not fid.strip():
            die("碎片 id 须是非空字符串（实际类型 %s）" % type(fid).__name__)
        if not isinstance(frag, str):
            die("碎片 %s 的 fragment 须是文件名字符串（实际类型 %s）"
                % (fid, type(frag).__name__))
        if fid in out:
            die("碎片 id 重复: %s" % fid)
        axes = entry.get("axes")
        if not isinstance(axes, dict) or len(axes) < 2:
            die("碎片 %s 的 axes 须是 ≥2 个键的映射（实际类型 %s）"
                % (fid, type(axes).__name__))
        unknown = sorted(set(axes) - FRAGMENT_AXES_KEYS)
        if unknown:
            die("碎片 %s 的 axes 含未知键 %s（允许：%s）"
                % (fid, unknown, sorted(FRAGMENT_AXES_KEYS)))
        # §3.1 的"static/ 下平铺 .md"是加载器强制，不只是文档描述：漏了这层，索引里一个
        # 笔误的 `../` 或绝对路径就会把**别的文件**当规则静默注入（D3）。
        if (not frag.endswith(".md") or frag != Path(frag).name
                or any(sep in frag for sep in ("/", "\\", ":")) or frag.startswith(".")):
            die("碎片 %s 的 fragment 须是 %s 下的裸文件名 .md（不得含路径分隔符、盘符或以 . 开头；"
                "实际文件名为 %s）" % (fid, _disp(static_dir), Path(frag).name or "空"))
        path = static_dir / frag
        if not path.resolve().is_relative_to(static_dir.resolve()):
            die("碎片 %s 的正文解析后越出 %s" % (fid, _disp(static_dir)))
        if not path.exists():
            die("碎片 %s 声明的文件不存在: %s" % (fid, _disp(path)))
        out[fid] = {"path": path, "axes": axes}
    return out


def _axes_mismatch(axes: dict, profile_axes: dict) -> list:
    """碎片 axes 与 profile axes 的不同键（标量按相等、列表按成员关系；profile 未用的轴不参与）。"""
    out = []
    for key, want in axes.items():
        if key not in profile_axes:
            continue                      # 领域档想用该轴才在 `axes:` 补声明，不补即不比较
        have = profile_axes[key]
        have_list = have if isinstance(have, list) else [have]
        if not have_list:
            continue                      # 空列表 = 该轴不适用（如 reporting: []）
        want_list = want if isinstance(want, list) else [want]
        if not ({str(x) for x in want_list} & {str(x) for x in have_list}):
            out.append("%s: profile=%r 碎片=%r" % (key, have, want))
    return out


def fragment_blocks(profile: dict, static_dir: Path) -> str:
    """按 profile 声明顺序把碎片正文拼成注入块；未声明返回空串（且完全不读 manifest）。

    "原样"指语义原样（不折叠空行、不改缩进，换行按 LF 归一）；marker 由本函数独占，
    碎片正文再出现该 marker 即拒，否则下游按 marker 计数的一致性判据不可靠。
    """
    declared = profile.get("fragments") or []
    if not declared:
        return ""
    if not isinstance(declared, list):
        die("profile 的 fragments 须是碎片 id 列表（实际类型 %s）" % type(declared).__name__)
    for fid in declared:
        if not isinstance(fid, str) or not fid.strip():
            die("profile 的 fragments 须全是碎片 id 字符串（有元素是 %s）"
                % type(fid).__name__)
    dup_decl = sorted({f for f in declared if declared.count(f) > 1})
    if dup_decl:
        # 与索引侧「碎片 id 重复」对称：重复声明会把同一片注入两次，marker 计数判据随之失真。
        die("profile 的 fragments 重复声明：%s" % dup_decl)
    index = load_fragment_manifest(static_dir)
    profile_axes = profile.get("axes") or {}
    blocks = []
    for fid in declared:
        if fid not in index:
            die("profile fragments 声明了未知碎片 id: %s（%s 已知：%s）"
                % (fid, _disp(static_dir / "manifest.yaml"), ", ".join(sorted(index)) or "无条目"))
        entry = index[fid]
        mismatch = _axes_mismatch(entry["axes"], profile_axes)
        if mismatch:
            print("   warn  碎片 %s 的 axes 与 profile 不符：%s（仅提示，不改退出码）"
                  % (fid, "；".join(mismatch)))
        try:
            body = entry["path"].read_text(encoding="utf-8-sig")
        except UnicodeDecodeError as exc:
            # 读不动要明说（conventions §2 读侧口径）：以崩代拒 = rc=1 加 traceback，
            # 硬读下去 = 乱码进规则片段，两条都比不过一次 rc=2 的定位报告。
            die("碎片 %s 的正文 %s 不是合法 UTF-8（%s）"
                % (fid, _disp(entry["path"]), exc.reason or "编码不符"))
        if "<!-- fragment:" in body:
            # 拼接层用该 marker 标块；碎片正文里再出现一次，下游按 marker 计数的一致性判据就不可靠了。
            die("碎片 %s 的正文含注入标记 <!-- fragment: … -->，须改写该正文（marker 由拼接层独占）" % fid)
        blocks.append("<!-- fragment: %s -->\n%s\n" % (fid, body.rstrip("\n")))
    return "\n".join(blocks)


def rules_fragment(profile: dict, static_dir: Path | None = None) -> str:
    # F8（2026-10-07 审查）：规则片段里的 policy 文案也须走 fill()——与 policy_lines 同源，
    # 否则 `{data}/…` 会以未解析占位符泄漏进 rules.fragment.md（78 AC6 守卫：须含解析后目录、
    # 且全篇无未解析占位符）。
    ctx = dict(profile.get("paths") or {})
    if profile.get("tool_dir"):
        ctx["tool_dir"] = profile["tool_dir"]

    def _f(v):
        try:
            return fill(v, ctx)
        except (KeyError, IndexError, ValueError):
            return v          # 字面花括号：保留原值，不裸崩

    pol = profile["evidence_policy"]
    lines = ["# 域口径规则片段（由 profiles/%s 生成，请并入项目 `rules/`）" % profile["id"], ""]
    for k, v in pol.items():
        lines.append("- **%s**：%s" % (k, _render_scalar(_f(v))))
    for key in ("figure_policy", "citation_policy"):
        if key in profile:
            lines += ["", "## %s" % key]
            for k, v in profile[key].items():
                lines.append("- **%s**：%s" % (k, _render_scalar(_f(v))))
    text = "\n".join(lines) + "\n"
    blocks = fragment_blocks(profile, STATIC_DIR if static_dir is None else static_dir)
    return text if not blocks else text + "\n" + blocks


TEXT_SUFFIXES = {".md", ".json", ".txt", ".yaml", ".yml", ".py", ".bib", ".tex", ".csv",
                 ".ps1", ".sh", ".js", ".html", ".css", ".toml", ".cfg", ".ini"}
_VERIFY_KEYS = ("files", "json_files", "globs", "absent_paths")


def _matches_exclude(path: str, excludes: list) -> bool:
    """判断 path 是否命中任一 exclude 模式（支持尾随 /* 前缀匹配）。"""
    for pat in excludes or []:
        if pat.endswith("/*"):
            prefix = pat[:-1]  # 去掉 /*
            if path.startswith(prefix):
                return True
        elif pat == path:
            return True
    return False


def _die_on_vacuous_excludes(apply_to: str, excludes: list, scoped_paths: list) -> None:
    """空命中上报（B13，G-15）：exclude 须命中至少一条本次生效路径，否则 die 点名。

    scoped_paths 是该模板下 exclude 实际能豁免的路径全集（文本模板=文本非 vendor，
    二进制模板=非文本）——只命中范围外的模式（前缀写错/过期/放错模板）与零命中同判，
    不再静默无事发生。无 exclude 时直接返回。
    """
    for pat in excludes or []:
        if not any(_matches_exclude(p, [pat]) for p in scoped_paths):
            die("通配模板 (apply_to: %s) 的 exclude %r 未命中任何本次生效路径"
                "（拼写/过期/放错模板？请修正或删除；静默豁免已取消）"
                % (apply_to, pat))


def profile_manifest_path(profile: dict) -> str:
    """verify manifest 的项目相对路径（正斜杠归一）。两制：
    新项目 70-tools/71-verify-manifest.json；paper1 冻结 scripts/verify_manifest.json。
    合成/最小 profile 两键皆缺时返回空串（调用方跳过）。"""
    path = profile.get("verify_manifest") or (
        "%s/71-verify-manifest.json" % profile["tool_dir"] if profile.get("tool_dir") else "")
    return str(path).replace("\\", "/")


# A1（2026-10-07 审查）：随技能 vendor 进项目的**发货工具**（真源 = install.py::install_project
# 的 (src_rel, dst_name) 清单）。它们由技能安装器写入，不是本任务 authored 的产物；通配
# apply_to: edit_files_text 会把 forbid:[AUTHOR CONFIRM, TODO] 挂到 task-assemble-draft /
# task-compose-raster-figures 的 files_to_edit 上，而这些工具源码含字面 TODO ×2 →
# 任何照装项目的该任务永久 rc=1。修法：生成器展开通配时**排除**这些 vendor 产物。
# R4-tail（2026-10-08）：40-style-check.py / 45-consistency-check.py 随 vendor 进 70-tools/
# （social 档两条 run: 的项目侧执行前提）。social 档对 40/45 仅 run: 引用、files_to_edit
# 未列 vendor 路径，故本次名单扩展对逐档生成物是 no-op（由 75 号守卫逐档复核）。
# 75 号守卫交叉核对本表与 install.py 实际清单（防两处漂移）。
VENDOR_TOOL_NAMES = frozenset({
    "70-verify.py",
    "71-verify-manifest.template.json",
    "72-assemble-draft.py",
    "72-compose-raster-figures.py",
    "72-latex-build-check.py",
    "40-style-check.py",
    "45-consistency-check.py",
})


def is_vendor_tool(path: str, tool_dir: str | None) -> bool:
    """path 是否为随技能发货的 vendor 工具（按**全路径**判：仅 `<tool_dir>/<件名>` 算）。

    B13 收口：旧口径只看 basename——项目自建 `10-data/70-verify.py` 这类同名不同目录
    文件会被误豁免（basename 旁路），其 forbid 断言静默丢失。现要求目录也对上
    profile 的 tool_dir，发货目录外的同名文件不再豁免。
    """
    norm = str(path).replace("\\", "/")
    while norm.startswith("./"):
        norm = norm[2:]
    name = norm.rsplit("/", 1)[-1]
    if name not in VENDOR_TOOL_NAMES:
        return False
    return norm == "%s/%s" % (tool_dir or "", name)


def strip_manifest_text_assertions(out: dict, profile: dict) -> None:
    """F1（2026-10-06 审查，沙盒实测）+ B13 收敛：verify manifest 本体不做缺席类文本自查。

    通配 forbid（AUTHOR CONFIRM/TODO）落到 manifest 文件上是自指死锁——生成的
    manifest JSON 必然含这些词（它们正是 forbid 值本身），citation-audit /
    assemble-draft 在每个生成项目永久 rc=1。manifest 是生成器拥有的工具产物，
    缺席类断言（forbid/forbid_regex）一律剥离；存在类断言（contains/min_matches/
    contains_regex/min_bytes 等）予以保留——它们可满足、不自指，旧口径连它们一起
    删是范围过大。通配与任务点名两条来源都经此归一。"""
    target = profile_manifest_path(profile)
    if not target:
        return
    for entry in out.values():
        for i, item in enumerate(entry.get("files") or []):
            if str(item.get("path", "")).replace("\\", "/") != target:
                continue
            entry["files"][i] = {k: v for k, v in item.items()
                                 if k not in ("forbid", "forbid_regex")}


def verify_fragment(profile: dict, tasks: list) -> dict:
    """把域档断言模板展开为 70-verify.py 原生形状的 manifest 片段。

    形状必须与 `70-verify.py --schema` 一致（files[].path/forbid、json_files[]…），
    否则任务 done 时基座查不到断言而空转 PASS。

    - 指定 task 的条目：files/json_files/globs/absent_paths/run 原样透传到该任务；
    - task:"*"：同样透传到每个任务；
    - task:"*" + apply_to: edit_files_text：把 forbid[]/min_bytes 挂到本任务 files_to_edit
      里每个文本后缀文件上（.pdf/.png 等二进制跳过）；
    - task:"*" + apply_to: edit_files_binary：把 min_bytes_each 挂到每个**非文本**产物
      （以 files 条目 + min_bytes 表达存在性与体积下限——二进制只验"是真产物、非占位"）。
    - vendor 豁免（A1，2026-10-07 审查）：files_to_edit 里命中 install.py vendor 清单的发货
      工具（70-verify.py / 72-*.py 等）不是本任务 authored 的产物，通配展开时整体排除，
      否则工具源码里的字面 TODO 会被 forbid 咬成永久红。目录须对上 profile 的 tool_dir——
    发货目录外的同名文件不豁免（basename 旁路消除）。
    展开后任何任务仍为空断言 = 门禁空转，直接 die（2026-09-26 审查：redraw/draw-schematics
    曾因只覆盖文本文件而生成 `{}`，done 时无任何检查）。
    - 占位符统一（B13，B-6）：通配模板的 forbid/exclude 先走 fill() 再展开与命中判定——`{ms}/…` 形态
    与字面路径同命中，未解析占位符不再静默失配；字面花括号保留原值，不裸崩。
    - 空命中上报（B13，G-15）：exclude 须命中至少一条本次生效路径（文本模板看文本非 vendor 路径，
    二进制模板看非文本路径），否则 die 点名——拼错/过期模式不再静默无事发生（静默 refund 消除）。
    """
    ctx = _expand_ctx(profile)
    tool_dir = profile.get("tool_dir")
    out: dict[str, dict] = {t["id"]: {} for t in tasks}
    for a in profile.get("verify_assertions_template", []):
        target = a.get("task", "*")
        if target == "*":
            targets = [t["id"] for t in tasks]
        else:
            if target not in out:
                die("verify_assertions_template targets unknown task: %s" % target)
            targets = [target]
        for tid in targets:
            entry = out[tid]
            for key in _VERIFY_KEYS:
                if key in a:
                    entry.setdefault(key, []).extend(a[key])
            if "run" in a:
                entry["run"] = a["run"]
        if target == "*" and a.get("apply_to") == "edit_files_text":
            forbid = _fill_str_list(a.get("forbid", []), ctx)
            min_bytes = a.get("min_bytes")
            excludes = _fill_str_list(a.get("exclude", []), ctx)
            for t in tasks:
                for path in t.get("files_to_edit", []):
                    # A1：vendor 发货工具（install.py 写入）不是本任务 authored 的产物，
                    # 其源码含字面占位词，通配 forbid 挂上去即永久红——一并排除（全路径匹配）。
                    if (Path(path).suffix.lower() in TEXT_SUFFIXES
                            and not is_vendor_tool(path, tool_dir)
                            and not _matches_exclude(path, excludes)):
                        item = {"path": path, "forbid": list(forbid)}
                        if min_bytes is not None:
                            item["min_bytes"] = min_bytes
                        out[t["id"]].setdefault("files", []).append(item)
            _die_on_vacuous_excludes("edit_files_text", excludes, [
                p for t in tasks for p in t.get("files_to_edit", [])
                if Path(p).suffix.lower() in TEXT_SUFFIXES
                and not is_vendor_tool(p, tool_dir)])
        if target == "*" and a.get("apply_to") == "edit_files_binary":
            min_bytes = a.get("min_bytes_each")
            excludes = _fill_str_list(a.get("exclude", []), ctx)
            if min_bytes is None:
                die("apply_to: edit_files_binary template needs min_bytes_each (binary "
                    "artifacts can only be checked for existence + size floor)")
            for t in tasks:
                for path in t.get("files_to_edit", []):
                    if Path(path).suffix.lower() not in TEXT_SUFFIXES and not _matches_exclude(path, excludes):
                        out[t["id"]].setdefault("files", []).append(
                            {"path": path, "min_bytes": min_bytes})
            _die_on_vacuous_excludes("edit_files_binary", excludes, [
                p for t in tasks for p in t.get("files_to_edit", [])
                if Path(p).suffix.lower() not in TEXT_SUFFIXES])
    for tid, entry in out.items():
        if not any(entry.get(k) for k in _VERIFY_KEYS) and not entry.get("run"):
            die("%s: verify assertions expand to EMPTY — gate would idle-PASS at done; "
                "add a task-specific assertion or cover its artifacts via apply_to templates" % tid)
    strip_manifest_text_assertions(out, profile)
    return out


def emit(built: dict, profile: dict, out: Path) -> None:
    # 先算全部载荷、后写盘：rules_fragment/verify_fragment 都有 die 路径（碎片未知 id、
    # 断言展开为空），曾的顺序是 proposals 与 master 先落盘再 die，现场留下半份生成物 +
    # 上一次的 rules.fragment.md，看起来像"跑过了"（与 N-4 的先拒后写同口径）。
    rules_text = rules_fragment(profile)
    verify_text = json.dumps(verify_fragment(profile, built["tasks"]),
                             ensure_ascii=False, indent=2) + "\n"
    (out / "proposals").mkdir(parents=True, exist_ok=True)
    keep = {"%s.json" % t["id"] for t in built["tasks"]}
    for old in (out / "proposals").glob("task-*.json"):   # 幂等：profile 删任务后不留过期提案
        if old.name not in keep:
            old.unlink()
    for t in built["tasks"]:
        p = {k: v for k, v in t.items()
             if k in ("id", "name", "brief", "module", "depends_on", "estimated_hours",
                      "difficulty", "requires", "acceptance_criteria", "files_to_read",
                      "files_to_edit", "exempt_files", "verify_command", "source")}
        (out / "proposals" / ("%s.json" % t["id"])).write_text(
            json.dumps(p, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (out / "_master.fragment.json").write_text(
        json.dumps(built["master"], ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (out / "rules.fragment.md").write_text(rules_text, encoding="utf-8")
    (out / "verify_manifest.fragment.json").write_text(verify_text, encoding="utf-8")
    print("emitted: %d proposals + master fragment + rules fragment + verify fragment -> %s"
          % (len(built["tasks"]), out))


def check(project: Path, built: dict, tmp: Path) -> int:
    """用 orchd 校验合成的 master（只读；临时文件写在技能工作区，绝不落进项目 .orchd/）。"""
    tmp.parent.mkdir(parents=True, exist_ok=True)
    tmp.write_text(json.dumps(built["master"], ensure_ascii=False, indent=2) + "\n",
                   encoding="utf-8")
    # -B：引擎是以 import 方式加载目标项目 .orchd/orchd 包的包内模块，默认会在**目标项目**里
    # 落 .pyc（内嵌其绝对路径）。技能对目标项目必须只读，故禁写字节码缓存。
    # P2（2026-10-05 审查）：引擎 validate 若挂起（死锁/异常）不得无限阻塞——带超时并给
    # 可定位诊断；120s 与引擎 verify_command 默认预算同量级，正常项目秒级完成。
    try:
        r = subprocess.run([sys.executable, "-B", "-X", "utf8", ".orchd/__main__.py", "validate", str(tmp)],
                           cwd=str(project), capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=120)
    except subprocess.TimeoutExpired:
        print("orchd validate -> TIMEOUT（120s）: .orchd/__main__.py validate 未在时限内返回"
              "（project=%s；引擎挂起或异常，请查该项目的 .orchd/ 状态）" % project)
        return 1
    # 引擎在"校验失败"时仍返回退出码 0，必须解析 JSON 的 valid 字段（实测：E-13 家族）。
    # B02（round3 E-8）：解码失败（非 UTF-8 引擎输出 → 出现替换字符 U+FFFD）归 rc=2 点名，
    # 不静默按乱码解析成"无法解析输出"。
    if "\ufffd" in (r.stdout or "") or "\ufffd" in (r.stderr or ""):
        print("orchd validate -> 输出含替换字符 U+FFFD（疑非 UTF-8 引擎输出，已加 -X utf8 仍如此）"
              "→ rc=2；请查目标项目 .orchd/ 引擎编码")
        return 2
    try:
        rep = json.loads((r.stdout or "").lstrip("\ufeff"))
    except json.JSONDecodeError:
        print("orchd validate -> 无法解析输出（rc=%d）" % r.returncode)
        print((r.stdout or r.stderr).strip()[:1000])
        return 1
    ok = bool(rep.get("valid"))
    print("orchd validate -> %s (rc=%d)" % ("PASS" if ok else "FAIL", r.returncode))
    for e in rep.get("errors", [])[:12]:
        print("   ERROR %s %s: %s" % (e.get("code"), e.get("path"), e.get("message")[:120]))
    for w in rep.get("warnings", [])[:12]:
        print("   warn  %s %s: %s" % (w.get("code"), w.get("path"), w.get("message")[:120]))
    print("   errors=%d warnings=%d" % (len(rep.get("errors", [])), len(rep.get("warnings", []))))
    return 0 if ok else 1


def regress(project: Path, built: dict, expectations: dict | None = None,
            ignore_baseline: set | None = None) -> int:
    """与目标项目的真实任务结构对比。

    A 类（不一致即失败）：任务集合、module、depends_on、verify_command。
    B 类（记录为 INFO，不算失败）：文件声明路径与数量、AC 文本 —— 已完成任务的声明
    是**历史快照**（终态不可改），与规范路径不同属预期。
    """
    exp = expectations or {}
    ignore = set(ignore_baseline or ())   # 一次性基础设施任务须由 profile 的 regress_ignore 显式登记，
                                          # 不内置项目专属默认值（审查：曾硬编码 paper1 的 task-migrate-layout-v2）
    try:
        base = json.loads((project / ".orchd" / "_master.json").read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        print("ERROR: %s 无 .orchd/_master.json，无法 regress 比对" % project)
        return 2
    except json.JSONDecodeError as exc:
        print("ERROR: %s 的 _master.json 不是合法 JSON: %s" % (project, exc))
        return 2
    b = {t["id"]: t for t in base["tasks"] if t["id"] not in ignore}
    g = {t["id"]: t for t in built["tasks"]}
    extra, missing = sorted(set(g) - set(b)), sorted(set(b) - set(g))
    print("== A 类：任务集合 ==")
    print("  生成 %d / 基线（去一次性基础设施任务）%d" % (len(g), len(b)))
    print("  生成多出：%s" % (extra or "无"))
    print("  基线多出：%s" % (missing or "无"))
    diffs, infos = [], []
    for tid in sorted(set(g) & set(b)):
        gt, bt = g[tid], b[tid]
        if gt["module"] != bt["module"]:
            diffs.append((tid, "module", gt["module"], bt["module"]))
        bdep = sorted(bt.get("depends_on", []))
        if gt["depends_on"] != bdep:
            if tid in exp and sorted(exp[tid]) == bdep:
                infos.append((tid, "depends_on（规范图有意升级）", gt["depends_on"], bdep))
            else:
                diffs.append((tid, "depends_on", gt["depends_on"], bdep))
        if gt["verify_command"] != bt.get("verify_command"):
            diffs.append((tid, "verify_command", gt["verify_command"], bt.get("verify_command")))
    print("== A 类：结构差异 ==")
    for row in diffs:
        print("  %-34s %-20s gen=%s base=%s" % row)
    if not diffs:
        print("  无——module / depends_on / verify_command 与基线一致")
    print("== B 类：有意差异（不算失败）==")
    for row in infos:
        print("  %-34s %s gen=%s base=%s" % row)
    print("== B 类：规模指标（生成 vs 基线；基线为历史快照）==")
    for tid in sorted(set(g) & set(b)):
        gt, bt = g[tid], b[tid]
        print("  %-34s ac %d/%d  read %d/%d  edit %d/%d" % (
            tid, len(gt["acceptance_criteria"]), len(bt.get("acceptance_criteria", [])),
            len(gt["files_to_read"]), len(bt.get("files_to_read", [])),
            len(gt["files_to_edit"]), len(bt.get("files_to_edit", []))))
    return 0 if not diffs and not missing else 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", required=True)
    ap.add_argument("--out", default="./build")
    ap.add_argument("--project")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--regress", action="store_true")
    ap.add_argument("--verify-layout", choices=("standard", "legacy"), default=None,
                    help="F2（2026-10-06）：standard = 把 tool_dir/verify_tool/verify_manifest "
                         "覆写为 70-tools/ 两制（新项目用）；legacy = 维持档声明（paper1 --regress "
                         "回归用）。缺省 = 档声明，且 emit 模式下对 scripts/ 冻结侧档案打 stderr 警告")
    a = ap.parse_args()

    # N-4：先拒后写。曾的写法是 `if a.project:` 包住 check/regress —— 缺 --project 时整段跳过，
    # 前面的 emit 照旧把 26 份生成物写进 --out（默认 ./build/），rc=0。现场看到的是"跑过了"，
    # 实际一步都没核对（实测 M6）。缺参数归用法错 2，且必须早于任何写盘动作。
    if (a.check or a.regress) and not a.project:
        die("--%s 必须同时给 --project <目标项目>（缺失参数 project）："
            "本脚本没有项目可核对，且不落任何生成物"
            % ("check" if a.check else "regress"))

    # C-7（B12 契约统一）：--profile 只认带目录成分的写法（推荐 profiles/<名>，
    # 与 install.py --profile 同口径）。裸名（无目录成分）以往落进 load_profile 报
    # 含糊的 "profile not found"，现前置指引 die（rc=2）。绝对路径与含目录的相对
    # 路径不受影响（75 号守卫全用绝对路径调用）。
    if len(Path(a.profile).parts) == 1:
        die("--profile 须带 profiles/ 前缀（收到 %r）：请改用 --profile profiles/%s"
            % (a.profile, a.profile))
    profile = load_profile(Path(a.profile))
    if a.verify_layout == "standard":
        # F2：在 build 之前覆写两制三键，占位符 fill 会把 70-tools 自然扩散到
        # verify_command、files_to_edit 与断言路径——不做任何事后字符串替换。
        profile["tool_dir"] = "70-tools"
        profile["verify_tool"] = "70-tools/70-verify.py"
        profile["verify_manifest"] = "70-tools/71-verify-manifest.json"
    elif a.verify_layout is None and not a.check and not a.regress \
            and str(profile.get("verify_tool", "")).startswith("scripts/"):
        sys.stderr.write(
            "警告：档 %s 的 verify_tool 冻结在 paper1 两制之 scripts/ 侧（%s）——新项目装配的判据"
            "脚本在 70-tools/，24 类任务的 verify_command 在 done 时将找不到脚本（E014）。"
            "新项目请加 --verify-layout standard；paper1 回归（--regress）保持缺省即可。\n"
            % (profile["id"], profile.get("verify_tool")))
    built = build(profile)
    if built["problems"]:
        print("== 生成期自检未通过（%d）==" % len(built["problems"]))
        for p in built["problems"]:
            print("  -", p)
        # B13：形态类违规（[shape] 前缀，含标量/char-split/未知轴值）是用法错，
        # 归 rc=2 并点名；其余内容类问题仍 rc=1。
        if any(p.startswith(SHAPE_PREFIX) for p in built["problems"]):
            return 2
        return 1
    print("profile=%s tasks=%d source=%s" % (profile["id"], len(built["tasks"]), built["source"]))
    emit(built, profile, Path(a.out))

    rc = 0
    if a.project:
        proj = Path(a.project).resolve()
        if a.check:
            rc |= check(proj, built, Path(a.out).resolve() / "_validate.proposed.json")
        if a.regress:
            rc |= regress(proj, built, profile.get("regress_expectations"),
                          set(profile.get("regress_ignore", [])) or None)
    return rc


if __name__ == "__main__":
    sys.exit(main())
