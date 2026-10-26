"""校验用的通用实体：box / cylinder / extrude，都可以带 rot。

所有几何判断都归结到「点在不在实体里」，这样旋转的板、圆柱、凹多边形拉伸体用同一套逻辑：
  穿插 = 两个实体包围盒交集里撒网格点，统计同时在两者内部的点
  贴面 = 五金件基点往里一点在实体内、往外一点在实体外
  遮挡 = 沿射线步进采样
与 guide.html 的约定一致：rot 是角度制欧拉角，顺序同 three.js 的 'XYZ'；
cylinder 长度沿局部 Y；extrude 的 profile 在局部 XY 平面，厚度 depth 沿局部 Z 居中。
"""
import math

SOLID_KINDS = {"box", "cylinder", "extrude"}


def rot_matrix(rot):
    if not rot:
        return ((1, 0, 0), (0, 1, 0), (0, 0, 1))
    x, y, z = (math.radians(a) for a in rot)
    cx, sx, cy, sy, cz, sz = math.cos(x), math.sin(x), math.cos(y), math.sin(y), math.cos(z), math.sin(z)
    # three.js Euler 'XYZ'：M = Rx · Ry · Rz
    return ((cy * cz, -cy * sz, sy),
            (cx * sz + sx * sy * cz, cx * cz - sx * sy * sz, -sx * cy),
            (sx * sz - cx * sy * cz, sx * cz + cx * sy * sz, cx * cy))


def mat_vec(m, v):
    return [m[0][0] * v[0] + m[0][1] * v[1] + m[0][2] * v[2],
            m[1][0] * v[0] + m[1][1] * v[1] + m[1][2] * v[2],
            m[2][0] * v[0] + m[2][1] * v[1] + m[2][2] * v[2]]


def mat_t_vec(m, v):
    return [m[0][0] * v[0] + m[1][0] * v[1] + m[2][0] * v[2],
            m[0][1] * v[0] + m[1][1] * v[1] + m[2][1] * v[2],
            m[0][2] * v[0] + m[1][2] * v[1] + m[2][2] * v[2]]


def in_polygon(x, y, poly):
    inside = False
    j = len(poly) - 1
    for i in range(len(poly)):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


def edge_dist(x, y, poly):
    best = float("inf")
    for i in range(len(poly)):
        (x1, y1), (x2, y2) = poly[i], poly[(i + 1) % len(poly)]
        dx, dy = x2 - x1, y2 - y1
        L = dx * dx + dy * dy
        t = 0 if L == 0 else max(0, min(1, ((x - x1) * dx + (y - y1) * dy) / L))
        best = min(best, math.hypot(x - x1 - t * dx, y - y1 - t * dy))
    return best


class Solid:
    def __init__(self, d, off=(0, 0, 0)):
        self.id, self.kind = d["id"], d["kind"]
        self.c = [p + o for p, o in zip(d["pos"], off)]
        self.R = rot_matrix(d.get("rot"))
        if self.kind == "box":
            self.h = [s / 2 for s in d["size"]]
        elif self.kind == "cylinder":
            self.r, self.hl = d["radius"], d["length"] / 2
        else:
            self.poly, self.hd = [tuple(p) for p in d["profile"]], d["depth"] / 2
        self._verts = None
        self._aabb = None

    def local(self, p):
        return mat_t_vec(self.R, [p[i] - self.c[i] for i in range(3)])

    def contains(self, p, shrink=0.0):
        q = self.local(p)
        if self.kind == "box":
            return all(abs(q[i]) <= self.h[i] - shrink for i in range(3))
        if self.kind == "cylinder":
            return abs(q[1]) <= self.hl - shrink and q[0] ** 2 + q[2] ** 2 <= (self.r - shrink) ** 2
        if abs(q[2]) > self.hd - shrink or not in_polygon(q[0], q[1], self.poly):
            return False
        return shrink <= 0 or edge_dist(q[0], q[1], self.poly) >= shrink

    def vertices(self):
        if self._verts is None:
            if self.kind == "box":
                loc = [[sx * self.h[0], sy * self.h[1], sz * self.h[2]] for sx in (-1, 1) for sy in (-1, 1) for sz in (-1, 1)]
            elif self.kind == "cylinder":
                loc = [[self.r * math.cos(a), s * self.hl, self.r * math.sin(a)]
                       for s in (-1, 1) for a in (i * math.pi / 8 for i in range(16))]
            else:
                loc = [[x, y, s * self.hd] for s in (-1, 1) for x, y in self.poly]
            self._verts = [[a + b for a, b in zip(mat_vec(self.R, v), self.c)] for v in loc]
        return self._verts

    def aabb(self):
        if self._aabb is None:
            vs = self.vertices()
            self._aabb = ([min(v[i] for v in vs) for i in range(3)], [max(v[i] for v in vs) for i in range(3)])
        return self._aabb


def overlap_volume(a, b, shrink=0.08, max_points=12000):
    (alo, ahi), (blo, bhi) = a.aabb(), b.aabb()
    lo = [max(alo[i], blo[i]) for i in range(3)]
    hi = [min(ahi[i], bhi[i]) for i in range(3)]
    if any(hi[i] - lo[i] <= 2 * shrink for i in range(3)):
        return 0.0
    vol = (hi[0] - lo[0]) * (hi[1] - lo[1]) * (hi[2] - lo[2])
    step = max(0.3, (vol / max_points) ** (1 / 3))
    n = [max(1, int((hi[i] - lo[i]) / step)) for i in range(3)]
    cell = [(hi[i] - lo[i]) / n[i] for i in range(3)]
    hits = 0
    for ix in range(n[0]):
        x = lo[0] + (ix + .5) * cell[0]
        for iy in range(n[1]):
            y = lo[1] + (iy + .5) * cell[1]
            for iz in range(n[2]):
                p = (x, y, lo[2] + (iz + .5) * cell[2])
                if a.contains(p, shrink) and b.contains(p, shrink):
                    hits += 1
    return hits * cell[0] * cell[1] * cell[2]


def anchored(point, axis, solids, eps=0.2):
    """五金件基点贴在某个实体表面上：往里 eps 在内部，往外 eps 在外部。"""
    inner = [p - a * eps for p, a in zip(point, axis)]
    outer = [p + a * eps for p, a in zip(point, axis)]
    return any(s.contains(inner) and not s.contains(outer) for s in solids)


def ray_blocked(o, d, solid, step=0.4, far=400):
    lo, hi = solid.aabb()
    t0, t1 = 0.0, far
    for i in range(3):
        if abs(d[i]) < 1e-9:
            if not lo[i] <= o[i] <= hi[i]:
                return False
            continue
        a, b = (lo[i] - o[i]) / d[i], (hi[i] - o[i]) / d[i]
        t0, t1 = max(t0, min(a, b)), min(t1, max(a, b))
        if t0 > t1:
            return False
    t = max(t0, 0.01)
    while t <= t1:
        if solid.contains([o[i] + d[i] * t for i in range(3)], 0.02):
            return True
        t += step
    return False
