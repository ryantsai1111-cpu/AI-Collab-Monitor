"""Apply only newly proven criteria; preserve the prior audit's evidence scopes."""
from pathlib import Path
from collections import Counter
import datetime
import json
import re

ROOT = Path(__file__).resolve().parents[1]
E = ROOT / 'evidence'
read = lambda p: json.loads((E / p).read_text(encoding='utf-8-sig'))
write = lambda p, v: (E / p).write_text(json.dumps(v, ensure_ascii=False, indent=2), encoding='utf-8')
now = datetime.datetime.now(datetime.timezone.utc).isoformat()
claude = read('live-claude-tools-ui/result.json')
screens = read('multi-monitor-ui/result.json')
assert claude['status'] == 'PASS' and all(claude['checks'].values())
assert screens['status'] == 'PASS' and len(screens['screens']) >= 2 and all(screens['checks'].values())
coverage = read('requirement-coverage.json')
criteria = {r['id']: r for r in coverage['criteria']}
mapping = {
    'R006.08': ('live-claude-tools-ui/result.json', 'actual_file_edit; native_file_event; file_edit_in_actual_UI',
                'Actual official Claude Edit and visible Qt file card after explicit human native approval; isolated fixture only'),
    'R006.09': ('live-claude-tools-ui/result.json', 'native_command_event; command_output_in_actual_UI; independent_test_pass',
                'Actual official Claude Bash unittest command/output in Qt after human native approval; independently verified fixture test'),
    'R041.05': ('multi-monitor-ui/result.json', '10 checks on two physical displays at 125%/175% scaling',
                'Actual source Qt move, full visibility, input reachability, reopen-position restoration, no backend startup; initial clipping failure preserved and corrected'),
}
for rid, (path, case, scope) in mapping.items():
    criteria[rid].update(status='PASS', reason=scope, evidence=[{'path': 'evidence/' + path, 'case': case, 'scope': scope}])
criteria['R006.06'].update(reason='Official Claude init reports configured MCP servers/tools, including connected, failed, needs-auth and pending states. Read-only inventory is available; actual authorized MCP execution is not verified. No new service or external tool call inferred.',
                          evidence=[{'path': 'evidence/existing-capabilities-inventory.json', 'scope': 'Allowlisted existing official handshake metadata only, not tool execution'},
                                    {'path': 'acw/adapters/claude.py', 'scope': 'Read-only diagnostic snapshot, never a runtime MCP pass'}])
for r in coverage['criteria']:
    r['reason'] = r.get('reason', '').replace('ungranted Claude Edit/command effect also remain blocked', 'configured MCP execution remains unverified')
coverage['status_counts'] = dict(Counter(r['status'] for r in coverage['criteria']))
for section in coverage['sections']:
    counts = Counter(r['status'] for r in coverage['criteria'] if r['section'] == section['section'])
    section['counts'] = dict(counts)
    section['status'] = next(s for s in ('FAIL', 'BLOCKED', 'PENDING', 'UNSUPPORTED', 'PASS') if counts[s])
coverage['observed_utc'] = now
coverage['authorized_followup'] = {'observed_utc': now, 'resolved': list(mapping),
    'scope': 'Single expressly authorized Claude human-approval run and isolated actual multi-monitor UI; previous audit and historical failures preserved'}
coverage['independent_reconciliation']['remaining_independent'] = []
coverage['independent_reconciliation']['authorized_followup_mapping'] = 'scripts/reconcile_authorized_followup.py'
baseline = read('pending-acceptance-classification.json')
for r in baseline['criteria']:
    if r['id'] in mapping:
        actual = criteria[r['id']]
        r.update(status='PASS', reason=actual['reason'], evidence=actual['evidence'][0])
baseline['outcome_counts'] = dict(Counter(r['status'] for r in baseline['criteria']))
baseline['reconciled_utc'] = now
write('pending-acceptance-classification.json', baseline)
write('requirement-coverage.json', coverage)
remaining = [{k: r.get(k) for k in ('id', 'criterion', 'status', 'reason', 'evidence')}
             for r in coverage['criteria'] if r['status'] != 'PASS']
write('REMAINING-ACCEPTANCE.json', {'observed_utc': now, 'final_gate': 'BLOCKED', 'counts': coverage['status_counts'], 'criteria': remaining})
(E / 'REMAINING-ACCEPTANCE.md').write_text('# Remaining acceptance criteria\n\nFinal remains BLOCKED. Scoped source acceptance does not replace native Dot or executable acceptance.\n\n| ID | Status | Requirement | Specific blocker or limitation |\n|---|---|---|---|\n' + '\n'.join(
    f"| {r['id']} | {r['status']} | {r['criterion']} | {r['reason'].replace('|', '/')} |" for r in remaining) + '\n', encoding='utf-8')
doc = ROOT / 'docs/REQUIREMENTS.md'
lines = doc.read_text(encoding='utf-8').splitlines()
sections = {s['section']: s for s in coverage['sections']}
for n, line in enumerate(lines):
    match = re.match(r'\| (R\d+\.\d+) /', line)
    if match and match[1] in {*mapping, 'R006.06'}:
        r = criteria[match[1]]
        links = '; '.join(f"{ev['path']} ({ev.get('case', ev.get('scope', ''))})" for ev in r['evidence'])
        lines[n] = f"| {r['id']} / {r['planned_case']} | {r['criterion']} | {r['status']} | {r['reason']} Evidence: {links} |"
    section_match = re.match(r'\| R(\d{3}) \|', line)
    if section_match:
        section = sections[int(section_match[1])]
        cells = line.split('|')
        cells[-3] = ' ' + section['status'] + ' '
        cells[-2] = ' ' + '; '.join(f'{count} {status}' for status, count in section['counts'].items()) + '; see individual rows '
        lines[n] = '|'.join(cells)
text = '\n'.join(lines) + '\n'
text = text.replace('589 PASS, 0 FAIL, 60 BLOCKED', '592 PASS, 0 FAIL, 57 BLOCKED')
text = text.replace('182PASS/2ungranted-Claude-tool-effect BLOCKED', '184PASS/0independent BLOCKED')
text = text.replace('Core125PASS/2opt-in skips (127discovered)', 'Core127PASS/2opt-in skips (129discovered)')
text = text.replace('actual Edit/command effects blocked by canceled ungranted native permission. No automatic reopen.', 'human-approved actual Edit/command effects7PASS; configured MCP execution still unverified.')
doc.write_text(text, encoding='utf-8')
print(json.dumps({'counts': coverage['status_counts'], 'newly_resolved': list(mapping)}, indent=2))
