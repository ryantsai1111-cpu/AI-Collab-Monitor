from pathlib import Path
p=Path('evidence/FINAL-ACCEPTANCE-REPORT.md');s=p.read_text(encoding='utf-8');s=s.replace('- Compiled Windows launcher:', '- Compiled Windows launcher (not launched or double-clicked):')
s=s.replace('No shortcut or installed-app acceptance claimed.', 'No shortcut or installed-app acceptance claimed.')
s += '''

## One-time UI test request prepared for the user

The exact smallest proposed action is:

```powershell
& 'C:\\Users\\ryant\\.cache\\codex-runtimes\\codex-primary-runtime\\dependencies\\python\\python.exe' scripts\\run_ui_tests.py --visible
```

Run once from the source directory in the normal interactive `ryant` user context, outside the restricted tool token, without administrator rights, network, downloads, ACL changes, login or real backend activity. The source-reviewed runner uses only synthetic UI fixtures, creates temporary datasets, saves test-window screenshots/results under `evidence/ui-acceptance`, and exits (180-second watchdog). It has **not run**. The process would have normal user filesystem rights and may change focus/show test windows; this is the narrow permission exception to approve or decline. Passing it would still not certify three live backend UI operation.

The candidate `.exe` has never been launched. A prior approved `python run.py` startup was closed after observing no startup traceback; no interaction was certified. The intended per-user app/data directories and both shortcuts do not exist yet. Source and all current test evidence remain in the task-2 workspace.
'''
p.write_text(s,encoding='utf-8')
