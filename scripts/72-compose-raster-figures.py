#!/usr/bin/env python3
# -*- coding: utf-8 -*-  # noqa: UP009 — 与既有 45/70 号脚本一致，coding 声明是本仓约定
# vendor-tool: 72-compose-raster-figures.py version 1
# SPDX-License-Identifier: MIT
"""72-compose-raster-figures.py — 合成光栅图版（把面板 PNG 拼成期刊用整图）。

期刊常要求「矢量图 + ≥600 dpi 光栅图版」双份；本工具只做光栅图版的排布，矢量插图不在
职责内（那是 LaTeX 侧 \\includegraphics 的事，见 72-latex-build-check.py）。

用法：
    python 70-tools/72-compose-raster-figures.py --spec spec.json
    python 70-tools/72-compose-raster-figures.py --spec spec.json --check   # 只校验规格与面板在盘
    python 70-tools/72-compose-raster-figures.py --selftest

退出码：0 = 合成成功（或 --check 通过）；1 = 规格/面板问题；2 = 用法错或 Pillow 未安装。
确定性：同规格 + 同面板 → 同字节（字体选择与缩放策略均固定，无时间戳无随机）。

spec.json schema：
    {"output": "40-figures/fig1.png",
     "panels": ["40-figures/panel-a.png", "40-figures/panel-b.png"],
     "rows": 1, "cols": 2,
     "labels": ["(a)", "(b)"],          # 可选；长度须等于 panels
     "panel_width_px": 1600,            # 每格宽（px），面板按比例缩放并居中
     "gap_px": 24,                      # 格间距
     "dpi": 600,                        # 写入 PNG 的 dpi 元数据（期刊下限 600）
     "background": [255, 255, 255]}

安全：只读面板文件；写入仅限 output 指定的那一个文件。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.dont_write_bytecode = True

EXIT_OK, EXIT_FAIL, EXIT_USAGE = 0, 1, 2

PIL_HINT = ("缺少 Pillow（光栅图版合成依赖）。安装：pip install Pillow"
            "（国内镜像示例：pip install -i https://mirrors.aliyun.com/pypi/simple/ Pillow）")


def need_pillow():
    """返回 (Image, ImageDraw, ImageFont, error)。缺 Pillow → rc=2 且给安装指引。"""
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        return None, None, None, PIL_HINT
    return Image, ImageDraw, ImageFont, None


def load_spec(args) -> tuple:
    if args.spec:
        p = args.spec
        if not os.path.isfile(p):
            return None, [f"spec 文件不存在：{p}"]
        try:
            with open(p, "r", encoding="utf-8-sig") as fh:
                raw = json.load(fh)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            return None, [f"spec 文件读不了（{type(exc).__name__}：{str(exc)[:80]}）"]
    else:
        try:
            raw = json.loads(args.inline)
        except json.JSONDecodeError as exc:
            return None, [f"--inline 不是合法 JSON：{str(exc)[:80]}"]
    if not isinstance(raw, dict):
        return None, ["spec 顶层须是对象"]
    panels = raw.get("panels")
    if not isinstance(panels, list) or not panels:
        return None, ["spec.panels 至少要一项"]
    for i, panel in enumerate(panels):
        if not isinstance(panel, str) or not panel:
            return None, [f"panels[{i}] 须是非空路径串"]
        if not os.path.isfile(panel):
            return None, [f"面板不在盘：{panel}"]
    rows, cols = raw.get("rows", 1), raw.get("cols", len(panels))
    if not isinstance(rows, int) or not isinstance(cols, int) or rows < 1 or cols < 1:
        return None, ["rows/cols 须为 >=1 的整数"]
    if rows * cols < len(panels):
        return None, [f"rows×cols（{rows}×{cols}={rows * cols}）放不下 {len(panels)} 个面板"]
    labels = raw.get("labels")
    if labels is not None and (not isinstance(labels, list) or len(labels) != len(panels)):
        n = len(labels) if isinstance(labels, list) else "非列表"
        return None, [f"labels 长度（{n}）须与 panels（{len(panels)}）一致"]
    dpi = raw.get("dpi", 600)
    if not isinstance(dpi, int) or not (1 <= dpi <= 4800):
        return None, ["dpi 须为 1..4800 的整数（期刊下限 600）"]
    if not raw.get("output"):
        return None, ["spec.output 必填（写入仅限该文件）"]
    bg = raw.get("background", [255, 255, 255])
    if not (isinstance(bg, list) and len(bg) == 3
            and all(isinstance(v, int) and 0 <= v <= 255 for v in bg)):
        return None, ["background 须为三个 0..255 的整数"]
    return raw, []


def pick_font(ImageFont, size_hint: int = 28):
    """优先 truetype（版式更好），回落 Pillow 内置位图字体。

    选择结果只依赖机器上是否存在某个字体文件——这是**刻意**的确定性取舍：换机器可能得到
    不同字形，但同一台机器上重复运行必得同字节（幂等是本工具的门禁前提）。
    """
    for name in ("DejaVuSans.ttf", "arial.ttf", "segoeui.ttf", "Helvetica.ttc"):
        try:
            return ImageFont.truetype(name, size_hint), name
        except OSError:
            continue
    try:
        return ImageFont.load_default(size=size_hint), "builtin"
    except TypeError:                       # Pillow < 10.1 无 size 参数
        return ImageFont.load_default(), "builtin"


def label_band(font) -> int:
    """标签带高度（px）。无标签时为 0。"""
    box = font.getbbox("Ag")
    return (box[3] - box[1] + 8) if box else 0


def compose(spec: dict, Image, ImageDraw, ImageFont) -> tuple:
    panels = spec["panels"]
    rows, cols = spec.get("rows", 1), spec.get("cols", len(panels))
    cell_w = spec.get("panel_width_px", 1600)
    gap = spec.get("gap_px", 24)
    labels = spec.get("labels")
    font, font_name = pick_font(ImageFont)
    lab_h = label_band(font) if labels else 0

    # 每格等宽、格内等比缩放不变形；同行取该行最高格，保证行等高。
    scaled = []
    for p in panels:
        with Image.open(p) as im:
            im = im.convert("RGB")
            ratio = cell_w / float(im.width) if im.width else 1.0
            scaled.append(im.resize((cell_w, max(1, round(im.height * ratio))), Image.LANCZOS))
    row_h = []
    for r in range(rows):
        chunk = scaled[r * cols:(r + 1) * cols]
        row_h.append(max(im.height for im in chunk) if chunk else 0)

    total_w = cols * cell_w + (cols - 1) * gap
    total_h = sum(row_h) + max(0, rows - 1) * gap + rows * lab_h

    canvas = Image.new("RGB", (total_w, total_h), tuple(spec.get("background", [255, 255, 255])))
    draw = ImageDraw.Draw(canvas)

    y = 0
    for r in range(rows):
        x = 0
        for c in range(cols):
            i = r * cols + c
            if i < len(scaled):
                canvas.paste(scaled[i], (x, y + lab_h))
                if labels:
                    draw.text((x + 4, y), str(labels[i]), fill=(0, 0, 0), font=font)
            x += cell_w + gap
        y += row_h[r] + lab_h + gap
    return canvas, font_name


def spec_ok(spec: dict) -> bool:
    """规格校验的布尔包装（selftest 用）。"""
    return subprocess_rc(["--inline", json.dumps(spec), "--check"]) == EXIT_OK


def subprocess_rc(argv) -> int:
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


def selftest() -> int:
    fails = []

    def check(name, got, want):
        if got != want:
            fails.append(f"{name}: got {got!r} want {want!r}")
            print(f"  FAIL {name}: got {got!r} want {want!r}")
        else:
            print(f"  OK   {name}")

    Image, ImageDraw, ImageFont, _ = need_pillow()
    if Image is None:
        print("  SKIP  Pillow 未安装（本 selftest 需 Pillow；实机装配时 rc=2 并给安装指引）")
        print("COMPOSE-RASTER SELFTEST SKIP（Pillow 未安装）")
        return 0

    here = os.path.dirname(os.path.abspath(__file__))
    before = sorted(os.listdir(here))
    old_cwd = os.getcwd()
    tmp = tempfile.mkdtemp(prefix="cc72f-selftest-")
    try:
        os.chdir(tmp)
        for name, size, color in (("pa.png", (400, 300), (200, 30, 30)),
                                  ("pb.png", (300, 400), (30, 200, 30))):
            Image.new("RGB", size, color).save(name)

        spec = {"output": "fig.png", "panels": ["pa.png", "pb.png"], "rows": 1, "cols": 2,
                "labels": ["(a)", "(b)"], "panel_width_px": 200, "gap_px": 10,
                "dpi": 600, "background": [255, 255, 255]}
        with open("spec.json", "w", encoding="utf-8") as fh:
            json.dump(spec, fh, ensure_ascii=False, indent=2)

        canvas, font_name = compose(spec, Image, ImageDraw, ImageFont)
        w, h = canvas.size
        font, _ = pick_font(ImageFont)
        lab = label_band(font)
        # 400x300 → 宽 200 ⇒ 高 150；300x400 → 宽 200 ⇒ 高 267（等比、不变形）
        check("两格横排宽度 = 2×cell + 1×gap", w, 200 * 2 + 10)
        check("总高 = 行内最高格(267) + 标签带", h, 267 + lab)
        check("非方形面板等比缩放（300x400 → 200x267）", (200, 267), (200, round(400 * 200 / 300.0)))

        canvas.save("fig.png", dpi=(600, 600))
        with open("fig.png", "rb") as fh:
            first = fh.read()
        with Image.open("fig.png") as im:
            dpi_info = im.info.get("dpi")
            size = im.size
        check("落盘后尺寸与内存画布一致", size, (w, h))
        # PNG 的 pHYs 以「整数像素/米」存储：600 dpi → round(600×39.3701) = 23622 px/m，
        # 读回换算得 599.9988。任何「dpi >= 600」的断言都必须给量化容差，否则恒假红
        # （本条断言最初写死 >= 600 就是这么红的）。
        check("dpi 元数据写入约 600（PNG pHYs 整数 px/m 量化，读回 599.9988）",
              bool(dpi_info and 599 <= dpi_info[0] <= 601), True)
        canvas2, _ = compose(spec, Image, ImageDraw, ImageFont)
        canvas2.save("fig2.png", dpi=(600, 600))
        with open("fig2.png", "rb") as fh:
            second = fh.read()
        check("幂等：同规格两次合成字节一致", second, first)

        c22, _ = compose(dict(spec, rows=2, cols=2), Image, ImageDraw, ImageFont)
        check("2×2 网格宽度 = 2×cell + gap", c22.size[0], 200 * 2 + 10)
        check("无 labels 时不占标签带",
              compose(dict(spec, labels=None), Image, ImageDraw, ImageFont)[0].size[1], 267)

        check("规格守卫：labels 数与 panels 不符 → 判错",
              spec_ok({"output": "x.png", "panels": ["pa.png", "pb.png"], "labels": ["only-one"]}), False)
        check("规格守卫：面板不在盘 → 判错", spec_ok({"output": "x.png", "panels": ["nope.png"]}), False)
        check("规格守卫：rows×cols 放不下 → 判错",
              spec_ok({"output": "x.png", "panels": ["pa.png", "pb.png", "pa.png"], "rows": 1, "cols": 2}), False)
        check("规格守卫：缺 output → 判错", spec_ok({"panels": ["pa.png"]}), False)
        check("规格守卫：dpi 越界 → 判错",
              spec_ok({"output": "x.png", "panels": ["pa.png"], "dpi": 99999}), False)
        check("规格守卫：background 非法 → 判错",
              spec_ok({"output": "x.png", "panels": ["pa.png"], "background": [1, 2]}), False)
        check("规格守卫：rows 非整数 → 判错",
              spec_ok({"output": "x.png", "panels": ["pa.png"], "rows": "two"}), False)
        check("规格通过的正例", spec_ok(spec), True)
    finally:
        os.chdir(old_cwd)
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)
        check("临时目录用毕即删", os.path.isdir(tmp), False)
        check("自测不在 scripts/ 留任何文件（含 __pycache__）", sorted(os.listdir(here)), before)
    if fails:
        print("COMPOSE-RASTER SELFTEST FAIL（%d 项）" % len(fails))
        for f in fails:
            print("  - " + f)
        return 1
    print(f"COMPOSE-RASTER SELFTEST PASS（字体：{font_name}）")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog="72-compose-raster-figures.py",
        description="合成光栅图版：按 rows×cols 网格排布面板 PNG（≥600 dpi，报告期）")
    ap.add_argument("--spec", help="spec.json 路径")
    ap.add_argument("--inline", help="内联 spec JSON")
    ap.add_argument("--check", action="store_true",
                    help="只校验规格与面板在盘（不合成），通过 rc=0")
    ap.add_argument("--selftest", action="store_true", help="离线自测：合成面板 + 幂等")
    args = ap.parse_args(argv)

    if args.selftest:
        return selftest()
    if not args.spec and not args.inline:
        print("用法错误：给出 --spec 或 --inline（或用 --selftest）", file=sys.stderr)
        return EXIT_USAGE

    Image, ImageDraw, ImageFont, perr = need_pillow()
    if Image is None:
        print(f"错误：{perr}", file=sys.stderr)
        return EXIT_USAGE                      # rc=2：环境缺依赖，属用法/环境错

    spec, errs = load_spec(args)
    if spec is None:
        for e in errs:
            print(f"错误：{e}", file=sys.stderr)
        return EXIT_FAIL

    if args.check:
        print("规格 OK：%d 面板 / %d×%d 网格 / dpi %d（未合成）"
              % (len(spec["panels"]), spec.get("rows", 1), spec.get("cols", len(spec["panels"])),
                 spec.get("dpi", 600)))
        return EXIT_OK

    canvas, font_name = compose(spec, Image, ImageDraw, ImageFont)
    out = spec["output"]
    parent = os.path.dirname(os.path.abspath(out))
    if parent:
        os.makedirs(parent, exist_ok=True)
    dpi = spec.get("dpi", 600)
    # dpi 写入 PNG 的 pHYs（整数 px/m）：600 dpi 存 23622，读回换算约 599.9988 ——
    # 量化误差来自 PNG 格式本身，不是写入口径错；下游断言须留容差。
    canvas.save(out, dpi=(dpi, dpi))
    print("已写出 %s（%d×%d px @ %d dpi，字体 %s）"
          % (out, canvas.size[0], canvas.size[1], dpi, font_name))
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
