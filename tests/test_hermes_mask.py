"""acw/hermes_mask.py is a deliberate copy of the hermes-delegation skill's masking rules: pin it, and compare."""
import importlib.util
import tempfile
import unittest
from pathlib import Path

from acw.hermes_mask import LineMasker, mask
from acw.security import sanitize

SKILL_FILTER = Path.home() / '.claude' / 'skills' / 'hermes-delegation' / 'scripts' / 'hermes_stream_filter.py'

# (input, text that must not survive masking)
CASES = [
    ('run it with --password hunter2x now', 'hunter2x'),
    ('slack xoxb-1234567890-abcdefghij here', 'xoxb-1234567890'),
    ('key AIza' + 'B' * 30 + ' end', 'AIzaBBBB'),
    ('Authorization: Token abcdefghijk1 sent', 'abcdefghijk1'),
    ('Authorization: Basic dXNlcjpwYXNzd29yZA== sent', 'dXNlcjpwYXNzd29yZA'),
    ('mysql -u root -pSECRETPW -h db', 'SECRETPW'),
    ('config mysecret=topsecretvalue1', 'topsecretvalue1'),
    ('OPENAI_API_KEY=sk-live-abcdefghijkl', 'sk-live-abcdefghijkl'),
    ('Bearer abcdefghijklmnop1234', 'abcdefghijklmnop1234'),
    ('git clone https://user:pa55w0rd@example.com/x.git', 'pa55w0rd'),
    ('ghp_abcdefghijklmnopqrstuvwxyz0123456789', 'ghp_abcdefghijkl'),
]


class HermesMaskTests(unittest.TestCase):
    def test_known_secrets_are_masked(self):
        for text, secret in CASES:
            with self.subTest(text=text):
                self.assertNotIn(secret, mask(text))

    def test_the_projection_pipeline_masks_what_the_core_alone_does_not(self):
        # The point of the copy: sanitize() (the core's rules) misses some of these, mask() does not.
        for text, secret in CASES:
            with self.subTest(text=text):
                self.assertNotIn(secret, mask(sanitize(text)))

    def test_ordinary_text_is_unchanged(self):
        text = '[TOOL DONE] terminal 12ms error=false and some normal sentence'
        self.assertEqual(text, mask(text))

    def test_multiline_private_key_block_is_masked_line_by_line(self):
        masker = LineMasker()
        lines = ['-----BEGIN RSA PRIVATE KEY-----', 'MIIEvQIBADANBgkqhkiG9w0BAQEFAASC', '-----END RSA PRIVATE KEY-----', 'after']
        out = [masker.render(line) for line in lines]
        self.assertNotIn('MIIEvQ', '\n'.join(out))
        self.assertEqual('after', out[-1])

    def test_matches_the_skills_filter_exactly(self):
        if not SKILL_FILTER.is_file():
            self.skipTest('hermes-delegation skill is not installed here')
        spec = importlib.util.spec_from_file_location('skill_hermes_stream_filter', SKILL_FILTER)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        for text, _ in CASES + [('plain text', ''), ('password: "a b c" next', ''), ('-----BEGIN PRIVATE KEY-----\nabc\n-----END PRIVATE KEY-----', '')]:
            with self.subTest(text=text):
                self.assertEqual(module.mask(text), mask(text))
        pem = ['-----BEGIN PRIVATE KEY-----', 'AAAA', '-----END PRIVATE KEY-----', 'tail', 'key password=abc']
        with tempfile.TemporaryDirectory() as folder:
            theirs = module.Filter('x', str(Path(folder) / 'raw.log'), '', '')
            try:
                expected = [theirs.render(line) for line in pem]
            finally:
                theirs.raw.close()
        masker = LineMasker()
        self.assertEqual(expected, [masker.render(line) for line in pem])


if __name__ == '__main__':
    unittest.main()
