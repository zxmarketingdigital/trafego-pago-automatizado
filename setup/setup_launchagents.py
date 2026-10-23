#!/usr/bin/env python3
"""
Setup 6 — Etapa 9: LaunchAgents (macOS)
Instala 2 plists em ~/Library/LaunchAgents e dá launchctl load.
Substitui os placeholders {LABEL}, {OPERACAO}, {PORT}, {HOME} e {PYTHON} no template.

Um agendamento POR PROJETO: o projeto padrão mantém os labels históricos
(com.zxlab.meta-fetch ...); um projeto nomeado instala
com.zxlab.meta-fetch.<nome> ... apontando para a pasta e a porta dele.

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
sys.path.insert(0, str(REPO_ROOT / "scripts"))
import tpa_paths  # noqa: E402

_P = tpa_paths.active_paths()
PLIST_SRC = REPO_ROOT / "launchagents"
LAUNCH_DST = Path.home() / "Library" / "LaunchAgents"
PROGRESS = _P.progress

# Templates (nome base) e o plist que cada um vira neste projeto.
BASE_PLISTS = [
    "com.zxlab.meta-fetch.plist",
    "com.zxlab.meta-dashboard-server.plist",
]
PLISTS = [tpa_paths.label_for(b[:-len(".plist")], _P.name) + ".plist" for b in BASE_PLISTS]

# Identifica meta-fetch entre os PLISTS (excluído quando há conflito)
FETCH_PLIST = PLISTS[0]

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
    """Retorna lista de labels LaunchAgent que são fetchers Meta de OUTRAS ferramentas.

    Os jobs deste produto (inclusive os de outros projetos/clientes, com sufixo .<nome>)
    nunca contam como conflito: cada cliente tem a própria conta de anúncios.

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
    """`name` é o arquivo do projeto (com sufixo no projeto nomeado)."""
    base_name = BASE_PLISTS[PLISTS.index(name)]
    src = PLIST_SRC / base_name
    dst = LAUNCH_DST / name
    if not src.exists():
        print(f"❌ Plist faltando: {src}")
        return False
    content = tpa_paths.render_plist(src.read_text(), _P, base_name[:-len(".plist")], python)
    dst.write_text(content)
    print(f"✅ {dst.name}")
    subprocess.run(["launchctl", "unload", str(dst)], capture_output=True)
    result = subprocess.run(["launchctl", "load", str(dst)], capture_output=True, text=True)
    if result.returncode != 0:
        print(f"   ⚠️  load retornou: {result.stderr.strip()}")
        return False
    return True


def main():
    tpa_paths.announce(_P)
    if platform.system() != "Darwin":
        print(f"⚠️  LaunchAgents é macOS-only. Você está em {platform.system()}.")
        print(f"   Pule esta etapa e agende os 2 jobs do projeto '{_P.name}' por cron (Linux ou Windows via WSL2):")
        print()
        for line in tpa_paths.cron_lines(_P):
            print(f"   {line}")
        print()
        print("   (rode 'crontab -e' e cole as 2 linhas acima — um par de linhas POR PROJETO;")
        print("    o marcador '# tpa:<nome>' no fim de cada linha diz de qual projeto ela é).")
        print("   No Windows sem WSL2 não há")
        print("   como agendar automaticamente — os scripts são bash; instale o WSL2")
        print("   ('wsl --install' no PowerShell como admin) e rode o setup dentro dele.")
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
    mine = {n[:-len(".plist")] for n in plists_to_install}
    active = [l for l in result.stdout.splitlines() if l.split() and l.split()[-1] in mine]
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
