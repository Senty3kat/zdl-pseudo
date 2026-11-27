from pathlib import Path
from PIL import Image, ImageDraw
import json

ROOT = Path(r"C:\zoom\zdlnew\SWEEP10_NATIVE")
report = json.loads((ROOT / "FINAL_REPORT.json").read_text(encoding="utf-8"))
thumbs = []
for r in report:
    p = Path(r["spec_orig_vs_rebuilt"])
    im = Image.open(p).convert("RGB")
    im.thumbnail((640, 360))
    thumbs.append((r["effect"], im))
w = 640 * 2
h = 400 * ((len(thumbs) + 1) // 2)
out = Image.new("RGB", (w, h), "white")
d = ImageDraw.Draw(out)
for i, (name, im) in enumerate(thumbs):
    x = (i % 2) * 640
    y = (i // 2) * 400
    d.text((x + 8, y + 4), name, fill="black")
    out.paste(im, (x, y + 30))
path = ROOT / "CONTACT_SPEC_ORIG_VS_REBUILT.png"
out.save(path)
print(path, out.size)
