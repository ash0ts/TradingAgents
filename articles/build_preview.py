"""Render canonical articles with local assets for responsive visual checks."""

import shutil
from pathlib import Path

import markdown

ROOT = Path(__file__).resolve().parent
OUT = Path("/private/tmp/tradingagents-visual-preview")
OUT.mkdir(exist_ok=True)
CSS = """
body{margin:0;background:#fcfaf6;color:#172633;font:18px/1.7 Georgia,serif}
main{max-width:760px;margin:65px auto;padding:0 26px 90px}h1{font-size:42px;line-height:1.16;margin-bottom:30px}
a{color:#226d86;text-underline-offset:3px}p{margin:1.2em 0}img{max-width:100%;height:auto;display:block;margin:34px auto 12px}
img:hover{cursor:zoom-in}em{font-size:15px;color:#46535d}table{border-collapse:collapse;width:100%;font:14px/1.5 system-ui,sans-serif}
th,td{padding:10px;border-bottom:1px solid #cbd5d4;text-align:left}th{background:#edf3f1}.table-scroll{overflow-x:auto}
code{font-size:.88em;overflow-wrap:anywhere}a:focus-visible,.table-scroll:focus-visible{outline:3px solid #b68730;outline-offset:3px}
@media(max-width:600px){main{margin-top:30px;padding:0 18px 60px}h1{font-size:32px}body{font-size:17px}th,td{min-width:105px}em{font-size:14px}}
"""
for path in [ROOT / "agent-lens-in-practice/article.md"]:
    dest = OUT / path.parent.name
    dest.mkdir(exist_ok=True)
    shutil.copytree(path.parent / "assets", dest / "assets", dirs_exist_ok=True)
    html = markdown.markdown(
        path.read_text().replace("/article.md)", "/article.html)"),
        extensions=["tables", "fenced_code"],
    )
    html = html.replace(
        "<table>",
        '<div class="table-scroll" tabindex="0" role="region" aria-label="Data table; scroll horizontally on narrow screens"><table>',
    ).replace("</table>", "</table></div>")
    (dest / "article.html").write_text(
        f'<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{path.parent.name}</title><style>{CSS}</style><main>{html}</main></html>'
    )
shutil.copytree(ROOT / "evidence", OUT / "evidence", dirs_exist_ok=True)
shutil.copytree(ROOT / "trading-scenarios", OUT / "trading-scenarios", dirs_exist_ok=True)
print(OUT)
