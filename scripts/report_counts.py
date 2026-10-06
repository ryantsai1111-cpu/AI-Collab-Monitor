from pathlib import Path
p=Path('evidence/FINAL-ACCEPTANCE-REPORT.md');s=p.read_text(encoding='utf-8-sig').replace('11 authored Qt tests','13 authored Qt tests').replace('the 11 Qt tests','the 13 Qt tests');p.write_text(s,encoding='utf-8')
