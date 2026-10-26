# What the validator checks

`scripts/validate.py <scene.json> [--extraction manuals/<slug>/extraction.json]` exits 0 when there are no errors. The pipeline runs it after every generation round and hands the errors back to Claude. Every rule comes from a mistake seen in a real manual.

## Structure

Unique ids, valid references; valid kind / axis / size / radius / profile; every part appears in some step and ends in its final position; manual-mode crops and highlights are 0–1 boxes on pages that exist.

## Part counts (against the transcribed manual)

- **Totals**: parts that point to the same inventory item (top and sides can be the same outer panel) are summed and may not exceed the manual's quantity. More is invented → error; fewer is a warning (spares or an unmodelled option).
- **Per step**: when one manual step is split into several scene steps, they are checked together; the hardware newly added = the "N×" printed in that manual step.
- **Relaxed**: parts drawn without a printed count are only checked in total. Parts whose printed counts add up to more than the inventory (BILLY redraws its shelf pins in step 13; MALM counts nails by the bag) are only checked in total, with a warning. Parts the scene installs in a step whose transcription doesn't list them (drawn, not counted, missed in extraction) also only get a warning to check the page. Inventory hardware may not be marked `noCount` to skip the count.

## Geometry (final state)

Everything reduces to "is this point inside a solid", so rotated boxes, cylinders and concave extrusions share one code path (`scripts/solids.py`):

- Solids overlapping by more than 0.5 cm³ → error (grid-sampled volume, 0.08 cm shrink tolerance so touching faces are fine).
- Hardware: 0.2 cm inward from its base point must be inside a solid and 0.2 cm outward must be outside, or it is floating.
- Nothing below the floor.

## Visibility (each step's camera)

- New parts are in frame: all vertices for solids, the exposed point for hardware; frame width assumed 1.5 × height (matches the player on narrow screens).
- Not hidden behind other panels: a ray from the part along the view direction, at the moment its own animation ends (being covered later is normal). A group moving together in one action (a whole drawer) only needs one visible member.
- Flat parts (pads, cam locks, flush bolts) must face the camera; if the same step has an identical part facing the opposite way that already faces the camera, it's only a warning (one camera can't see both sides).
- The camera may not be near-vertical (normalised dir.y between -0.6 and 0.85); the view height must be at least half the projected height of what is assembled.

## What it can't catch

A part mounted backwards or on the wrong face can be geometrically valid. That's why SKILL.md step 3 asks for a manual pass and a comparison against the original pages.
