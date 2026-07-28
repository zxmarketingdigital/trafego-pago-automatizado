#!/usr/bin/env python3
"""
Setup 6 — Etapa 9: LaunchAgents (macOS)
Instala 2 plists em ~/Library/LaunchAgents e dá launchctl load.
Substitui placeholders {HOME} e {PYTHON} no template.

Detecta conflitos com outros fetchers Meta antes de instalar (evita
duplicar chamadas API com creative-roas-dashboard, meta-capi-refund, etc.).
"""
import json
import platform
import re
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PLIST_SRC = REPO_ROOT / "launchagents"
LAUNCH_DST = Path.home() / "Library" / "LaunchAgents"
PROGRESS = Path.home() / ".operacao-ia" / "config" / "setup6_progress.json"

PLISTS = [
    "com.zxlab.meta-fetch.plist",
    "com.zxlab.meta-dashboard-server.plist",
]

# Identifica meta-fetch entre os PLISTS (excluído quando há conflito)
FETCH_PLIST = "com.zxlab.meta-fetch.plist"

# Whitelist de labels conhecidos como fetchers Meta API. Restritivo —
# evita falso positivo em labels com substring "meta" (ex: metadata helper).
CONFLICT_LABELS = {
    "com.zxlab.creative-roas-dashboard",
    "com.zxlab.meta-capi-refund",
    "com.zxlab.meta-ads-fetch",
    "com.zxlab.fb-ads-fetch",
}
# Padrão extra: labels que claramente são fetchers Meta de outros projetos.
CONFLICT_PATTERN = re.compile(
    r"\.(meta-ads|fb-ads|facebook-ads|meta-fetch|creative-roas)(\b|[._-])",
    re.IGNORECASE,
)
SELF_LABEL_PATTERN = re.compile(r"com\.zxlab\.meta-(fetch|dashboard-server)")


def detect_conflicts():
    """Retorna lista de labels LaunchAgent que são fetchers Meta de outros projetos.

    Match restrito: whitelist de labels conhecidos OU padrão `.meta-ads/.fb-ads/
    .creative-roas/.meta-fetch.`. Não usa substring 'meta' solta — falso
    positivo com `metadata`, `apple.metalkit`, etc.
    """
    try:
        result = subprocess.run(["launchctl", "list"], capture_output=True, text=True, timeout=10)
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return []
    matches = []
    for line in result.stdout.splitlines()[1:]:  # skip header
        parts = line.split()
        if len(parts) < 3:
            continue
        label = parts[2]
        if SELF_LABEL_PATTERN.search(label):
            continue  # ignora os nossos
        if label in CONFLICT_LABELS or CONFLICT_PATTERN.search(label):
            matches.append(label)
    return matches


def update_progress(key, value):
    PROGRESS.parent.mkdir(parents=True, exist_ok=True)
    data = {}
    if PROGRESS.exists():
        try:
            data = json.loads(PROGRESS.read_text())
        except Exception:
            data = {}
    data[key] = value
    PROGRESS.write_text(json.dumps(data, indent=2))


def clear_progress_keys(*keys):
    """Remove keys de setup6_progress.json (no-op se não existirem)."""
    if not PROGRESS.exists():
        return
    try:
        data = json.loads(PROGRESS.read_text())
    except Exception:
        return
    changed = False
    for k in keys:
        if k in data:
            del data[k]
            changed = True
    if changed:
        PROGRESS.write_text(json.dumps(data, indent=2))


def install_plist(name, home, python):
    src = PLIST_SRC / name
    dst = LAUNCH_DST / name
    if not src.exists():
        print(f"❌ Plist faltando: {src}")
        return False
    content = src.read_text().replace("{HOME}", home).replace("{PYTHON}", python)
    dst.write_text(content)
    print(f"✅ {dst.name}")
    subprocess.run(["launchctl", "unload", str(dst)], capture_output=True)
    result = subprocess.run(["launchctl", "load", str(dst)], capture_output=True, text=True)
    if result.returncode != 0:
        print(f"   ⚠️  load retornou: {result.stderr.strip()}")
        return False
    return True


def main():
    if platform.system() != "Darwin":
        print(f"⚠️  LaunchAgents é macOS-only. Você está em {platform.system()}.")
        print("   Pule esta etapa. No Linux/Windows, use cron ou Task Scheduler manualmente.")
        sys.exit(0)

    plists_to_install = list(PLISTS)
    conflicts = detect_conflicts()
    if conflicts:
        print("⚠️  Detectei outros fetchers Meta rodando no seu Mac:")
        for label in conflicts:
            print(f"     - {label}")
        print()
        print("Instalar `com.zxlab.meta-fetch` vai duplicar chamadas Meta API.")
        print()
        print("Opções:")
        print("  [A] Pular fetch (manter apenas dashboard server) — recomendado")
        print("  [B] Instalar mesmo assim (duplica chamadas)")
        print("  [C] Cancelar Etapa 9")
        print()
        try:
            choice = input("Escolha [A/B/C] (default A): ").strip().upper() or "A"
        except (EOFError, KeyboardInterrupt):
            choice = "C"
        if choice == "C":
            print("Etapa 9 cancelada.")
            sys.exit(0)
        if choice == "A":
            plists_to_install = [p for p in PLISTS if p != FETCH_PLIST]
            update_progress("fetch_skipped_reason", f"conflict:{','.join(conflicts)}")
            print(f"   Pulando {FETCH_PLIST}. Outros fetchers continuam rodando.")
        else:
            update_progress("fetch_conflict_acknowledged", ",".join(conflicts))
            # Re-instalando fetch após skip prévio: limpa flag stale.
            clear_progress_keys("fetch_skipped_reason")
    else:
        # Sem conflito → instala tudo. Limpa flag stale de skip prévio.
        clear_progress_keys("fetch_skipped_reason", "fetch_conflict_acknowledged")

    LAUNCH_DST.mkdir(parents=True, exist_ok=True)
    home = str(Path.home())
    python = sys.executable

    for name in plists_to_install:
        install_plist(name, home, python)

    print("\n📋 Validando jobs ativos...")
    result = subprocess.run(["launchctl", "list"], capture_output=True, text=True)
    active = [l for l in result.stdout.splitlines() if "zxlab.meta" in l]
    for line in active:
        print(f"   {line}")

    expected = len(plists_to_install)
    if len(active) >= expected:
        print(f"\n✅ {len(active)} jobs ativos.")
    else:
        print(f"\n⚠️  Esperava {expected}, encontrou {len(active)}. Rode `launchctl list | grep zxlab.meta` manualmente.")

    print("\nPronto para a Etapa 10 (auditoria + finalização).")


if __name__ == "__main__":
    main()
