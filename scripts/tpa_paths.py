#!/usr/bin/env python3
"""
tpa_paths.py — resolução ÚNICA de pastas do Tráfego Pago Automatizado.

Todo script de setup e de runtime importa este módulo em vez de escrever
`Path.home() / ".operacao-ia"`. Assim "uma conta, um projeto por cliente"
vale em qualquer lugar: config Meta, perfil, dashboards, logs, briefings,
LaunchAgents e cron ficam dentro do projeto do cliente.

Modelo:
  base      = $OPERACAO_IA_HOME  ou  ~/.operacao-ia            (como sempre foi)
  default   = projeto "default" = a pasta base EXATAMENTE como antes
              (quem já instalou e dá `git pull` continua nela, sem migração)
  nomeado   = <base>/tpa-projetos/<nome>/  com config/, scripts/meta/,
              dashboards/, logs/, briefings/, leads/ e projeto.json

Qual projeto está valendo (nesta ordem):
  1. script INSTALADO (…/scripts/meta/tpa_paths.py): o projeto onde ele mora.
     Agendamentos (LaunchAgent/cron) sempre operam no próprio projeto.
  2. variável de ambiente TPA_PROJECT
  3. ponteiro <base>/tpa-projetos/ativo  (gravado por `tpa_projeto.py trocar`)
  4. "default"

`config/config.json` (phase_completed) é compartilhado entre os setups da ZX
e fica SEMPRE na pasta base, em todos os projetos.

Só biblioteca padrão. Python 3.8+.
"""
import json
import os
import re
import socket
import sys
from pathlib import Path

DEFAULT_NAME = "default"
RESERVED_NAMES = {DEFAULT_NAME, "ativo"}
NAME_RE = re.compile(r"[a-z0-9][a-z0-9_-]{0,39}")  # sempre com fullmatch: "$" aceitaria LF no fim
PROJECTS_SUBDIR = "tpa-projetos"
POINTER_NAME = "ativo"
PROJECT_FILE = "projeto.json"
DEFAULT_PORT = 8888
FIRST_NAMED_PORT = 8889
LAST_PORT = 8999
SUBDIRS = ("config", "scripts/meta", "dashboards", "logs", "briefings", "leads")


class TpaError(Exception):
    """Erro de projeto (nome inválido, projeto inexistente, porta, etc.)."""


# ---------------------------------------------------------------- texto (Windows)
def _utf8_stdio():
    """Windows: stdout/stderr redirecionados saem em cp1252 e o primeiro emoji derruba o
    script. Força UTF-8 neles e PYTHONUTF8=1 nos subprocessos (que então gravam UTF-8
    por padrão). macOS/Linux já são UTF-8: nada muda."""
    if os.name != "nt":
        return
    os.environ.setdefault("PYTHONUTF8", "1")
    for stream in (sys.stdout, sys.stderr):  # pythonw: os dois são None
        if stream is not None and hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except (OSError, ValueError):
                pass


_utf8_stdio()


def read_text_compat(path):
    """Lê um arquivo de texto em UTF-8 (com ou sem BOM). meta.env antigo, gravado em
    cp1252 por versões anteriores no Windows, cai no fallback em vez de quebrar."""
    data = Path(path).read_bytes()
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("cp1252", errors="replace")


# ---------------------------------------------------------------- bases
def base_dir(env=None):
    """Pasta base: $OPERACAO_IA_HOME ou ~/.operacao-ia."""
    env = os.environ if env is None else env
    raw = (env.get("OPERACAO_IA_HOME") or "").strip()
    if raw:
        return Path(os.path.abspath(os.path.expanduser(raw)))  # absoluto: cron/launchd não herdam o cwd
    return Path.home() / ".operacao-ia"


def projects_dir(base):
    return Path(base) / PROJECTS_SUBDIR


def validate_name(name):
    """Valida e devolve o nome do projeto (minúsculo, sem espaço)."""
    if not isinstance(name, str) or not NAME_RE.fullmatch(name):
        raise TpaError(
            "Nome de projeto inválido: %r. Use letras minúsculas, números, "
            "'-' ou '_' (até 40 caracteres, começando por letra ou número). "
            "Exemplo: cliente-silva" % (name,)
        )
    return name


def project_home(name, base):
    """Pasta do projeto. 'default' = a própria base (layout legado)."""
    if name == DEFAULT_NAME:
        return Path(base)
    return projects_dir(base) / validate_name(name)


# ---------------------------------------------------------------- paths
class Paths(object):
    """Todos os caminhos de UM projeto."""

    def __init__(self, name, base):
        self.name = name
        self.base = Path(base)
        self.home = project_home(name, self.base)
        self.config_dir = self.home / "config"
        self.meta_env = self.config_dir / "meta.env"
        self.perfil = self.config_dir / "meta_perfil.json"
        self.progress = self.config_dir / "setup6_progress.json"
        self.shared_config = self.base / "config" / "config.json"
        self.scripts_meta = self.home / "scripts" / "meta"
        self.dashboards = self.home / "dashboards"
        self.logs = self.home / "logs"
        self.briefings = self.home / "briefings"
        self.leads = self.home / "leads"
        self.project_file = self.home / PROJECT_FILE

    @property
    def is_default(self):
        return self.name == DEFAULT_NAME

    @property
    def port(self):
        return dashboard_port(self.name, self.base)

    def __repr__(self):
        return "Paths(name=%r, home=%r)" % (self.name, str(self.home))


def read_project_file(name, base):
    """Lê o projeto.json (dict) ou {} se ausente/ilegível."""
    try:
        data = json.loads(project_home(name, base).joinpath(PROJECT_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def dashboard_port(name, base):
    """Porta do dashboard: 8888 no default; no nomeado, a gravada em projeto.json."""
    if name == DEFAULT_NAME:
        return DEFAULT_PORT
    port = read_project_file(name, base).get("porta")
    if not (isinstance(port, int) and not isinstance(port, bool) and FIRST_NAMED_PORT <= port <= LAST_PORT):
        raise TpaError(
            "Projeto '%s' sem porta de dashboard válida (%d a %d) em %s. Recrie com "
            "`python3 setup/tpa_projeto.py criar %s`."
            % (name, FIRST_NAMED_PORT, LAST_PORT, project_home(name, base) / PROJECT_FILE, name)
        )
    # pasta de projeto copiada à mão leva a porta do original: dois dashboards na mesma porta
    # derrubariam um ao outro, então a duplicata é erro.
    pdir = projects_dir(base)
    if pdir.is_dir():
        for other in sorted(pdir.iterdir()):
            if other.name != name and other.is_dir() and NAME_RE.fullmatch(other.name):
                if read_project_file(other.name, base).get("porta") == port:
                    raise TpaError(
                        "Os projetos '%s' e '%s' usam a mesma porta de dashboard (%d). Corrija o "
                        "projeto.json de um deles (ou recrie com `python3 setup/tpa_projeto.py criar <nome>`)."
                        % (name, other.name, port)
                    )
    return port


# ---------------------------------------------------------------- resolução
def installed_location(file=None):
    """Se este arquivo é uma cópia instalada (…/scripts/meta/tpa_paths.py),
    devolve (nome, base) do projeto onde ele mora; senão None.

    Usa abspath (não resolve): se o próprio arquivo for um link simbólico para o
    repositório, a cópia continua pertencendo à pasta onde o link está."""
    here = Path(os.path.abspath(str(file or __file__)))
    meta = here.parent
    if meta.name != "meta" or meta.parent.name != "scripts":
        return None
    home = meta.parent.parent
    if home.parent.name == PROJECTS_SUBDIR:
        pdir = home.parent
        # Pasta de projetos NOSSA = tem o ponteiro ou algum projeto com projeto.json. Aí
        # qualquer pasta que não seja um projeto válido FALHA (nunca vira o default). Uma
        # base legada que por acaso mora numa pasta chamada tpa-projetos (sem nada disso)
        # continua sendo o projeto padrão.
        ours = (pdir / POINTER_NAME).exists() or any(
            (c / PROJECT_FILE).is_file() for c in pdir.iterdir() if c.is_dir()
        )
        if ours:
            if not NAME_RE.fullmatch(home.name) or home.name in RESERVED_NAMES:
                raise TpaError("A pasta %s não é um nome de projeto válido (minúsculas, números, - e _; "
                               "'default' e 'ativo' são reservados). Renomeie-a." % home)
            if not (home / PROJECT_FILE).is_file():
                raise TpaError("O projeto em %s está sem %s. Recrie-o com "
                               "'python3 setup/tpa_projeto.py criar %s' ou remova a pasta."
                               % (home, PROJECT_FILE, home.name))
            return home.name, pdir.parent
    return DEFAULT_NAME, home


def read_pointer(base):
    """Nome do projeto ativo, ou "" se não há ponteiro. Ponteiro vazio ou ilegível
    é erro (nunca cai em silêncio no default: era assim que o cliente anterior
    seria sobrescrito)."""
    path = projects_dir(base) / POINTER_NAME
    try:
        text = path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return ""
    except OSError as exc:
        raise TpaError("Não consegui ler o projeto ativo em %s (%s). Corrija com: "
                       "python3 setup/tpa_projeto.py trocar <nome>" % (path, exc))
    if not text:
        raise TpaError("O arquivo do projeto ativo está vazio (%s). Corrija com: "
                       "python3 setup/tpa_projeto.py trocar <nome>  |  trocar default" % path)
    return text


def project_exists(name, base):
    if name == DEFAULT_NAME:
        return True
    return project_home(name, base).joinpath(PROJECT_FILE).is_file()


def resolve(env=None, file=None):
    """Devolve Paths do projeto vigente. Levanta TpaError se o projeto pedido
    (env/ponteiro) não existe: nunca cai em silêncio no default, porque era
    exatamente assim que o cliente anterior seria sobrescrito."""
    installed = installed_location(file)
    if installed:
        name, base = installed
        return Paths(name, base)

    env = os.environ if env is None else env
    base = base_dir(env)
    wanted = (env.get("TPA_PROJECT") or "").strip()
    origem = "variável TPA_PROJECT"
    if not wanted:
        wanted = read_pointer(base)
        origem = "projeto ativo (%s)" % (projects_dir(base) / POINTER_NAME)
    if not wanted:
        wanted = DEFAULT_NAME
    if wanted != DEFAULT_NAME:
        validate_name(wanted)
        if not project_exists(wanted, base):
            raise TpaError(
                "O projeto '%s' (%s) não existe. Crie com: "
                "python3 setup/tpa_projeto.py criar %s   |   ou volte ao padrão: "
                "python3 setup/tpa_projeto.py trocar default" % (wanted, origem, wanted)
            )
    return Paths(wanted, base)


def active_paths(env=None, file=None):
    """Como resolve(), mas encerra o script com mensagem clara em caso de erro."""
    try:
        paths = resolve(env, file)
        paths.port  # valida a porta já aqui: erro de projeto aparece uma vez, claro
        wanted = ((os.environ if env is None else env).get("TPA_PROJECT") or "").strip()
        if installed_location(file) and wanted and wanted != paths.name:
            sys.stderr.write(
                "⚠️  TPA_PROJECT=%s ignorada: esta cópia instalada pertence ao projeto '%s' e "
                "sempre trabalha nele.\n" % (wanted, paths.name)
            )
        return paths
    except TpaError as exc:
        sys.exit("❌ %s" % exc)


def active_home():
    return active_paths().home


def announce(p, out=None):
    """Diz em qual projeto o script vai trabalhar (evita configurar o cliente errado)."""
    out = out or sys.stdout
    out.write("📁 Projeto: %s  (%s)\n" % (p.name, p.home))
    if p.is_default:
        others = [n for n, _q in list_projects(p.base) if n != DEFAULT_NAME]
        if others:
            out.write(
                "   Há outros projetos (%s). Este é o projeto padrão; para trabalhar em outro: "
                "python3 setup/tpa_projeto.py trocar <nome>\n" % ", ".join(others)
            )


# ---------------------------------------------------------------- registro
def list_projects(base):
    """[(nome, Paths)] — default primeiro, depois os nomeados em ordem alfabética."""
    out = [(DEFAULT_NAME, Paths(DEFAULT_NAME, base))]
    pdir = projects_dir(base)
    if pdir.is_dir():
        for child in sorted(pdir.iterdir()):
            if (child.is_dir() and (child / PROJECT_FILE).is_file() and NAME_RE.fullmatch(child.name)
                    and child.name not in RESERVED_NAMES):
                out.append((child.name, Paths(child.name, base)))
    return out


def _atomic_write(path, text):
    import tempfile

    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
        os.replace(tmp, str(path))
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def set_active(name, base):
    """Grava o ponteiro do projeto ativo (default = remove o ponteiro)."""
    pointer = projects_dir(base) / POINTER_NAME
    if name == DEFAULT_NAME:
        try:
            pointer.unlink()
        except FileNotFoundError:
            pass
        except OSError as exc:
            raise TpaError("Não consegui remover o projeto ativo (%s): %s" % (pointer, exc))
        return
    validate_name(name)
    if not project_exists(name, base):
        raise TpaError("Projeto '%s' não existe." % name)
    _atomic_write(pointer, name + "\n")


def _port_is_free(port):
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind(("127.0.0.1", port))
        return True
    except OSError:
        return False
    finally:
        sock.close()


def allocate_port(base, port_free=_port_is_free):
    """Próxima porta de dashboard livre (8889..8999), sem repetir a de outro projeto."""
    used = {DEFAULT_PORT}
    for name, _p in list_projects(base):
        if name != DEFAULT_NAME:
            port = read_project_file(name, base).get("porta")
            if not isinstance(port, int):
                raise TpaError(
                    "O projeto.json de '%s' está ilegível ou sem porta (%s). Corrija-o antes de "
                    "criar outro projeto, para não repetir a porta dele." % (name, project_home(name, base) / PROJECT_FILE)
                )
            used.add(port)
    for port in range(FIRST_NAMED_PORT, LAST_PORT + 1):
        if port not in used and port_free(port):
            return port
    raise TpaError("Sem porta livre entre %d e %d para o dashboard." % (FIRST_NAMED_PORT, LAST_PORT))


def create_project(name, base, activate=True, port_free=_port_is_free):
    """Cria o projeto nomeado (pastas + projeto.json). Nunca toca em outro projeto."""
    from datetime import datetime

    validate_name(name)
    if name in RESERVED_NAMES:
        raise TpaError("'%s' é um nome reservado. Escolha outro (ex.: cliente-silva)." % name)
    if project_exists(name, base):
        raise TpaError("O projeto '%s' já existe. Para usá-lo: python3 setup/tpa_projeto.py trocar %s" % (name, name))
    home = project_home(name, base)
    port = allocate_port(base, port_free)  # antes de criar pastas: se falhar, nada fica pela metade
    for sub in SUBDIRS:
        (home / sub).mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(str(home / "config"), 0o700)
    except OSError:
        pass
    data = {
        "nome": name,
        "porta": port,
        "criado_em": datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    _atomic_write(home / PROJECT_FILE, json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    if activate:
        set_active(name, base)
    return Paths(name, base)


def other_projects_configured(p):
    """True se algum OUTRO projeto (default incluído) ainda tem meta.env OU scripts
    instalados (as skills são globais: um irmão no meio da configuração ainda as usa)."""
    return any(q.meta_env.exists() or q.scripts_meta.exists()
               for n, q in list_projects(p.base) if n != p.name)


# ---------------------------------------------------------------- agendamento
def label_for(base_label, name):
    """Label do LaunchAgent: default mantém o nome histórico; nomeado leva sufixo."""
    return base_label if name == DEFAULT_NAME else "%s.%s" % (base_label, name)


WIN_TASK_FETCH = "ZXLab Meta Fetch"
WIN_TASK_DASH = "ZXLab Meta Dashboard"


def win_task_name(base_task, name):
    """Tarefa do Agendador (Windows): default usa o nome base; nomeado leva ' - <nome>'."""
    return base_task if name == DEFAULT_NAME else "%s - %s" % (base_task, name)


def win_task_names(p):
    """(fetch, dashboard) do projeto `p` no Agendador de Tarefas."""
    return win_task_name(WIN_TASK_FETCH, p.name), win_task_name(WIN_TASK_DASH, p.name)


def ps_quote(text):
    # PowerShell aceita ' e as tipográficas U+2018/2019/201A/201B como aspas simples: todas dobram
    return "'" + re.sub("['\u2018\u2019\u201a\u201b]", lambda m: m.group(0) * 2, str(text)) + "'"


def run_powershell(script, timeout=60):
    import subprocess

    return subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", script],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout,
    )


def win_task_owner(name, scripts_dir):
    """De quem é a tarefa `name`: "absent", "mine", "foreign" ou "unknown" (não deu para ler,
    o que nunca conta como desta instalação). Devolve (estado, argumentos da ação)."""
    q = ps_quote(name)
    script = (
        "[Console]::OutputEncoding = [Text.Encoding]::UTF8; "
        "try { 'ACTION:' + (Get-ScheduledTask -TaskName %s -ErrorAction Stop).Actions[0].Arguments } "
        "catch { if ($_.CategoryInfo.Category -eq 'ObjectNotFound') { 'ABSENT' } else { throw } }" % q
    )
    try:
        res = run_powershell(script)
    except Exception:  # noqa: BLE001
        return "unknown", ""
    out = res.stdout.strip() if res.returncode == 0 else ""
    if out == "ABSENT":
        return "absent", ""
    if not out.startswith("ACTION:") or not out[len("ACTION:"):].strip():
        return "unknown", ""
    action = out[len("ACTION:"):].strip()
    mine = os.path.join(str(scripts_dir), "").lower() in action.lower()
    return ("mine" if mine else "foreign"), action


def win_task_states(names):
    """{nome: estado} das tarefas que existem (Ready, Running, Disabled...). Busca pelo
    nome exato: nunca casa com a tarefa de outro projeto. Erro do PowerShell -> TpaError."""
    script = (
        "[Console]::OutputEncoding = [Text.Encoding]::UTF8; "
        # tarefa ausente vira ObjectNotFound: não é erro; qualquer outro erro sai com código != 0
        "foreach ($n in @(%s)) { try { $t = Get-ScheduledTask -TaskName $n -ErrorAction Stop; "
        "$t.TaskName + '|' + $t.State } catch { if ($_.CategoryInfo.Category -ne 'ObjectNotFound') { throw } } }; "
        "exit 0"  # sem isso o erro tratado ainda vira código 1; o throw acima sai antes daqui
        % ",".join(ps_quote(n) for n in names)
    )
    res = run_powershell(script)
    if res.returncode != 0:
        raise TpaError("Get-ScheduledTask falhou: %s" % (res.stderr or res.stdout).strip()[:200])
    states = {}
    for line in res.stdout.splitlines():
        task, _, state = line.strip().rpartition("|")
        if task in names:
            states[task] = state
    return states


def render_plist(template_text, p, base_label, python):
    """Preenche o template de plist para o projeto `p`."""
    from xml.sax.saxutils import escape  # caminho com & < > não pode quebrar o XML do plist

    return (
        template_text.replace("{LABEL}", label_for(base_label, p.name))
        .replace("{OPERACAO}", escape(str(p.home)))
        .replace("{PORT}", str(p.port))
        .replace("{HOME}", escape(str(Path.home())))
        .replace("{PYTHON}", escape(str(python)))
    )


def cron_lines(p):
    """Linhas de cron (Linux/WSL2) do projeto — uma por job, com marcador #tpa:<nome>."""
    import shlex

    # default: linhas idênticas às de sempre (sem marcador); nomeado: marcador do projeto
    tag = "" if p.name == DEFAULT_NAME else " # tpa:%s" % p.name

    def script(nome):
        # cron trata "%" como quebra de linha e separa por espaço: aspas + "\%"
        return shlex.quote(str(p.scripts_meta / nome)).replace("%", "\\%")

    return [
        "5 8,13,19 * * * /bin/bash %s%s" % (script("run_fetch.sh"), tag),
        "@reboot /bin/bash %s%s" % (script("start_dashboard.sh"), tag),
    ]


# ---------------------------------------------------------------- cópia
def sync_helper(dst_dir):
    """Copia este arquivo para a pasta de scripts instalados do projeto, para que
    os scripts instalados achem o próprio projeto. Devolve o caminho de destino."""
    import shutil

    dst_dir = Path(dst_dir)
    dst_dir.mkdir(parents=True, exist_ok=True)
    dst = dst_dir / "tpa_paths.py"
    src = Path(__file__).resolve()
    if dst.is_symlink():
        dst.unlink()  # nunca escrever através de um link (iria sobrescrever o repositório)
    if not dst.exists() or dst.resolve() != src:
        shutil.copy2(str(src), str(dst))
    try:
        os.chmod(str(dst), 0o700)
    except OSError:
        pass
    return dst


def main(argv=None):
    """CLI mínima usada pelos .sh: --home | --port | --name."""
    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) != 1 or argv[0] not in ("--home", "--port", "--name"):
        sys.exit("uso: tpa_paths.py --home | --port | --name")
    p = active_paths()
    if argv[0] == "--home":
        print(p.home)
    elif argv[0] == "--name":
        print(p.name)
    else:
        try:
            print(p.port)
        except TpaError as exc:
            sys.exit("❌ %s" % exc)


if __name__ == "__main__":
    main()
