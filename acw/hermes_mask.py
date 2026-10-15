"""Credential masking for the Monitor projection (acw/requests.py).

DELIBERATE COPY. Everything from the ``_WORDS`` comment down to ``mask()`` is copied unchanged from
    ~/.claude/skills/hermes-delegation/scripts/hermes_stream_filter.py
so that a Hermes step handed to the workspace is masked exactly like one run directly by run.sh.
When one side changes, change the other and run tests/test_hermes_mask.py (it compares the two when the
skill file exists). Standard library only.
"""
import re

# key name must END with one of these words (prefixes like OPENAI_API_KEY or X-Auth-Token are fine)
_WORDS = r"(?:password|passwd|pwd|secret|api[_-]?key|access[_-]?key|private[_-]?key|token)"
_VALUE = r"""(\\"[^"]*"|"(?:\\.|[^"\\])*"|'[^']*'|[^\s"',;&}]+|\\?["']\S*)"""
_KV = re.compile(r"""(?i)([A-Za-z0-9_-]*""" + _WORDS + r"""\\?["']?\s*[=:]\s*)""" + _VALUE)
_LONG_FLAG = re.compile(r"(?i)(?<![\w-])(--(?:password|passwd|token|api-?key|secret)\s+)(?!-)(\S+)")
_SHORT_FLAG = re.compile(r"(?<![\w-])(-[up]\s*)(?!-)(\S+)")  # also -pSECRET with no space
_NET_CTX = re.compile(r"(?i)\b(?:curl|wget|mysql|mysqldump|psql|sshpass|mongosh?|redis-cli|smbclient|ftp|docker\s+login)\b")
_URL_CRED = re.compile(r"(://)[^/\s:@]+:[^/\s@]+@")
_PEM = re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.S)
_PEM_BEGIN = re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")
_PEM_END = re.compile(r"-----END [A-Z ]*PRIVATE KEY-----")
_OUTPUT_KEY = re.compile(r'\boutput\\?"')
_PEM_MASKED = "-----BEGIN PRIVATE KEY----- *** -----END PRIVATE KEY-----"
_TOKENS = [
    (re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{8,}"), "Bearer ***"),
    (re.compile(r"(?i)\bBasic\s+[A-Za-z0-9+/=]{8,}"), "Basic ***"),
    (re.compile(r"(?i)\bToken\s+[A-Za-z0-9._~+/=-]{8,}"), "Token ***"),
    (re.compile(r"\bsk-[A-Za-z0-9_-]{8,}"), "***"),
    (re.compile(r"\b(?:ghp|gho|ghs|ghu|ghr)_[A-Za-z0-9]{8,}"), "***"),
    (re.compile(r"\bgithub_pat_[A-Za-z0-9_]{8,}"), "***"),
    (re.compile(r"\bAKIA[0-9A-Z]{8,}"), "***"),
    (re.compile(r"\bxox[abp]-[A-Za-z0-9-]{10,}"), "***"),
    (re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"), "***"),
    (re.compile(r"\bAIza[0-9A-Za-z_-]{20,}"), "***"),
]


def mask(text):
    text = _PEM.sub(_PEM_MASKED, text)
    for pattern, repl in _TOKENS[:3]:
        text = pattern.sub(repl, text)
    text = _KV.sub(lambda m: m.group(1) + "***", text)
    text = _LONG_FLAG.sub(lambda m: m.group(1) + "***", text)
    if _NET_CTX.search(text):
        text = _SHORT_FLAG.sub(lambda m: m.group(1) + "***", text)
    text = _URL_CRED.sub(r"\1***:***@", text)
    for pattern, repl in _TOKENS[3:]:
        text = pattern.sub(repl, text)
    return text


class LineMasker:
    """Line by line masking that keeps track of multi-line PEM private key blocks.

    ``render`` is hermes_stream_filter.Filter.render, with its state held here.
    """

    def __init__(self):
        self.in_pem = False

    def render(self, line):
        """Mask one line, keeping track of multi-line PEM private key blocks."""
        line = line.rstrip("\r")
        if self.in_pem:
            if _PEM_END.search(line):
                self.in_pem = False
                return "-----END PRIVATE KEY-----"
            return "***"
        out = mask(line)
        begin = _PEM_BEGIN.search(out)
        if begin and not _PEM_END.search(out):
            self.in_pem = True
            out = out[: begin.start()] + "-----BEGIN PRIVATE KEY-----"
        return out
