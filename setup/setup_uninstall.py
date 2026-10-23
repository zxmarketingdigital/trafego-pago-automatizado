#!/usr/bin/env python3
"""
Setup 6 — Uninstall

Remove configs, LaunchAgents, dashboards e (opcional) skills do Setup 6
DO PROJETO VIGENTE (padrão: ~/.operacao-ia; ou o projeto ativo / TPA_PROJECT).
Nunca toca nos outros projetos. Reverte phase_completed 6→5 em config.json
só quando nenhum outro projeto continua configurado.

Uso:
  python3 setup/setup_uninstall.py
  TPA_PROJECT=cliente-silva python3 setup/setup_uninstall.py   # outro projeto
"""
import json
import platform
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import tpa_paths  # noqa: E402

_P = tpa_paths.active_paths()
OPERACAO = _P.home
CONFIG = _P.shared_config  # phase_completed é compartilhado entre os projetos
META_ENV = _P.meta_env
PERFIL = _P.perfil
PROGRESS = _P.progress
META_SCRIPTS = _P.scripts_meta
DASH_DIR = _P.dashboards
LAUNCH = Path.home() / "Library" / "LaunchAgents"
SKILLS_HOME = Path.home() / ".claude" / "skills"

# Labels base dos jobs do produto; o do projeto nomeado leva o nome no sufixo.
BASE_LABELS = [
    "com.zxlab.meta-fetch",
    "com.zxlab.meta-dashboard-server",
    "com.zxlab.meta-report-email",
    "com.zxlab.meta-report-whatsapp",
]
PLISTS = [tpa_paths.label_for(b, _P.name) + ".plist" for b in BASE_LABELS]

SKILLS = [
    "agente-trafego-pago",
    "meta-campaign-launcher",
    "meta-creative-brief",
    "meta-metrics-fetcher",
    "meta-performance-analyzer",
    "meta-budget-optimizer",
]


PENDENCIAS = []  # o que não deu para desfazer: o uninstall não pode dizer "completo" com isso


def remove_path(p, label):
    if p.exists():
        if p.is_dir():
            shutil.rmtree(p)
        else:
            p.unlink()
        print(f"  ✓ {label}: {p}")
    else:
        print(f"  - {label}: já removido")


def _label_loaded(label):
    try:
        res = subprocess.run(["launchctl", "list"], capture_output=True, text=True, timeout=10)
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return True  # sem como confirmar: trata como carregado e não apaga o plist
    if res.returncode != 0:
        return True
    out = res.stdout
    return any(line.split("\t")[-1:] == [label] for line in out.splitlines())


def unload_launchagents():
    if platform.system() != "Darwin":
        print("  - LaunchAgents (não-macOS, pulando)")
        return
    for name in PLISTS:
        dst = LAUNCH / name
        if dst.exists():
            res = subprocess.run(["launchctl", "unload", str(dst)], capture_output=True, text=True)
            if res.returncode != 0 and _label_loaded(dst.stem):
                # descarregar falhou e o job segue ativo: manter o plist para poder tentar de novo
                print(f"  ✗ LaunchAgent {name}: não consegui descarregar ({(res.stderr or '').strip()[:120]}); plist mantido")
                PENDENCIAS.append(f"descarregar o LaunchAgent {dst.stem}: launchctl unload {dst}")
                continue
            dst.unlink()
            print(f"  ✓ LaunchAgent: {name}")
        else:
            print(f"  - LaunchAgent {name}: já removido")


def kill_dashboard_server():
    """Encerra o http.server do dashboard DESTE projeto (porta 8888 no padrão).
    Só mexe em quem está ESCUTANDO a porta e é um http.server: nunca navegador
    com a aba aberta, nunca outro programa que por acaso use a porta."""
    port = _P.port
    try:
        result = subprocess.run(
            ["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-t"], capture_output=True, text=True, timeout=5
        )
        pids = [p for p in result.stdout.strip().split("\n") if p]
        for pid in pids:
            cmd = subprocess.run(["ps", "-o", "command=", "-p", pid], capture_output=True, text=True).stdout
            if "http.server" not in cmd:
                print(f"  ⚠️  :{port} está em uso por outro programa (pid {pid}); não mexi nele")
                continue
            res = subprocess.run(["kill", pid], capture_output=True, text=True)
            if res.returncode == 0:
                print(f"  ✓ Dashboard :{port} encerrado (pid {pid})")
            else:
                print(f"  ✗ Não consegui encerrar o pid {pid}: {(res.stderr or '').strip()[:120]}")
                PENDENCIAS.append(f"encerrar o servidor do dashboard (pid {pid}): kill {pid}")
    except (subprocess.TimeoutExpired, FileNotFoundError):
        print(f"  ⚠️  Não consegui verificar a porta :{port} (lsof indisponível ou lento). "
              "Confirme que nenhum 'http.server' continua escutando nela.")
        PENDENCIAS.append(f"conferir se algum 'http.server' ainda escuta a porta {port}")


def revert_phase():
    if not CONFIG.exists():
        print("  - config.json: não existe")
        return
    try:
        data = json.loads(CONFIG.read_text())
    except Exception as e:
        print(f"  ⚠️  config.json inválido: {e}")
        PENDENCIAS.append(f"conferir {CONFIG}: JSON inválido, phase_completed não foi revertido")
        return
    if tpa_paths.other_projects_configured(_P):
        print("  - phase_completed mantido: outro projeto ainda está configurado")
        return
    if data.get("phase_completed") == 6:
        data["phase_completed"] = 5
        CONFIG.write_text(json.dumps(data, indent=2))
        print("  ✓ phase_completed: 6 → 5")
    else:
        print(f"  - phase_completed já é {data.get('phase_completed')}")


def read_demo_campaign_ids():
    """Lê IDs DEMO de progress.json ANTES do uninstall remover o arquivo."""
    if not PROGRESS.exists():
        return []
    try:
        return json.loads(PROGRESS.read_text()).get("demo_campaign_ids", []) or []
    except Exception:
        return []


def show_demo_campaigns(ids):
    if ids:
        print()
        print("⚠️  Setup criou campanhas DEMO (em PAUSED):")
        for cid in ids:
            print(f"     - {cid}")
        print("   Pause/exclua manualmente no Ads Manager se quiser limpar.")


def main():
    print("=" * 60)
    print("DESINSTALAR Setup 6 — Tráfego Pago Meta ADS")
    print("=" * 60)
    print()
    tpa_paths.announce(_P)
    print("   (só este projeto é afetado; os outros ficam intactos)")
    print()
    print("[A] Manter skills + remover só configs/launchagents (recomendado se vai reinstalar)")
    print("[B] Remover TUDO (skills, configs, launchagents, dashboards, scripts)")
    print("[C] Cancelar")
    print()
    try:
        choice = input("Escolha [A/B/C]: ").strip().upper()
    except (EOFError, KeyboardInterrupt):
        choice = "C"

    if choice not in ("A", "B"):
        print("Cancelado.")
        return 0

    # Cache demo IDs ANTES de remover progress.json
    demo_ids = read_demo_campaign_ids()

    print()
    print("Removendo…")
    print()

    print("LaunchAgents:")
    unload_launchagents()
    kill_dashboard_server()

    if not _P.is_default and tpa_paths.read_pointer(_P.base) == _P.name:
        # o projeto ativo está sendo desinstalado: não deixar o ponteiro apontando para ele
        tpa_paths.set_active(tpa_paths.DEFAULT_NAME, _P.base)
        print(f"  ✓ Projeto ativo voltou para 'default' (o '{_P.name}' foi desinstalado)")

    print("\nConfigs:")
    remove_path(META_ENV, "meta.env")
    remove_path(PERFIL, "meta_perfil.json")
    remove_path(PROGRESS, "setup6_progress.json")

    print("\nScripts:")
    remove_path(META_SCRIPTS, "scripts/meta/")

    print("\nDashboards:")
    if DASH_DIR.exists():
        for f in DASH_DIR.glob("paid-traffic-*"):
            remove_path(f, f.name)
    else:
        print("  - dashboards/: não existe")

    if choice == "B" and tpa_paths.other_projects_configured(_P):
        print("\nSkills: mantidas (outro projeto ainda usa as mesmas skills)")
    elif choice == "B":
        print("\nSkills:")
        for slug in SKILLS:
            remove_path(SKILLS_HOME / slug, f"skill {slug}")
    else:
        print("\nSkills: mantidas (escolha [A])")

    print("\nReverter fase:")
    revert_phase()

    show_demo_campaigns(demo_ids)

    print()
    if PENDENCIAS:
        print("⚠️  Uninstall INCOMPLETO. Falta fazer à mão:")
        for item in PENDENCIAS:
            print(f"   - {item}")
        return 1
    print("✅ Uninstall completo.")
    if choice == "A":
        print("   Pra reinstalar: re-rode o setup do zero (INICIAR SETUP).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
