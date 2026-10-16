"""Explicit transcript-availability double for offline tests with synthetic session IDs.

These fixtures exercise routing and UI behavior, not native transcript discovery.
Real file existence and missing-session recovery use the production Core in test_core.
"""
from acw.core import WorkspaceCore


class TranscriptFixtureCore(WorkspaceCore):
    def session_available(self, agent, session_id):
        self.provider(agent)
        return True
