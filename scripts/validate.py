"""校验 scene JSON：结构、零件数（对照说明书抽取结果）、几何、可见性。

用法：python3 scripts/validate.py scenes/kallax-2x2.json [--extraction manuals/kallax-2x2/extraction.json]
返回码 0 = 没有 error（warning 不算）。
"""
import argparse
import itertools
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from solids import SOLID_KINDS, Solid, anchored, overlap_volume, ray_blocked  # noqa: E402

HARDWARE_KINDS = {"cam_bolt", "dowel", "cam_lock", "screw", "pad"}
KINDS = SOLID_KINDS | HARDWARE_KINDS
AXES = {"+x": (1, 0, 0), "-x": (-1, 0, 0), "+y": (0, 1, 0), "-y": (0, -1, 0), "+z": (0, 0, 1), "-z": (0, 0, -1)}
ICONS = {"panel", "bolt", "dowel", "camlock", "bracket", "screw", "pad", "screwdriver", "hammer", "drill", "allen"}


def ease(t):
    return 4 * t ** 3 if t < .5 else 1 - (-2 * t + 2) ** 3 / 2


def apply_step(state, step, t=float("inf")):
    """与 guide.html 里的 applyStep 同一套语义。"""
    for a in step["actions"]:
        for i, iid in enumerate(a["ids"]):
            st = state.get(iid)
            if st is None:
                continue
            at = a["at"] + a.get("stagger", 0) * i
            if t < at:
                continue
            p = ease(min(1, (t - at) / max(a["dur"], 1e-6)))
            if "from" in a or "to" in a:
                frm = a.get("from", st["off"])
                to = a.get("to", [0, 0, 0])
                st["off"] = [f + (b - f) * p for f, b in zip(frm, to)]
            st["vis"] = True
            st["spin"] += a.get("spin", 0) * p


def simulate(scene):
    """返回每一步开始时的状态列表（长度 = 步数 + 1）。"""
    state = {d["id"]: {"vis": False, "off": [0, 0, 0], "spin": 0} for d in scene["instances"]}
    bases = [json.loads(json.dumps(state))]
    for step in scene["steps"]:
        apply_step(state, step)
        bases.append(json.loads(json.dumps(state)))
    return bases


VIEW_DIR = (1, 0.8, 1.2)  # 与 guide.html 的默认视角一致


def norm(v):
    n = sum(x * x for x in v) ** .5
    return [x / n for x in v]


def is_solid(d):
    return d["kind"] in SOLID_KINDS


def check_view(scene, bases, intro, by_id, E, W=None):
    """每一步新出现的零件：在这一步的机位下不能被别的板挡住，也不能出画。原图模式的步骤不查。"""
    for n, st in enumerate(scene["steps"]):
        if st.get("mode") == "manual":
            continue
        cam = st.get("camera", {})
        d = norm(cam.get("dir", VIEW_DIR))
        target, height = cam.get("target", [0, 0, 0]), cam.get("height", 100)
        # 相机平面的两个基向量
        up = [0, 1, 0]
        right = norm([up[1] * d[2] - up[2] * d[1], up[2] * d[0] - up[0] * d[2], up[0] * d[1] - up[1] * d[0]])
        upv = [d[1] * right[2] - d[2] * right[1], d[2] * right[0] - d[0] * right[2], d[0] * right[1] - d[1] * right[0]]
        if not -0.6 <= d[1] <= 0.85:
            E(f"第 {n + 1} 步 camera.dir 太接近垂直（归一化后 y={d[1]:.2f}，要在 -0.6 到 0.85 之间），画面会看不出形状")
        vis = [Solid(by_id[i]) for i, s in bases[n + 1].items()
               if s["vis"] and is_solid(by_id[i]) and not by_id[i].get("plain")]
        if vis:
            ys = [sum((v[i] - target[i]) * upv[i] for i in range(3)) for s in vis for v in s.vertices()]
            span = max(ys) - min(ys)
            if height < 0.5 * span:
                E(f"第 {n + 1} 步取景太近：画面高 {height}，已装部分在画面里约 {span:.0f} 高，至少要 {0.5 * span:.0f}，否则看不出在装哪里")

        def blockers_at(t):
            s = json.loads(json.dumps(bases[n]))
            apply_step(s, st, t)
            return [Solid(by_id[i], s[i]["off"]) for i, v in s.items()
                    if v["vis"] and is_solid(by_id[i]) and not by_id[i].get("plain")]
        appear_end = {}  # 零件在这一步第一次动画结束的时刻：按那一刻判断遮挡，之后被盖住是正常的
        group_of = {}    # 同一个动作里不错开、一起移动的多个零件算一个整体（比如整个抽屉推进柜子），整体里看得见一个就行
        for ai, a in enumerate(st.get("actions", [])):
            rigid = len(a["ids"]) > 1 and not a.get("stagger") and ("from" in a or "to" in a)
            for i, iid in enumerate(a["ids"]):
                appear_end.setdefault(iid, a["at"] + a.get("stagger", 0) * i + a["dur"])
                if rigid:
                    group_of.setdefault(iid, ai)
        hidden = {}      # 组号 → [(零件, 挡住它的板)]；组里全被挡住才报
        seen = set()
        for iid, k in intro.items():
            if k != n or by_id[iid].get("plain"):
                continue
            item = by_id[iid]
            if is_solid(item):
                me = Solid(item)
                o = list(me.c)
                pts = me.vertices()
            else:
                ax = AXES[item["axis"]]
                lift = 0.3 if item.get("flush") else 0.8
                o = [p + a * lift for p, a in zip(item["pos"], ax)]
                pts = [o]
            # 实体看所有顶点，五金件看露出的那一点；都要落在画面里（宽按 1.5 倍高算，与渲染器窄屏取景一致）
            worst = 0
            for pt in pts:
                rel = [pt[i] - target[i] for i in range(3)]
                x, y = sum(r * c for r, c in zip(rel, right)), sum(r * c for r, c in zip(rel, upv))
                worst = max(worst, abs(y) / (height * 0.5), abs(x) / (height * 0.75))
            if worst > 1.03:
                E(f"第 {n + 1} 步新装的 {iid} 有一部分在画面外（超出约 {(worst - 1) * 100:.0f}%）：加大 camera.height 或移动 target")
                continue
            flat = item["kind"] in ("pad", "cam_lock") or item.get("flush")
            if flat and sum(x * y for x, y in zip(AXES[item["axis"]], d)) < 0.2:
                # 这一步另有朝向相反、正对相机的扁平零件时（比如左右两侧同时上锁），一个机位不可能两面都看到，只提示
                opposite_ok = any(
                    k2 == n and j != iid and (by_id[j]["kind"] in ("pad", "cam_lock") or by_id[j].get("flush"))
                    and sum(x * y for x, y in zip(AXES[by_id[j]["axis"]], d)) >= 0.2
                    and sum(x * y for x, y in zip(AXES[by_id[j]["axis"]], AXES[item["axis"]])) < -0.5
                    for j, k2 in intro.items())
                msg = f"第 {n + 1} 步新装的 {iid} 朝 {item['axis']}，几乎是背对或侧对相机"
                if opposite_ok and W:
                    W(msg + "（同一步另一侧的零件正对相机，一个机位看不到两面）")
                else:
                    E(msg + "：camera.dir 要从它露出来的那一侧看（扁平零件侧着看只是一条线）")
                continue
            for blk in blockers_at(appear_end.get(iid, float("inf")) + 1e-3):
                if blk.id == iid or blk.contains(o, -0.05):
                    continue
                if ray_blocked(o, d, blk):
                    if iid in group_of:
                        hidden.setdefault(group_of[iid], []).append((iid, blk.id))
                    else:
                        E(f"第 {n + 1} 步新装的 {iid} 被 {blk.id} 挡住了：换个 camera.dir，或调整 target")
                    break
            else:
                if iid in group_of:
                    seen.add(group_of[iid])
        for g, items in hidden.items():
            if g not in seen:
                names = "、".join(f"{i}（被 {b} 挡住）" for i, b in items[:4])
                E(f"第 {n + 1} 步一起移动的那组零件全被挡住了：{names}：换个 camera.dir，或调整 target")


def num3(v):
    return isinstance(v, list) and len(v) == 3 and all(isinstance(x, (int, float)) for x in v)


def validate(scene, extraction=None):
    errors, warnings = [], []
    E, W = errors.append, warnings.append

    for key in ("product", "parts", "instances", "steps"):
        if key not in scene:
            E(f"缺少顶层字段 {key}")
    if errors:
        return errors, warnings

    parts, insts, steps = scene["parts"], scene["instances"], scene["steps"]
    tools = scene.get("tools", {})
    by_id = {}
    for d in insts:
        iid = d.get("id")
        if iid in by_id:
            E(f"instance id 重复：{iid}")
        by_id[iid] = d
        kind = d.get("kind")
        if d.get("part") not in parts:
            E(f"{iid}：part {d.get('part')!r} 不在 parts 里")
        if kind not in KINDS:
            E(f"{iid}：kind {kind!r} 不支持（可用 {sorted(KINDS)}）")
        if not num3(d.get("pos")):
            E(f"{iid}：pos 必须是三元数组")
        if "rot" in d and not num3(d["rot"]):
            E(f"{iid}：rot 必须是三元数组（角度制欧拉角）")
        if kind == "box":
            if not (num3(d.get("size")) and all(s > 0 for s in d["size"])):
                E(f"{iid}：box 需要正数 size[3]")
        elif kind == "cylinder":
            if not (d.get("radius", 0) > 0 and d.get("length", 0) > 0):
                E(f"{iid}：cylinder 需要正数 radius 和 length")
        elif kind == "extrude":
            prof = d.get("profile")
            if not (isinstance(prof, list) and len(prof) >= 3 and all(isinstance(p, list) and len(p) == 2 for p in prof)
                    and d.get("depth", 0) > 0):
                E(f"{iid}：extrude 需要 profile（至少 3 个 [x, y] 点）和正数 depth")
        elif kind in HARDWARE_KINDS and d.get("axis") not in AXES:
            E(f"{iid}：五金件需要 axis（{sorted(AXES)}）")
    for k, p in parts.items():
        if p.get("icon") and p["icon"] not in ICONS:
            W(f"part {k}：icon {p['icon']!r} 没有对应图标")

    from m3d_paths import SITE
    n_pages = len(list((SITE / scene.get("manual", {}).get("pages", "x/x").rsplit("/", 1)[0]).glob("*.png")))
    for n, st in enumerate(steps, 1):
        for f in ("title", "desc", "say", "actions", "camera"):
            if f not in st:
                E(f"第 {n} 步缺少 {f}")
        for a in st.get("actions", []):
            for iid in a.get("ids", []):
                if iid not in by_id:
                    E(f"第 {n} 步引用了不存在的 instance {iid}")
            if a.get("dur", 0) <= 0:
                E(f"第 {n} 步有 dur <= 0 的动作")
        for tk in st.get("tools", []):
            if tk not in tools:
                E(f"第 {n} 步的工具 {tk!r} 不在 tools 里")
        if st.get("mode") == "manual":
            crop = st.get("crop") or {}
            box = crop.get("box")
            if not isinstance(crop.get("page"), int) or not (1 <= crop["page"] <= max(n_pages, 1)):
                E(f"第 {n} 步是原图模式，crop.page 要是 1～{n_pages} 之间的页码")
            if not (isinstance(box, list) and len(box) == 4 and 0 <= box[0] < box[2] <= 1 and 0 <= box[1] < box[3] <= 1):
                E(f"第 {n} 步是原图模式，crop.box 要是 [x0, y0, x1, y1]，取值 0～1 且 x0<x1、y0<y1")
            for h in st.get("highlights", []):
                if not (isinstance(h, list) and len(h) == 4 and 0 <= h[0] < h[2] <= 1 and 0 <= h[1] < h[3] <= 1):
                    E(f"第 {n} 步的 highlights 里有不合法的框 {h}")
    if errors:
        return errors, warnings

    bases = simulate(scene)
    final = bases[-1]
    intro = {}
    for iid in by_id:
        for k in range(len(steps)):
            if not bases[k][iid]["vis"] and bases[k + 1][iid]["vis"]:
                intro[iid] = k
                break
        else:
            if not by_id[iid].get("noCount"):
                E(f"{iid} 从没出现在任何一步里")
        if any(abs(o) > 1e-3 for o in final[iid]["off"]):
            E(f"{iid} 最后没有回到最终位置（偏移 {final[iid]['off']}）")

    # ---- 几何：最终状态下实体不互相穿插，五金件贴在实体表面，不低于地面 ----
    solids = [Solid(d) for d in by_id.values() if is_solid(d)]
    for a, b in itertools.combinations(solids, 2):
        v = overlap_volume(a, b)
        if v > 0.5:
            E(f"板件穿插：{a.id} 和 {b.id} 重叠约 {v:.1f} cm³")
    for s in solids:
        low = s.aabb()[0][1]
        if low < -0.01:
            E(f"{s.id} 低于地面（最低点 y={low:.2f}）")
    for iid, d in by_id.items():
        if is_solid(d):
            continue
        if not anchored(d["pos"], AXES[d["axis"]], solids):
            E(f"{iid}（{d['kind']}）没有贴在任何板面上：pos={d['pos']} axis={d['axis']}")

    check_view(scene, bases, intro, by_id, E, W)

    # ---- 零件数：对照说明书抽取结果 ----
    counted = {}
    for d in insts:
        if not d.get("noCount"):
            counted[d["part"]] = counted.get(d["part"], 0) + 1
    if extraction:
        inv = {it["id"]: it for it in extraction.get("inventory", [])}
        by_src, keys_of = {}, {}  # 几种 part 可以指向清单里的同一项（比如顶板和侧板是同一种外板），按清单项合计
        for key, p in parts.items():
            src = p.get("source")
            if src is None:
                if counted.get(key):
                    W(f"part {key} 没有 source，无法和说明书清单核对")
                continue
            if src not in inv:
                E(f"part {key} 的 source {src!r} 不在说明书清单里")
                continue
            by_src[src] = by_src.get(src, 0) + counted.get(key, 0)
            keys_of.setdefault(src, []).append(key)
        for src, got in by_src.items():
            want, name, keys = inv[src]["qty"], inv[src].get("name_en", src), "/".join(keys_of[src])
            if got > want:
                E(f"{keys}（{name}）场景里 {got} 个，说明书清单只有 {want} 个：多出来的是编的")
            elif got < want:
                W(f"{keys}（{name}）场景里用了 {got} 个，清单有 {want} 个（备用件或没建模的分支）")
        for src, it in inv.items():
            if src not in by_src and it.get("kind") not in ("tool",):
                W(f"说明书清单里的 {src}（{it.get('name_en')} ×{it['qty']}）在场景里没有对应零件")

        # 每一步：场景这几步新出现的五金件数量 = 说明书对应步骤印的 “Nx”
        src_steps = {str(s["manual_step"]) + ("" if s.get("branch", "main") == "main" else "@" + s["branch"]): s
                     for s in extraction.get("steps", [])}
        src_of_part = {key: p.get("source") for key, p in parts.items()}
        # 各步印的数量加起来超过清单的零件：说明书在后面的步骤里重复画了已装好的件，或清单按包计数，只核总数
        total_printed = {}
        for s in extraction.get("steps", []):
            if s.get("branch", "main") == "main":
                for h in s.get("hardware", []):
                    if h.get("qty_printed"):
                        total_printed[h["ref"]] = total_printed.get(h["ref"], 0) + h["qty_printed"]
        loose = {r for r, t in total_printed.items() if r in inv and t > inv[r]["qty"]}
        for r in sorted(loose):
            W(f"{inv[r].get('name_en', r)}：说明书各步印的数量合计 {total_printed[r]}，超过清单的 {inv[r]['qty']}（重复提及或按包计），只核总数")

        # 共用同一个说明书步骤的场景步骤合成一组（说明书一步被拆成几步演示时，合起来核对）
        groups, owner = [], {}
        for n, st in enumerate(steps):
            refs = [str(r) for r in (st.get("source") or {}).get("manual_steps", [])]
            if not refs:
                W(f"第 {n + 1} 步没有标注对应说明书的哪一步")
                continue
            hit = {owner[r] for r in refs if r in owner}
            g = {"steps": [n], "refs": set(refs)}
            for gi in sorted(hit, reverse=True):
                old = groups.pop(gi)
                g["steps"] = sorted(old["steps"] + g["steps"]); g["refs"] |= old["refs"]
            groups.append(g)
            owner = {r: i for i, gr in enumerate(groups) for r in gr["refs"]}
        for g in groups:
            printed, unprinted = {}, set()  # 说明书画了但没印数量的零件，只核总数，不逐步核
            for r in sorted(g["refs"]):
                s = src_steps.get(r)
                if s is None:
                    E(f"第 {g['steps'][0] + 1} 步对应的说明书步骤 {r!r} 在抽取结果里找不到")
                    continue
                for h in s.get("hardware", []):
                    if h.get("qty_printed"):
                        printed[h["ref"]] = printed.get(h["ref"], 0) + h["qty_printed"]
                    else:
                        unprinted.add(h["ref"])
            got = {}
            for iid, k in intro.items():
                d = by_id[iid]
                src = src_of_part.get(d["part"])
                if k in g["steps"] and not d.get("noCount") and inv.get(src, {}).get("kind") != "panel":
                    got[src] = got.get(src, 0) + 1
            label = "、".join(str(n + 1) for n in g["steps"])
            for src in set(printed) | set(got):
                if src is None or src in loose or (src in unprinted and src not in printed):
                    continue
                name = inv.get(src, {}).get("name_en", src)
                if src not in printed:
                    # 抽取结果里这一步根本没列这个零件（说明书只画了没印数，抽取时漏了）：只核总数，提醒去看原页
                    W(f"第 {label} 步（说明书 {', '.join(sorted(g['refs']))}）装了 {got[src]} 个 {name}，抽取结果里这一步没列它：对照原页确认")
                    continue
                if printed.get(src, 0) != got.get(src, 0):
                    E(f"第 {label} 步（说明书 {', '.join(sorted(g['refs']))}）{name}：说明书印 {printed.get(src, 0)}×，场景装了 {got.get(src, 0)} 个")
    return errors, warnings


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("scene")
    ap.add_argument("--extraction")
    a = ap.parse_args()
    scene = json.load(open(a.scene))
    ext = json.load(open(a.extraction)) if a.extraction else None
    errors, warnings = validate(scene, ext)
    for e in errors:
        print("ERROR  ", e)
    for w in warnings:
        print("warning", w)
    print(f"\n{len(errors)} error, {len(warnings)} warning")
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
