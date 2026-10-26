# Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| No search results | Query not in English, or the name is misspelled | English product name + type (`BEKVAM step stool`; ä can be a); `--list` to see candidates |
| "No assembly PDF on the product page" | Some IKEA markets don't link the manual (us/en often) | The script tries th/en first; otherwise pass the th/en product page with `--url`, or download the PDF and use `--pdf --name --dims` |
| Long side ends up as depth | IKEA product pages sometimes swap width and depth | The model is told to decide from the drawings; if still wrong pass `--dims WxHxD` and rerun with `--reuse-extraction` |
| `claude 调用失败` (claude call failed) | Not logged in, out of quota, or network | Check `claude` works in a terminal; rerun later with `--reuse-extraction` if extraction finished |
| Errors left after 3 repair rounds | Coordinate conflicts or a camera it can't fix | `python3 scripts/pipeline.py ~/manual-to-3d/manuals/<slug>/manual.pdf --slug <slug> --name … --dims … --resume --repairs 2`; for a few camera errors, edit that step's `camera` (target / height / dir) in `scenes/<slug>.json` and rerun `validate.py` |
| Repair rounds regress or invent unsupported kinds | Model drift during repair | The pipeline keeps the round with the fewest errors; `--resume` for another try |
| A part is off-screen or hidden in the player | The validator samples the moment a part lands | Open `?step=N`, adjust that step's `camera`, confirm with `validate.py` |
| Blank thumbnail | No Chrome, or WebGL unavailable | Install Chrome, or open `guide.html?scene=<slug>&thumb=1` and save a screenshot as `thumbs/<slug>.png` |
| `build_public.py` reports errors | Steps that showed a manual illustration had no 3D camera planned | `python3 scripts/fix_public.py <slug>`; otherwise edit the camera in `scenes/public/<slug>.json` |

Script logs and validator messages are currently in Chinese; the meaning is usually clear from the part ids and numbers, and the table above covers the common ones.
