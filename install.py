#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""install.py — paper-pipeline 技能安装器（开发/发布分离的装配通道）。

形式：仓根单文件脚本，仅标准库；源 = 本脚本所在的仓库工作副本或其全新 clone。
发布面以仓根 `MANIFEST.in` 纯白名单为单一真源：清单内 = 发布，清单外 = 开发层
（.orchd/、build/、reports/、docs/、scripts/76 号本仓自检等物理上进不了安装流）。

用法：
    python install.py <target> --mode skill                  # 整套发布面装进宿主技能目录
    python install.py <target> --mode project --profile profiles/<名>  # 判据基座 vendor 进论文项目
    python install.py <target> ... --cleanup                 # 安装成功后删除源（仅干净 clone）
    python install.py --selftest                             # 离线自测（临时目录，用毕即删）

退出码（conventions §3）：0 = 通过；1 = 判据命中/安装失败；2 = 用法错误。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HERE = Path(__file__).resolve().parent
MANIFEST = HERE / "MANIFEST.in"
DEV_ABSENT = (".orchd", "build", "reports", "docs", ".gitignore",
              "scripts/76-doc-refs-selftest.py")          # 开发层，装配后必须缺席

# B09（C-3）：随 project 模式 vendor 进论文项目的六件（70 判据基座 + 72 三件套 + 40/45 机检双件）。
# 每件文件头带版本戳行 `# vendor-tool: <件名> version <版本>`（件名与版本双含）；
# provenance() 把逐件 {version, sha256} 写进 PROVENANCE.json，75 号守卫校两端一致。
_VENDOR_TOOL_FILES = ("scripts/70-verify.py",
                      "scripts/72-assemble-draft.py",
                      "scripts/72-compose-raster-figures.py",
                      "scripts/72-latex-build-check.py",
                      "scripts/40-style-check.py",
                      "scripts/45-consistency-check.py")
_VENDOR_STAMP_RE = re.compile(r"^# vendor-tool:\s*(\S+)\s+version\s+(\S+)\s*$")


def die(msg: str) -> None:
    print("ERROR: %s" % msg)
    sys.exit(2)


def read_manifest() -> list:
    """解析纯白名单清单：只支持 `include <路径>` 与 # 注释；未知指令 = 用法错。"""
    if not MANIFEST.exists():
        die("MANIFEST.in 不在盘（%s）——发布面缺单一真源" % MANIFEST)
    out = []
    for i, line in enumerate(MANIFEST.read_text(encoding="utf-8-sig").splitlines(), 1):
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        if s.startswith("include "):
            out.append(s[len("include "):].strip())
        else:
            die("MANIFEST.in:%d 非白名单指令（只支持 include <路径> 与 # 注释）：%s" % (i, s[:60]))
    if not out:
        die("MANIFEST.in 无任何 include 条目")
    return out


def _git(args: list) -> str | None:
    try:
        r = subprocess.run(["git", "-C", str(HERE)] + args, capture_output=True,
                           text=True, encoding="utf-8", errors="replace", timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return r.stdout.strip() if r.returncode == 0 else None


def cleanup_allowed(src: Path) -> bool:
    """B04（round3 A-1）：--cleanup 仅允许删除**系统临时目录之下**的源。

    删源判据若只看「工作树干净」，任何刚 commit 完的开发仓与临时克隆同形——本轮本仓即被
    删空一次（reports/ 与 .orchd/ 运行时不可从 git 恢复）。故加位置硬约束。
    """
    try:
        return Path(src).resolve().is_relative_to(Path(tempfile.gettempdir()).resolve())
    except (ValueError, OSError):
        return False


def provenance(mode: str, files: int) -> dict:
    commit = _git(["rev-parse", "--short", "HEAD"])
    describe = _git(["describe", "--tags", "--always"])
    status = _git(["status", "--porcelain"])
    if commit is None:
        # B04（round3 A-15）：非 git 源——回退读 VERSION；缺/空则 rc=2，绝不写 "unknown"。
        vp = HERE / "VERSION"
        version = ""
        if vp.is_file():
            lines = vp.read_text(encoding="utf-8-sig").strip().splitlines()
            version = lines[0].strip() if lines else ""
        if not version:
            die("PROVENANCE 版本无法确定：源非 git 仓库且 VERSION 缺失/为空"
                "（不写 unknown；请补 VERSION 或改用 git 源）")
        commit = describe = version
    else:
        describe = describe or commit
    return {
        "skill": "paper-pipeline",
        "version": describe,
        # E4（2026-10-07 审查）：源标识脱敏——不落本机绝对路径（换机 / 换用户名泄漏）。
        # 需要追源时用 version + commit；具体本机路径不进目标项目历史。
        "source": "<paper-pipeline repo>",
        "commit": commit,
        "source_dirty": bool(status),
        "mode": mode,
        "files": files,
        "installed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        # B09（C-3）：vendor 六件逐件 {version, sha256}——件头版本戳的另一端，
        # 75 号 vendor 豁免守卫内同一断言校两端一致（改一件内容即红并点名）。
        "vendor_tools": vendor_tool_records(),
    }


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def vendor_tool_stamp(path: Path) -> str:
    """解析 vendor 件文件头版本戳（`# vendor-tool: <件名> version <版本>`）。

    只认前 12 行、且件名须与文件名一致；缺戳/件名对不上/不可读一律返回 ""——
    调用方（provenance 缺省记录、selftest 显式判红）据此分流，本函数永不 die
    （合成源如 cleanup 护栏夹具缺 vendor 件时不得崩）。
    """
    try:
        text = path.read_text(encoding="utf-8-sig")
    except OSError:
        return ""
    want = path.name
    for line in text.splitlines()[:12]:
        m = _VENDOR_STAMP_RE.match(line.strip())
        if m and m.group(1) == want:
            return m.group(2)
    return ""


def vendor_tool_records() -> dict:
    """B09（C-3）：vendor 六件逐件记录 {件名: {"version": 戳版本, "sha256": hex}}。

    best-effort：源缺件时该件记空串（绝不 die——cleanup 护栏的合成源只拷
    install.py，provenance 照常走完才到护栏判定）。
    """
    rec = {}
    for src_rel in _VENDOR_TOOL_FILES:
        p = HERE / src_rel
        try:
            digest = _sha256_file(p)
        except OSError:
            digest = ""
        rec[Path(src_rel).name] = {"version": vendor_tool_stamp(p) if digest else "",
                                   "sha256": digest}
    return rec


def _atomic_install(target: Path, files: list, force: bool = False) -> None:
    """B04（round3 A-15）：可写性预检 + 冲突预检 + 暂存校验 + 原子搬移（失败回滚）。

    ``files`` = [(相对目标根的 posix 路径, 源文件 Path)]。任一步失败即回滚已搬移项、不留半装；
    调用方在成功后**才**写 PROVENANCE。
    """
    conflicts = []
    for rel, src in files:
        if not src.is_file():
            die("源文件不在盘（发布面破损）：%s" % src)
        dst = target / rel
        # F2（复审）：dst 存在同名**目录**同样算冲突（否则 os.replace 会把整目录移入备份后删掉）。
        if dst.exists() and not (dst.is_file() and dst.read_bytes() == src.read_bytes()):
            conflicts.append(rel)
    if conflicts and not force:
        die("目标已有 %d 个不同内容的文件，拒绝静默覆盖；核验无误请加 --force：\n  %s"
            % (len(conflicts), "\n  ".join(conflicts[:12])))
    # 可写性预检：目标不可写即失败，且未做任何改动。
    try:
        target.mkdir(parents=True, exist_ok=True)
        probe = target / ".pp-write-probe"
        probe.write_text("x", encoding="utf-8")
        probe.unlink()
    except OSError as exc:
        die("目标不可写（%s）：%s —— 安装前预检失败，未做任何改动" % (target, exc))
    stage, backup = target / ".pp-stage", target / ".pp-backup"
    for d in (stage, backup):
        if d.exists():
            _force_rmtree(d)
        d.mkdir(parents=True)
    moved: list = []          # 已放入新件的 rel
    backed: list = []         # 既有内容已移入备份的 rel（F1：备份后即登记，防放入失败漏回滚）
    try:
        for rel, src in files:                       # 暂存 + 逐件字节校验
            sp = stage / rel
            sp.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, sp)
            if sp.read_bytes() != src.read_bytes():
                raise OSError("staged content mismatch: %s" % rel)
        for rel, _ in files:                          # 备份既有 → 原子搬移
            dst = target / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            if dst.exists():
                bp = backup / rel
                bp.parent.mkdir(parents=True, exist_ok=True)
                os.replace(dst, bp)
                backed.append(rel)                    # F1：先登记备份，再放新件
            os.replace(stage / rel, dst)
            moved.append(rel)
    except OSError as exc:
        # F1（复审）：对**所有已触碰（备份或放入）的 rel** 回滚——先清当前 dst，再有备份则还原。
        # 旧实现只遍历 moved：若"备份成功但放入失败"，该件未进 moved，既有内容随备份被删=数据丢失。
        for rel in sorted(set(moved) | set(backed)):
            dst, bp = target / rel, backup / rel
            try:
                if dst.exists():
                    if dst.is_dir():
                        _force_rmtree(dst)
                    else:
                        dst.unlink()
                if bp.exists():
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    os.replace(bp, dst)
            except OSError:
                pass
        die("装配失败并已回滚（未写 PROVENANCE）：%s" % exc)
    finally:
        for d in (stage, backup):
            if d.exists():
                _force_rmtree(d)


def install_skill(target: Path, entries: list, force: bool = False) -> None:
    _atomic_install(target, [(rel, HERE / rel) for rel in entries], force)


_PROJECT_FILES = (("scripts/70-verify.py", "70-verify.py"),
                  ("assets/10-verify-manifest.template.json", "71-verify-manifest.template.json"),
                  ("scripts/72-assemble-draft.py", "72-assemble-draft.py"),
                  ("scripts/72-compose-raster-figures.py", "72-compose-raster-figures.py"),
                  ("scripts/72-latex-build-check.py", "72-latex-build-check.py"),
                  ("scripts/40-style-check.py", "40-style-check.py"),
                  ("scripts/45-consistency-check.py", "45-consistency-check.py"))


def install_project(target: Path, profile: str | None, force: bool = False) -> None:
    """vendor 判据基座 + LaTeX 三件套 + 40/45 机检双件（+ 可选 profile 快照）进 <target>/70-tools/。

    70-verify 是 done 门禁；72 三件套（assemble-draft / compose-raster-figures /
    latex-build-check）随技能发货，免得每个论文项目重建一遍排版工具链；40-style-check /
    45-consistency-check 是 social 档两条 run: 的项目侧执行前提。B04 起走
    :func:`_atomic_install`（冲突预检 + 可写性预检 + 原子搬移 + 回滚）。
    """
    files = [("70-tools/" + dst, HERE / src_rel) for src_rel, dst in _PROJECT_FILES]
    if profile:
        # A8（2026-10-07 审查）：曾把 --profile ../SKILL.md 解析成 profiles/../SKILL.md 并
        # 拷进 70-tools/SKILL.md（越界落盘）；绝对路径还触发 SameFileError 裸崩。
        # 现只取 basename，并要求解析结果确实落在 profiles/ 子树且存在，否则用法错 rc=2。
        name = Path(profile).name
        if name.startswith("00-"):
            # B04（round3 A-15）：基类档可装但生成器随即 rc=2（无独立任务）——属误装，拒装。
            die("--profile 不得为 `00-` 前缀基类档（%s）：基类可装但生成器随即 rc=2，拒装" % name)
        profiles_root = (HERE / "profiles").resolve()
        src = (HERE / "profiles" / name).resolve()
        if src.parent != profiles_root or not src.is_file():
            die("--profile 须为 profiles/ 下的文件名（收到 %r）：解析后 %s 不在 profiles/ 子树或不存在"
                % (profile, src))
        files.append(("70-tools/profiles/" + name, src))
    _atomic_install(target, files, force)
    if not (target / ".orchd").exists():
        print("hint  目标项目未安装 orchd 引擎——请先按 orchd-core 的安装器接入"
              "（本安装器不代装引擎，单一职责）。")


def verify_project_install(target: Path, profile: str | None) -> list:
    """B04（round3 A-15）：project 模式**逐件字节校验**（此前零完整性断言）。"""
    bad = []
    for src_rel, dst in _PROJECT_FILES:
        p = target / "70-tools" / dst
        if not p.is_file() or p.read_bytes() != (HERE / src_rel).read_bytes():
            bad.append("70-tools/%s 缺失或内容不一致" % dst)
    if profile:
        name = Path(profile).name
        p = target / "70-tools" / "profiles" / name
        if not p.is_file() or p.read_bytes() != (HERE / "profiles" / name).read_bytes():
            bad.append("70-tools/profiles/%s 缺失或内容不一致" % name)
    return bad


def verify_skill_install(target: Path, entries: list) -> list:
    """装配完整性断言：清单逐项在盘且字节一致；清单内不得出现开发层路径。

    A7（2026-10-07 审查）：旧版对 DEV_ABSENT 逐项检查**目标目录是否已存在**该路径，于是
    目标目录原本就有 `.gitignore`/`docs` 的常见场景恒被判「开发层泄漏」（假阳性 rc=1）。
    安装器的唯一写入面是清单 entries，故开发层泄漏的真正判据是「清单是否列入开发层路径」，
    与目标目录既有内容无关。
    """
    bad = []
    for rel in entries:
        dst = target / rel
        if not dst.is_file():
            bad.append("清单项缺失：%s" % rel)
        elif dst.read_bytes() != (HERE / rel).read_bytes():
            bad.append("清单项内容不一致：%s" % rel)
    for rel in entries:
        if any(rel == d or rel.startswith(d + "/") for d in DEV_ABSENT):
            bad.append("开发层文件被列入清单（发布面破损）：%s" % rel)
    return bad


def _force_rmtree(root: Path) -> None:
    """best-effort 删除目录：只读位（Windows）先清再删；单文件失败不中断整体。

    B10（2026-10-07 审查）：旧版 shutil.rmtree(ignore_errors=False) 遇占用/只读位即裸
    traceback；本函数用 onerror 清只读位重试，把「删不净」留给调用方显式判 rc=2 + 报残留。
    """
    def _onerror(func, path, exc_info):                      # noqa: ANN001
        try:
            os.chmod(path, stat.S_IWRITE)
            func(path)
        except OSError:
            pass
    shutil.rmtree(root, onerror=_onerror)


def run_smoke(target: Path, tmp: Path) -> None:
    """副本内冒烟：生成器对任一发布 profile 生成 rc=0；判据基座 --schema rc=0。

    R5（round4 R4-2）：子进程输入必须 hermetic——profile 传 target 内**绝对路径**且
    `cwd=str(target)`。旧版传相对 profile 且不设 cwd：cwd 在开发仓根时 30 号实际读到
    开发仓的 profiles/（extends 同落开发仓，冒名冒烟、假绿方向）；cwd 下无仓时
    rc=2（profile not found）。修后「副本自足」是真断言：target 缺 profiles 即冒烟红，
    与调用方 cwd 无关。
    """
    gen = target / "scripts" / "30-gen-proposals.py"
    prof = target / "profiles" / "10-materials-chemistry.yaml"
    r = subprocess.run([sys.executable, "-B", "-X", "utf8", str(gen),
                        "--profile", str(prof),
                        "--out", str(tmp / "smoke-out")],
                       capture_output=True, text=True, encoding="utf-8", errors="replace",
                       cwd=str(target), timeout=60)
    if r.returncode != 0:
        die("副本内生成器冒烟失败 rc=%d\n%s" % (r.returncode, (r.stdout + r.stderr)[-400:]))
    ver = target / "scripts" / "70-verify.py"
    r = subprocess.run([sys.executable, "-B", "-X", "utf8", str(ver), "--schema"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace",
                       cwd=str(target), timeout=60)
    if r.returncode != 0:
        die("副本内判据基座 --schema 冒烟失败 rc=%d\n%s" % (r.returncode, (r.stdout + r.stderr)[-400:]))


def selftest() -> int:
    """离线自测：临时目录双模式装配 + 完整性断言 + 副本冒烟 + --cleanup 拒绝护栏。"""
    import tempfile
    entries = read_manifest()
    failures = []
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        target = tmp / "skill-copy"
        target.mkdir()
        install_skill(target, entries)
        bad = verify_skill_install(target, entries)
        failures += bad
        print("  skill 模式装配（%d 文件，清单逐项一致 + 开发层缺席）  %s"
              % (len(entries), "OK" if not bad else "MISMATCH %s" % bad[:2]))
        if not bad:
            run_smoke(target, tmp)
            print("  副本内冒烟（30 号生成 rc=0 / 70 号 --schema rc=0）  OK")
            # R5（round4 R4-2 反向对照）：从副本删一份 profile 后冒烟必须红——旧版因冒名
            # 开发仓真源而保持绿，本对照在旧版下不红。子进程 probe 刻意以 tmp 为 cwd
            # （无仓目录），证明冒烟与调用方 cwd 无关；run_smoke 自身 die 即非零退出。
            (target / "profiles" / "10-materials-chemistry.yaml").unlink()
            probe = tmp / "smoke-neg-probe.py"
            probe.write_text(
                "import sys; sys.path.insert(0, %r); "
                "from pathlib import Path; "
                "from install import run_smoke; "
                "run_smoke(Path(%r), Path(%r))\n"
                % (str(HERE), str(target), str(tmp / "smoke-neg-out")),
                encoding="utf-8")
            r = subprocess.run([sys.executable, "-B", "-X", "utf8", str(probe)],
                               capture_output=True, text=True, encoding="utf-8",
                               errors="replace", cwd=str(tmp), timeout=60)
            ok_neg = r.returncode != 0
            print("  副本缺 profile 冒烟必红（自足真断言反向对照）  %s"
                  % ("OK" if ok_neg else "MISMATCH rc=%d" % r.returncode))
            if not ok_neg:
                failures.append("副本缺 profile 冒烟未红（自足断言仍冒名）")
        # project 模式
        ptarget = tmp / "paper-project"
        ptarget.mkdir()
        install_project(ptarget, "10-materials-chemistry.yaml")
        vbase = ptarget / "70-tools" / "70-verify.py"
        ok_p = vbase.is_file() and (ptarget / "70-tools" / "profiles" / "10-materials-chemistry.yaml").is_file()
        if ok_p:
            r = subprocess.run([sys.executable, "-B", "-X", "utf8", str(vbase), "--schema"],
                               capture_output=True, text=True, encoding="utf-8",
                               errors="replace", timeout=60)
            ok_p = r.returncode == 0
        print("  project 模式装配（70-tools 基座 + profile 快照 + --schema）  %s"
              % ("OK" if ok_p else "MISMATCH"))
        if not ok_p:
            failures.append("project 模式装配失败")
        # F19：LaTeX 三件套必须随 project 模式 vendor 到 70-tools/，且各自 --selftest 真跑 rc=0。
        # 「在盘」不够——脚本可能自身坏掉（语法错、依赖缺失、降级路径走错），故真跑一遍。
        for name in ("72-assemble-draft.py", "72-compose-raster-figures.py", "72-latex-build-check.py"):
            tool = ptarget / "70-tools" / name
            if not tool.is_file():
                print("  project 模式 vendor 72 三件套：%s  MISSING（未 vendor）" % name)
                failures.append("project 模式未 vendor %s" % name)
                continue
            r = subprocess.run([sys.executable, "-B", "-X", "utf8", str(tool), "--selftest"],
                               capture_output=True, text=True, encoding="utf-8",
                               errors="replace", timeout=90, check=False)
            tail = (r.stdout or "").strip().splitlines()[-1:] or [""]
            print("  project 模式 72 工具 selftest %-28s rc=%d  %s"
                  % (name, r.returncode, "OK" if r.returncode == 0 else "MISMATCH"))
            if r.returncode != 0:
                failures.append("%s --selftest rc=%d（%s）" % (name, r.returncode, tail[0][:60]))
        # 幂等：同一目标重复安装仍完整一致
        install_skill(target, entries)
        bad2 = verify_skill_install(target, entries)
        print("  幂等重装（第二次装配后完整性复验）  %s" % ("OK" if not bad2 else "MISMATCH"))
        if bad2:
            failures += bad2
        # --cleanup 护栏（脏 git 源）：**构造**一个带未提交改动的临时 git 源。
        # 旧实现直接拿本仓当源、断言「源脏才拒绝」。这既不安全也不可靠：done 前实现者通常
        # 已把改动 commit 掉，源变干净 → 护栏不触发 → 代码一路走到 shutil.rmtree(HERE)
        # 真去删源目录。本机仅因 Windows 文件占用才没删成（rc!=0，但 traceback 里没有
        # "cleanup" 字样 → 断言反而判 MISMATCH，报了个与真因无关的错）。故改为构造源。
        dirty_src = tmp / "dirty-git-src"
        dirty_src.mkdir()
        shutil.copy2(HERE / "install.py", dirty_src / "install.py")
        (dirty_src / "MANIFEST.in").write_text("include fake.md\n", encoding="utf-8")
        (dirty_src / "fake.md").write_text("fake\n", encoding="utf-8")
        (dirty_src / "VERSION").write_text("v0.0.0-test\n", encoding="utf-8")
        subprocess.run(["git", "init", "-q"], cwd=str(dirty_src), capture_output=True)
        subprocess.run(["git", "-C", str(dirty_src), "add", "-A"], capture_output=True)
        # 故意不 commit —— status --porcelain 非空即「脏」，护栏必须据此拒绝自删。
        ddst = tmp / "dirty-dst"
        ddst.mkdir()
        r = subprocess.run([sys.executable, "-B", "-X", "utf8", str(dirty_src / "install.py"),
                            str(ddst), "--mode", "skill", "--cleanup"],
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace", cwd=str(tmp), timeout=60)
        blob = (r.stdout or "") + (r.stderr or "")
        refused = (r.returncode != 0 and "cleanup" in blob.lower()
                   and (dirty_src / "install.py").exists())
        print("  --cleanup 护栏（脏 git 源拒绝自删且源完好）  %s" % ("OK" if refused else "MISMATCH"))
        if not refused:
            failures.append("cleanup 护栏（脏 git 源）未生效")
        # --cleanup 护栏（非 git 源，审查 P1）：源不是 git 仓库（git 不可用/无 .git）时
        # 旧判定会绕过护栏直接删除源文件。此处构造非 git 临时源复现该场景，必须拒绝且源完好。
        nongit_src = tmp / "nongit-src"
        nongit_src.mkdir()
        shutil.copy2(HERE / "install.py", nongit_src / "install.py")
        (nongit_src / "MANIFEST.in").write_text("include fake.md\n", encoding="utf-8")
        (nongit_src / "fake.md").write_text("fake\n", encoding="utf-8")
        (nongit_src / "VERSION").write_text("v0.0.0-test\n", encoding="utf-8")
        ndst = tmp / "nongit-dst"
        ndst.mkdir()
        r = subprocess.run([sys.executable, "-B", "-X", "utf8", str(nongit_src / "install.py"),
                            str(ndst), "--mode", "skill", "--cleanup"],
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace", cwd=str(tmp), timeout=60)
        refused = (r.returncode != 0
                   and "cleanup" in ((r.stdout or "") + (r.stderr or "")).lower()
                   and (nongit_src / "install.py").exists())
        print("  --cleanup 护栏（非 git 源拒绝自删且源完好）  %s" % ("OK" if refused else "MISMATCH"))
        if not refused:
            failures.append("cleanup 护栏（非 git 源）未生效")

        # ── A7/A8/B10/B11（2026-10-07 审查）──────────────────────────────────
        # A7：目标目录预置 .gitignore/docs 不属「开发层泄漏」（旧版恒假阳性 rc=1）
        a7 = tmp / "a7-target"
        a7.mkdir()
        (a7 / ".gitignore").write_text("# pre-existing\n", encoding="utf-8")
        (a7 / "docs").mkdir()
        r = subprocess.run([sys.executable, "-B", "-X", "utf8", str(HERE / "install.py"),
                            str(a7), "--mode", "skill"],
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace", cwd=str(tmp), timeout=120)
        ok_a7 = r.returncode == 0
        print("  A7 目标预置 .gitignore/docs 的 skill 装配（假阳性修复）  %s"
              % ("OK" if ok_a7 else "MISMATCH rc=%d" % r.returncode))
        if not ok_a7:
            failures.append("A7 预置 .gitignore 仍被判泄漏 rc=%d" % r.returncode)
        # A8：--profile 越界（相对 ../ 与绝对路径）必须 rc=2 且不落 70-tools/SKILL.md
        for tag, bad_profile in (("rel", "../SKILL.md"), ("abs", str(HERE / "SKILL.md"))):
            a8 = tmp / ("a8-" + tag)
            a8.mkdir()
            r = subprocess.run([sys.executable, "-B", "-X", "utf8", str(HERE / "install.py"),
                                str(a8), "--mode", "project", "--profile", bad_profile],
                               capture_output=True, text=True, encoding="utf-8",
                               errors="replace", cwd=str(tmp), timeout=60)
            ok_a8 = (r.returncode == 2 and not (a8 / "70-tools" / "SKILL.md").exists())
            print("  A8 --profile 越界 (%s) -> rc=2 且无越界产物  %s"
                  % (tag, "OK" if ok_a8 else "MISMATCH rc=%d" % r.returncode))
            if not ok_a8:
                failures.append("A8 --profile 越界未拦：%s rc=%d" % (tag, r.returncode))
        # B11：坏输入（清单列不在盘文件）必须 rc=2（旧版 rc=1）
        broken_src = tmp / "broken-src"
        broken_src.mkdir()
        shutil.copy2(HERE / "install.py", broken_src / "install.py")
        (broken_src / "MANIFEST.in").write_text("include nope.md\n", encoding="utf-8")
        bdst = tmp / "broken-dst"
        bdst.mkdir()
        r = subprocess.run([sys.executable, "-B", "-X", "utf8", str(broken_src / "install.py"),
                            str(bdst), "--mode", "skill"],
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace", cwd=str(tmp), timeout=60)
        ok_b11 = r.returncode == 2
        print("  B11 坏输入（清单列缺件）-> rc=2  %s"
              % ("OK" if ok_b11 else "MISMATCH rc=%d" % r.returncode))
        if not ok_b11:
            failures.append("B11 坏输入未归 rc=2（实 rc=%d）" % r.returncode)
        # B10：--cleanup 接受路径（干净 clone）真删成功且 rc=0
        clone = tmp / "clean-clone"
        clone.mkdir()
        shutil.copy2(HERE / "install.py", clone / "install.py")
        (clone / "MANIFEST.in").write_text("include install.py\ninclude fake.md\n", encoding="utf-8")
        (clone / "fake.md").write_text("x\n", encoding="utf-8")
        subprocess.run(["git", "init", "-q"], cwd=str(clone), capture_output=True)
        subprocess.run(["git", "-C", str(clone), "add", "-A"], capture_output=True)
        subprocess.run(["git", "-C", str(clone), "-c", "user.email=t@t", "-c", "user.name=t",
                        "commit", "-qm", "base"], capture_output=True)
        ctarget = tmp / "clean-dst"
        ctarget.mkdir()
        r = subprocess.run([sys.executable, "-B", "-X", "utf8", str(clone / "install.py"),
                            str(ctarget), "--mode", "skill", "--cleanup"],
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace", cwd=str(tmp), timeout=120)
        ok_b10 = (r.returncode == 0 and not clone.exists())
        print("  B10 --cleanup 接受路径（干净 clone 真删）rc=0 且源删净  %s"
              % ("OK" if ok_b10 else "MISMATCH rc=%d remain=%s" % (r.returncode, clone.exists())))
        if not ok_b10:
            failures.append("B10 cleanup 接受路径失败 rc=%d remain=%s" % (r.returncode, clone.exists()))

        # ── C13/E2（2026-10-07 审查）────────────────────────────────────────
        # C13a：--mode skill 传 --profile 必须 rc=2（旧版静默忽略，用户以为装了档）
        c13a = tmp / "c13a"
        c13a.mkdir()
        r = subprocess.run([sys.executable, "-B", "-X", "utf8", str(HERE / "install.py"),
                            str(c13a), "--mode", "skill", "--profile", "10-materials-chemistry.yaml"],
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace", cwd=str(tmp), timeout=60)
        ok_c13a = r.returncode == 2
        print("  C13 --mode skill + --profile -> rc=2（不静默忽略）  %s"
              % ("OK" if ok_c13a else "MISMATCH rc=%d" % r.returncode))
        if not ok_c13a:
            failures.append("C13 skill+profile 未归 rc=2（实 rc=%d）" % r.returncode)
        # C13b：target 指向已存在文件 → rc=2 脱敏（旧版裸 FileExistsError）
        afile = tmp / "existing-file"
        afile.write_text("x\n", encoding="utf-8")
        r = subprocess.run([sys.executable, "-B", "-X", "utf8", str(HERE / "install.py"),
                            str(afile), "--mode", "skill"],
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace", cwd=str(tmp), timeout=60)
        blob = (r.stdout or "") + (r.stderr or "")
        ok_c13b = r.returncode == 2 and "Traceback" not in blob
        print("  C13 target 指向已存在文件 -> rc=2 且无 Traceback  %s"
              % ("OK" if ok_c13b else "MISMATCH rc=%d" % r.returncode))
        if not ok_c13b:
            failures.append("C13 target 文件未归 rc=2（实 rc=%d）" % r.returncode)
        # E2：模板逐字复制到项目后，70-verify 不得因条目内 _ 注记键判 rc=2（键即契约）。
        tpl = tmp / "tpl-project"
        (tpl / "70-tools").mkdir(parents=True)
        shutil.copy2(HERE / "assets" / "10-verify-manifest.template.json",
                     tpl / "70-tools" / "71-verify-manifest.json")
        r = subprocess.run([sys.executable, "-B", "-X", "utf8", str(HERE / "scripts" / "70-verify.py"),
                            "task-<id>-示例-产物文件", "--quiet", "--root", str(tpl),
                            "--manifest", str(tpl / "70-tools" / "71-verify-manifest.json")],
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace", cwd=str(tmp), timeout=60)
        out = (r.stdout or "") + (r.stderr or "")
        ok_e2 = r.returncode != 2 and "未知键" not in out and "形态不合" not in out
        print("  E2 模板逐字复制后 70-verify 不因 _ 注记键 rc=2  %s"
              % ("OK" if ok_e2 else "MISMATCH rc=%d %s" % (r.returncode, out[-80:])))
        if not ok_e2:
            failures.append("E2 模板内 _ 注记键触发形态错 rc=2（实 rc=%d）" % r.returncode)
        # ── B04（round3）：删源位置护栏 + 00- 基类档拒装 ─────────────────────
        # R5（round4 R4-1）：拒绝侧样本不得是本仓自身（HERE）——仓落在 %TEMP% 下
        # （README 教的 git clone $env:TEMP 流程、zip 解临时目录、部分 CI）时判据合法地
        # 判「允许」，用例假设塌 → install --selftest rc=1 并连锁 76 G0b 假红。
        # 改用与被删/被留对象无关的构造路径：tmp 内允许、tempdir.parent 按定义拒绝。
        # 本断言至此与本仓落盘位置、调用方 cwd 彻底无关（A-3 同族第四次复发即此根治）。
        tmp_outside = Path(tempfile.gettempdir()).resolve().parent
        ok_b04a = cleanup_allowed(tmp) and not cleanup_allowed(tmp_outside)
        print("  B04 删源位置护栏（tmp 内允许 / temp 外拒绝，与本仓位置无关）  %s"
              % ("OK" if ok_b04a else "MISMATCH"))
        if not ok_b04a:
            failures.append("B04 cleanup_allowed 位置判据失效")
        b04_00 = tmp / "b04-00"
        b04_00.mkdir()
        r = subprocess.run([sys.executable, "-B", "-X", "utf8", str(HERE / "install.py"),
                            str(b04_00), "--mode", "project", "--profile", "00-base-empirical.yaml"],
                           capture_output=True, text=True, encoding="utf-8", errors="replace",
                           cwd=str(tmp), timeout=60)
        ok_b04b = r.returncode == 2
        print("  B04 00- 基类档拒装 -> rc=2  %s"
              % ("OK" if ok_b04b else "MISMATCH rc=%d" % r.returncode))
        if not ok_b04b:
            failures.append("B04 00- 基类档未拒装（rc=%d）" % r.returncode)
        # B04：冲突护栏（目标已有不同内容文件 → 默认拒；--force 才覆盖）
        cft = tmp / "conflict-target"
        cft.mkdir()
        (cft / "SKILL.md").write_text("EXISTING DIFFERENT CONTENT\n", encoding="utf-8")
        r = subprocess.run([sys.executable, "-B", "-X", "utf8", str(HERE / "install.py"),
                            str(cft), "--mode", "skill"],
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace", cwd=str(tmp), timeout=60)
        ok_conf = r.returncode == 2 and (cft / "SKILL.md").read_text(
            encoding="utf-8").startswith("EXISTING")
        r2 = subprocess.run([sys.executable, "-B", "-X", "utf8", str(HERE / "install.py"),
                             str(cft), "--mode", "skill", "--force"],
                            capture_output=True, text=True, encoding="utf-8",
                            errors="replace", cwd=str(tmp), timeout=60)
        ok_force = r2.returncode == 0 and not (cft / "SKILL.md").read_text(
            encoding="utf-8").startswith("EXISTING")
        print("  B04 冲突护栏（默认拒覆盖 rc=2 / --force 覆盖 rc=0）  %s"
              % ("OK" if (ok_conf and ok_force) else "MISMATCH rc=%d/%d" % (r.returncode, r2.returncode)))
        if not (ok_conf and ok_force):
            failures.append("B04 冲突护栏失效 rc=%d/%d" % (r.returncode, r2.returncode))
        # B04：project 模式逐件字节校验（对已装配的 ptarget）
        ok_pv = verify_project_install(ptarget, "10-materials-chemistry.yaml") == []
        print("  B04 project 模式逐件字节校验  %s" % ("OK" if ok_pv else "MISMATCH"))
        if not ok_pv:
            failures.append("B04 project 逐件字节校验失败")
        # B09（C-3，install 侧）：vendor 六件版本戳可解析且 sha 非空——
        # provenance() 写入 PROVENANCE 的逐件记录即出自 vendor_tool_records()，
        # 此处先钉死"戳在位且可解析"，两端一致性由 75 号守卫同一断言正反判定。
        vrec = vendor_tool_records()
        ok_v = (set(vrec) == {"70-verify.py", "72-assemble-draft.py",
                              "72-compose-raster-figures.py", "72-latex-build-check.py",
                              "40-style-check.py", "45-consistency-check.py"}
                and all(v["version"] and v["sha256"] for v in vrec.values()))
        print("  B09 vendor 六件版本戳可解析且逐件 sha 非空  %s"
              % ("OK" if ok_v else "MISMATCH %s" % vrec))
        if not ok_v:
            failures.append("B09 vendor 版本戳/逐件 sha 缺失：%s" % vrec)
        # B04/F2（复审）：目标存在同名**目录** → 冲突 rc=2 且目录及内容完好（不静默吞掉）
        dirconf = tmp / "dir-conflict"
        (dirconf / "SKILL.md").mkdir(parents=True)
        (dirconf / "SKILL.md" / "user.txt").write_text("u\n", encoding="utf-8")
        r = subprocess.run([sys.executable, "-B", "-X", "utf8", str(HERE / "install.py"),
                            str(dirconf), "--mode", "skill"],
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace", cwd=str(tmp), timeout=60)
        ok_dir = r.returncode == 2 and (dirconf / "SKILL.md" / "user.txt").is_file()
        print("  B04/F2 目标同名目录 → 冲突 rc=2 且目录完好  %s"
              % ("OK" if ok_dir else "MISMATCH rc=%d" % r.returncode))
        if not ok_dir:
            failures.append("B04/F2 同名目录未判冲突（rc=%d）" % r.returncode)
    if failures:
        print("SELFTEST FAIL（%d）：%s" % (len(failures), failures[:4]))
        return 1
    print("SELFTEST PASS  双模式装配 + 冒烟 + 幂等 + cleanup 护栏×2（脏 git 源 / 非 git 源）"
          " + A7 预置 .gitignore + A8 profile 越界×2 + B10 cleanup 接受路径 + B11 坏输入 rc=2"
          " + C13 skill+profile/target文件 rc=2 + E2 模板无 _ 注记键 + B09 vendor 版本戳与逐件 sha")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="paper-pipeline 技能安装器")
    ap.add_argument("target", nargs="?", help="安装目标目录")
    ap.add_argument("--mode", choices=("skill", "project"), default="skill")
    ap.add_argument("--profile", help="project 模式：随基座一起快照的领域档（传 profiles/<名>，与 30-gen 同口径；只取文件名，裸名亦兼容）")
    ap.add_argument("--cleanup", action="store_true",
                    help="安装成功后删除源目录（仅限系统临时目录之下的干净 git clone："
                         "位置 + 干净双重约束，开发仓/正式仓一律拒绝）")
    ap.add_argument("--force", action="store_true",
                    help="目标已有不同内容文件时覆盖（默认拒绝并列出冲突清单）")
    ap.add_argument("--selftest", action="store_true", help="离线自测（临时目录，用毕即删）")
    a = ap.parse_args()

    if a.selftest:
        return selftest()
    if not a.target:
        die("缺少 <target>（或用 --selftest）")
    # C13（2026-10-07 审查）：skill 模式不接受 --profile（旧版静默忽略，用户以为装了档）。
    if a.mode == "skill" and a.profile:
        die("--profile 仅 project 模式有效；--mode skill 不接受 --profile（收到 %r）" % a.profile)
    target = Path(a.target).resolve()
    if target == HERE:
        die("target 不得等于源目录（%s）" % HERE)
    # C13：target 指向已存在文件时，旧版在 dst.parent.mkdir 处裸崩（FileExistsError）。
    if target.exists() and not target.is_dir():
        die("target 已存在且不是目录（%s）——安装目标须是目录或尚不存在" % target)
    entries = read_manifest()

    if a.mode == "skill":
        install_skill(target, entries, a.force)
        bad = verify_skill_install(target, entries)
        if bad:
            die("装配完整性断言失败（已停止，不触发 cleanup）：\n  " + "\n  ".join(bad[:6]))
        n = len(entries)
    else:
        install_project(target, a.profile, a.force)
        bad = verify_project_install(target, a.profile)
        if bad:
            die("project 装配完整性断言失败（逐件字节校验）：\n  " + "\n  ".join(bad[:6]))
        n = 7 + (1 if a.profile else 0)          # 判据基座 2 件 + LaTeX 三件套 3 件 + 40/45 机检 2 件（+ profile 快照）

    prov = provenance(a.mode, n)
    (target / "PROVENANCE.json").write_text(
        json.dumps(prov, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("installed: %d files -> %s (%s; version %s)"
          % (n, target, a.mode, prov["version"]))
    # E4：PROVENANCE.json 是安装痕迹（含 version/commit/时间），建议目标项目 gitignore 之。
    print("hint  PROVENANCE.json 为安装痕迹，建议加入目标项目 .gitignore"
          "（source 已脱敏、不含本机绝对路径，但 commit/时间仍属本机元数据）。")

    if a.cleanup:
        # B04（round3 A-1）：删源硬约束——源必须在系统临时目录之下。任何刚提交完的开发仓与
        # 临时克隆在「工作树干净」判据上同形（本轮本仓被删空一次），故先按**位置**拒删。
        if not cleanup_allowed(HERE):
            die("--cleanup 已拒绝：源目录不在系统临时目录之下（%s）——开发仓/正式仓不得自删。"
                "清理临时克隆请把 clone 放在系统临时目录（%s）之下。本次安装不受影响。"
                % (HERE.resolve(), Path(tempfile.gettempdir()).resolve()))
        # 删前逐件校验：源仍须像本技能 clone，避免误删异类目录。
        if not (HERE / "install.py").is_file() or not (HERE / "MANIFEST.in").is_file():
            die("--cleanup 已拒绝：源目录不含 install.py/MANIFEST.in（非本技能 clone？）。")
        status = _git(["status", "--porcelain"])
        # P1（2026-10-05 审查实锤）：_git 在源不是 git 仓库 / git 不可用时返回 None，
        # 旧判定 `if status:` 对 None 为假 → 直接删除源。必须把"无法确认干净 clone"
        # 与"确认不干净"同等对待，一律拒绝。
        if status is None or status:
            die("--cleanup 已拒绝：源目录不是干净的 git clone（非 git 仓库、"
                "git 不可用或存在未提交内容，均不可自删）。本次安装不受影响。")
        _force_rmtree(HERE)
        if HERE.exists():
            remaining = sorted(str(p.relative_to(HERE)) for p in HERE.rglob("*"))[:10]
            die("--cleanup 未能删净源目录，残留（前 10 项）：%s" % remaining)
        print("cleanup: 源 clone 已删除")
    return 0


if __name__ == "__main__":
    sys.exit(main())
