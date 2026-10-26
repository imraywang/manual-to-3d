# scene JSON 格式

播放器 `assets/guide.html` 读这个格式。单位厘米，Y 轴朝上，地面 y=0，家具底面中心在原点，正面朝 +z。

```jsonc
{
  "product": { "name": "KALLAX", "sub": "置物架 2×2", "size": "77 × 77 × 39 cm" },
  "manual": { "pages": "manuals/kallax-2x2/pages/hi-{nn}.png" },   // 可选：说明书页图，{nn} 是两位页码
  "parts": {                       // 零件类型。key 自定，instances 用 part 引用
    "A": { "name": "侧板", "label": "A", "dims": "77 × 39 cm", "icon": "panel", "source": "P1" },
    "dowel": { "name": "木销", "dims": "8 × 30 mm", "icon": "dowel", "source": "H3" }
  },
  "tools": { "allen": { "name": "内六角扳手（随附）", "icon": "allen" } },
  "instances": [
    // 板件：kind=box，pos 是长方体中心，size=[x, y, z]
    { "id": "left", "part": "A", "kind": "box", "size": [3.8, 77, 39], "pos": [-36.6, 38.5, 0] },
    // 带旋转的板（斜腿）：rot 是角度制欧拉角 [x, y, z]，顺序同 three.js 'XYZ'，绕 pos 旋转
    { "id": "leg1", "part": "L", "kind": "box", "size": [3, 40, 3], "pos": [10, 20, 10], "rot": [8, 0, -8] },
    // 圆柱：长度沿局部 Y，pos 是中心；要横放就用 rot
    { "id": "bar", "part": "R", "kind": "cylinder", "radius": 1.5, "length": 60, "pos": [0, 15, 0], "rot": [0, 0, 90] },
    // 拉伸体：profile 是局部 XY 平面上的多边形（厘米，可以是凹的），沿局部 Z 拉伸 depth、居中；pos 是轮廓坐标原点
    { "id": "side", "part": "S", "kind": "extrude", "profile": [[0,0],[40,0],[34,50],[6,50]], "depth": 2, "pos": [-20, 0, 18] },
    // 五金件：pos 是它扎进板面的那个点（必须正好落在某块板的面上），axis 是露出来的方向
    { "id": "dw1", "part": "dowel", "kind": "dowel", "pos": [-34.7, 20, 12], "axis": "+x" },
    // 沉头螺栓 / 螺丝：拧到底与板面齐平，只露一个圆头，加 "flush": true
    { "id": "cb1", "part": "cam_bolt", "kind": "cam_bolt", "pos": [-38.5, 6, 12], "axis": "-x", "flush": true }
  ],
  "steps": [
    {
      "title": "…", "desc": "…", "tip": "…", "say": "口语化的一句朗读",
      "minutes": 3, "tools": ["allen"],
      "source": { "manual_steps": ["1"], "pages": [8] },     // 对应说明书哪一步、哪一页
      "camera": { "target": [0, 20, 0], "height": 80, "dir": [1, 0.8, 1.2] },  // 看向哪里、画面高度（厘米）；dir 可选，是从目标指向相机的方向，默认右前上方
      "actions": [
        // from / to 是相对最终位置的偏移；不写 to 就是回到最终位置；只写 spin 就是原地转
        { "ids": ["left"], "at": 0, "dur": 1.2, "from": [-30, 0, 0] },
        { "ids": ["dw1"], "at": 1.4, "dur": 0.5, "stagger": 0.25, "from": [8, 0, 0] },
        { "ids": ["bolt1"], "at": 2.2, "dur": 1, "spin": 12.6 }
      ],
      "arrows": [ { "at": [x, y, z], "dir": [0, -1, 0], "len": 12, "t0": 0, "t1": 1.2 } ],   // at 是箭头尖
      "callouts": [ { "at": [x, y, z], "icon": "twist|tap|screw", "text": "≤8 个字", "t0": 1.4, "t1": 3 } ]
    },
    {
      // 原图模式：3D 不适合表现的步骤（几十颗钉子钉背板、装抽屉滑轨、穿线、调节铰链），画面换成说明书插图
      "mode": "manual", "title": "…", "desc": "…", "say": "…", "camera": { "target": [0, 40, 0], "height": 100 },
      "source": { "manual_steps": ["14"], "pages": [16] },
      "crop": { "page": 16, "box": [0.05, 0.12, 0.95, 0.7] },      // 页面上的裁切框，按页宽高的比例 0～1，[x0, y0, x1, y1]
      "highlights": [[0.6, 0.3, 0.85, 0.5]],                          // 可选，同一坐标系里要高亮的区域
      "actions": [ { "ids": ["back"], "at": 0, "dur": 0.01, "from": [0, 0, 0] } ]   // 3D 状态照常推进（画面不显示），保证后面的步骤接得上
    }
  ],
  "afterChecks": ["…"]
}
```

## 规则

- `kind`：结构件 `box`、`cylinder`、`extrude`（都可以带 `rot`）；五金件 `cam_bolt`（带球头的连接螺栓）、`screw`（普通螺丝）、`dowel`（木销）、`cam_lock`（偏心锁）、`pad`（圆形脚垫或盖片）。
- `icon`：`panel` `bolt` `dowel` `camlock` `bracket` `screw` `pad` `screwdriver` `hammer` `drill` `allen`。
- 斜的、弯的、圆的零件不要再近似成竖直长方体：斜腿用带 `rot` 的 box，圆腿、横杆用 cylinder，异形侧板（梯形、带弧的近似多边形）用 extrude。
- 说明书里沉头、拧到底和板面齐平的螺栓 / 螺丝一律加 `"flush": true`。
- 原图模式是降级手段：只有 3D 确实表现不清楚的步骤才用，整份说明书里应该是少数。用了也要照常把这一步新装的零件放进 actions，数量核对不变；裁切框要框住这一步的完整插图（包括数量标注），highlights 框住动作的关键位置。
- 五金件只画露在外面的部分，几何从 `pos` 沿 `axis` 长出：螺栓约 3.4 cm，木销 1.6 cm，偏心锁和脚垫是薄圆片。
- 最终状态下板件之间不能互相穿插（贴面可以），所有东西都不能低于地面。
- 每个不带 `noCount` 的 instance 都必须在某一步出现。只用来示意的东西（墙面、同一个零件的第二块板）加 `"noCount": true`；说明书清单里的五金件不能标 noCount，数量要和清单对得上。
- `parts[].source` 指向说明书抽取结果里的清单 id。同一种零件的数量由 instances 推算：不能超过清单数量；每一步新出现的五金件数量，要等于说明书那一步印的「N×」。
- 每一步新装的零件必须在画面里、而且不被别的板挡住（校验器会从零件朝相机打射线检查）。零件在背面或格子里面时，用 `camera.dir` 换个角度，比如从背后看用 `[0.6, 0.5, -1]`、从下往上看底面用 `[0.6, -0.5, 1]`。dir 不能接近垂直（归一化后 y 在 -0.6 到 0.85 之间）；画面高度至少是已装部分投影高度的一半，让人看得出在装哪里。
- 所有 instance 按装好之后的正立姿态摆放。说明书里躺着装、最后再立起来的，在 tip 里说明，不做整体翻转。
