#!/usr/bin/env python3
"""Formata o relatório Meta já coletado, sem rede e sem recalcular métricas."""

import argparse
import html
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


WHATSAPP_LIMIT = 1200
STALE_AFTER = timedelta(hours=26)
STATUS_LABELS = {
    "green": "BOM",
    "yellow": "ATENÇÃO",
    "red": "RUIM",
    "gray": "SEM DADOS",
}
STATUS_EMOJIS = {
    "green": "🟢",
    "yellow": "🟡",
    "red": "🔴",
    "gray": "⚪",
}
STATUS_COLORS = {
    "green": "#18794e",
    "yellow": "#8a6100",
    "red": "#b42318",
    "gray": "#667085",
}


def _operation_dir(operation_dir: Optional[Path] = None) -> Path:
    return Path(operation_dir) if operation_dir else Path.home() / ".operacao-ia"


def format_number_br(value: Any, decimals: int = 2) -> str:
    """Formata número com ponto de milhar e vírgula decimal."""
    if value is None:
        return "—"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "—"
    rendered = f"{number:,.{decimals}f}"
    return rendered.replace(",", "\0").replace(".", ",").replace("\0", ".")


def format_metric(value: Any, format_name: str, currency: str = "BRL") -> str:
    if value is None:
        return "—"
    if format_name == "currency":
        prefix = "R$ " if currency == "BRL" else f"{currency} "
        return prefix + format_number_br(value)
    if format_name == "percent":
        return format_number_br(value) + "%"
    return format_number_br(value)


def describe_kpi_direction(value: Any, target: Any, better: str) -> str:
    """Explica a direção sem inverter KPIs em que um valor maior é melhor."""
    try:
        current = float(value)
        goal = float(target)
    except (TypeError, ValueError):
        return "sem comparação com a meta"
    if goal <= 0:
        return "meta inválida"
    if abs(current - goal) < 1e-12:
        return "na meta"
    relation = "acima" if current > goal else "abaixo"
    favorable = (better == "higher" and current > goal) or (
        better == "lower" and current < goal
    )
    quality = "direção favorável" if favorable else "direção desfavorável"
    delta = abs((current - goal) / goal * 100)
    return f"{format_number_br(delta, 1)}% {relation} da meta; {quality}"


def _safe_float(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _read_json(path: Path) -> Dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("a raiz do JSON precisa ser um objeto")
    return data


def _profile_window(profile: Dict[str, Any], requested: Optional[int]) -> int:
    if requested is not None:
        if requested < 1:
            raise ValueError("--window precisa ser maior que zero")
        return requested
    windows = profile.get("windows") or [4, 7, 14, 30]
    valid = [int(item) for item in windows if isinstance(item, int) and item > 0]
    return min(valid) if valid else 7


def _parse_generated_at(value: Any) -> Optional[datetime]:
    if not isinstance(value, str) or not value.strip():
        return None
    raw = value.strip().replace("Z", "+00:00")
    parsed = datetime.fromisoformat(raw)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _display_datetime(value: Optional[datetime]) -> str:
    if value is None:
        return "data desconhecida"
    return value.strftime("%d/%m/%Y às %H:%M")


def _iter_ads(campaign: Dict[str, Any]) -> Iterable[Dict[str, Any]]:
    """Aceita o contrato atual (ads em adsets) e o formato direto legado."""
    for ad in campaign.get("ads") or []:
        if isinstance(ad, dict):
            yield ad
    for adset in campaign.get("adsets") or []:
        if not isinstance(adset, dict):
            continue
        for ad in adset.get("ads") or []:
            if isinstance(ad, dict):
                yield ad


def _empty_report(window: int, source: Path, reason: str) -> Dict[str, Any]:
    return {
        "available": False,
        "warning": (
            "DADOS INDISPONÍVEIS: "
            + reason
            + " O relatório não inventou números. Verifique o coletor de métricas."
        ),
        "stale": False,
        "account": "não informada",
        "window": window,
        "generated_display": "coleta indisponível",
        "spend": None,
        "currency": "BRL",
        "kpis": [],
        "campaigns": [],
        "scale_ads": [],
        "kill_ads": [],
        "source": str(source),
        "footer": (
            f"Fonte esperada: {source}. Para conferir na hora: "
            "python3 ~/.operacao-ia/scripts/meta/report_formatter.py --format text"
        ),
    }


def assemble_report(
    window: Optional[int] = None,
    *,
    operation_dir: Optional[Path] = None,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Monta uma única estrutura usada pelos três renderizadores."""
    base = _operation_dir(operation_dir)
    profile_path = base / "config" / "meta_perfil.json"
    profile: Dict[str, Any] = {}
    profile_error = ""
    try:
        profile = _read_json(profile_path)
    except FileNotFoundError:
        profile_error = f"{profile_path} não existe."
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        profile_error = f"{profile_path} não pôde ser lido ({exc})."

    try:
        selected_window = _profile_window(profile, window)
    except ValueError:
        raise
    source = base / "dashboards" / f"paid-traffic-{selected_window}d.json"
    if profile_error:
        return _empty_report(selected_window, source, profile_error)

    try:
        payload = _read_json(source)
    except FileNotFoundError:
        return _empty_report(
            selected_window,
            source,
            f"{source} não existe. Rode o coletor antes do relatório.",
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return _empty_report(
            selected_window,
            source,
            f"{source} está inválido ou ilegível ({exc}).",
        )

    generated_error = ""
    try:
        generated_at = _parse_generated_at(payload.get("generated_at"))
    except ValueError as exc:
        generated_at = None
        generated_error = f"generated_at inválido ({exc})"

    reference_now = now or datetime.now(timezone.utc)
    if reference_now.tzinfo is None:
        reference_now = reference_now.replace(tzinfo=timezone.utc)
    age = (
        reference_now.astimezone(timezone.utc)
        - generated_at.astimezone(timezone.utc)
        if generated_at
        else None
    )
    # 26h tolera pequenos atrasos do job diário sem esconder falha do coletor.
    stale = generated_at is None or (age is not None and age > STALE_AFTER)
    warning = ""
    if stale:
        detail = generated_error or "a última coleta tem mais de 26 horas"
        warning = (
            "DADO DEFASADO: "
            + detail
            + ". O coletor pode ter falhado; confira antes de decidir."
        )

    kpi_meta = {
        item.get("key"): item
        for item in profile.get("kpis") or []
        if isinstance(item, dict) and item.get("key")
    }
    kpis = []
    for key, summary in (payload.get("kpis_summary") or {}).items():
        if not isinstance(summary, dict):
            continue
        meta = kpi_meta.get(key, {})
        status = str(summary.get("status") or "gray").lower()
        if status not in STATUS_LABELS:
            status = "gray"
        value = summary.get("value")
        target = summary.get("target", meta.get("target"))
        format_name = str(meta.get("format") or "ratio")
        better = str(meta.get("better") or "lower")
        kpis.append(
            {
                "key": key,
                "label": meta.get("label") or key.upper(),
                "value": value,
                "value_display": format_metric(
                    value, format_name, str(payload.get("currency") or "BRL")
                ),
                "target_display": format_metric(
                    target, format_name, str(payload.get("currency") or "BRL")
                ),
                "status": status,
                "status_label": STATUS_LABELS[status],
                "direction": describe_kpi_direction(value, target, better),
            }
        )

    primary = str(payload.get("primary_kpi") or profile.get("primary_kpi") or "")
    primary_meta = kpi_meta.get(primary, {})
    primary_format = str(primary_meta.get("format") or "ratio")
    primary_label = str(primary_meta.get("label") or primary.upper() or "KPI")
    raw_campaigns = [
        item for item in payload.get("campaigns") or [] if isinstance(item, dict)
    ]
    raw_campaigns.sort(key=lambda item: _safe_float(item.get("spend")), reverse=True)
    campaigns = []
    scale_ads = []
    kill_ads = []
    seen_ads = set()
    for campaign in raw_campaigns:
        metric_value = (campaign.get("metrics") or {}).get(primary)
        campaigns.append(
            {
                "name": campaign.get("name") or "Campanha sem nome",
                "spend": format_metric(
                    campaign.get("spend"),
                    "currency",
                    str(payload.get("currency") or "BRL"),
                ),
                "primary_label": primary_label,
                "primary_value": format_metric(
                    metric_value,
                    primary_format,
                    str(payload.get("currency") or "BRL"),
                ),
            }
        )
        for ad in _iter_ads(campaign):
            identity = ad.get("ad_id") or id(ad)
            if identity in seen_ads:
                continue
            seen_ads.add(identity)
            decision = str(ad.get("decide") or "").upper()
            if decision not in ("SCALE", "KILL"):
                continue
            item = {
                "campaign": campaign.get("name") or "Campanha sem nome",
                "name": ad.get("ad_name") or "Anúncio sem nome",
                "reason": ad.get("decide_reason") or "motivo não informado",
                "spend_value": _safe_float(ad.get("spend")),
            }
            (scale_ads if decision == "SCALE" else kill_ads).append(item)
    scale_ads.sort(key=lambda item: item["spend_value"], reverse=True)
    kill_ads.sort(key=lambda item: item["spend_value"], reverse=True)

    return {
        "available": True,
        "warning": warning,
        "stale": stale,
        "account": payload.get("ad_account_id") or profile.get("ad_account_id") or "não informada",
        "window": payload.get("window_days") or selected_window,
        "generated_display": _display_datetime(generated_at),
        "spend": format_metric(
            payload.get("spend_total"),
            "currency",
            str(payload.get("currency") or "BRL"),
        ),
        "currency": payload.get("currency") or "BRL",
        "kpis": kpis,
        "campaigns": campaigns[:5],
        "scale_ads": scale_ads,
        "kill_ads": kill_ads,
        "source": str(source),
        "footer": (
            f"Dados do coletor local: paid-traffic-{selected_window}d.json. "
            "Para conferir na hora: python3 ~/.operacao-ia/scripts/meta/"
            "report_formatter.py --format text"
        ),
    }


def render_text(report: Optional[Dict[str, Any]] = None, **assemble_kwargs: Any) -> str:
    report = report or assemble_report(**assemble_kwargs)
    lines: List[str] = []
    if report.get("warning"):
        lines.extend([f"⚠ {report['warning']}", ""])
    lines.append(
        "RELATÓRIO META ADS — conta "
        f"{report['account']} — {report['window']} dias — {report['generated_display']}"
    )
    if report.get("available"):
        lines.extend(["", f"Gasto total: {report['spend']}", "", "KPIs"])
        if report["kpis"]:
            for item in report["kpis"]:
                lines.append(
                    f"- {item['label']}: {item['value_display']} | meta "
                    f"{item['target_display']} | {item['status_label']} "
                    f"({item['direction']})"
                )
        else:
            lines.append("- Nenhum KPI disponível no JSON.")

        lines.extend(["", "Top campanhas por gasto"])
        if report["campaigns"]:
            for item in report["campaigns"]:
                lines.append(
                    f"- {item['name']}: {item['spend']} | "
                    f"{item['primary_label']}: {item['primary_value']}"
                )
        else:
            lines.append("- Nenhuma campanha com dados.")

        lines.extend(["", "Anúncios para SCALE"])
        if report["scale_ads"]:
            for item in report["scale_ads"]:
                lines.append(
                    f"- {item['name']} ({item['campaign']}): {item['reason']}"
                )
        else:
            lines.append("- Nenhum.")

        lines.extend(["", "Anúncios para KILL"])
        if report["kill_ads"]:
            for item in report["kill_ads"]:
                lines.append(
                    f"- {item['name']} ({item['campaign']}): {item['reason']}"
                )
        else:
            lines.append("- Nenhum.")
    lines.extend(["", report["footer"]])
    return "\n".join(lines)


def render_html(report: Optional[Dict[str, Any]] = None, **assemble_kwargs: Any) -> str:
    report = report or assemble_report(**assemble_kwargs)

    def esc(value: Any) -> str:
        return html.escape(str(value), quote=True)

    parts = [
        '<!doctype html><html><body style="font-family:Arial,sans-serif;'
        'color:#252525;line-height:1.45;max-width:760px;margin:0 auto;padding:20px">'
    ]
    if report.get("warning"):
        parts.append(
            '<div style="background:#fff4e5;border:1px solid #f5a623;'
            'padding:12px;margin-bottom:16px"><strong>⚠ '
            + esc(report["warning"])
            + "</strong></div>"
        )
    parts.append(
        "<h2 style=\"margin:0 0 8px\">Relatório Meta Ads</h2>"
        f"<p style=\"margin:0 0 18px\">Conta <strong>{esc(report['account'])}</strong>"
        f" · {esc(report['window'])} dias · {esc(report['generated_display'])}</p>"
    )
    if report.get("available"):
        parts.append(f"<h3>Gasto total: {esc(report['spend'])}</h3>")
        parts.append(
            '<h3>KPIs</h3><table style="border-collapse:collapse;width:100%">'
            "<thead><tr><th align=\"left\">KPI</th><th align=\"left\">Valor</th>"
            "<th align=\"left\">Meta</th><th align=\"left\">Status</th>"
            "<th align=\"left\">Leitura</th></tr></thead><tbody>"
        )
        for item in report["kpis"]:
            color = STATUS_COLORS[item["status"]]
            parts.append(
                "<tr>"
                f"<td style=\"padding:8px;border-top:1px solid #ddd\">{esc(item['label'])}</td>"
                f"<td style=\"padding:8px;border-top:1px solid #ddd\">{esc(item['value_display'])}</td>"
                f"<td style=\"padding:8px;border-top:1px solid #ddd\">{esc(item['target_display'])}</td>"
                f"<td style=\"padding:8px;border-top:1px solid #ddd;color:{color};"
                f"font-weight:bold\">{esc(item['status_label'])}</td>"
                f"<td style=\"padding:8px;border-top:1px solid #ddd\">{esc(item['direction'])}</td>"
                "</tr>"
            )
        if not report["kpis"]:
            parts.append('<tr><td colspan="5">Nenhum KPI disponível no JSON.</td></tr>')
        parts.append("</tbody></table>")

        parts.append(
            '<h3>Top campanhas por gasto</h3><table style="border-collapse:collapse;width:100%">'
            "<thead><tr><th align=\"left\">Campanha</th><th align=\"left\">Gasto</th>"
            "<th align=\"left\">KPI primário</th></tr></thead><tbody>"
        )
        for item in report["campaigns"]:
            parts.append(
                "<tr>"
                f"<td style=\"padding:8px;border-top:1px solid #ddd\">{esc(item['name'])}</td>"
                f"<td style=\"padding:8px;border-top:1px solid #ddd\">{esc(item['spend'])}</td>"
                f"<td style=\"padding:8px;border-top:1px solid #ddd\">"
                f"{esc(item['primary_label'])}: {esc(item['primary_value'])}</td></tr>"
            )
        if not report["campaigns"]:
            parts.append('<tr><td colspan="3">Nenhuma campanha com dados.</td></tr>')
        parts.append("</tbody></table>")

        for title, key, color in (
            ("Anúncios para SCALE", "scale_ads", "#18794e"),
            ("Anúncios para KILL", "kill_ads", "#b42318"),
        ):
            parts.append(f"<h3 style=\"color:{color}\">{esc(title)}</h3><ul>")
            if report[key]:
                for item in report[key]:
                    parts.append(
                        f"<li><strong>{esc(item['name'])}</strong> "
                        f"({esc(item['campaign'])}): {esc(item['reason'])}</li>"
                    )
            else:
                parts.append("<li>Nenhum.</li>")
            parts.append("</ul>")
    parts.append(
        f'<p style="font-size:12px;color:#667085;border-top:1px solid #ddd;'
        f'padding-top:12px">{esc(report["footer"])}</p></body></html>'
    )
    return "".join(parts)


def _shorten(value: Any, limit: int) -> str:
    text = " ".join(str(value).split())
    if len(text) <= limit:
        return text
    return text[: max(1, limit - 1)].rstrip() + "…"


def _whatsapp_candidate(
    report: Dict[str, Any],
    *,
    campaign_limit: int,
    action_limit: int,
    reason_limit: int,
    summarized: bool,
) -> str:
    lines: List[str] = []
    if report.get("warning"):
        lines.append("⚠️ *" + _shorten(report["warning"], 210) + "*")
    lines.append(
        f"*RELATÓRIO META* | {report['account']} | {report['window']}d | "
        f"{report['generated_display']}"
    )
    if report.get("available"):
        lines.append(f"*Gasto:* {report['spend']}")
        lines.append("")
        lines.append("*KPIs*")
        for item in report["kpis"]:
            lines.append(
                f"{STATUS_EMOJIS[item['status']]} *{item['label']}:* "
                f"{item['value_display']} (meta {item['target_display']})"
            )
        lines.append("")
        lines.append("*Top campanhas*")
        for item in report["campaigns"][:campaign_limit]:
            lines.append(
                f"• {_shorten(item['name'], 48)} — {item['spend']} | "
                f"{item['primary_value']}"
            )
        if not report["campaigns"]:
            lines.append("• Nenhuma campanha com dados.")
        for title, emoji, key in (
            ("SCALE", "📈", "scale_ads"),
            ("KILL", "🛑", "kill_ads"),
        ):
            lines.append("")
            lines.append(f"{emoji} *{title}*")
            items = report[key][:action_limit]
            if items:
                for item in items:
                    lines.append(
                        f"• {_shorten(item['name'], 42)}: "
                        f"{_shorten(item['reason'], reason_limit)}"
                    )
            else:
                lines.append("• Nenhum.")
    lines.extend(["", _shorten(report["footer"], 150)])
    if summarized:
        lines.append("… *Relatório resumido para caber no WhatsApp.*")
    return "\n".join(lines)


def render_whatsapp(
    report: Optional[Dict[str, Any]] = None, **assemble_kwargs: Any
) -> str:
    report = report or assemble_report(**assemble_kwargs)
    total_actions = max(len(report["scale_ads"]), len(report["kill_ads"]))
    options = [
        (5, total_actions, 150),
        (3, min(total_actions, 8), 100),
        (2, min(total_actions, 5), 70),
        (1, min(total_actions, 3), 45),
        (0, min(total_actions, 2), 32),
    ]
    for campaign_limit, action_limit, reason_limit in options:
        summarized = (
            campaign_limit < len(report["campaigns"])
            or action_limit < len(report["scale_ads"])
            or action_limit < len(report["kill_ads"])
            or reason_limit < 150
        )
        candidate = _whatsapp_candidate(
            report,
            campaign_limit=campaign_limit,
            action_limit=action_limit,
            reason_limit=reason_limit,
            summarized=summarized,
        )
        if len(candidate) <= WHATSAPP_LIMIT:
            return candidate
    # Última barreira: a API recebe sempre menos de 1200 caracteres.
    suffix = "\n… *Relatório resumido para caber no WhatsApp.*"
    raw = _whatsapp_candidate(
        report,
        campaign_limit=0,
        action_limit=1,
        reason_limit=20,
        summarized=False,
    )
    return raw[: WHATSAPP_LIMIT - len(suffix)].rstrip() + suffix


def main() -> int:
    parser = argparse.ArgumentParser(description="Inspeciona o relatório Meta sem enviar")
    parser.add_argument("--window", type=int, help="janela do JSON em dias")
    parser.add_argument(
        "--format",
        choices=("text", "html", "whatsapp"),
        default="text",
        help="formato de saída (default: text)",
    )
    args = parser.parse_args()
    try:
        report = assemble_report(window=args.window)
        renderer = {
            "text": render_text,
            "html": render_html,
            "whatsapp": render_whatsapp,
        }[args.format]
        print(renderer(report))
        return 0
    except (OSError, ValueError) as exc:
        print(f"❌ Não foi possível montar o relatório: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
