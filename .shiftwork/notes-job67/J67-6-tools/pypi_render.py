import re, sys, pathlib, importlib.metadata as md
from readme_renderer.markdown import render
src = pathlib.Path(sys.argv[1]).read_text(encoding="utf-8")
html = render(src, variant="GFM")
assert html, "render returned None"
pathlib.Path(sys.argv[2]).write_text(html, encoding="utf-8")
ids = set(re.findall(r'id="([^"]+)"', html))
hrefs = re.findall(r'href="([^"]+)"', html)
inpage = [h for h in hrefs if h.startswith("#")]
bad = [h for h in inpage if h[1:] not in ids]
rel = [h for h in hrefs if not h.startswith(("#", "http://", "https://"))]
imgs = re.findall(r'<img [^>]*src="([^"]+)"', html)
print(f"readme_renderer {md.version('readme_renderer')}: {len(hrefs)} hrefs, {len(inpage)} in-page, {len(bad)} unresolved, {len(rel)} relative, {len(imgs)} images, {len(ids)} ids")
for h in bad: print("UNRESOLVED", h)
for h in rel: print("RELATIVE", h)
print("headings:", re.findall(r'<h2 id="([^"]+)"', html)[:20])
