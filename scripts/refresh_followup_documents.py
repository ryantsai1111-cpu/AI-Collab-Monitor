"""Update the existing audited report renderer without replacing its audit fixes."""
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
p = ROOT / 'scripts/current_acceptance_report.py'
text = p.read_text(encoding='utf-8')
text = text.replace("'Claude actual Edit/command attempt canceled without approval after user reported closed window; no automatic re-send',", '')
text = text.replace('Configured official MCP and physical multi-monitor prerequisites not established; unapproved private integration unused',
                    'Configured official MCP tool execution remains unverified; physical two-monitor source UI passed; unapproved private integration unused')
text = text.replace('the original184 independent criteria have182 scoped PASS and2 actual Claude tool-effect checks BLOCKED by ungranted native permission',
                    'the original184 independent criteria now have184 scoped PASS, including the subsequently expressly authorized human-approved Claude tool-effect run')
text = text.replace('Eleven older blockers were independently resolved with new evidence.',
                    'Eleven older blockers and three later criteria were resolved with new evidence.')
lines = text.splitlines()
for n, line in enumerate(lines):
    if line.startswith('| Claude actual Edit/command effects |'):
        lines[n] = '| Claude actual Edit/command effects |7 checks PASS | `live-claude-tools-ui/result.json`: one newly expressly authorized run, actual native human Edit and Bash approvals, fixture minus-to-plus edit, file/command UI cards and independent unittest PASS. Earlier canceled request is retained in `live-claude-tools-ui-first/`; no permission mode or sandbox change. |'
    if line.startswith('The smallest possible user action for Claude is'):
        lines[n] = 'Claude\'s previously canceled request stayed expired. The user subsequently explicitly authorized one new isolated run and personally approved its Edit/Bash requests;7 checks passed. No further prompt or approval is needed for these two resolved criteria.'
    if line.startswith('The EXE needs only user-visible security diagnosis'):
        lines[n] = 'EXE work is now explicitly deferred by the user. No executable, launcher, antivirus or security-setting operation is part of this continuation. Historical security rejection details remain in `EXE-SECURITY-BLOCKER.md`; no false-positive or runtime acceptance is claimed.'
    if line.startswith('Dot requires a verified authorized official supported integration route.'):
        lines[n] += ' New static GitHub/official research: `docs/GITHUB-DOT-RESEARCH.md` and `github-dot-research.json`. Official OSS/local OAuth may support separately authorized Responses inference without a new API key, but explicitly excludes existing ChatGPT/Dot conversations/account context. No new login, token transfer, service or backend was used.'
    if line.startswith('Repairs exercised this continuation:'):
        lines[n] += ' Actual two-monitor testing found secondary-screen clipping at175% scaling; a scrollable workspace and bounded restored geometry fixed it. Current `multi-monitor-ui/result.json`10PASS, first failure preserved. Claude Diagnostics also exposes only allowlisted MCP names/status/tool-name snapshots; unknown and cached state never claim successful tool execution.'
    if line.startswith('Normal: `python scripts/run_tests.py`.'):
        lines[n] = 'Normal: `python scripts/run_tests.py`. Visible isolated UI: `python scripts/run_ui_tests.py --visible`. Physical displays: `python scripts/verify_multi_monitor_ui.py`. Read-only recorded capability inventory: `python scripts/inventory_existing_capabilities.py`. Live scripts remain opt-in with existing official permissions; never replay completed or canceled write prompts without new explicit authorization. Package: `python scripts/package_source.py`.'
text = '\n'.join(lines) + '\n'
text = text.replace('Baseline outcome:182PASS and15BLOCKED. Independent R006.08/R006.09 were actually attempted and remain blocked as described above.',
                    'Current baseline outcome:185PASS and12BLOCKED. Independent R006.08/R006.09 passed the new expressly authorized human-approval run; R041.05 passed actual dual-display Qt verification.')
text = text.replace('remaining60BLOCKED and4UNSUPPORTED', 'remaining57BLOCKED and4UNSUPPORTED')
text = text.replace('R041.05 (physical multi-monitor verification outstanding)', 'R041.05 (now resolved by actual two-monitor source UI10PASS)')
text = text.replace("'pass':182,'blocked':['R006.08','R006.09']", "'pass':184,'blocked':[]")
text = text.replace("'independent_pass':182,'independent_blocked':2", "'independent_pass':184,'independent_blocked':0")
p.write_text(text, encoding='utf-8')
readme = ROOT / 'README.md'
s = readme.read_text(encoding='utf-8').replace('125PASS/0FAIL/2opt-in skips (127discovered)', '127PASS/0FAIL/2opt-in skips (129discovered)')
s = s.replace('The canceled ungranted Claude Edit/command attempt remains blocked and will not be reopened/re-sent automatically.',
              'One subsequently expressly authorized Claude run passed7 actual human-approved file/command/UI checks. Physical two-monitor Qt checks passed10 after fixing high-DPI clipping; previous canceled/failed attempts are preserved.')
s = s.replace('589PASS/0FAIL/60BLOCKED', '592PASS/0FAIL/57BLOCKED')
readme.write_text(s, encoding='utf-8')
(ROOT / 'docs/CONTINUATION-NOTES.md').write_text('''# Validated authorized follow-up

592 scoped criteria PASS /0FAIL /57BLOCKED /4UNSUPPORTED /0PENDING. Final remains BLOCKED by native Dot transport, deferred EXE acceptance, unverified configured MCP tool execution and the individually listed gates. All184 originally independent criteria have scoped PASS. Counts are not653 native end-to-end tests.

The old Claude Edit request was canceled and remains historical. The user subsequently explicitly approved reopening exactly one isolated run. Actual human Edit/Bash approvals, file mutation, visible Qt file/command cards and independent unittest passed7 checks. No automatic grant, permission-mode change, sandbox change or production repo operation occurred.

Ryan-PC has two physical displays at125% and175% scaling. Initial secondary-screen clipping was preserved, repaired with a scrollable workspace and geometry bounds, then10 actual move/visibility/input/reopen/no-backend checks passed. Normal suite127PASS/2opt-in skips (129discovered). Current visible50-case regression and historical failures are separately recorded.

Official MCP metadata includes connected, needs-auth, failed and pending servers. Diagnostics now shows an allowlisted read-only snapshot without service URLs, arguments or credentials; this does not prove tool execution. No new MCP service or external tool was invoked.

GitHub/official static research in GITHUB-DOT-RESEARCH.md confirms eligible OSS OAuth can enable separately authorized inference without a new API key, but excludes existing ChatGPT/Dot conversations. Native Dot continuity is still BLOCKED. No fake Dot runtime acceptance.

Installed Python/document sources are backed up and hash-checked separately from runtime acceptance. User data, legacy Monitor and active sessions stay untouched. EXE and antivirus operations are deferred; no executable restore/copy/rebuild/start or security change is authorized here. Use the current Final Acceptance Report and remaining-criterion ledger.
''', encoding='utf-8')
guide = ROOT / 'docs/USER_GUIDE.md'
content = guide.read_text(encoding='utf-8')
note = '\n## Smaller high-DPI screens\n\nThe workspace can scroll vertically and horizontally when the three panels exceed the available logical screen area. Scroll to reach input/actions; reopening restores the selected screen and bounds the window to available space. Diagnostics shows Claude MCP server/tool names as an observed snapshot only, with current agent connection state; it does not execute or authorize tools.\n'
if '## Smaller high-DPI screens' not in content:
    guide.write_text(content + note, encoding='utf-8')
print('Audited renderer preserved; authorized follow-up documents updated')
