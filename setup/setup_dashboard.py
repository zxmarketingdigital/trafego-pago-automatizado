#!/usr/bin/env python3
"""
Setup 6 — Etapa 5: Dashboard local
Copia paid_traffic_dashboard.py + template HTML + start_dashboard.sh,
gera o HTML e abre no browser.
"""
import json
import shutil
import subprocess
import sys
import webbrowser
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
OPERACAO = Path.home() / ".operacao-ia"
META_DIR = OPERACAO / "scripts" / "meta"
DASH_DIR = OPERACAO / "dashboards"

FILES = [
    (REPO_ROOT / "scripts" / "paid_traffic_dashboard.py", META_DIR / "paid_traffic_dashboard.py"),
    (REPO_ROOT / "scripts" / "start_dashboard.sh",        META_DIR / "start_dashboard.sh"),
    (REPO_ROOT / "docs" / "paid-traffic-dashboard-template.html",
     META_DIR / "paid-traffic-dashboard-template.html"),
]


def main():
    META_DIR.mkdir(parents=True, exist_ok=True)
    DASH_DIR.mkdir(parents=True, exist_ok=True)

    for src, dst in FILES:
        if not src.exists():
            print(f"❌ Arquivo faltando no repo: {src}")
            sys.exit(1)
        shutil.copy2(src, dst)
        if dst.suffix in (".py", ".sh"):
            dst.chmod(0o755)
        print(f"✅ {dst.name}")

    print("\n🎨 Gerando HTMLs do dashboard...")
    result = subprocess.run(
        [sys.executable, str(META_DIR / "paid_traffic_dashboard.py")],
        capture_output=True,
        text=True,
    )
    print(result.stdout)
    if result.returncode != 0:
        print(f"⚠️  Geração falhou: {result.stderr}")

    print("\n🌐 Iniciando server em background (localhost:8888)...")
    subprocess.Popen(
        ["bash", str(META_DIR / "start_dashboard.sh")],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    url = "http://localhost:8888/paid-traffic-dashboard-7d.html"
    print(f"📊 Abrindo {url}")
    try:
        webbrowser.open(url)
    except Exception:
        pass

    print("\n✅ Dashboard rodando.")
    print("Pronto para a Etapa 6 (criar primeira campanha).")


if __name__ == "__main__":
    main()
