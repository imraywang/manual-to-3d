"""把场景里的文本字段翻译成英文，写到 scenes/en/<slug>.json；坐标、动画不动。

用法：python3 scripts/translate.py kallax-2x2 lack-55 ...
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pipeline import ask_model, parse_json  # noqa: E402

from m3d_paths import SITE as ROOT, SCHEMA, EXAMPLE  # noqa: E402

PROMPT = """Translate the values of this JSON object from Simplified Chinese into natural, concise English for an IKEA-style assembly guide app. Keep the keys exactly. Keep product names (KALLAX, BILLY…), part letters and numbers unchanged. "say" values are spoken aloud by text-to-speech: make them short, friendly spoken sentences. Callout texts must stay very short (max ~4 words). Return the full JSON object.

{payload}"""


def text_fields(scene):
    """返回 [(路径, 文本)]；路径是 key 和下标组成的元组。"""
    out = []

    def add(path, v):
        if isinstance(v, str) and v.strip():
            out.append((path, v))
    add(("product", "sub"), scene["product"].get("sub"))
    add(("disclaimer",), scene.get("disclaimer"))
    for k, p in scene.get("parts", {}).items():
        add(("parts", k, "name"), p.get("name"))
        add(("parts", k, "dims"), p.get("dims"))
    for k, t in scene.get("tools", {}).items():
        add(("tools", k, "name"), t.get("name"))
    for i, st in enumerate(scene["steps"]):
        for f in ("title", "desc", "tip", "say"):
            add(("steps", i, f), st.get(f))
        for j, c in enumerate(st.get("callouts", [])):
            add(("steps", i, "callouts", j, "text"), c.get("text"))
    for i, c in enumerate(scene.get("afterChecks", [])):
        add(("afterChecks", i), c)
    return out


def set_path(obj, path, value):
    for k in path[:-1]:
        obj = obj[k]
    obj[path[-1]] = value


def translate(slug):
    scene = json.loads((ROOT / "scenes" / f"{slug}.json").read_text())
    fields = text_fields(scene)
    payload = {"/".join(map(str, p)): v for p, v in fields}
    result = parse_json(ask_model([{"type": "text", "text": PROMPT.format(
        payload=json.dumps(payload, ensure_ascii=False, indent=1))}], "sonnet"))
    missing = [k for k in payload if k not in result]
    if missing:
        raise RuntimeError(f"{slug}: 翻译结果缺少 {len(missing)} 个字段，比如 {missing[:3]}")
    for p, _ in fields:
        set_path(scene, p, result["/".join(map(str, p))])
    scene["lang"] = "en"
    out = ROOT / "scenes" / "en" / f"{slug}.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(scene, ensure_ascii=False, indent=1))
    print(f"{slug}: {len(fields)} 个字段 → {out.relative_to(ROOT)}")


if __name__ == "__main__":
    for s in sys.argv[1:]:
        translate(s)
