#!/usr/bin/env python3
"""
Setup 6 — Etapa 4: Primeira coleta de métricas
Copia fetch_metrics.py para <projeto>/scripts/meta/ (padrão: ~/.operacao-ia) e dispara a primeira execução.
"""
import json
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))
import tpa_paths  # noqa: E402

_P = tpa_paths.active_paths()
OPERACAO = _P.home
SCRIPT_SRC = REPO_ROOT / "scripts" / "fetch_metrics.py"
SCRIPT_DST = _P.scripts_meta / "fetch_metrics.py"
RUNNER_SRC = REPO_ROOT / "scripts" / "run_fetch.sh"
RUNNER_DST = _P.scripts_meta / "run_fetch.sh"
PERFIL = _P.perfil
DASH_DIR = _P.dashboards


def main():
    tpa_paths.announce(_P)
    if not PERFIL.exists():
        print("❌ Perfil não encontrado. Rode setup_perfil_campanhas.py (Etapa 2) primeiro.")
        sys.exit(1)

    SCRIPT_DST.parent.mkdir(parents=True, exist_ok=True)
    tpa_paths.sync_helper(SCRIPT_DST.parent)  # o script instalado acha o próprio projeto
    shutil.copy2(SCRIPT_SRC, SCRIPT_DST)
    SCRIPT_DST.chmod(0o755)
    print(f"✅ fetch_metrics.py copiado para {SCRIPT_DST}")

    if RUNNER_SRC.exists():
        shutil.copy2(RUNNER_SRC, RUNNER_DST)
        RUNNER_DST.chmod(0o755)
        print(f"✅ run_fetch.sh copiado para {RUNNER_DST}")

    print("\n🔄 Executando primeira coleta...")
    result = subprocess.run(
        [sys.executable, str(SCRIPT_DST), "--check"],
        capture_output=True,
        text=True,
    )
    print(result.stdout)
    if result.returncode != 0:
        print(f"⚠️  --check falhou: {result.stderr}")
        print("Tentando coleta real mesmo assim...")

    result = subprocess.run(
        [sys.executable, str(SCRIPT_DST)],
        capture_output=True,
        text=True,
    )
    print(result.stdout)
    if result.returncode != 0:
        print(f"❌ fetch falhou: {result.stderr}")
        sys.exit(1)

    DASH_DIR.mkdir(parents=True, exist_ok=True)
    perfil = json.loads(PERFIL.read_text())
    windows = perfil.get("windows", [4, 7, 14, 30])

    found = []
    for w in windows:
        f = DASH_DIR / f"paid-traffic-{w}d.json"
        if f.exists() and f.stat().st_size > 0:
            found.append(w)

    if not found:
        print("⚠️  Nenhum JSON gerado. Verifique se MCP Meta está autenticado.")
        sys.exit(1)

    print(f"\n✅ Janelas geradas: {found} dias")
    print("Pronto para a Etapa 5 (dashboard local).")


if __name__ == "__main__":
    main()
