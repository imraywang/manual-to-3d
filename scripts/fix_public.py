"""公开版去掉原图模式后，那几步要改用 3D 演示：让 Claude 只修机位 / 箭头 / 标注，存到 scenes/public/。

- 只允许改 camera、arrows、callouts 和动作的时间、起点；文字、零件、步骤数都不许动（改了就报错）
- 英文版：把 scenes/en/ 里的译文按同样路径套到修好的结构上，存到 scenes/public/en/

用法：python3 scripts/fix_public.py kallax-2x2 malm-3-drawer
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_public import strip  # noqa: E402
from pipeline import SYSTEM, ask_claude, parse_json  # noqa: E402,F401
from translate import set_path, text_fields  # noqa: E402
from validate import validate  # noqa: E402

from m3d_paths import SITE as ROOT, SCHEMA, EXAMPLE  # noqa: E402

PROMPT = """This assembly scene is shown as interactive 3D. Some steps used to show a manual illustration instead and now must work in 3D, so their camera, arrows and callouts need fixing.
Fix every ERROR below by changing ONLY: steps[].camera (target, height, dir), steps[].arrows, steps[].callouts positions/timing, and actions' "at", "dur", "stagger", "from". Do NOT change any text, instances, parts, tools, step count or action ids. Do not use "mode": "manual".

=== SCENE FORMAT SPEC ===
{schema}

=== VALIDATION ERRORS ===
{errors}

=== SCENE ===
{scene}
"""


def frozen(scene):
    """不允许修复改动的部分。"""
    return json.dumps({"instances": scene["instances"], "parts": scene["parts"], "tools": scene.get("tools"),
                       "text": text_fields(scene), "ids": [[a["ids"] for a in st["actions"]] for st in scene["steps"]]},
                      ensure_ascii=False, sort_keys=True)


def fix(slug, rounds=2):
    scene = strip(json.loads((ROOT / "scenes" / f"{slug}.json").read_text()))
    schema = SCHEMA.read_text()
    lock = frozen(scene)
    errors, _ = validate(scene)
    best = (scene, errors)
    for r in range(rounds):
        if not best[1]:
            break
        print(f"{slug}: 第 {r + 1} 轮修复，{len(best[1])} 个 error")
        cand = parse_json(ask_claude([{"type": "text", "text": PROMPT.format(
            schema=schema, errors="\n".join(best[1]), scene=json.dumps(best[0], ensure_ascii=False, indent=1))}], "opus"))
        cand = strip(cand)
        if frozen(cand) != lock:
            print(f"{slug}: 修复改动了文字或零件，丢弃这一版")
            continue
        errs, _ = validate(cand)
        if len(errs) < len(best[1]):
            best = (cand, errs)
    scene, errors = best
    out = ROOT / "scenes" / "public" / f"{slug}.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(scene, ensure_ascii=False, indent=1))
    en_src = ROOT / "scenes" / "en" / f"{slug}.json"
    if en_src.exists():
        en = json.loads(en_src.read_text())
        merged = json.loads(json.dumps(scene))
        for path, value in text_fields(en):
            set_path(merged, path, value)
        merged["lang"] = "en"
        (ROOT / "scenes" / "public" / "en").mkdir(exist_ok=True)
        (ROOT / "scenes" / "public" / "en" / f"{slug}.json").write_text(json.dumps(merged, ensure_ascii=False, indent=1))
    print(f"{slug}: 公开版 {len(errors)} error → {out.relative_to(ROOT)}")
    for e in errors[:8]:
        print("   ", e)


if __name__ == "__main__":
    for s in sys.argv[1:]:
        fix(s)
