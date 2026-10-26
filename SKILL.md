---
name: manual-to-3d
description: Turn a flat-pack furniture assembly manual (IKEA and similar) into an interactive 3D step-by-step guide in the browser. Give it one sentence with a product name ("LACK coffee table", "KALLAX shelving unit 2x4"), an IKEA product link, or a manual PDF; it finds the manual and outer size, has Claude read every page and transcribe the parts list, builds an animated 3D scene, checks part counts, geometry and visibility, repairs it automatically, and writes a playable web guide with step animation, parts list, read-aloud and voice commands. Use for "turn this assembly manual into a 3D guide", "animate how to build X", "make a 3D demo of this IKEA manual", "把宜家 XX 做成 3D 演示". Runs locally; it never publishes anything.
---

# manual-to-3d

One sentence in, a playable 3D assembly guide out. Code is in `scripts/`; the player (`guide.html`) and gallery (`index.html`) are in `assets/` and get copied into the workspace on first run. The workspace is `~/manual-to-3d` unless `MANUAL_TO_3D_HOME` is set.

Requirements: the `claude` CLI logged in (all model calls go through `claude -p`, no API key), Python 3.9+, poppler (`pdftoppm`, `pdfinfo`), and optionally Google Chrome for thumbnails.

## 1. Turn the request into a query

IKEA search only understands English product names. Build "NAME + product type + size":

| User says | Query |
|---|---|
| IKEA LACK coffee table / 宜家 LACK 咖啡桌 | `LACK coffee table 90x55` |
| the 2×4 KALLAX | `KALLAX shelving unit 77x147` |
| MALM three-drawer dresser | `MALM chest of 3 drawers` |
| BILLY bookcase, 80 wide | `BILLY bookcase 80x28x202` |
| step stool | `BEKVAM step stool` |

If a name has several sizes, run `python3 scripts/fetch_manual.py "<query>" --list` first. If the user gave no size, pick the most common one (usually the first) and say which one you picked. With an IKEA link use `--url`; with a PDF use `--pdf --name --dims WxHxD` (centimetres). The PDF route works for any brand's manual.

## 2. Run it

```bash
python3 <this skill>/scripts/make.py "<query>"        # run in the background, ~6–12 min
```

It runs `fetch_manual.py` (search, download the manual, read the size) → `pipeline.py` (Claude reads all pages and transcribes the inventory, then builds the scene from the step pages; validate and repair up to 3 rounds) → a headless-Chrome thumbnail → `build_cases.py` (gallery). It ends by printing JSON with steps, parts, remaining errors and warnings, and a preview command.

Useful flags: `--lang zh` (Chinese text and narration, plus an English copy), `--pick N` (Nth search result), `--notes "…"` (extra product facts, e.g. "drawers run on metal slides"), `--reuse-extraction` (rerun without re-reading pages), `--public` (also write `dist/` without any manual page images).

## 3. Check it yourself before reporting (required)

Passing validation is not the same as looking right.

1. Look at `errors` in the JSON. If any remain, follow [troubleshooting.md](references/troubleshooting.md); usually `pipeline.py … --resume --repairs 2` for another round.
2. Serve the workspace (`python3 -m http.server 8931 --directory ~/manual-to-3d`) and open `guide.html?scene=<slug>` (`&step=N` jumps to a step). Go through every step: the new parts are in frame, nothing floats or interpenetrates, the camera shows the action. Compare two or three steps with `manuals/<slug>/pages/hi-NN.png` to make sure nothing is mounted backwards.
3. Read the warnings. "Used M, inventory has N" is usually spare hardware or an unmodelled alternative (e.g. wall-mounting options). "Printed counts exceed the inventory" means the manual draws a part twice or counts by the bag. "Not listed for this step" means the manual drew a part without printing a count; check the page.
4. Report: the product picked (name, size, link), manual pages, steps, parts, repair rounds, remaining warnings and what they mean, the preview URL, the thumbnail path, and anything you noticed while checking.

## 4. Publishing

Only when the user asks. `python3 scripts/build_public.py` writes `dist/`: no manual page images, steps that showed a manual illustration fall back to 3D. If it reports camera problems for those steps, run `python3 scripts/fix_public.py <slug>`. `dist/` is plain static files; host it anywhere. Manual pages are copyrighted by the manufacturer, so never publish `manuals/`.

## What works well

- Best: panel and frame furniture (cabinets, shelves, tables, stools, chests of drawers). Scenes support boxes, rotation, cylinders, extruded profiles and flush hardware; steps 3D can't show clearly (nailing a back panel, drawer runners) fall back to a crop of the manual illustration.
- Poor: bent wood, upholstery, fabric, or products with lots of small mechanisms (POÄNG, sofas, PAX interiors). Tell the user to expect many illustration fallbacks.
- Scenes are posed upright as assembled; "assemble lying down, then stand it up" only appears in tips.

## References

- [scene-schema.md](references/scene-schema.md): the scene format (fed to the model verbatim; written in Chinese, which the model handles fine)
- [validation.md](references/validation.md): what the validator checks and why
- [troubleshooting.md](references/troubleshooting.md): common failures
- [example-scene.json](references/example-scene.json) / [example-scene.en.json](references/example-scene.en.json): a hand-written example (simplified KALLAX)
