import hashlib
import io
import socket
import sys
import time
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import source_evidence as evidence


ARTICLE = "The central bank released its updated economic projections and policy decision. " * 8


class Response:
    def __init__(self, body=ARTICLE, status=200, **headers):
        self.status = status
        self.headers = {"Content-Type": "text/html", **headers}
        self.body = io.BytesIO(body.encode() if isinstance(body, str) else body)

    def getheader(self, name, default=None):
        return self.headers.get(name, default)

    def read1(self, count):
        return self.body.read(count)


class SourceEvidenceTests(unittest.TestCase):
    def fetch(self, responses, url="https://news.example.com/article", deadline=None):
        connections = [Mock(getresponse=Mock(return_value=response)) for response in responses]
        with patch.object(evidence, "_resolve_global", return_value="93.184.216.34") as resolve, \
             patch.object(evidence, "_PinnedHTTPSConnection", side_effect=connections) as connect:
            result = evidence.fetch_source(url, deadline or time.monotonic() + 10)
        return result, connections, resolve, connect

    def test_html_evidence_contains_visible_title_body_and_exact_text_hash(self):
        html = f"<html><head><title>Policy decision</title><style>hidden-css</style></head><body><script>secret-script</script><noscript>hidden-alternative</noscript><p>{ARTICLE}</p></body></html>"
        result, connections, _, _ = self.fetch([Response(html)])
        self.assertTrue(result["success"])
        self.assertEqual(result["text"], "Policy decision " + ARTICLE.strip())
        self.assertEqual(result["content_sha256"], hashlib.sha256(result["text"].encode()).hexdigest())
        self.assertEqual(datetime.fromisoformat(result["fetched_at"]).utcoffset().total_seconds(), 0)
        self.assertIsNone(result["error"])
        connections[0].close.assert_called_once()

    def test_redirect_preserves_original_and_records_final_url(self):
        result, connections, resolve, _ = self.fetch([
            Response(status=302, Location="https://publisher.example.org/full"), Response()
        ])
        self.assertTrue(result["success"])
        self.assertEqual(result["url"], "https://news.example.com/article")
        self.assertEqual(result["final_url"], "https://publisher.example.org/full")
        self.assertEqual([call.args[0] for call in resolve.call_args_list], ["news.example.com", "publisher.example.org"])
        for connection in connections:
            connection.close.assert_called_once()

    def test_redirect_limit_is_three_hops(self):
        result, _, _, connect = self.fetch([Response(status=302, Location="/next")] * 4)
        self.assertEqual(result["error"], "redirect_limit")
        self.assertEqual(connect.call_count, 4)

    def test_unsafe_redirects_never_connect(self):
        for target in ("http://news.example.com/a", "https://127.0.0.1/a", "https://user:password@example.com/a"):
            with self.subTest(target=target):
                result, _, _, connect = self.fetch([Response(status=302, Location=target)])
                self.assertEqual(result["error"], "unsafe_url")
                self.assertEqual(connect.call_count, 1)

    def test_unsafe_inputs_and_credentials_do_not_resolve_or_echo(self):
        for url in ("http://example.com", "https://localhost/", "https://host.local/a", "https://10.0.0.1/", "https://8.8.8.8/", "https://[::1]/", "https://user:secret@example.com/", "https://example.com:8443/", "https://example.com/?token=secret", "https://example.com/?X-Amz-Signature=secret", "https://example.com/\nheader"):
            with self.subTest(url=url):
                result, _, resolve, connect = self.fetch([], url)
                self.assertEqual(result["error"], "unsafe_url")
                self.assertIsNone(result["url"])
                resolve.assert_not_called()
                connect.assert_not_called()

    def test_private_or_mixed_dns_is_rejected(self):
        for addresses in (["127.0.0.1"], ["169.254.169.254"], ["93.184.216.34", "192.168.0.1"], ["::1"]):
            with self.subTest(addresses=addresses), \
                 patch.object(evidence.socket, "getaddrinfo", return_value=[(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, 443)) for address in addresses]), \
                 patch.object(evidence, "_PinnedHTTPSConnection") as connect:
                result = evidence.fetch_source("https://news.example.com", time.monotonic() + 10)
                self.assertEqual(result["error"], "non_public_address")
                connect.assert_not_called()

    def test_public_dns_selects_only_verified_address(self):
        with patch.object(evidence.socket, "getaddrinfo", return_value=[(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))]):
            self.assertEqual(evidence._resolve_global("news.example.com", time.monotonic() + 10), "93.184.216.34")

    def test_tls_connects_to_pinned_ip_with_original_hostname(self):
        context, raw = Mock(), Mock()
        with patch.object(evidence.ssl, "create_default_context", return_value=context), \
             patch.object(evidence.socket, "create_connection", return_value=raw) as connect:
            connection = evidence._PinnedHTTPSConnection("news.example.com", "93.184.216.34", time.monotonic() + 10)
            connection.connect()
            self.assertEqual(connect.call_args.args[0], ("93.184.216.34", 443))
            context.wrap_socket.assert_called_once_with(raw, server_hostname="news.example.com")
            self.assertLessEqual(connect.call_args.kwargs["timeout"], 10)

    def test_failures_never_supply_partial_evidence(self):
        cases = [
            (Response(status=403), "http_error"),
            (Response(**{"Content-Type": "application/pdf"}), "unsupported_content"),
            (Response(**{"Content-Encoding": "gzip"}), "unsupported_encoding"),
            (Response("short"), "insufficient_text"),
            (Response("Access denied. " + ARTICLE), "blocked_page"),
            (Response("Please verify you are human. " + ARTICLE), "blocked_page"),
            (Response("x" * (evidence.MAX_BYTES + 1)), "response_too_large"),
        ]
        for response, error in cases:
            with self.subTest(error=error):
                result, _, _, _ = self.fetch([response])
                self.assertFalse(result["success"])
                self.assertEqual(result["error"], error)
                self.assertEqual(result["text"], "")
                self.assertIsNone(result["content_sha256"])
                self.assertIsNone(result["fetched_at"])

    def test_text_is_capped_and_hash_describes_returned_text(self):
        result, _, _, _ = self.fetch([Response(ARTICLE * 100, **{"Content-Type": "text/plain; charset=utf-8"})])
        self.assertTrue(result["success"])
        self.assertEqual(len(result["text"]), evidence.MAX_TEXT)
        self.assertEqual(result["content_sha256"], hashlib.sha256(result["text"].encode()).hexdigest())

    def test_expired_deadline_never_starts_dns_or_http(self):
        with patch.object(evidence.socket, "getaddrinfo") as resolve, patch.object(evidence, "_PinnedHTTPSConnection") as connect:
            result = evidence.fetch_source("https://news.example.com", time.monotonic() - 1)
        self.assertEqual(result["error"], "timeout")
        resolve.assert_not_called()
        connect.assert_not_called()

    def test_transport_errors_are_sanitized(self):
        with patch.object(evidence, "_resolve_global", side_effect=OSError("private credentials secret")):
            result = evidence.fetch_source("https://news.example.com", time.monotonic() + 10)
        self.assertEqual(result["error"], "transport_error")
        self.assertNotIn("secret", str(result))

    def test_reader_enforces_deadline_per_read_and_owns_file_reference(self):
        sock = Mock()
        sock.makefile.return_value = io.BytesIO(b"response")
        reader = evidence._DeadlineReader(sock, time.monotonic() + 10)
        self.assertEqual(reader.readinto(bytearray(4)), 4)
        sock.makefile.assert_called_once_with("rb", buffering=0)
        reader.deadline = time.monotonic() - 1
        with self.assertRaisesRegex(evidence.EvidenceError, "timeout"):
            reader.readinto(bytearray(4))
        reader.close()
        self.assertTrue(sock.makefile.return_value.closed)


if __name__ == "__main__":
    unittest.main()
