"""说明书 PDF → scene JSON。

  1. pdftoppm 把每页转成 PNG
  2. 抽取（看图）：Claude 逐页读说明书，转录零件清单和每一步印的「N×」，不推测
  3. 组装（看图 + 抽取结果）：Claude 按 SCENE_SCHEMA 写出带坐标和动画的 scene
  4. 校验：scripts/validate.py；有 error 就把错误清单交回 Claude 修，最多 --repairs 轮

用法：
  python3 scripts/pipeline.py manuals/kallax-2x2/manual.pdf --slug kallax-2x2 \
      --name KALLAX --sub "Shelving unit 2×2" --dims 77x77x39 [--lang en|zh]

模型调用见 llm.py：默认走本机的 `claude -p`（用当前登录的 Claude 账号），也可以配 OpenAI 兼容接口（火山方舟 / 豆包等）。
"""
import argparse
import base64
import json
import re
import subprocess
import sys
import time
from pathlib import Path

from m3d_paths import SITE as ROOT, SCHEMA, EXAMPLE, EXAMPLE_EN  # noqa: E402
sys.path.insert(0, str(Path(__file__).resolve().parent))
from validate import validate  # noqa: E402
from llm import SYSTEM, ask_model, describe  # noqa: E402,F401


EXTRACT_PROMPT = """These are all {n} pages of an IKEA assembly manual for {name} ({sub}, outer size {dims} cm W×H×D), in page order. Page numbers are given before each image.

Transcribe what the manual shows. Do not guess counts: copy the "N x" labels exactly as printed. If something is unreadable, say so in "notes".

Return JSON:
{{
  "product": {{"name": "...", "article": "AA-... if printed"}},
  "inventory": [  // the hardware overview pages, plus each distinct panel type you can identify
    {{"id": "H1", "kind": "cam_bolt|screw|dowel|cam_lock|pad|bracket|tool|panel|other",
      "name_en": "short description", "part_number": "printed number or null", "qty": 8, "page": 5, "notes": ""}}
  ],
  "steps": [
    {{"manual_step": "1", "page": 8, "branch": "main",  // use "alt" (or "alt2") for alternative branches such as a different wall-fixing method
      "panels": ["which panels are handled, in your words"],
      "hardware": [{{"ref": "H2", "qty_printed": 2}}],   // only counts printed on this step
      "tools": ["allen key", "hammer", ...],
      "action": "what happens, precisely: which panel joins which, where the holes are, direction of the arrows",
      "warnings": ["info boxes, do/don't icons, two-person icons"]}}
  ],
  "notes": "anything ambiguous, e.g. step numbering restarting for alternative branches"
}}
Panels: give them inventory ids P1, P2... with qty (count how many of each the drawings show) and the role (outer side, outer top/bottom, inner divider...). Hardware ids start with H."""

COMPOSE_PROMPT = """Build an animated 3D assembly scene for {name} ({sub}). Outer size {dims} cm (W×H×D). {notes}

Inputs:
1. The scene format spec (below). Follow it exactly.
2. The transcription of the manual (below), produced from the page images. Treat its counts as ground truth.
3. The step pages of the manual (images), so you can see where each hole, dowel and bolt goes.
4. A FORMAT EXAMPLE of a hand-written scene for a different, simplified assembly order. Copy its style (short UI text, short spoken lines, camera framing, timing, arrows and callouts), NOT its structure: the real manual's order and panel layout win.

Requirements:
- Follow the main branch of the manual step by step; you may merge trivial steps, but every scene step must list its source manual_steps and pages. Skip alternative branches, but mention them in a tip.
- Every part in "parts" that corresponds to inventory must have "source" = the inventory id. Instance counts per part must not exceed inventory qty, and the hardware newly introduced in each scene step must equal the "qty_printed" numbers of its source manual steps exactly.
- Compute coordinates carefully: panels touch but never interpenetrate; each piece of hardware has its pos exactly on a panel face and its axis pointing out of that face. Work out thicknesses so the outer size matches.
- Use the right geometry: rotated boxes ("rot") for slanted legs, "cylinder" for round legs and rods, "extrude" for shaped panels; never approximate a slanted or round part as an upright box. Mark countersunk bolts and screws that end flush with the surface as "flush": true.
- If a step genuinely cannot be shown clearly in 3D (dozens of nails into a back panel, drawer runners, cables, hinge adjustment), use "mode": "manual" with a crop box around that step's illustration on its page image (fractions 0-1 of the page width/height; you can see the pages) and optional highlights. Keep these rare, and still include the parts that step adds in its actions.
- All text in {language} except product names. "say" is one natural spoken sentence for TTS.
- Set "manual": {{"pages": "{pages_pattern}"}}.

=== SCENE FORMAT SPEC ===
{schema}

=== MANUAL TRANSCRIPTION ===
{extraction}

=== FORMAT EXAMPLE (different assembly order, do not copy the structure) ===
{example}
"""

REPAIR_PROMPT = """The scene you produced fails validation. Fix every ERROR below (warnings are informational) and return the complete corrected scene JSON.
Only use the kinds and icons the format spec allows; model anything else (plates, brackets, caps) as kind "box" with a small size.

=== SCENE FORMAT SPEC ===
{schema}

=== VALIDATION ERRORS ===
{errors}

=== MANUAL TRANSCRIPTION (ground truth for counts) ===
{extraction}

=== YOUR PREVIOUS SCENE ===
{scene}
"""


LANG_NAME = {"en": "English", "zh": "Simplified Chinese"}
DISCLAIMER = {
    "en": "Generated by AI from the assembly manual PDF and checked against its parts list. It may still contain mistakes: follow the paper manual.",
    "zh": "由 AI 读说明书 PDF 自动生成，已对照说明书核对零件数；仍可能有误，以纸质说明书为准。",
}


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def image_block(path):
    data = base64.b64encode(Path(path).read_bytes()).decode()
    return {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": data}}


def parse_json(text):
    m = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.S)
    raw = m.group(1) if m else text[text.find("{"): text.rfind("}") + 1]
    raw = re.sub(r"//[^\n\"]*$", "", raw, flags=re.M)  # 模型偶尔照抄 spec 里的注释
    return json.loads(raw)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf")
    ap.add_argument("--slug", required=True)
    ap.add_argument("--name", required=True)
    ap.add_argument("--sub", default="")
    ap.add_argument("--dims", required=True, help="外形尺寸 宽x高x深，厘米")
    ap.add_argument("--notes", default="", help="额外的产品事实，比如板厚")
    ap.add_argument("--model", default="opus")
    ap.add_argument("--lang", choices=["en", "zh"], default="en", help="界面文字和朗读的语言")
    ap.add_argument("--repairs", type=int, default=2)
    ap.add_argument("--reuse-extraction", action="store_true")
    ap.add_argument("--resume", action="store_true", help="沿用已生成的 scene，只做校验和修复（隐含 --reuse-extraction）")
    a = ap.parse_args()

    log(f"模型：{describe()}")
    mdir = ROOT / "manuals" / a.slug
    pages_dir = mdir / "pages"
    pages_dir.mkdir(parents=True, exist_ok=True)
    pdf = Path(a.pdf).resolve()
    if not sorted(pages_dir.glob("hi-*.png")):
        log("把 PDF 转成图片")
        subprocess.run(["pdftoppm", "-r", "110", "-png", str(pdf), str(pages_dir / "hi")], check=True)
        for p in pages_dir.glob("hi-*.png"):  # 不足 10 页时 pdftoppm 不补零，统一成两位页码，和 manual.pages 的 {nn} 对上
            p.rename(pages_dir / f"hi-{int(p.stem.split('-')[1]):02d}.png")
    pages = sorted(pages_dir.glob("hi-*.png"))
    num = lambda p: int(p.stem.split("-")[1])  # noqa: E731
    dims = a.dims.replace("x", "×")

    # ---- 抽取 ----
    ext_path = mdir / "extraction.json"
    if (a.reuse_extraction or a.resume) and ext_path.exists():
        extraction = json.loads(ext_path.read_text())
        log("沿用已有的抽取结果")
    else:
        log(f"抽取：把 {len(pages)} 页交给模型读")
        content = []
        for p in pages:
            content += [{"type": "text", "text": f"Page {num(p)}:"}, image_block(p)]
        content.append({"type": "text", "text": EXTRACT_PROMPT.format(n=len(pages), name=a.name, sub=a.sub, dims=dims)})
        extraction = parse_json(ask_model(content, a.model))
        ext_path.write_text(json.dumps(extraction, ensure_ascii=False, indent=1))
    log(f"抽取完成：清单 {len(extraction.get('inventory', []))} 项，步骤 {len(extraction.get('steps', []))} 个 → {ext_path.relative_to(ROOT)}")

    # ---- 组装 ----
    step_pages = sorted({s["page"] for s in extraction.get("steps", []) if s.get("branch", "main") == "main"})
    hw_pages = sorted({it["page"] for it in extraction.get("inventory", []) if it.get("page")})
    use_pages = [p for p in pages if num(p) in set(step_pages) | set(hw_pages)]
    schema = SCHEMA.read_text()
    example = (EXAMPLE_EN if a.lang == "en" and EXAMPLE_EN.exists() else EXAMPLE).read_text()
    pattern = f"manuals/{a.slug}/pages/hi-{{nn}}.png"
    prompt = COMPOSE_PROMPT.format(name=a.name, sub=a.sub, dims=dims, notes=a.notes, pages_pattern=pattern,
                                   schema=schema, extraction=json.dumps(extraction, ensure_ascii=False, indent=1),
                                   example=example, language=LANG_NAME[a.lang])
    out = ROOT / "scenes" / f"{a.slug}.json"
    if a.resume and out.exists():
        scene = json.loads(out.read_text())
        log(f"沿用已有的 {out.relative_to(ROOT)}，直接进入校验和修复")
    else:
        content = []
        for p in use_pages:
            content += [{"type": "text", "text": f"Manual page {num(p)}:"}, image_block(p)]
        content.append({"type": "text", "text": prompt})
        log(f"组装：带 {len(use_pages)} 页图生成 scene")
        scene = parse_json(ask_model(content, a.model))

    disclaimer = DISCLAIMER[a.lang]
    report, best = [], None
    for round_ in range(a.repairs + 1):
        scene["disclaimer"] = disclaimer
        scene["lang"] = a.lang
        errors, warnings = validate(scene, extraction)
        report.append({"round": round_, "errors": errors, "warnings": warnings})
        log(f"校验第 {round_} 轮：{len(errors)} error，{len(warnings)} warning")
        for e in errors[:12]:
            print("   ERROR ", e)
        if best is None or len(errors) < len(best[1]):  # 修复可能退步，只保留错误最少的一版
            best = (scene, errors, warnings)
        if not errors or round_ == a.repairs:
            break
        log("把错误交回模型修")
        scene = parse_json(ask_model([{"type": "text", "text": REPAIR_PROMPT.format(
            errors="\n".join(errors), schema=schema, extraction=json.dumps(extraction, ensure_ascii=False, indent=1),
            scene=json.dumps(best[0], ensure_ascii=False, indent=1))}], a.model))

    scene, errors, warnings = best
    out.write_text(json.dumps(scene, ensure_ascii=False, indent=1))
    (mdir / "report.json").write_text(json.dumps({"final": {"errors": errors, "warnings": warnings}, "rounds": report},
                                                 ensure_ascii=False, indent=1))
    for w in warnings:
        print("   warning", w)
    log(f"写出 {out.relative_to(ROOT)}；{len(errors)} error。打开 ?scene={a.slug} 查看")
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
