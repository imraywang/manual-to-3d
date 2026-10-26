"""生成可公开部署的 dist/：不带任何说明书原页图。

- 只拷首页、播放器、封面图（thumbs/ 是自己渲染的 3D 成品）和案例场景（中文 + 英文）
- 场景去掉 manual（页图路径）；原图模式的步骤改回 3D 演示（3D 状态本来就照常推进）
- cases.json 去掉指向说明书第一页的 cover
- manuals/、抽取结果、日志一律不拷

用法：python3 scripts/build_cases.py && python3 scripts/build_public.py
"""
import json
import shutil
import sys
from pathlib import Path

from m3d_paths import SITE as ROOT, SCHEMA, EXAMPLE  # noqa: E402
DIST = ROOT / "dist"
sys.path.insert(0, str(Path(__file__).resolve().parent))
from validate import validate  # noqa: E402


def strip(scene):
    scene = json.loads(json.dumps(scene))
    scene.pop("manual", None)
    for st in scene["steps"]:
        if st.pop("mode", None) == "manual":
            st.pop("crop", None)
            st.pop("highlights", None)
    return scene


def main():
    cases = json.loads((ROOT / "cases.json").read_text())
    if DIST.exists():
        shutil.rmtree(DIST)
    (DIST / "scenes" / "en").mkdir(parents=True)
    (DIST / "thumbs").mkdir()
    for f in ("index.html", "guide.html"):
        shutil.copy(ROOT / f, DIST / f)
    for c in cases:
        c.pop("cover", None)
        if c.get("thumb"):
            shutil.copy(ROOT / c["thumb"], DIST / c["thumb"])
        for sub in ("", "en"):
            src = ROOT / "scenes" / "public" / sub / f"{c['slug']}.json"  # fix_public.py 修过机位的版本优先
            if not src.exists():
                src = ROOT / "scenes" / sub / f"{c['slug']}.json"
            if src.exists():
                scene = strip(json.loads(src.read_text()))
                (DIST / "scenes" / sub / src.name).write_text(json.dumps(scene, ensure_ascii=False, separators=(",", ":")))
                if not sub:
                    errors, _ = validate(scene)
                    note = f"，去掉原图模式后有 {len(errors)} 个 error（多半是取景）" if errors else ""
                    print(f"  {c['slug']}{note}")
    (DIST / "cases.json").write_text(json.dumps(cases, ensure_ascii=False, separators=(",", ":")))
    leaked = [p for p in DIST.rglob("*") if "manuals" in p.as_posix() or (p.suffix == ".json" and "manuals/" in p.read_text())]
    if leaked:
        raise SystemExit(f"dist 里还有说明书引用：{leaked}")
    files = [p for p in DIST.rglob("*") if p.is_file()]
    print(f"dist/：{len(files)} 个文件，{sum(p.stat().st_size for p in files) / 1024:.0f} KB，无说明书原页")


if __name__ == "__main__":
    main()
