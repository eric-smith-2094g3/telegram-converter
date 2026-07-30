import json
import logging
import os
import sys
import time
import urllib.error
import urllib.request
from http.server import HTTPServer, BaseHTTPRequestHandler

from telegram_converter.formatter import format_alertmanager, format_grafana

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("telegram_converter")

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
DEFAULT_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
THREAD_ID = os.environ.get("TELEGRAM_THREAD_ID", "").strip()
LISTEN_HOST = os.environ.get("LISTEN_HOST", "0.0.0.0")
LISTEN_PORT = int(os.environ.get("LISTEN_PORT", "9087"))

# Telegram message hard limit is 4096; keep headroom for tags and wrapper
MAX_CHUNK_LEN = 3900


def _split_text(text, max_len=MAX_CHUNK_LEN):
    if len(text) <= max_len:
        return [text]
    chunks = []
    lines = text.split("\n")
    curr = ""
    for line in lines:
        if len(curr) + len(line) + 1 > max_len:
            if curr:
                chunks.append(curr)
            curr = line
        else:
            curr = f"{curr}\n{line}" if curr else line
    if curr:
        chunks.append(curr)
    return chunks


def send_telegram(text, chat_id, thread_id=None):
    """Deliver preformatted HTML to the Telegram Bot API."""
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    chunks = _split_text(text)

    for part in chunks:
        payload = {
            "chat_id": chat_id,
            "text": part,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        if thread_id:
            payload["message_thread_id"] = int(thread_id)

        encoded = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=encoded,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        # print(f"DEBUG raw payload: {encoded}")
        # Retry loop for 429 flood control
        for attempt in range(3):
            try:
                with urllib.request.urlopen(req, timeout=15) as resp:
                    break
            except urllib.error.HTTPError as err:
                if err.code == 429:
                    retry_after = 2
                    try:
                        err_data = json.loads(err.read().decode("utf-8"))
                        retry_after = err_data.get("parameters", {}).get("retry_after", 2)
                    except Exception:
                        pass
                    log.warning("Hit rate limit, backing off for %d seconds", retry_after)
                    time.sleep(retry_after + 0.5)
                    continue
                raise


class AlertHandler(BaseHTTPRequestHandler):
    server_version = "AlertConverter/0.2"

    def do_GET(self):
        if self.path in ("/health", "/healthz"):
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"OK")
            return
        self.send_response(404)
        self.end_headers()

    def do_POST(self):
        clean_path = self.path.split("?")[0].rstrip("/")
        if clean_path not in ("/alertmanager", "/grafana"):
            self.send_response(404)
            self.end_headers()
            return

        content_len = int(self.headers.get("Content-Length", 0))
        if content_len == 0:
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b"Empty request body")
            return

        body = self.rfile.read(content_len)
        try:
            data = json.loads(body.decode("utf-8"))
        except Exception as err:
            log.warning("Malformed JSON payload: %s", err)
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b"Invalid JSON")
            return

        tgt_chat = DEFAULT_CHAT_ID
        if not tgt_chat:
            log.error("TELEGRAM_CHAT_ID is not configured")
            self.send_response(500)
            self.end_headers()
            self.wfile.write(b"Server missing TELEGRAM_CHAT_ID")
            return

        # FIXME: grafana unified alerting puts annotations inside alerts[].annotations, legacy had evalMatches
        try:
            if clean_path == "/alertmanager":
                message = format_alertmanager(data)
            else:
                message = format_grafana(data)

            send_telegram(message, tgt_chat, thread_id=THREAD_ID or None)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"status":"sent"}')
        except urllib.error.HTTPError as err:
            body_err = err.read().decode("utf-8", errors="replace")
            log.error("Telegram API returned %d: %s", err.code, body_err)
            self.send_response(502)
            self.end_headers()
            self.wfile.write(b"Telegram upstream error")
        except Exception as exc:
            log.exception("Failed processing alert: %s", exc)
            self.send_response(500)
            self.end_headers()
            self.wfile.write(b"Internal error")

    def log_message(self, fmt, *args):
        pass


def main():
    if not BOT_TOKEN:
        log.error("TELEGRAM_BOT_TOKEN environment variable must be set")
        sys.exit(1)
    if not DEFAULT_CHAT_ID:
        log.warning("TELEGRAM_CHAT_ID is empty, notifications will fail until set")

    server_addr = (LISTEN_HOST, LISTEN_PORT)
    httpd = HTTPServer(server_addr, AlertHandler)
    log.info("Webhook receiver running on %s:%d", LISTEN_HOST, LISTEN_PORT)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        log.info("Shutting down...")
        httpd.server_close()


if __name__ == "__main__":
    main()
