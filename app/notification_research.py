from __future__ import annotations

from datetime import datetime
from html import escape
from typing import Any

from app.console_utils import safe_print as print


def send_research_notification(
    service: Any,
    result: dict,
    *,
    task_id: str | None = None,
    selected_modules: list[str] | None = None,
) -> bool:
    """Send research completion notification through configured email/webhook channels."""
    try:
        service.reload_runtime_config()
        result = result if isinstance(result, dict) else {}
        rows = _result_rows(result)
        modules = result.get("modules") if isinstance(result.get("modules"), list) else []
        market_view = result.get("marketView") if isinstance(result.get("marketView"), list) else []
        summary = result.get("summary") if isinstance(result.get("summary"), dict) else {}
        updated_at = result.get("updatedAt") or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        module_names = [str(item.get("name") or "") for item in modules if isinstance(item, dict) and item.get("name")]
        selected_text = ", ".join(selected_modules or module_names) or "全部模块"

        subject = f"研究情报完成 - {len(rows)}只股票输出"
        text_body = _format_text_body(
            result,
            rows=rows,
            modules=modules,
            market_view=market_view,
            summary=summary,
            updated_at=updated_at,
            task_id=task_id,
            selected_text=selected_text,
        )
        html_body = _format_html_body(
            result,
            rows=rows,
            modules=modules,
            market_view=market_view,
            summary=summary,
            updated_at=updated_at,
            task_id=task_id,
            selected_text=selected_text,
        )

        success = False
        if service.config["email_enabled"]:
            success = service._send_custom_email(subject, html_body, text_body) or success
        if service.config["webhook_enabled"]:
            success = _send_webhook(service, subject, text_body, rows=rows, modules=modules) or success
        if not success:
            service._show_ui_notification(
                {
                    "symbol": "RESEARCH",
                    "name": "研究情报",
                    "type": "完成",
                    "message": text_body[:1000],
                    "triggered_at": updated_at,
                }
            )
            success = True
        return success
    except Exception as exc:
        print(f"[ERROR] 发送研究情报通知失败: {str(exc)}")
        return False


def _result_rows(result: dict) -> list:
    output_table = result.get("outputTable")
    return (output_table.get("rows") or []) if isinstance(output_table, dict) else []


def _format_text_body(
    result: dict,
    *,
    rows: list,
    modules: list,
    market_view: list,
    summary: dict,
    updated_at: str,
    task_id: str | None,
    selected_text: str,
) -> str:
    lines = [
        "研究情报任务完成",
        "",
        f"任务ID: {task_id or '--'}",
        f"完成时间: {updated_at}",
        f"执行模块: {selected_text}",
        f"模块数: {len(modules)}",
        f"股票输出: {len(rows)}",
        f"结论: {summary.get('body') or result.get('summaryText') or '--'}",
    ]
    if market_view:
        lines.extend(["", "市场观点:"])
        for item in market_view[:5]:
            if isinstance(item, dict):
                lines.append(f"- {item.get('title') or '观点'}: {item.get('body') or item.get('text') or '--'}")
    if rows:
        lines.extend(["", "股票输出:"])
        for row in rows[:10]:
            if not isinstance(row, dict):
                continue
            lines.append(
                f"- {row.get('code') or row.get('id') or '--'} {row.get('name') or ''}: "
                f"{row.get('source') or row.get('source_module') or '--'}；"
                f"{row.get('reason') or row.get('body') or row.get('latestPrice') or '--'}"
            )
        if len(rows) > 10:
            lines.append(f"...还有 {len(rows) - 10} 条股票输出未展示")
    return "\n".join(lines)


def _format_html_body(
    result: dict,
    *,
    rows: list,
    modules: list,
    market_view: list,
    summary: dict,
    updated_at: str,
    task_id: str | None,
    selected_text: str,
) -> str:
    row_items = ""
    for row in rows[:10]:
        if not isinstance(row, dict):
            continue
        row_items += (
            "<tr>"
            f"<td>{escape(str(row.get('code') or row.get('id') or '--'))}</td>"
            f"<td>{escape(str(row.get('name') or ''))}</td>"
            f"<td>{escape(str(row.get('source') or row.get('source_module') or '--'))}</td>"
            f"<td>{escape(str(row.get('reason') or row.get('body') or row.get('latestPrice') or '--'))}</td>"
            "</tr>"
        )
    market_items = "".join(
        f"<li><strong>{escape(str(item.get('title') or '观点'))}</strong>: "
        f"{escape(str(item.get('body') or item.get('text') or '--'))}</li>"
        for item in market_view[:5]
        if isinstance(item, dict)
    )
    return f"""
    <html>
    <body>
        <h2>研究情报任务完成</h2>
        <p><strong>任务ID:</strong> {escape(str(task_id or '--'))}</p>
        <p><strong>完成时间:</strong> {escape(str(updated_at))}</p>
        <p><strong>执行模块:</strong> {escape(selected_text)}</p>
        <p><strong>模块数:</strong> {len(modules)} | <strong>股票输出:</strong> {len(rows)}</p>
        <p><strong>结论:</strong> {escape(str(summary.get('body') or result.get('summaryText') or '--'))}</p>
        <h3>市场观点</h3>
        <ul>{market_items or '<li>暂无</li>'}</ul>
        <h3>股票输出</h3>
        <table border="1" cellspacing="0" cellpadding="6">
            <thead><tr><th>代码</th><th>名称</th><th>来源模块</th><th>依据</th></tr></thead>
            <tbody>{row_items or '<tr><td colspan="4">暂无股票输出</td></tr>'}</tbody>
        </table>
    </body>
    </html>
    """


def _send_webhook(service: Any, subject: str, text_body: str, *, rows: list, modules: list) -> bool:
    try:
        import requests

        if not service.config.get("webhook_url"):
            return False
        content = f"{subject}\n\n{text_body}"
        webhook_type = service.config.get("webhook_type")
        if webhook_type == "dingtalk":
            data = _dingtalk_payload(service, subject, text_body)
        elif webhook_type == "feishu":
            data = _feishu_payload(subject, content, rows=rows, modules=modules)
        else:
            return False

        response = requests.post(
            service.config["webhook_url"],
            json=data,
            headers={"Content-Type": "application/json"},
            timeout=10,
        )
        if response.status_code != 200:
            return False
        try:
            result = response.json()
        except Exception:
            return True
        if webhook_type == "dingtalk":
            return result.get("errcode") in {0, None}
        if webhook_type == "feishu":
            return result.get("code") in {0, None}
        return True
    except Exception as exc:
        print(f"[ERROR] 研究情报Webhook发送失败: {str(exc)}")
        return False


def _dingtalk_payload(service: Any, subject: str, text_body: str) -> dict:
    keyword = service.config.get("webhook_keyword", "")
    markdown_text = f"{keyword}\n\n### {subject}\n\n{text_body}" if keyword else f"### {subject}\n\n{text_body}"
    return {"msgtype": "markdown", "markdown": {"title": subject, "text": markdown_text}}


def _feishu_payload(subject: str, content: str, *, rows: list, modules: list) -> dict:
    return {
        "msg_type": "interactive",
        "card": {
            "header": {"title": {"content": subject, "tag": "plain_text"}, "template": "blue"},
            "elements": [
                {
                    "tag": "div",
                    "fields": [
                        {"is_short": True, "text": {"content": f"**模块数**\n{len(modules)}", "tag": "lark_md"}},
                        {"is_short": True, "text": {"content": f"**股票输出**\n{len(rows)}", "tag": "lark_md"}},
                    ],
                },
                {"tag": "div", "text": {"content": content[:3500], "tag": "lark_md"}},
            ],
        },
    }
