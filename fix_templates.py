"""Fix 6 templates with illegal \\T<digit> macro names and ${CMD} placeholders."""
from pathlib import Path
import re

base = Path("skills/resume-master/examples")
templates = ["purple_tech", "orange_warm", "teal_clean", "navy_sidebar", "dark_sidebar", "minimal_bw"]

for tmpl in templates:
    cls_path = base / tmpl / "latex" / f"{tmpl}.cls"
    if not cls_path.is_file():
        print(f"SKIP {tmpl}: no cls")
        continue

    # Fix cls: \T9Foo -> \Foo
    ctxt = cls_path.read_text(encoding="utf-8")
    # Find commands like \T9Header, \T5SectionTitle etc
    # Use plain string replacement for each distinct command family
    digit_cmds = re.findall(r'\\T(\d)([A-Z][a-zA-Z]*)', ctxt)
    families = set(name for (_digit, name) in digit_cmds)
    for name in sorted(families):
        ctxt = re.sub(r'\\T\d' + re.escape(name), r'\\' + name, ctxt)
    if families:
        cls_path.write_text(ctxt, encoding="utf-8")
        print(f"{tmpl}.cls: fixed {len(families)} commands: {sorted(families)}")
    else:
        print(f"{tmpl}.cls: already clean")

    # Fix partials: ${CMD} -> backslash
    partials_dir = base / tmpl / "latex" / "partials"
    if not partials_dir.is_dir():
        continue
    for p in partials_dir.glob("*.tex.j2"):
        txt = p.read_text(encoding="utf-8")
        new_txt = txt.replace("${CMD}", "\\")
        if new_txt != txt:
            p.write_text(new_txt, encoding="utf-8")
            print(f"  partial {p.name}: {txt.count('${CMD}')} subs")
