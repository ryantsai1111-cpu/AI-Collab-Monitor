from pathlib import Path
p=Path('run.py');s=p.read_text(encoding='utf-8-sig');s=s.replace("exe=settings.pop('executable',default)","exe=settings.pop('executable',default)\n        settings.setdefault('attachment_roots',[str(core.store.artifact_dir)])")
s=s.replace('        raise\n','        sys.exit(1)\n');p.write_text(s,encoding='utf-8')
p=Path('README.md');s=p.read_text(encoding='utf-8-sig');s=s.replace('`python -m unittest discover -s tests -v` runs unit/contract tests', '`python scripts/run_tests.py` runs the normal-permission core/adapter/security suites. The separate `python -m unittest discover -s tests -p test_ui.py -v` suite requires working Qt access and is currently BLOCKED by the recorded dependency permission issue. Tests')
p.write_text(s,encoding='utf-8')
