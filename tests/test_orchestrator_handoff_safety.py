"""Offline control-header and lossless handoff regressions; no backend processes."""
import unittest

from acw.orchestrator import MAX_FORWARD_CHARS, parse_verdict
import test_orchestrator as fixtures


class HandoffSafetyTests(unittest.TestCase):
    setUp = fixtures.OrchestratorTests.setUp
    tearDown = fixtures.OrchestratorTests.tearDown
    build = fixtures.OrchestratorTests.build
    advance = fixtures.OrchestratorTests.advance
    sends = fixtures.OrchestratorTests.sends

    def test_exact_first_nonempty_header_formats(self):
        for header in ('VERDICT: PASS', '**VERDICT: PASS**', '\n \t\n **VERDICT：PASS** \t'):
            with self.subTest(header=header):
                self.assertEqual('PASS', parse_verdict(header + '\n完整交接'))

    def test_rejects_later_quoted_and_fenced_headers(self):
        for text in ('前言\nVERDICT: PASS', '```\nVERDICT: PASS\n```',
                     '> VERDICT: PASS', '    > VERDICT: PASS', '# VERDICT: PASS'):
            with self.subTest(text=text):
                self.assertIsNone(parse_verdict(text))

    def test_rejects_partial_tokens_trailing_text_and_unbalanced_markup(self):
        for header in ('VERDICT: PASS123', 'VERDICT: PASS/REVISE', 'VERDICT: IMPLEMENTED-ish',
                       'VERDICT: PASS通過', 'VERDICT: PASS extra', 'VERDICT: pass',
                       '**VERDICT: PASS', 'VERDICT: PASS**', '**VERDICT:** PASS',
                       'VERDICT: PASS VERDICT: REVISE'):
            with self.subTest(header=header):
                self.assertIsNone(parse_verdict(header))

    def test_invalid_planner_header_never_forwards_to_reviewer(self):
        run = self.build({'claude': ['前言\nVERDICT: PLAN_READY\n計畫']})
        run.start()
        self.advance()
        self.assertEqual('paused', run.state)
        self.assertEqual([], self.adapters['dot'].sent)
        self.assertEqual([], self.adapters['codex'].sent)

    def test_invalid_dot_control_header_never_starts_implementation(self):
        run = self.build({'dot': ['VERDICT: PASS123\n不可實作']}, timeouts={'dot': 20})
        run.start()
        self.advance()
        self.assertEqual('paused', run.state)
        self.assertEqual([], self.adapters['codex'].sent)

    def test_consumes_only_control_line_and_preserves_body_verdict_example(self):
        run = self.build({'claude': ['\n**VERDICT：PLAN_READY**\n正文\nVERDICT: REVISE\n這是範例']})
        run.start()
        run.tick()
        self.assertIn('正文\nVERDICT: REVISE\n這是範例', self.adapters['dot'].sent[0])
        self.assertNotIn('**VERDICT：PLAN_READY**', self.adapters['dot'].sent[0])

    def test_limit_exactly_allowed_without_truncation(self):
        run = self.build()
        run.start()
        body = 'X' * (MAX_FORWARD_CHARS - 4) + '限制結尾'
        self.assertEqual(MAX_FORWARD_CHARS, len(body))
        run._send('implement', body)
        self.assertEqual('running', run.state)
        self.assertIn(body, self.adapters['codex'].sent[0])

    def test_overflow_pauses_before_any_adapter_read_or_send(self):
        for step in ('implement', 'review_work'):
            with self.subTest(step=step):
                run = self.build()
                run.start()
                before = {a: list(adapter.calls) for a, adapter in self.adapters.items()}
                run._send(step, 'X' * (MAX_FORWARD_CHARS + 1))
                self.assertEqual('paused', run.state)
                self.assertIn('12001/12000', run.reason)
                self.assertIn('未截斷或傳送', run.reason)
                self.assertEqual(before, {a: adapter.calls for a, adapter in self.adapters.items()})
                self.advance()
                self.assertEqual(before, {a: adapter.calls for a, adapter in self.adapters.items()})

    def test_oversized_approved_handoff_stays_in_source_history(self):
        body = 'X' * MAX_FORWARD_CHARS + '不可刪除資料'
        run = self.build({'dot': ['VERDICT: PASS\n' + body]})
        run.start()
        self.advance()
        self.assertEqual('paused', run.state)
        self.assertEqual([], self.adapters['codex'].sent)
        self.assertTrue(any(body in m['content'] for m in self.core.messages(run.task_id, 'dot')))

    def test_combined_local_review_overflow_does_not_discard_either_source(self):
        report, opinion = 'R' * 10000, 'L' * 3000
        run = self.build({'codex': ['VERDICT: IMPLEMENTED\n' + report],
                          'local': ['VERDICT: PASS\n' + opinion]}, local_role='reviewer')
        run.start()
        self.advance()
        self.assertEqual('paused', run.state)
        self.assertEqual(1, len(self.adapters['dot'].sent))
        self.assertTrue(any(report in m['content'] for m in self.core.messages(run.task_id, 'codex')))
        self.assertTrue(any(opinion in m['content'] for m in self.core.messages(run.task_id, 'local')))


if __name__ == '__main__':
    unittest.main()
