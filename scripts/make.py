"""One command: a product name (or IKEA link, or PDF) → assembly manual → interactive 3D step-by-step guide.

  python3 make.py "LACK coffee table 90x55"
  python3 make.py --url https://www.ikea.com/th/en/p/...      [--pick 2] [--lang zh] [--public]
  python3 make.py --pdf manual.pdf --name LACK --sub "Side table" --dims 55x45x55

Steps: fetch_manual (find the product, download the manual, read its size) → pipeline (read pages, build the
scene, validate, repair) → translate (Chinese guides also get an English version) → headless Chrome renders a 3D
thumbnail → build_cases (gallery page). --public also writes dist/, a copy without any manual page images.
Everything is written to the workspace (~/manual-to-3d, or $MANUAL_TO_3D_HOME). Nothing is published.
Takes about 6–12 minutes, mostly Claude reading pages and building the scene.
"""
import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from m3d_paths import SITE, SKILL, EXAMPLE, EXAMPLE_EN  # noqa: E402

PY = sys.executable
GENERIC_NOTES = ("Infer part thicknesses from the drawings: IKEA particleboard panels are usually 1.6–1.8 cm, "
                 "hollow-core tops and sides 3.8–5 cm, back panels 0.3 cm hardboard, legs about 5×5 cm. ")


def run(args, check=True):
    print("$", " ".join(str(a) for a in args), flush=True)
    r = subprocess.run([str(a) for a in args], cwd=SITE)
    if check and r.returncode != 0:
        sys.exit(f"失败：{args[1]}（退出码 {r.returncode}）")
    return r.returncode


def ensure_site():
    """第一次运行时建好工作目录：播放器、案例页和一个手写的示例场景。"""
    for d in ("scenes/en", "manuals", "thumbs"):
        (SITE / d).mkdir(parents=True, exist_ok=True)
    for f in ("guide.html", "index.html"):
        if not (SITE / f).exists():
            shutil.copy(SKILL / "assets" / f, SITE / f)
            print(f"初始化工作目录 {SITE}：复制 {f}")
    if not (SITE / "scenes" / "kallax-handmade.json").exists():
        shutil.copy(EXAMPLE, SITE / "scenes" / "kallax-handmade.json")
        if EXAMPLE_EN.exists():
            shutil.copy(EXAMPLE_EN, SITE / "scenes" / "en" / "kallax-handmade.json")


def chrome():
    for c in ("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", shutil.which("google-chrome"),
              shutil.which("chromium"), shutil.which("chromium-browser")):
        if c and Path(c).exists():
            return c
    return None


def render_thumb(slug):
    exe = chrome()
    if not exe:
        print("  ! 没找到 Chrome，跳过封面图")
        return
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    srv = subprocess.Popen([PY, "-m", "http.server", str(port), "--bind", "127.0.0.1", "--directory", str(SITE)],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        time.sleep(0.8)
        out = SITE / "thumbs" / f"{slug}.png"
        lang = "en" if (SITE / "scenes" / "en" / f"{slug}.json").exists() else "zh"
        subprocess.run([exe, "--headless=new", "--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--hide-scrollbars",
                        "--window-size=800,600", "--virtual-time-budget=6000", f"--screenshot={out}",
                        f"http://127.0.0.1:{port}/guide.html?scene={slug}&thumb=1&lang={lang}"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=120)
        print(f"  封面 → thumbs/{slug}.png" if out.exists() else "  ! 封面渲染失败")
    finally:
        srv.terminate()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("query", nargs="?")
    ap.add_argument("--url")
    ap.add_argument("--pdf")
    ap.add_argument("--name")
    ap.add_argument("--sub", default="")
    ap.add_argument("--dims")
    ap.add_argument("--pick", type=int, default=1)
    ap.add_argument("--slug")
    ap.add_argument("--notes", default="", help="额外的产品事实，比如板厚、是否带抽屉")
    ap.add_argument("--model", default="opus")
    ap.add_argument("--lang", choices=["en", "zh"], default="en", help="界面文字和朗读的语言；zh 会另外生成英文版")
    ap.add_argument("--repairs", type=int, default=3)
    ap.add_argument("--reuse-extraction", action="store_true", help="同一件产品重跑时跳过读图抽取")
    ap.add_argument("--no-en", action="store_true", help="不生成英文版")
    ap.add_argument("--public", action="store_true", help="最后生成不含说明书原页的 dist/（不部署）")
    a = ap.parse_args()
    t0 = time.time()
    ensure_site()

    # 1. 找说明书
    if a.slug and (SITE / "manuals" / a.slug / "meta.json").exists() and not (a.query or a.url or a.pdf):
        slug = a.slug
    else:
        fetch = [PY, HERE / "fetch_manual.py"]
        fetch += [a.query] if a.query else []
        for k in ("url", "pdf", "name", "dims", "slug"):
            if getattr(a, k):
                fetch += [f"--{k}", getattr(a, k)]
        fetch += ["--sub", a.sub, "--pick", str(a.pick)]
        print("$", " ".join(str(x) for x in fetch), flush=True)
        r = subprocess.run([str(x) for x in fetch], cwd=SITE, capture_output=True, text=True)
        print(r.stdout, end="")
        if r.returncode != 0:
            sys.exit(r.stderr.strip() or "找说明书失败")
        slug = r.stdout.strip().splitlines()[-1]
    meta = json.loads((SITE / "manuals" / slug / "meta.json").read_text())
    w, h, d = meta["dims"]
    dims = "x".join(f"{v:g}" if v else "?" for v in (w, h, d))
    notes = GENERIC_NOTES + (f"The product page lists width {w} cm, depth {d} cm, height {h} cm; IKEA sometimes swaps "
                             "width and depth, so decide from the drawings which horizontal side is the long one. " if all((w, h, d)) else
                             "Some outer dimensions are unknown; estimate them from the drawings and the parts. ") + a.notes

    # 2. 读图抽取 → 生成场景 → 校验 → 修复
    pipe = [PY, HERE / "pipeline.py", SITE / "manuals" / slug / "manual.pdf", "--slug", slug, "--name", meta["name"],
            "--sub", meta.get("sub", ""), "--dims", dims, "--notes", notes, "--model", a.model, "--repairs", str(a.repairs),
            "--lang", a.lang]
    if a.reuse_extraction:
        pipe.append("--reuse-extraction")
    code = run(pipe, check=False)
    if not (SITE / "scenes" / f"{slug}.json").exists():
        sys.exit("没有生成场景，看上面的日志")

    # 3. 英文版、封面、案例页
    if a.lang == "zh" and not a.no_en:
        run([PY, HERE / "translate.py", slug], check=False)
    render_thumb(slug)
    run([PY, HERE / "build_cases.py"], check=False)
    if a.public:
        run([PY, HERE / "build_public.py"], check=False)

    report = json.loads((SITE / "manuals" / slug / "report.json").read_text())
    final = report.get("final", {})
    scene = json.loads((SITE / "scenes" / f"{slug}.json").read_text())
    summary = {
        "slug": slug, "product": f"{meta['name']} · {meta.get('sub', '')}", "manual_pages": meta.get("pages"),
        "steps": len(scene["steps"]), "parts": sum(1 for i in scene["instances"] if not i.get("noCount")),
        "errors": final.get("errors", []), "warnings": final.get("warnings", []),
        "language": a.lang, "english": a.lang == "en" or (SITE / "scenes" / "en" / f"{slug}.json").exists(), "minutes": round((time.time() - t0) / 60, 1),
        "site": str(SITE),
        "preview": f"python3 -m http.server 8931 --directory {SITE}  →  http://127.0.0.1:8931/guide.html?scene={slug}",
    }
    print("\n==== 结果 ====")
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    sys.exit(1 if code != 0 or summary["errors"] else 0)


if __name__ == "__main__":
    main()
