#!/usr/bin/env python3
"""
Setup 6 — Uninstall

Remove configs, LaunchAgents (no Windows, as tarefas do Agendador), dashboards
e (opcional) skills do Setup 6
DO PROJETO VIGENTE (padrão: ~/.operacao-ia; ou o projeto ativo / TPA_PROJECT).
Nunca toca nos outros projetos. Reverte phase_completed 6→(fase anterior à instalação) em config.json
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

sys.path.insert(0, str(Path(__file__).resolve().parent))
from setup_base_s6 import write_config_atomic  # noqa: E402

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


def unregister_windows_tasks():
    """Remove as 2 tarefas do Agendador DESTE projeto (nome exato; as de outros
    projetos têm outro sufixo e nunca são tocadas). Stop antes encerra o
    serve_dashboard_win.py que a tarefa subiu."""
    names = tpa_paths.win_task_names(_P)
    try:
        present = tpa_paths.win_task_states(names)
    except Exception as e:
        print(f"  ✗ Não consegui listar as tarefas: {e}")
        PENDENCIAS.append(f"remover no Agendador de Tarefas: {', '.join(names)}")
        return
    for name in names:
        if name not in present:
            print(f"  - Tarefa '{name}': já removida")
            continue
        owner, action = tpa_paths.win_task_owner(name, META_SCRIPTS)
        if owner == "absent":
            print(f"  - Tarefa '{name}': já removida")
            continue
        if owner != "mine":
            motivo = f"roda outra instalação ({action[:120]})" if owner == "foreign" else "não consegui conferir de quem é"
            print(f"  ✗ Tarefa '{name}': {motivo}; mantida")
            PENDENCIAS.append(f"conferir a tarefa '{name}' no Agendador de Tarefas: {motivo}")
            continue
        q = tpa_paths.ps_quote(name)
        res = tpa_paths.run_powershell(
            f"$ErrorActionPreference = 'Stop'; Stop-ScheduledTask -TaskName {q}; "
            f"Unregister-ScheduledTask -TaskName {q} -Confirm:$false"
        )
        if res.returncode != 0:
            print(f"  ✗ Tarefa '{name}': não consegui remover ({(res.stderr or res.stdout).strip()[:120]})")
            PENDENCIAS.append(f"remover a tarefa '{name}': Unregister-ScheduledTask -TaskName {q} -Confirm:$false")
            continue
        print(f"  ✓ Tarefa: {name}")


def unload_launchagents():
    if platform.system() == "Windows":
        unregister_windows_tasks()
        return
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


def _is_project_server_win(cmd):
    """Linha de comando é o server deste projeto? serve_dashboard_win.py da pasta do
    projeto (tarefa da Etapa 9) ou `-m http.server --directory <dashboards>` (Etapa 5)."""
    cmd = (cmd or "").lower()
    if str(META_SCRIPTS / "serve_dashboard_win.py").lower() in cmd:
        return True
    return "http.server" in cmd and str(DASH_DIR).lower() in cmd


def _port_owner_pids_win(port):
    """PIDs com socket TCP local na porta e sem endereço remoto (o que escuta). Usa
    netstat em vez de Get-NetTCPConnection, que às vezes não acha o socket LISTEN. Não
    filtra pela coluna de estado (o texto muda com o idioma do Windows): quem decide se
    o processo é encerrado é _is_project_server_win."""
    out = subprocess.run(["netstat", "-ano"], capture_output=True, text=True, errors="replace",
                         timeout=30, check=True).stdout
    pids = set()
    for line in out.splitlines():
        cols = line.split()
        if (len(cols) >= 5 and cols[0].upper() == "TCP" and cols[1].endswith(f":{port}")
                and cols[2].endswith(":0") and cols[-1].isdigit() and cols[-1] != "0"):
            pids.add(cols[-1])
    return sorted(pids, key=int)


def kill_dashboard_server_windows():
    port = _P.port
    try:
        pids = _port_owner_pids_win(port)
        res = tpa_paths.run_powershell(
            "[Console]::OutputEncoding = [Text.Encoding]::UTF8; "
            f"foreach ($id in @({','.join(pids) or '0'})) {{ "
            "$p = Get-CimInstance Win32_Process -Filter \"ProcessId=$id\"; "
            "if ($p) { \"$id|\" + $p.CommandLine } }",
            timeout=30,
        ) if pids else None
    except (subprocess.SubprocessError, OSError):
        print(f"  ⚠️  Não consegui verificar a porta :{port}. "
              "Confirme que nenhum servidor do dashboard continua escutando nela.")
        PENDENCIAS.append(f"conferir se algum servidor do dashboard ainda escuta a porta {port}")
        return
    if res is not None and res.returncode != 0:
        print(f"  ⚠️  Não consegui ler os processos da porta :{port} (pids {', '.join(pids)}).")
        PENDENCIAS.append(f"conferir se algum servidor do dashboard ainda escuta a porta {port}")
        return
    for line in (res.stdout.splitlines() if res else []):
        pid, _, cmd = line.strip().partition("|")
        if not pid.isdigit():
            continue
        if not _is_project_server_win(cmd):
            print(f"  ⚠️  :{port} está em uso por outro programa (pid {pid}); não mexi nele")
            continue
        kill = tpa_paths.run_powershell(f"Stop-Process -Id {pid} -Force -ErrorAction Stop")
        if kill.returncode == 0:
            print(f"  ✓ Dashboard :{port} encerrado (pid {pid})")
        else:
            print(f"  ✗ Não consegui encerrar o pid {pid}: {(kill.stderr or '').strip()[:120]}")
            PENDENCIAS.append(f"encerrar o servidor do dashboard (pid {pid}): Stop-Process -Id {pid}")


def kill_dashboard_server():
    """Encerra o http.server do dashboard DESTE projeto (porta 8888 no padrão).
    Só mexe em quem está ESCUTANDO a porta e é um http.server: nunca navegador
    com a aba aberta, nunca outro programa que por acaso use a porta."""
    if platform.system() == "Windows":
        kill_dashboard_server_windows()
        return
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
        texto = tpa_paths.read_text_compat(CONFIG)
    except OSError as e:
        print(f"  ⚠️  não consegui ler config.json: {e}")
        PENDENCIAS.append(f"conferir {CONFIG}: arquivo em uso, phase_completed não foi revertido (feche o programa que o usa e rode de novo)")
        return
    try:
        data = json.loads(texto)
        if not isinstance(data, dict):
            raise ValueError("config.json não é um objeto JSON")
    except Exception as e:
        print(f"  ⚠️  config.json inválido: {e}")
        PENDENCIAS.append(f"conferir {CONFIG}: JSON inválido, phase_completed não foi revertido")
        return
    if tpa_paths.other_projects_configured(_P):
        print("  - phase_completed mantido: outro projeto ainda está configurado")
        return
    if data.get("phase_completed") == 6:
        # volta para a fase de antes deste setup (gravada na instalação). Sem registro
        # (instalação feita antes deste fix), assume 5: nunca derruba abaixo do que um
        # setup antigo de turma possa conferir.
        setup6 = data.get("setup6")
        before = setup6.get("phase_before", 5) if isinstance(setup6, dict) else 5
        if isinstance(before, bool) or not isinstance(before, (int, float, str)):
            before = 5  # so restaura valor de fase valido (inclui o texto original, ex.: "week5")
        data["phase_completed"] = before
        data.pop("setup6", None)
        try:
            write_config_atomic(data, CONFIG)
        except OSError as e:
            print(f"  ⚠️  não consegui gravar config.json: {e}")
            PENDENCIAS.append(f"conferir {CONFIG}: phase_completed não foi revertido ({e})")
            return
        print(f"  ✓ phase_completed: 6 → {before}")
    else:
        print(f"  - phase_completed já é {data.get('phase_completed')}")


def read_demo_campaign_ids():
    """Lê IDs DEMO de progress.json ANTES do uninstall remover o arquivo."""
    if not PROGRESS.exists():
        return []
    try:
        return json.loads(PROGRESS.read_text(encoding="utf-8")).get("demo_campaign_ids", []) or []
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

    print("Agendador de Tarefas:" if platform.system() == "Windows" else "LaunchAgents:")
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
