#!/usr/bin/env python3
"""
paid_traffic_dashboard.py — gera HTML do dashboard a partir dos JSONs.

Lê ~/.operacao-ia/dashboards/paid-traffic-{N}d.json e o template,
emite paid-traffic-dashboard-{N}d.html injetando JSON_DATA inline.
"""
import json
import sys
from datetime import datetime
from pathlib import Path

OPERACAO = Path.home() / ".operacao-ia"
DASH_DIR = OPERACAO / "dashboards"
META_DIR = OPERACAO / "scripts" / "meta"
TEMPLATE_LOCAL = META_DIR / "paid-traffic-dashboard-template.html"
TEMPLATE_REPO  = Path(__file__).resolve().parent.parent / "docs" / "paid-traffic-dashboard-template.html"


def find_template():
    if TEMPLATE_LOCAL.exists():
        return TEMPLATE_LOCAL
    if TEMPLATE_REPO.exists():
        return TEMPLATE_REPO
    return None


def main():
    tpl = find_template()
    if not tpl:
        print(f"❌ Template HTML não encontrado em {TEMPLATE_LOCAL} ou {TEMPLATE_REPO}")
        sys.exit(1)

    if not DASH_DIR.exists():
        print(f"❌ {DASH_DIR} não existe — rode fetch_metrics.py primeiro")
        sys.exit(1)

    jsons = sorted(DASH_DIR.glob("paid-traffic-*d.json"))
    if not jsons:
        print(f"❌ Nenhum JSON em {DASH_DIR}")
        sys.exit(1)

    template = tpl.read_text()
    generated = 0
    for jf in jsons:
        try:
            data = json.loads(jf.read_text())
        except Exception as e:
            print(f"⚠️  Pulando {jf.name}: {e}")
            continue
        days = data["window_days"]
        html = template.replace(
            "/*__JSON_DATA__*/",
            f"window.PAID_TRAFFIC_DATA = {json.dumps(data, ensure_ascii=False)};"
        ).replace(
            "<!--__GENERATED_AT__-->",
            f"Atualizado: {data.get('generated_at', '')}"
        ).replace(
            "<!--__TITLE__-->",
            f"Tráfego Pago — {days}d"
        )
        out = DASH_DIR / f"paid-traffic-dashboard-{days}d.html"
        out.write_text(html)
        print(f"✅ {out.name}")
        generated += 1

    # Index com links
    index = ['<!doctype html><html><head><meta charset="utf-8"><title>ZX Control — Tráfego Pago</title>',
             '<style>body{background:#0a0a0a;color:#e5e5e5;font-family:system-ui;padding:40px;text-align:center}',
             'a{display:inline-block;margin:8px;padding:12px 24px;background:#1f2937;color:#fbbf24;text-decoration:none;border-radius:8px;border:1px solid #374151}',
             'h1{color:#fbbf24}</style></head><body>',
             '<h1>ZX Control — Tráfego Pago</h1>',
             f'<p style="color:#9ca3af">Última atualização: {datetime.now().strftime("%d/%m/%Y %H:%M")}</p>',
             '<div>']
    for jf in jsons:
        days = jf.stem.replace("paid-traffic-", "").replace("d", "")
        index.append(f'<a href="paid-traffic-dashboard-{days}d.html">Janela {days}d</a>')
    index.append('</div></body></html>')
    (DASH_DIR / "index.html").write_text("".join(index))

    print(f"\n{generated} dashboards gerados em {DASH_DIR}")


if __name__ == "__main__":
    main()
