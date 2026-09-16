"""Bounded public-article retrieval. Retrieved text remains untrusted, not factual approval."""

import hashlib
import http.client
import io
import ipaddress
import queue
import re
import socket
import ssl
import threading
import time
from datetime import datetime, timezone
from html.parser import HTMLParser
from urllib.parse import parse_qsl, urljoin, urlsplit

MAX_BYTES = 1_000_000
MAX_TEXT = 40_000
MIN_TEXT = 120
MAX_REDIRECTS = 3
AUTH_QUERY_KEYS = {"key", "api_key", "apikey", "token", "access_token", "auth", "authorization", "signature", "sig"}


class EvidenceError(Exception):
    pass


def _remaining(deadline):
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise EvidenceError("timeout")
    return min(20.0, remaining)


def _validated_url(url):
    if not isinstance(url, str) or any(char.isspace() or ord(char) < 32 for char in url):
        raise EvidenceError("unsafe_url")
    try:
        parsed = urlsplit(url)
        if parsed.scheme.lower() != "https" or parsed.username is not None or parsed.password is not None:
            raise EvidenceError("unsafe_url")
        host = (parsed.hostname or "").rstrip(".").encode("idna").decode("ascii").lower()
        if parsed.port not in (None, 443) or "." not in host or host.endswith((".local", ".localhost", ".internal", ".lan", ".home", ".localdomain")):
            raise EvidenceError("unsafe_url")
        try:
            ipaddress.ip_address(host)
        except ValueError:
            pass
        else:
            raise EvidenceError("unsafe_url")
        if any(key.casefold() in AUTH_QUERY_KEYS or key.casefold().startswith(("x-amz-", "x-goog-"))
               for key, _ in parse_qsl(parsed.query, keep_blank_values=True)):
            raise EvidenceError("unsafe_url")
        path = parsed.path or "/"
        return host, path + ("?" + parsed.query if parsed.query else "")
    except (ValueError, UnicodeError):
        raise EvidenceError("unsafe_url") from None


def _resolve_global(host, deadline):
    _remaining(deadline)
    # The OS resolver has no per-call timeout. A daemon worker bounds the caller's wait.
    result = queue.Queue(maxsize=1)

    def resolve():
        try:
            result.put(socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM))
        except OSError:
            result.put(None)

    threading.Thread(target=resolve, daemon=True).start()
    try:
        records = result.get(timeout=_remaining(deadline))
    except queue.Empty:
        raise EvidenceError("timeout") from None
    if not records:
        raise EvidenceError("dns_error")
    addresses = {record[4][0] for record in records}
    try:
        if any(not ipaddress.ip_address(address).is_global for address in addresses):
            raise EvidenceError("non_public_address")
    except ValueError:
        raise EvidenceError("dns_error") from None
    return sorted(addresses)[0]


class _DeadlineReader(io.RawIOBase):
    def __init__(self, sock, deadline):
        self.sock, self.deadline = sock, deadline
        # Preserve the socket file reference after HTTPConnection closes a
        # Connection: close peer; the response body still needs to be readable.
        self.raw = sock.makefile("rb", buffering=0)

    def readable(self):
        return True

    def readinto(self, buffer):
        self.sock.settimeout(_remaining(self.deadline))
        return self.raw.readinto(buffer)

    def close(self):
        try:
            self.raw.close()
        finally:
            super().close()


class _DeadlineSocket:
    def __init__(self, sock, deadline):
        self.sock, self.deadline = sock, deadline

    def makefile(self, mode, *args, **kwargs):
        if mode != "rb":
            raise EvidenceError("transport_error")
        return io.BufferedReader(_DeadlineReader(self.sock, self.deadline))

    def sendall(self, data):
        self.sock.settimeout(_remaining(self.deadline))
        return self.sock.sendall(data)

    def __getattr__(self, name):
        return getattr(self.sock, name)


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, host, address, deadline):
        super().__init__(host, timeout=_remaining(deadline), context=ssl.create_default_context())
        self.address, self.deadline = address, deadline

    def connect(self):
        # Pin the validated IP; do not let a second hostname resolution bypass the check.
        raw = socket.create_connection((self.address, 443), timeout=_remaining(self.deadline))
        try:
            raw.settimeout(_remaining(self.deadline))
            secured = self._context.wrap_socket(raw, server_hostname=self.host)
        except Exception:
            raw.close()
            raise
        self.sock = _DeadlineSocket(secured, self.deadline)


class _ArticleText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.hidden = []
        self.in_head = False
        self.in_title = False
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "noscript"):
            self.hidden.append(tag)
        if tag == "head":
            self.in_head = True
        if tag == "title":
            self.in_title = True

    def handle_endtag(self, tag):
        if self.hidden and tag == self.hidden[-1]:
            self.hidden.pop()
        if tag == "head":
            self.in_head = False
        if tag == "title":
            self.in_title = False

    def handle_data(self, data):
        if not self.hidden and (not self.in_head or self.in_title):
            self.parts.append(data)


def _extract_text(body, content_type):
    charset = re.search(r"charset\s*=\s*[\"']?([^;\s\"']+)", content_type, re.I)
    try:
        decoded = body.decode(charset.group(1) if charset else "utf-8", errors="replace")
    except LookupError:
        raise EvidenceError("unsupported_encoding") from None
    if "html" in content_type.lower():
        parser = _ArticleText()
        parser.feed(decoded)
        decoded = " ".join(parser.parts)
    text = " ".join(decoded.split())
    if len(text) < MIN_TEXT:
        raise EvidenceError("insufficient_text")
    prefix = text[:1500].lower()
    blocked = (re.match(r"^(access denied|403 forbidden|sign in|log in|login required)", prefix)
               or any(phrase in prefix for phrase in ("verify you are human", "verify that you are human",
                      "checking your browser", "captcha", "attention required!", "enable javascript and cookies",
                      "just a moment...")))
    if blocked and len(text) < 10_000:
        raise EvidenceError("blocked_page")
    return text[:MAX_TEXT]


def fetch_source(url, deadline):
    """Return evidence or a sanitized failure; deadline is an absolute monotonic time.

    HTTPS only, globally routable DNS, pinned TLS peers, three redirects, 1 MB input,
    40k characters output. Block-page detection is heuristic, not universal verification.
    """
    result = {"success": False, "url": None, "final_url": None, "text": "",
              "fetched_at": None, "content_sha256": None, "error": None}
    try:
        _validated_url(url)
        result["url"] = url
        current = url
        for hop in range(MAX_REDIRECTS + 1):
            host, path = _validated_url(current)
            address = _resolve_global(host, deadline)
            connection = _PinnedHTTPSConnection(host, address, deadline)
            try:
                connection.request("GET", path, headers={"User-Agent": "HK-China-Memo-Evidence/1.0",
                    "Accept": "text/html,application/xhtml+xml,text/plain", "Accept-Encoding": "identity"})
                response = connection.getresponse()
                if response.status in (301, 302, 303, 307, 308):
                    location = response.getheader("Location")
                    if not location or hop == MAX_REDIRECTS:
                        raise EvidenceError("redirect_limit")
                    current = urljoin(current, location)
                    continue
                if response.status != 200:
                    raise EvidenceError("http_error")
                content_type = response.getheader("Content-Type", "")
                mime = content_type.split(";", 1)[0].strip().lower()
                if mime not in ("text/html", "application/xhtml+xml", "text/plain"):
                    raise EvidenceError("unsupported_content")
                if response.getheader("Content-Encoding", "identity").lower() not in ("", "identity"):
                    raise EvidenceError("unsupported_encoding")
                body = bytearray()
                while True:
                    _remaining(deadline)
                    chunk = response.read1(min(65536, MAX_BYTES + 1 - len(body)))
                    if not chunk:
                        break
                    body.extend(chunk)
                    if len(body) > MAX_BYTES:
                        raise EvidenceError("response_too_large")
                text = _extract_text(bytes(body), content_type)
                _remaining(deadline)
                result.update(success=True, final_url=current, text=text,
                              fetched_at=datetime.now(timezone.utc).isoformat(),
                              content_sha256=hashlib.sha256(text.encode("utf-8")).hexdigest())
                return result
            finally:
                connection.close()
        raise EvidenceError("redirect_limit")
    except EvidenceError as error:
        result["error"] = str(error)
    except (TimeoutError, socket.timeout):
        result["error"] = "timeout"
    except (OSError, ssl.SSLError, http.client.HTTPException, ValueError):
        result["error"] = "transport_error"
    return result
