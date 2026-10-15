"""Local, read-only collaboration dashboard. Rendering never calls an adapter."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton,
                               QScrollArea, QSizePolicy, QVBoxLayout, QWidget)

from .presentation import compact, time_label
from .theme import MUTED_COLOR, RADIUS, SPACE, desktop_state_color

ROLES = {'claude': ('Claude', '依本次任務分工'), 'codex': ('Codex', '依本次任務分工'),
         'dot': ('G8毛', '可選複核'), 'local': ('Hermes', '可選協作')}
STATES = {'Connected': '已連線', 'Busy': '執行中', 'Disconnected': '未連線',
          'Offline': '離線', 'Error': '錯誤', 'Blocked': '受阻', 'Connecting': '連線中',
          'Stopping': '停止中', 'Interrupted': '已中斷'}
COLORS = {'accent': '#a3e635', 'running': '#67e8f9', 'ready': '#86efac',
          'waiting': '#fbbf24', 'error': '#fda4af', 'muted': '#94a3a0'}


def collect_snapshot(core, panels, run=None):
    """Bounded queries against Workspace metadata; no discovery or remote history."""
    roles = []
    for agent in panels:
        task, project = core.agent_task(agent) or {}, core.agent_project(agent) or {}
        sid = task.get(agent + '_session') or ''
        rows = core.store.query('SELECT title FROM sessions WHERE agent=? AND id=? LIMIT 1', (agent, sid)) if sid else []
        roles.append(dict(agent=agent, name=core.agent_name(agent), provider=core.provider(agent), project=compact(project.get('name')) or '未選專案',
                          task=compact(task.get('title')) or '尚未開啟對話',
                          session=compact(rows[0]['title']) if rows and rows[0]['title'] and rows[0]['title'] != sid else ('已綁定對話' if sid else '尚未綁定對話'),
                          session_id=sid, task_id=task.get('id'), project_id=project.get('id'),
                          state=getattr(core.adapters.get(agent), 'state', 'Disconnected'),
                          approvals=len(panels[agent].pending_approval_events)))
    state = run.snapshot() if run else None
    task_id = state['task_id'] if state else core.current_task_id
    events = core.store.query("SELECT * FROM events WHERE task_id=? AND type='orchestration' "
                              "ORDER BY timestamp DESC,rowid DESC LIMIT 120", (task_id,)) if task_id else []
    events = [e for e in events if not state or e.get('payload', {}).get('run_id') == state['run_id']]
    project = core.get_project(state['project_id']) if state and state['project_id'] else None
    return dict(run=state, roles=roles, events=events[:10],
                project=compact((project or {}).get('name')) or '各 Agent 獨立 Project')


def text(value='', kind='body'):
    item = QLabel(value)
    item.setTextFormat(Qt.PlainText)
    item.setWordWrap(True)
    item.setProperty('kind', kind)
    item.setMinimumWidth(0)
    item.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
    return item


def duration(seconds):
    minutes, seconds = divmod(max(0, int(seconds)), 60)
    return f'{minutes:02d}:{seconds:02d}'


class RoleCard(QFrame):
    def __init__(self, agent, open_role, name=None):
        super().__init__()
        self.setObjectName('monitor_role_' + agent)
        self.setProperty('card', True)
        box = QVBoxLayout(self)
        box.setContentsMargins(SPACE['lg'], SPACE['lg'], SPACE['lg'], SPACE['lg'])
        box.setSpacing(SPACE['sm'])
        top = QHBoxLayout()
        self.title = text(name or ROLES.get(agent, (agent,))[0], 'role')
        self.status = text('', 'muted')
        self.status.setProperty('terminal', True)
        self.status.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        top.addWidget(self.title, 1)
        top.addWidget(self.status, 1)
        box.addLayout(top)
        self.duty = text('依本次任務分工', 'muted')
        self.context = text()
        self.session = text('', 'muted')
        self.action = QPushButton('開啟對話 →')
        self.action.setCursor(Qt.PointingHandCursor)
        self.action.clicked.connect(lambda: open_role.emit(agent))
        for item in (self.duty, self.context, self.session):
            box.addWidget(item)
        box.addStretch()
        box.addWidget(self.action)

    def update_data(self, row, run):
        in_scope = bool(run and row['agent'] in run['agents'] and row['task_id'] == run['task_id'] and row['project_id'] == run['project_id'])
        current = bool(in_scope and run['state'] == 'running' and run['agent'] == row['agent'])
        color = (COLORS['error'] if row['state'] in ('Error', 'Interrupted') else
                 COLORS['waiting'] if row['approvals'] or row['state'] == 'Blocked' else
                 COLORS['running'] if current or row['state'] == 'Busy' else
                 COLORS['ready'] if row['state'] == 'Connected' else COLORS['muted'])
        self.status.setText(f"{row['approvals']} 待核准" if row['approvals'] else STATES.get(row['state'], row['state']))
        desktop = self.window().property('theme') == 'desktop'
        self.status.setStyleSheet('color: ' + (desktop_state_color(row['state'], row['approvals']) if desktop else color))
        participation = ('本輪參與' if run['state'] == 'running' else '最近協作角色') if in_scope else '獨立角色'
        duty = ROLES.get(row.get('provider', row['agent']), ('', '依本次任務分工'))[1]
        if in_scope:
            duty = ('派工 / 驗收' if row['agent'] == run['lead'] else
                    '實作 / 回報' if row['agent'] == run['implementer'] else '複核 / 第二意見')
        self.duty.setText('目前負責 · ' + run['stage'] if current else duty + ' · ' + participation)
        self.context.setText(row['project'] + '\n' + row['task'])
        self.session.setText(row['session'])
        self.session.setToolTip('Session ID：' + (row['session_id'] or '無'))
        self.action.setText('檢視待核准項目 →' if row['approvals'] else '開啟對話 →')
        self.setStyleSheet('' if desktop else f'QFrame#monitor_role_{row["agent"]} {{ border-top: 2px solid {color}; }}')


class MonitorDashboard(QScrollArea):
    open_role = Signal(str)
    open_transcripts = Signal()

    def __init__(self, parent=None, *, names=None):
        super().__init__(parent)
        self.names = names if names is not None else {key: value[0] for key, value in ROLES.items()}
        self.setObjectName('monitor_dashboard')
        self.setAccessibleName('協作監看總覽')
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.body = QWidget()
        self.body.setObjectName('monitor_body')
        self.setWidget(self.body)
        self.box = QVBoxLayout(self.body)
        self.box.setContentsMargins(SPACE['xl'], SPACE['xl'], SPACE['xl'], SPACE['xl'])
        self.box.setSpacing(SPACE['lg'])
        eyebrow = text('>_ ACW / OPERATIONS CONSOLE', 'eyebrow')
        eyebrow.setProperty('terminal', True)
        self.box.addWidget(eyebrow)
        self.heading = text('協作總覽', 'heading')
        self.box.addWidget(self.heading)
        self.subtitle = text('', 'muted')
        self.box.addWidget(self.subtitle)
        transcripts = QPushButton('檢視唯讀對話與 legacy 紀錄 →')
        transcripts.clicked.connect(self.open_transcripts.emit)
        self.box.addWidget(transcripts, alignment=Qt.AlignLeft)
        self.hero = QFrame()
        self.hero.setObjectName('monitor_run')
        self.hero.setProperty('card', True)
        hero = QVBoxLayout(self.hero)
        hero.setContentsMargins(SPACE['xl'], SPACE['lg'], SPACE['xl'], SPACE['lg'])
        hero.setSpacing(SPACE['md'])
        self.phase = text('尚未啟動協作', 'phase')
        self.task = text()
        self.metrics = text('', 'accent')
        self.metrics.setProperty('terminal', True)
        self.route = text('', 'muted')
        for item in (self.phase, self.task, self.metrics, self.route):
            hero.addWidget(item)
        self.box.addWidget(self.hero)
        self.attention = text('', 'attention')
        self.box.addWidget(self.attention)
        self.box.addWidget(text('01 / AGENTS    角色與工作範圍', 'section'))
        self.grid = QGridLayout()
        self.grid.setSpacing(SPACE['md'])
        self.cards = {agent: RoleCard(agent, self.open_role, name) for agent, name in self.names.items()}
        self.columns = 0
        self.box.addLayout(self.grid)
        self.box.addWidget(text('02 / POLICY    執行規則', 'section'))
        self.rules = text('', 'muted')
        self.box.addWidget(self.rules)
        self.box.addWidget(text('03 / EVENT LOG    交接紀錄', 'section'))
        self.timeline = text('', 'body')
        self.timeline.setObjectName('monitor_log')
        self.timeline.setProperty('terminal', True)
        self.timeline.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.box.addWidget(self.timeline)
        self.box.addStretch()
        self.console_style = '''
            QScrollArea#monitor_dashboard, QWidget#monitor_body { background: #080d0c; }
            QFrame[card="true"] { background: #101816; border: 1px solid #30423b; border-radius: 3px; }
            QFrame#monitor_run { border-left: 3px solid #a3e635; }
            QLabel { border: none; background: transparent; color: #e4ece7; font-size: 13px; }
            QLabel[terminal="true"], QLabel[kind="section"] { font-family: 'Cascadia Code', 'Consolas', 'Microsoft JhengHei UI'; }
            QLabel[kind="eyebrow"] { color: #a3e635; font-size: 12px; font-weight: 600; }
            QLabel[kind="heading"] { font-size: 28px; font-weight: 600; color: #f0f7f2; }
            QLabel[kind="phase"] { font-size: 21px; font-weight: 600; }
            QLabel[kind="role"] { font-size: 18px; font-weight: 600; }
            QLabel[kind="section"] { font-size: 12px; font-weight: 600; color: #a3e635; padding-top: 8px; }
            QLabel[kind="muted"] { color: #94a3a0; }
            QLabel[kind="accent"] { color: #67e8f9; }
            QLabel[kind="attention"] { color: #fbbf24; padding: 12px; background: #251e10; border: 1px solid #705426; border-radius: 3px; }
            QLabel#monitor_log { color: #b6c7be; background: #0c1310; border: 1px solid #30423b; border-radius: 3px; padding: 14px; }
            QPushButton { color: #dce9e0; background: #17231e; border: 1px solid #486153; border-radius: 3px; padding: 9px 12px; }
            QPushButton:hover { color: #d9f99d; border-color: #a3e635; background: #22331c; }
            QPushButton:focus { border: 2px solid #a3e635; padding: 8px 11px; }
            QPushButton:pressed { color: #080d0c; background: #a3e635; }
            QScrollBar:vertical { width: 10px; background: #080d0c; }
            QScrollBar::handle:vertical { background: #486153; border: none; border-radius: 2px; min-height: 28px; }
        '''
        self.apply_theme('hacker')
        self.reflow()

    def apply_theme(self, name):
        self.setProperty('theme', name)
        style = self.console_style
        if name == 'desktop':
            style = """QScrollArea#monitor_dashboard, QWidget#monitor_body { background: #262624; }
                QFrame[card="true"] { background: #30302e; border: 1px solid #3a3a3a; border-radius: @RADIUS@px; }
                QLabel { color: #d6d5d0; background: transparent; border: none; font-size: 13px; }
                QLabel[kind="heading"] { color: #ececea; font-size: 24px; font-weight: 600; }
                QLabel[kind="phase"] { color: #ececea; font-size: 20px; font-weight: 600; }
                QLabel[kind="role"] { color: #ececea; font-size: 16px; font-weight: 600; }
                QLabel[kind="section"], QLabel[kind="eyebrow"], QLabel[kind="muted"] { color: @MUTED@; }
                QLabel[kind="section"] { font-weight: 600; padding-top: 8px; }
                QLabel[kind="eyebrow"] { font-size: 11px; }
                QLabel[kind="attention"], QLabel#monitor_log { color: @MUTED@; background: #262624; border: 1px solid #3a3a3a; border-radius: @RADIUS@px; padding: 12px; }
            """
        self.setStyleSheet(style.replace('@RADIUS@', str(RADIUS)).replace('@MUTED@', MUTED_COLOR))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.reflow()

    def reflow(self):
        columns = 4 if self.viewport().width() >= 1100 else 2 if self.viewport().width() >= 560 else 1
        if columns == self.columns:
            return
        for index, card in enumerate(self.cards.values()):
            self.grid.removeWidget(card)
            self.grid.addWidget(card, index // columns, index % columns)
        for column in range(4):
            self.grid.setColumnStretch(column, 1 if column < columns else 0)
        self.columns = columns

    def refresh(self, snapshot):
        for row in snapshot['roles']:
            if row['agent'] not in self.cards:
                self.names[row['agent']] = row.get('name', row['agent'])
                self.cards[row['agent']] = RoleCard(row['agent'], self.open_role, self.names[row['agent']])
                self.columns = 0
        participants = (snapshot.get('run') or {}).get('agents', ())
        order = [agent for agent in participants if agent in self.cards]
        order += [row['agent'] for row in snapshot['roles'] if row['agent'] not in order]
        if order != list(self.cards):
            self.cards = {agent: self.cards[agent] for agent in order}
            self.columns = 0
        self.reflow()
        run = snapshot['run']
        self.subtitle.setText(snapshot['project'] + ' · 唯讀總覽 · 本機狀態每秒更新')
        active = run and run['state'] == 'running'
        self.phase.setText(('等待工具核准 · ' if run['waiting_approval'] else '進行中 · ') + run['stage'] if active else
                           {'done': self.names.get(run['lead'], run['lead']) + ' 已確認完成', 'paused': '協作已暫停', 'stopped': '協作已停止'}.get(run['state'], '準備中') if run else '尚未啟動協作')
        self.task.setText(compact(run['task'], 260) if run else '返回對話後，在「自動協作」選擇本次主導者。Claude 與 Codex 都能派工、實作與驗收。')
        self.metrics.setText(f"第 {run['round']} / {run['max_rounds']} 回合    ·    {run['steps']} / {run['max_steps']} 步    ·    有效時間剩餘 {duration(run['remaining_seconds'])}" if run else '等待使用者啟動 · 不會自動接續上次執行')
        stages = list(run['stages']) if run else [('plan', '主導者派工'), ('implement', '協作者實作'), ('final_review', '主導者驗收')]
        if run and 'local_review' in dict(stages):
            local = next(item for item in stages if item[0] == 'local_review')
            stages.remove(local)
            stages.insert(next(i for i, item in enumerate(stages) if item[0] == 'implement') + 1, local)
        self.route.setText(' → '.join(('● ' if active and key == run['step'] else '') + title for key, title in stages))
        notices = [f"{self.names.get(r['agent'], r['agent'])} 有 {r['approvals']} 項待核准" for r in snapshot['roles'] if r['approvals']]
        notices += [f"{self.names.get(r['agent'], r['agent'])}：{STATES.get(r['state'], r['state'])}" for r in snapshot['roles'] if r['state'] in ('Error', 'Blocked', 'Interrupted')]
        if run and run['reason']:
            notices.insert(0, run['reason'])
        self.attention.setText(' · '.join(notices))
        self.attention.setVisible(bool(notices))
        for row in snapshot['roles']:
            self.cards[row['agent']].update_data(row, run)
        limits = f"{run['max_rounds']} 回合 / {run['max_steps']} 步 / {duration(run['max_active_seconds'])} 有效時間" if run else '上限於啟動時設定'
        lead_name = self.names.get(run['lead'], run['lead']) if run else '本次主導者'
        self.rules.setText(lead_name + ' 決定完成    ·    範圍內自動交接    ·    工具操作由你核准\n'
                           '執行中鎖定 project / task / session；綁定改變、交接無法驗證或必要角色異常時暫停。\n'
                           + limits + '；核准等待不計時。傳送結果不確定時不自動重送。\n'
                           '唯讀審查是角色指示；實際權限仍由後端與工具核准控制。')
        entries = snapshot['events']
        self.timeline.setText(('本次執行\n\n' if run else '目前任務的歷史紀錄（未自動恢復執行）\n\n') + '\n\n'.join(time_label(e.get('timestamp')) + '   ' + compact(e.get('summary') or e.get('payload', {}).get('content'), 180) for e in entries)
                              if entries else '目前沒有交接紀錄。啟動後會記錄派工、驗收與停止原因。')

class AgentRail(QScrollArea):
    """Local status projection beside the existing live conversation widgets."""
    open_role = Signal(str)
    add_agent = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('agent_rail')
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setFixedWidth(244)
        body = QWidget()
        body.setObjectName('agent_rail_body')
        self.box = QVBoxLayout(body)
        self.box.setContentsMargins(SPACE['md'], SPACE['lg'], SPACE['md'], SPACE['md'])
        self.box.setSpacing(SPACE['md'])
        self.heading = text('AGENTS / 00', 'eyebrow')
        self.heading.setObjectName('console_section')
        self.summary = text('各 Agent 可獨立工作', 'muted')
        self.box.addWidget(self.heading)
        self.box.addWidget(self.summary)
        self.rows = QVBoxLayout()
        self.rows.setSpacing(SPACE['sm'])
        self.box.addLayout(self.rows)
        self.box.addStretch()
        self.add_button = QPushButton('＋ 新增 Agent')
        self.add_button.setObjectName('rail_add_agent')
        self.add_button.clicked.connect(self.add_agent.emit)
        self.box.addWidget(self.add_button)
        self.note = text('選取只切換畫面\n各自固定 project / session', 'muted')
        self.box.addWidget(self.note)
        self.setWidget(body)
        self.cards = {}

    def refresh(self, snapshot, selected):
        self.heading.setText(f"AGENTS / {len(snapshot['roles']):02d}")
        run = snapshot.get('run')
        busy = sum(row['state'] == 'Busy' for row in snapshot['roles'])
        ready = sum(row['state'] == 'Connected' for row in snapshot['roles'])
        self.summary.setText(
            ('協作中 · ' + run['stage']) if run and run['state'] == 'running'
            else f'{busy} 執行中 · {ready} 已連線\n可獨立對話，也可組隊協作')
        for row in snapshot['roles']:
            agent = row['agent']
            if agent not in self.cards:
                card = QFrame()
                card.setObjectName('teammate')
                box = QVBoxLayout(card)
                margin = SPACE['md']
                box.setContentsMargins(margin, margin, margin, margin)
                box.setSpacing(SPACE['sm'])
                action = QPushButton()
                action.setObjectName('teammate_open')
                action.clicked.connect(lambda checked=False, agent=agent: self.open_role.emit(agent))
                status = text('', 'muted')
                context = text('', 'muted')
                session = text('', 'muted')
                for item in (action, status, context, session):
                    box.addWidget(item)
                self.rows.addWidget(card)
                self.cards[agent] = (card, action, status, context, session)
            card, action, status, context, session = self.cards[agent]
            action.setText(action.fontMetrics().elidedText(row['name'], Qt.ElideRight, 170) + ('  ←' if agent == selected else ''))
            action.setToolTip(row['name'])
            action.setAccessibleName('開啟 ' + row['name'] + ' 對話')
            state = f"{row['approvals']} 待核准" if row['approvals'] else STATES.get(row['state'], row['state'])
            color = (COLORS['waiting'] if row['approvals'] else
                     COLORS['error'] if row['state'] in ('Error', 'Blocked', 'Interrupted') else
                     COLORS['running'] if row['state'] == 'Busy' else
                     COLORS['ready'] if row['state'] == 'Connected' else COLORS['muted'])
            status.setText('● ' + state)
            status.setStyleSheet('color: ' + (desktop_state_color(row['state'], row['approvals']) if self.property('theme') == 'desktop' else color))
            context.setText(row['project'])
            context.setToolTip(row['project'] + '\n' + row['task'])
            session.setText(row['session'])
            session.setToolTip('Session ID: ' + (row['session_id'] or '無'))
            if card.property('selected') != (agent == selected):
                card.setProperty('selected', agent == selected)
                card.style().unpolish(card)
                card.style().polish(card)
