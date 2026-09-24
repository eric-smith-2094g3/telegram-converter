# telegram-converter

A small webhook receiver that turns Prometheus Alertmanager and Grafana notification payloads into clean Telegram HTML messages and pushes them to your chat.

I got tired of running bloated notification relays that need two config files and a redis instance just to tell me a disk is full. This runs as a single script, listens on a local port, parses incoming alerts, and dispatches them straight to Telegram.

## Setup

Install the dependency:

```text
pip install -r requirements.txt
```

Set the two required environment variables:

```text
set TELEGRAM_BOT_TOKEN=123456789:ABCdefGHIjklMNOpqrsTUVwxyz
set TELEGRAM_CHAT_ID=-1001234567890
```

Optional variables:
- `LISTEN_HOST`: default `0.0.0.0`
- `LISTEN_PORT`: default `9087`
- `SILENT_RESOLVED`: set to `1` or `true` to send resolved alerts without notification sound.

## Running

Start the server:

```text
python telegram_converter.py
```

Or pass flags directly:

```text
python telegram_converter.py --host 127.0.0.1 --port 9087
```

Point Alertmanager's `webhook_configs` to `http://localhost:9087/alerts`:

```yaml
receivers:
  - name: telegram-alerts
    webhook_configs:
      - url: http://127.0.0.1:9087/alerts
        send_resolved: true
```

Grafana webhook alerts can be sent to the same endpoint or `http://127.0.0.1:9087/grafana`.

<!-- generated: 2026-09-24 -->
