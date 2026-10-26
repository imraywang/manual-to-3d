"""汇总 scenes/ 和 manuals/ 生成 cases.json，给案例页 index.html 用。

用法：python3 scripts/build_cases.py
"""
import json
from pathlib import Path

from m3d_paths import SITE as ROOT, SCHEMA, EXAMPLE  # noqa: E402

cases = []
for scene_path in sorted((ROOT / "scenes").glob("*.json")):
    slug = scene_path.stem
    if slug.endswith("-handmade") or slug.startswith("_"):
        continue
    scene = json.loads(scene_path.read_text())
    mdir = ROOT / "manuals" / slug
    report = json.loads((mdir / "report.json").read_text()) if (mdir / "report.json").exists() else {}
    final = report.get("final") or (report[-1] if isinstance(report, list) and report else {})
    extraction = json.loads((mdir / "extraction.json").read_text()) if (mdir / "extraction.json").exists() else {}
    parts = sum(1 for d in scene["instances"] if not d.get("noCount"))
    pages = sorted(mdir.glob("pages/hi-*.png"))
    cases.append({
        "slug": slug,
        "name": scene["product"]["name"],
        "sub": scene["product"].get("sub", ""),
        "subEn": (json.loads((ROOT / "scenes" / "en" / f"{slug}.json").read_text())["product"].get("sub", "")
                  if (ROOT / "scenes" / "en" / f"{slug}.json").exists() else ""),
        "size": scene["product"].get("size", ""),
        "steps": len(scene["steps"]),
        "parts": parts,
        "manualPages": len(pages),
        "manualSteps": len([s for s in extraction.get("steps", []) if s.get("branch", "main") == "main"]),
        "errors": len(final.get("errors", [])),
        "warnings": final.get("warnings", []),
        # 修复轮数优先从运行日志里数（--resume 重跑会覆盖 report.json 里的轮次记录）；make.py 不写 pipeline.log，退回 report.json
        "rounds": (1 + (mdir / "pipeline.log").read_text().count("把错误交回 Claude 修") if (mdir / "pipeline.log").exists()
                   else len(report.get("rounds", []) if isinstance(report, dict) else report) or 1),
        "cover": f"manuals/{slug}/pages/hi-01.png" if pages else None,
        "thumb": f"thumbs/{slug}.png" if (ROOT / "thumbs" / f"{slug}.png").exists() else None,
    })

(ROOT / "cases.json").write_text(json.dumps(cases, ensure_ascii=False, indent=1))
print(f"{len(cases)} 个案例 → cases.json")
for c in cases:
    print(f"  {c['slug']:16} {c['steps']:>2} 步 {c['parts']:>3} 件  {c['errors']} error  修复 {c['rounds'] - 1} 轮")
