from pathlib import Path
from datetime import datetime
import shutil, py_compile

PACKAGE = Path(__file__).resolve().parent
ROOT = Path.home() / "PyForge"
if not (ROOT / "main.py").is_file() or not (ROOT / "vision_studio" / "router.py").is_file():
    raise SystemExit("PyForge root not found at ~/PyForge. Nothing changed.")
main = ROOT / "main.py"
dashboard = ROOT / "dashboard_v2" / "index.html"
advanced = ROOT / "vision_studio" / "advanced.py"
for path in (main, dashboard):
    if not path.is_file():
        raise SystemExit(f"Required file missing: {path}")

stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
shutil.copy2(main, main.with_name(main.name + f".vision-full-backup-{stamp}"))
shutil.copy2(dashboard, dashboard.with_name(dashboard.name + f".vision-full-backup-{stamp}"))
shutil.copy2(PACKAGE / "vision_studio" / "advanced.py", advanced)

src = main.read_text(encoding="utf-8")
import_line = "from vision_studio.advanced import router as vision_advanced_router"
if import_line not in src:
    anchor = "from vision_studio.router import router as vision_router"
    if anchor not in src:
        raise SystemExit("Could not find existing Vision router import. Backups retained; main.py unchanged.")
    src = src.replace(anchor, anchor + "\n" + import_line, 1)
registration = "app.include_router(vision_advanced_router)"
if registration not in src:
    anchor = "app.include_router(vision_router)"
    if anchor not in src:
        raise SystemExit("Could not find existing Vision router registration. Backups retained; main.py unchanged.")
    src = src.replace(anchor, anchor + "\n" + registration, 1)
main.write_text(src, encoding="utf-8")

html = dashboard.read_text(encoding="utf-8")
if "PYFORGE_VISION_FULL_ENGINE_UI_V1" not in html:
    review_panel = (PACKAGE / "review_panel.html").read_text(encoding="utf-8")
    app_panel = (PACKAGE / "app_panel.html").read_text(encoding="utf-8")

    def add_to_section(document, section_id, panel):
        start = document.find(f'<section class="page" id="{section_id}">')
        if start < 0:
            raise SystemExit(f"Could not find existing {section_id}; backups retained.")
        end = document.find("</section>", start)
        if end < 0:
            raise SystemExit(f"Could not find closing section for {section_id}; backups retained.")
        return document[:end] + "\n" + panel + "\n" + document[end:]

    html = add_to_section(html, "page-vision-review", review_panel)
    html = add_to_section(html, "page-vision-app", app_panel)
    js = (PACKAGE / "vision_ui.js").read_text(encoding="utf-8")
    html += "\n<script>\n" + js + "\n</script>\n"
    dashboard.write_text(html, encoding="utf-8")

py_compile.compile(str(advanced), doraise=True)
py_compile.compile(str(main), doraise=True)
print("PyForge Vision AI Studio full engine installed successfully.")
print("Only these existing files were modified: main.py and dashboard_v2/index.html")
print("New backend module: vision_studio/advanced.py")
print("Backups:")
print(" -", main.name + f".vision-full-backup-{stamp}")
print(" -", dashboard.name + f".vision-full-backup-{stamp}")
print("No existing project, original reference image, login database, supervisor or Backup Guardian was changed.")
