from pathlib import Path
p = Path("/app/app/api/endpoints.py")
if not p.exists():
    print("File not found:", p)
    raise SystemExit(1)
bak = p.with_name(p.name + ".bak2")
bak.write_text(p.read_text(encoding="utf-8"), encoding="utf-8")
s = p.read_text(encoding="utf-8")
lines = s.splitlines()
idx = None
for i, L in enumerate(lines):
    if "return ReportResponse(" in L:
        idx = i
        break
if idx is None:
    print("Could not find return ReportResponse(...) in", p)
    raise SystemExit(1)

patch = [
"# --- BEGIN PATCH: ensure summary is a string ---",
"if not isinstance(report.get('summary', ''), str):",
"    try:",
"        import json",
"        summary = json.dumps(report.get('summary', ''), ensure_ascii=False, indent=2)",
"    except Exception:",
"        summary = str(report.get('summary', ''))",
"else:",
"    summary = report.get('summary', '')",
"# --- END PATCH ---"
]

lines[idx:idx] = patch

ret_start = idx + len(patch)
ret_lines = []
j = ret_start
while j < len(lines):
    ret_lines.append(lines[j])
    if ')' in lines[j]:
        break
    j += 1
ret_block = '\n'.join(ret_lines)
ret_block_new = ret_block.replace('summary=report.get(\"summary\", \"\")', 'summary=summary')
ret_block_new.replace("summary=report.get('summary', '')", 'summary=summary')
new_ret_lines = ret_block_new.split('\n')
lines[ret_start: j+1] = new_ret_lines

p.write_text('\n'.join(lines) + '\n', encoding='utf-8')
print('Patched', p, 'backup at', bak)
