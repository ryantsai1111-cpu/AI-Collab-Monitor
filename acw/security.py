"""Persistence boundary filtering. Credentials and private reasoning never enter disk."""
from __future__ import annotations

import re
import struct
import zlib
from pathlib import Path
from typing import Any

REDACTED = "[REDACTED]"
OMITTED_REASONING = "[OMITTED: hidden reasoning]"
_SECRET_KEYS = re.compile(r"^(?:authorization|proxy.authorization|api[ _-]?key|access[ _-]?token|refresh[ _-]?token|id[ _-]?token|auth[ _-]?token|token|cookie|set.cookie|password|passwd|client[ _-]?secret|secret|private[ _-]?key|credentials?)$", re.I)
_ENV_SECRET = re.compile(r"(?:^|[_-])(?:api[_-]?key|password|passwd|token|secret(?:[_-]access)?[_-]?key|client[_-]?secret)$", re.I)
_REASON_KEYS = {"chain_of_thought", "hidden_reasoning", "reasoning_content", "encrypted_content", "reasoning_text", "thinking", "signature"}
_REASON_TYPES = {"reasoning", "thinking", "redacted_thinking", "reasoning_delta", "thinking_delta", "reasoning_text", "reasoning_text_delta", "reasoning_summary_text_delta"}
_SECRET_FILES = {"auth.json", "credentials.json", "credentials", "cookies", "cookies.json", "cookies.sqlite", "cookies.db", "login data", ".env", "id_rsa", "id_ed25519", ".netrc", "token", "token.json", "tokens.json", "password", "passwords.json", "api_key", "apikey", "api_key.json"}

def _redact_assignment(match):
    prefix=match.group(1)
    value=match.group(0)[len(prefix):]
    quote=value[0] if value and value[0] in ('"',"'") and value[-1:]==value[0] else ''
    return prefix+quote+REDACTED+quote

_TEXT_PATTERNS = [
    (re.compile(r"(?im)(\b[A-Z][A-Z0-9_]*(?:API_KEY|PASSWORD|PASSWD|TOKEN|SECRET_ACCESS_KEY|CLIENT_SECRET)\s*[:=]\s*)[^\r\n,;&}]+"), _redact_assignment),
    (re.compile(r"(?im)(\b(?:cookie|set-cookie)\s*:\s*)[^\r\n]+"), r"\1" + REDACTED),
    (re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----[\s\S]*?(?:-----END (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|$)"), REDACTED),
    (re.compile(r"(?im)(\b(?:authorization|proxy-authorization)\s*[:=]\s*)(?:bearer\s+|basic\s+)?[^\r\n,}]+"), r"\1" + REDACTED),
    (re.compile(r"(?im)([\"']?\b(?:api[_ -]?key|access[_ -]?token|refresh[_ -]?token|id[_ -]?token|auth[_ -]?token|token|cookie|set-cookie|password|passwd|client[_ -]?secret|secret)\b[\"']?\s*[:=]\s*)(?:\"[^\"\r\n]*\"|'[^'\r\n]*'|[^\r\n,;}]+)"), _redact_assignment),
    (re.compile(r"(?i)\b(?:sk-(?:proj-|ant-)?[A-Za-z0-9_\-]{8,}|gh[pousr]_[A-Za-z0-9]{12,}|github_pat_[A-Za-z0-9_]{12,}|AKIA[A-Z0-9]{16})\b"), REDACTED),
    (re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"), REDACTED),
    (re.compile(r"(?i)(https?://)[^\s/@:]+:[^\s/@]+@"), r"\1" + REDACTED + "@"),
    (re.compile(r"(?is)<(?:thinking|analysis|chain_of_thought)>.*?(?:</(?:thinking|analysis|chain_of_thought)>|$)"), OMITTED_REASONING),
]


def redact_text(value: str) -> str:
    for pattern, replacement in _TEXT_PATTERNS:
        value = pattern.sub(replacement, value)
    return value


def is_hidden_reasoning(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    kind = str(value.get("type", value.get("method", ""))).lower().replace("-", "_")
    return kind in _REASON_TYPES or "reasoning" in kind or kind.startswith("thinking")


def sanitize(value: Any) -> Any:
    """Return JSON-compatible sanitized copy; never mutate the backend value."""
    if isinstance(value, dict):
        if is_hidden_reasoning(value):
            return {"type": "omitted_reasoning", "redaction": "hidden reasoning excluded"}
        kind = str(value.get("method", value.get("type", ""))).lower()
        if any(word in kind for word in ('delta', 'partial', 'stream_event')) and ('/' in kind or kind.startswith('content_block')):
            return {"type": "omitted_stream_fragment", "redaction": "Raw streaming fragment excluded; completed sanitized message retained"}
        out = {}
        for key, item in value.items():
            name = str(key)
            if _SECRET_KEYS.match(name) or _ENV_SECRET.search(name):
                out[name] = REDACTED
            elif name.lower() in _REASON_KEYS:
                out[name] = OMITTED_REASONING
            else:
                out[name] = sanitize(item)
        return out
    if isinstance(value, (list, tuple, set)):
        return [sanitize(item) for item in value]
    if isinstance(value, str):
        return redact_text(value)
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return redact_text(str(value))


def redaction_changed(original: Any, cleaned: Any) -> bool:
    return original != cleaned


def is_secret_path(path: str | Path) -> bool:
    p = Path(path)
    names = [part.lower().rstrip(' .') for part in p.parts]
    return any(name in _SECRET_FILES or name.startswith(".env.") or name.endswith((".pem", ".p12", ".pfx", ".key")) for name in names)


def safe_file(path: str | Path, roots: list[str | Path], *, must_exist=True, max_bytes=16 * 1024 * 1024) -> Path:
    """Resolve symlinks and enforce explicit project/artifact roots before any read."""
    if is_secret_path(path):
        raise PermissionError('Credential or secret files are excluded')
    candidate = Path(path).expanduser().resolve()
    if is_secret_path(candidate):
        raise PermissionError("Credential or secret files are excluded")
    allowed = [Path(root).expanduser().resolve() for root in roots if root]
    if not any(candidate.is_relative_to(root) for root in allowed):
        raise PermissionError("File is outside the selected project and workspace artifact roots")
    if must_exist:
        if not candidate.is_file():
            raise FileNotFoundError(candidate)
        if candidate.stat().st_size > max_bytes:
            raise ValueError("File exceeds the artifact size limit")
    return candidate


def reject_link_ancestors(path: str | Path) -> None:
    """Reject symlink/junction destinations before resolution hides their identity."""
    absolute=Path(path).expanduser().absolute()
    for part in (absolute,*absolute.parents):
        if part.is_symlink() or (hasattr(part,'is_junction') and part.is_junction()):
            raise PermissionError('Symlink or junction paths are not allowed for managed writes or exports')


def safe_export_path(path: str | Path, *, allowed_suffixes=None) -> Path:
    """Validate an explicitly user-chosen output without creating parent directories."""
    given=Path(path).expanduser()
    reject_link_ancestors(given)
    if is_secret_path(given):
        raise PermissionError('Credential filenames cannot be export destinations')
    for part in given.parts:
        if part==given.anchor:
            continue
        if ':' in part or re.fullmatch(r'(?:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?',part,re.I):
            raise PermissionError('Device paths and alternate data streams are not export destinations')
        if part.rstrip(' .')!=part:
            raise PermissionError('Ambiguous trailing dots or spaces are not allowed in export paths')
    if given.is_symlink():
        raise PermissionError('Export destinations cannot be symlinks')
    candidate=given.resolve()
    if is_secret_path(candidate):
        raise PermissionError('Credential filenames cannot be export destinations')
    if not candidate.parent.is_dir():
        raise FileNotFoundError('Choose an existing export directory')
    if candidate.exists() and not candidate.is_file():
        raise ValueError('Export destination must be a file')
    if allowed_suffixes is not None and candidate.suffix.lower() not in allowed_suffixes:
        raise ValueError('Unexpected export file extension: '+candidate.suffix)
    return candidate


def verify_screenshot(data: bytes, suffix: str) -> dict:
    """Verify bounded PNG/JPEG structure; pixels are never claimed to be redacted."""
    if not data or len(data)>16*1024*1024:
        raise ValueError('Screenshot exceeds the 16 MiB limit or is empty')
    width=height=0
    suffix=suffix.lower()
    if suffix=='.png':
        if not data.startswith(b'\x89PNG\r\n\x1a\n'):
            raise ValueError('PNG signature does not match screenshot file extension')
        offset=8
        chunks=[]
        idat=[]
        while offset<len(data):
            if offset+12>len(data): raise ValueError('Truncated PNG chunk')
            length=int.from_bytes(data[offset:offset+4],'big')
            end=offset+12+length
            if end>len(data): raise ValueError('Truncated PNG payload')
            kind=data[offset+4:offset+8]
            payload=data[offset+8:offset+8+length]
            crc=int.from_bytes(data[offset+8+length:end],'big')
            if zlib.crc32(kind+payload)&0xffffffff!=crc: raise ValueError('PNG checksum mismatch')
            chunks.append(kind)
            if kind==b'IHDR':
                if len(chunks)!=1 or length!=13: raise ValueError('Invalid PNG image header')
                width,height,depth,color,compression,filter_method,interlace=struct.unpack('>IIBBBBB',payload)
                valid_depths={0:{1,2,4,8,16},2:{8,16},3:{1,2,4,8},4:{8,16},6:{8,16}}
                if depth not in valid_depths.get(color,set()) or compression or filter_method or interlace not in (0,1):
                    raise ValueError('Unsupported PNG header')
            elif kind==b'IDAT': idat.append(payload)
            elif kind==b'PLTE':
                if not length or length%3 or length>768: raise ValueError('Invalid PNG palette')
            elif kind==b'tRNS':
                if color==3:
                    if not 1<=length<=256: raise ValueError('Invalid PNG transparency palette')
                elif length!={0:2,2:6}.get(color): raise ValueError('Invalid PNG transparency')
            elif kind==b'sRGB':
                if length!=1 or payload[0]>3: raise ValueError('Invalid PNG color intent')
            elif kind==b'gAMA':
                if length!=4 or not int.from_bytes(payload,'big'): raise ValueError('Invalid PNG gamma')
            elif kind==b'cHRM':
                if length!=32: raise ValueError('Invalid PNG chromaticity')
            elif kind==b'pHYs':
                if length!=9 or payload[-1] not in (0,1): raise ValueError('Invalid PNG pixel dimensions')
            elif kind==b'sBIT':
                expected={0:1,2:3,3:3,4:2,6:4}[color]
                if length!=expected or any(not 1<=bit<=(8 if color==3 else depth) for bit in payload):
                    raise ValueError('Invalid PNG significant bits')
            elif kind==b'bKGD':
                if length!={0:2,2:6,3:1,4:2,6:6}[color]: raise ValueError('Invalid PNG background color')
            elif kind!=b'IEND':
                raise ValueError('Screenshot contains excluded PNG metadata or unsupported chunk '+kind.decode('ascii',errors='replace')+'; choose an image without embedded text, EXIF, or unknown metadata')
            if kind==b'IEND':
                if length or end!=len(data): raise ValueError('Invalid PNG end or trailing payload')
                break
            offset=end
        if not chunks or chunks[0]!=b'IHDR' or chunks[-1]!=b'IEND' or not idat:
            raise ValueError('PNG is missing required chunks')
        if not (0<width<=32768 and 0<height<=32768 and width*height<=64000000):
            raise ValueError('Screenshot dimensions exceed limits')
        inflater=zlib.decompressobj()
        limit=min(height*(width*8+1)+1024,128*1024*1024)
        try: pixels=inflater.decompress(b''.join(idat),limit+1)
        except zlib.error as exc: raise ValueError('Invalid PNG image data') from exc
        if len(pixels)>limit or not inflater.eof or inflater.unused_data:
            raise ValueError('Invalid or oversized PNG image stream')
        if interlace==0:
            channels={0:1,2:3,3:1,4:2,6:4}[color]
            stride=(width*channels*depth+7)//8+1
            if len(pixels)!=height*stride or any(pixels[n]>4 for n in range(0,len(pixels),stride)):
                raise ValueError('Invalid PNG scanlines')
        mime='image/png'
    elif suffix in ('.jpg','.jpeg'):
        if not data.startswith(b'\xff\xd8') or not data.endswith(b'\xff\xd9'):
            raise ValueError('JPEG signature does not match screenshot file extension')
        offset=2
        saw_scan=False
        while offset<len(data)-2:
            if data[offset]!=255: raise ValueError('Invalid JPEG marker')
            while offset<len(data) and data[offset]==255: offset+=1
            marker=data[offset];offset+=1
            if marker in (0xd8,0xd9,0x00): raise ValueError('Invalid JPEG marker sequence')
            if marker in range(0xd0,0xd8) or marker==1: continue
            if offset+2>len(data): raise ValueError('Truncated JPEG segment')
            length=int.from_bytes(data[offset:offset+2],'big')
            if length<2 or offset+length>len(data): raise ValueError('Truncated JPEG payload')
            payload=data[offset+2:offset+length]
            if marker in (0xc0,0xc1,0xc2,0xc3,0xc5,0xc6,0xc7,0xc9,0xca,0xcb,0xcd,0xce,0xcf):
                if len(payload)<6: raise ValueError('Invalid JPEG frame header')
                height=int.from_bytes(payload[1:3],'big');width=int.from_bytes(payload[3:5],'big')
            if marker==0xe0:
                if len(payload)!=14 or not payload.startswith(b'JFIF\0') or payload[-2:]!=b'\0\0':
                    raise ValueError('Screenshot contains excluded JPEG APP0 metadata or an embedded thumbnail')
            elif marker==0xee:
                if len(payload)!=12 or not payload.startswith(b'Adobe') or payload[-1] not in (0,1,2):
                    raise ValueError('Screenshot contains unrecognized JPEG color metadata')
            elif marker in range(0xe0,0xf0) or marker==0xfe:
                raise ValueError('Screenshot contains excluded JPEG APP/COM metadata; choose an image without embedded EXIF, comments, or unknown metadata')
            offset+=length
            if marker==0xda:
                saw_scan=True
                while offset<len(data)-2:
                    if data[offset]!=255: offset+=1;continue
                    following=data[offset+1]
                    if following==0 or following in range(0xd0,0xd8): offset+=2;continue
                    if following==255: offset+=1;continue
                    break
        if not saw_scan or offset!=len(data)-2 or not (0<width<=32768 and 0<height<=32768 and width*height<=64000000):
            raise ValueError('JPEG is missing a valid frame or image scan')
        mime='image/jpeg'
    else:
        raise ValueError('Screenshots must be verified PNG or JPEG files')
    return {'mime_type':mime,'width':width,'height':height,'byte_size':len(data),
            'pixel_redaction':'not performed','embedded_metadata':'Restricted image-format/color allowlist; text, EXIF, unknown metadata rejected',
            'security_note':'User-selected image bytes; visible pixels may contain sensitive information. No secret-free image guarantee.'}
