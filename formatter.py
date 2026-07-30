import html
from datetime import datetime

MAX_MESSAGE_LEN = 3900  # telegram limit is 4096, leave head room


def escape_tg(val) -> str:
    if val is None:
        return ""
    return html.escape(str(val), quote=False)


def _parse_iso(ts_str: str) -> str:
    if not ts_str or ts_str.startswith("0001"):
        return ""
    # alertmanager sends 2023-11-04T18:22:01.123456789Z or +00:00
    clean = ts_str.rstrip("Z").split(".")[0]
    try:
        dt = datetime.fromisoformat(clean)
        return dt.strftime("%Y-%m-%d %H:%M:%S UTC")
    except ValueError:
        return ts_str


def _format_grafana_legacy(data: dict) -> list[str]:
    title = data.get("ruleName") or data.get("title") or "Grafana Alert"
    state = data.get("state", "unknown").upper()
    
    icon = "🔥" if state in ("ALERTING", "FIRING") else "✅"
    if state == "PENDING":
        icon = "⚠️"

    lines = [
        f"{icon} <b>[{state}] {escape_tg(title)}</b>",
    ]

    msg = data.get("message")
    if msg:
        lines.append(f"<i>{escape_tg(msg.strip())}</i>")

    eval_matches = data.get("evalMatches", [])
    if eval_matches:
        lines.append("")
        lines.append("<b>Metrics:</b>")
        for m in eval_matches:
            metric_name = m.get("metric", "value")
            val = m.get("value", "?")
            lines.append(f"  • <code>{escape_tg(metric_name)}</code>: {escape_tg(val)}")

    rule_url = data.get("ruleUrl")
    if rule_url:
        lines.append(f'\n<a href="{escape_tg(rule_url)}">Open in Grafana</a>')

    return ["\n".join(lines)]


def _format_single_alert(a: dict, common_labels: dict) -> str:
    status = a.get("status", "firing").lower()
    icon = "🔥" if status == "firing" else "✅"

    labels = a.get("labels", {})
    annotations = a.get("annotations", {})

    alertname = labels.get("alertname") or labels.get("alert_name") or "Alert"
    severity = labels.get("severity", "").upper()
    
    header_parts = [icon, f"<b>{escape_tg(alertname)}</b>"]
    if severity:
        header_parts.append(f"[{escape_tg(severity)}]")

    block = [" ".join(header_parts)]

    summary = annotations.get("summary") or annotations.get("message")
    if summary:
        block.append(f"<i>{escape_tg(summary.strip())}</i>")

    desc = annotations.get("description")
    if desc and desc != summary:
        block.append(escape_tg(desc.strip()))

    # print unique labels that aren't in common_labels
    unique_labels = {
        k: v for k, v in labels.items()
        if k not in ("alertname", "alert_name", "severity") and common_labels.get(k) != v
    }
    if unique_labels:
        tag_items = [f"<code>{escape_tg(k)}={escape_tg(v)}</code>" for k, v in sorted(unique_labels.items())]
        block.append("Labels: " + ", ".join(tag_items))

    # FIXME: grafana sends 0001-01-01T00:00:00Z for endsAt while still firing
    started = _parse_iso(a.get("startsAt", ""))
    ended = _parse_iso(a.get("endsAt", ""))
    if status == "resolved" and ended:
        block.append(f"Resolved at: {ended}")
    elif started:
        block.append(f"Started at: {started}")

    gen_url = a.get("generatorURL") or a.get("dashboardURL") or a.get("panelURL")
    if gen_url:
        block.append(f'<a href="{escape_tg(gen_url)}">Source</a>')

    return "\n".join(block)


def format_alert_payload(data: dict) -> list[str]:
    """Convert alertmanager or grafana webhook payload into telegram HTML chunks."""
    # print("raw keys:", list(data.keys()))
    if "evalMatches" in data:
        return _format_grafana_legacy(data)

    # grafana unified alert has ruleUrl & orgId together with alertmanager structure
    is_grafana_unified = "orgId" in data and "alerts" in data

    status = data.get("status", "firing").upper()
    rawAlerts = data.get("alerts", [])
    common_labels = data.get("commonLabels", {})
    common_ann = data.get("commonAnnotations", {})

    top_icon = "🔥" if status == "FIRING" else "✅"
    
    # grafana puts rule title in title field sometimes
    default_title = data.get("title") or f"Batch ({len(rawAlerts)} alerts)"
    group_title = common_labels.get("alertname") or default_title
    
    summary_hdr = common_ann.get("summary")
    header_lines = [f"{top_icon} <b>{escape_tg(status)}: {escape_tg(group_title)}</b>"]
    if summary_hdr:
        header_lines.append(f"<i>{escape_tg(summary_hdr)}</i>")
    
    shared_env = common_labels.get("environment") or common_labels.get("env")
    if shared_env:
        header_lines.append(f"Env: <code>{escape_tg(shared_env)}</code>")

    if is_grafana_unified and data.get("externalURL"):
        header_lines.append(f'<a href="{escape_tg(data["externalURL"])}">Grafana Instance</a>')

    lead_block = "\n".join(header_lines)

    if not rawAlerts:
        return [lead_block]

    body_blocks = []
    for item in rawAlerts:
        body_blocks.append(_format_single_alert(item, common_labels))

    # pack into telegram messages without exceeding limits
    chunks = []
    current_buf = lead_block

    for block in body_blocks:
        addition = "\n\n" + block
        if len(current_buf) + len(addition) > MAX_MESSAGE_LEN:
            chunks.append(current_buf)
            current_buf = block
        else:
            current_buf += addition

    if current_buf:
        chunks.append(current_buf)

    return chunks
