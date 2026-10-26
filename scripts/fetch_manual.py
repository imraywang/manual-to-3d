"""一句话 → IKEA 商品 → 说明书 PDF + 外形尺寸，存到 <站点>/manuals/<slug>/。

用法：
  python3 fetch_manual.py "LACK coffee table 90x55"          # 搜索，自动挑最匹配的一件
  python3 fetch_manual.py "BILLY" --list                     # 只列候选，不下载
  python3 fetch_manual.py "BILLY" --pick 2                   # 选第 2 个候选
  python3 fetch_manual.py --url https://www.ikea.com/th/en/p/...
  python3 fetch_manual.py --pdf ~/Downloads/x.pdf --name LACK --sub "Side table" --dims 55x45x55

输出 meta.json：slug、name、sub、dims（宽x高x深，厘米）、商品页、PDF 链接；最后一行打印 slug。
尺寸取自商品页的结构化数据（schema.org Product 的 width / depth / height）；IKEA 偶尔把宽和深写反，交给模型时会注明。
"""
import argparse
import json
import re
import subprocess
import sys
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from m3d_paths import SITE  # noqa: E402

UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/150 Safari/537.36"}
MARKETS = ["th/en", "gb/en", "us/en"]   # th/en 的商品页里直接带说明书链接，排第一


def get(url, binary=False):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=40) as r:
        data = r.read()
    return data if binary else data.decode("utf-8", "replace")


def search(query, market):
    q = urllib.parse.quote(query)
    url = f"https://sik.search.blue.cdtapps.com/{market}/search-result-page?q={q}&size=12&types=PRODUCT"
    items = json.loads(get(url))["searchResultPage"]["products"]["main"]["items"]
    out = []
    for it in items:
        p = it.get("product") or {}
        if p.get("pipUrl"):
            out.append({"name": p.get("name", ""), "type": p.get("typeName", ""),
                        "measure": p.get("itemMeasureReferenceText", ""), "url": p["pipUrl"]})
    return out


def score(c, query):
    """名称、类型、尺寸里命中查询词越多越靠前；尺寸数字完全一致加重分。"""
    q = query.lower()
    words = [w for w in re.split(r"[^\wÀ-ɏ]+", q) if w]
    hay = f"{c['name']} {c['type']} {c['measure']}".lower()
    s = sum(2 if w == c["name"].lower() else 1 for w in words if w in hay)
    for size in re.findall(r"\d+(?:x\d+)+", q):
        if size in c["measure"].replace(" ", "").lower():
            s += 3
    return s


def cm(v):
    m = re.search(r"([\d.]+)\s*cm", v or "")
    return float(m.group(1)) if m else None


def product_page(url):
    html = get(url)
    m = re.search(r'id="pip-range-json-ld">(.*?)</script>', html, re.S)
    ld = json.loads(m.group(1)) if m else {}
    pdfs = sorted(set(re.findall(r'https://www\.ikea\.com/[a-z/]*assembly_instructions/[^"]+?\.pdf', html)))
    w, d, h = cm(ld.get("width")), cm(ld.get("depth")), cm(ld.get("height"))
    title = ld.get("name") or ""
    return {"title": title, "dims": (w, h, d), "pdfs": pdfs}


def pdf_pages(path):
    out = subprocess.run(["pdfinfo", str(path)], capture_output=True, text=True).stdout
    m = re.search(r"Pages:\s+(\d+)", out)
    return int(m.group(1)) if m else 0


def slugify(*parts):
    s = "-".join(p for p in parts if p).lower()
    s = s.replace("ä", "a").replace("ö", "o").replace("å", "a").replace("×", "x")
    return re.sub(r"[^a-z0-9x]+", "-", s).strip("-")[:48]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("query", nargs="?")
    ap.add_argument("--url")
    ap.add_argument("--pdf")
    ap.add_argument("--name")
    ap.add_argument("--sub", default="")
    ap.add_argument("--dims", help="宽x高x深（厘米），给 --pdf 时必填")
    ap.add_argument("--pick", type=int, default=1)
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--slug")
    a = ap.parse_args()

    if a.pdf:
        if not (a.name and a.dims):
            sys.exit("给本地 PDF 时要同时给 --name 和 --dims（宽x高x深，厘米）")
        w, h, d = (float(x) for x in a.dims.lower().split("x"))
        meta = {"name": a.name, "sub": a.sub, "dims": [w, h, d], "page": None, "pdf_url": None, "source": "local pdf"}
        slug = a.slug or slugify(a.name, a.sub)
        mdir = SITE / "manuals" / slug
        mdir.mkdir(parents=True, exist_ok=True)
        (mdir / "manual.pdf").write_bytes(Path(a.pdf).expanduser().read_bytes())
    else:
        if a.url:
            cand = {"url": a.url, "name": "", "type": "", "measure": ""}
        else:
            if not a.query:
                sys.exit("给一个商品描述（比如 \"LACK coffee table 90x55\"）、--url 或 --pdf")
            cands, market = [], None
            for market in MARKETS:
                try:
                    cands = search(a.query, market)
                except Exception as e:  # 某个站点搜不了就换下一个
                    print(f"  {market} 搜索失败：{e}", file=sys.stderr)
                    continue
                if cands:
                    break
            if not cands:
                sys.exit(f"没搜到「{a.query}」，换个英文商品名试试（IKEA 商品名 + 类型 + 尺寸，比如 \"MALM chest of 3 drawers\"）")
            cands.sort(key=lambda c: -score(c, a.query))
            for i, c in enumerate(cands[:8], 1):
                print(f"  {i}. {c['name']} · {c['type']} · {c['measure']}  {c['url']}")
            if a.list:
                return
            cand = cands[min(a.pick, len(cands)) - 1]
            print(f"选中第 {a.pick} 个：{cand['name']} · {cand['type']} · {cand['measure']}")
        page = product_page(cand["url"])
        if not page["pdfs"]:
            sys.exit(f"商品页里没找到说明书 PDF：{cand['url']}（可能这个站点没上传，试 --url 换成 th/en 的同款商品页，或手动下载后用 --pdf）")
        w, h, d = page["dims"]
        if not all((w, h, d)):
            print(f"  ! 商品页没给全尺寸（宽 {w} 高 {h} 深 {d}），缺的会交给模型从说明书推断", file=sys.stderr)
        name = cand["name"] or page["title"].split(" ")[0]
        sub = " ".join(x for x in (cand["type"], cand["measure"]) if x) or page["title"]
        slug = a.slug or slugify(name, cand["type"].split(",")[0][:24], re.sub(r"\s*cm$", "", cand["measure"]))
        mdir = SITE / "manuals" / slug
        mdir.mkdir(parents=True, exist_ok=True)
        best, best_pages = None, -1
        for i, u in enumerate(page["pdfs"]):
            tmp = mdir / f"_candidate-{i}.pdf"
            tmp.write_bytes(get(u, binary=True))
            n = pdf_pages(tmp)
            print(f"  说明书 {u.rsplit('/', 1)[-1]}：{n} 页")
            if n > best_pages:
                best, best_pages = (u, tmp), n
        best[1].replace(mdir / "manual.pdf")
        for tmp in mdir.glob("_candidate-*.pdf"):
            tmp.unlink()
        meta = {"name": name, "sub": sub, "dims": [w, h, d], "page": cand["url"], "pdf_url": best[0],
                "title": page["title"], "source": "ikea.com"}
    meta["slug"] = slug
    meta["pages"] = pdf_pages(SITE / "manuals" / slug / "manual.pdf")
    (SITE / "manuals" / slug / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1))
    print(f"说明书 {meta['pages']} 页，尺寸 宽{meta['dims'][0]} × 高{meta['dims'][1]} × 深{meta['dims'][2]} cm → manuals/{slug}/")
    print(slug)


if __name__ == "__main__":
    main()
