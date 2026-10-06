"""Read active Qt screen topology and already-recorded official MCP metadata.

No agent connects, MCP tools execute, config files open, or screen settings change.
"""
from pathlib import Path
import datetime
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'vendor'), str(ROOT)]
from PySide6.QtGui import QGuiApplication

app = QGuiApplication([])
screens = []
for screen in app.screens():
    geometry = screen.geometry()
    available = screen.availableGeometry()
    screens.append({
        'name': screen.name(),
        'geometry': [geometry.x(), geometry.y(), geometry.width(), geometry.height()],
        'available_geometry': [available.x(), available.y(), available.width(), available.height()],
        'logical_dpi': screen.logicalDotsPerInch(),
        'device_pixel_ratio': screen.devicePixelRatio(),
        'primary': screen == app.primaryScreen(),
    })

source = ROOT / 'evidence/live-claude-tools-ui/public-events.json'
events = json.loads(source.read_text(encoding='utf-8'))
initializations = []
for event in events:
    payload = event.get('payload', {})
    if 'mcp_servers' in payload:
        servers = payload.get('mcp_servers') or []
        initializations.append({
            'timestamp': event.get('timestamp'),
            'servers': [{'name': str(s.get('name', '')), 'status': str(s.get('status', 'unknown'))}
                        for s in servers if isinstance(s, dict)],
            'mcp_tool_names': [str(t) for t in payload.get('tools', []) if str(t).startswith('mcp__')],
        })

report = {
    'observed_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
    'scope': 'Read-only active screen topology and allowlisted metadata from existing isolated official Claude evidence; no backend/config/credential reads or service/tool calls',
    'screens': screens,
    'multi_monitor_acceptance': 'BLOCKED' if len(screens) < 2 else 'NOT YET TESTED',
    'mcp_evidence_source': source.relative_to(ROOT).as_posix(),
    'official_claude_initializations': initializations,
    'mcp_runtime_acceptance': 'BLOCKED',
    'mcp_limit': 'Metadata does not demonstrate configured MCP tool execution; no new service or tool approval inferred',
    'system_settings_changed': False,
    'mcp_tools_called': False,
}
out = ROOT / 'evidence/existing-capabilities-inventory.json'
out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps(report, ensure_ascii=True, indent=2))
