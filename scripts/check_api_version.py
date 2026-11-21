#!/usr/bin/env python3
"""
check_api_version.py — checagem semanal da versão da Graph API da Meta.

O que faz (só leitura, 1 chamada barata por projeto):
  1. Descobre a versão da Graph API que os scripts do projeto usam (v21.0, v22.0...).
  2. Chama `GET /<versão>/me?fields=id` com o token do projeto.
  3. Lê os headers e o erro (se houver) da RESPOSTA da Meta:
       - `facebook-api-version`: a versão que a Meta de fato usou para atender a chamada.
         Se for diferente da pedida, a versão pedida já saiu do ar (a Meta atendeu com outra).
       - `Deprecation` / `Sunset` / qualquer header com "deprecat" no nome / `Warning`.
       - mensagem de erro contendo "deprecated".
  4. Grava o resultado em <projeto>/dashboards/api-status.json (o dashboard e os
     relatórios leem esse arquivo) e imprime um resumo claro.

Não existe tabela de datas aqui: a única fonte é o que a própria API responde. Se a Meta
não mandar aviso nenhum, o status é "ok" — isso NÃO é garantia de que a versão não vai
expirar, só de que hoje a API não avisou.

Uso:
  python3 scripts/check_api_version.py                     projeto vigente
  python3 scripts/check_api_version.py --projeto cliente-a um projeto específico
  python3 scripts/check_api_version.py --todos             todos os projetos com token
  python3 scripts/check_api_version.py --agendamento       mostra como agendar toda semana

Código de saída (para cron/agendador): 0 ok · 1 atenção · 2 crítico · 3 não foi possível verificar.
Só biblioteca padrão.
"""
import argparse
import ast
import http.client
import json
import os
import re
import shlex
import sys
import traceback
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

sys.path.insert(0, str(Path(__file__).resolve().parent))
import tpa_paths  # noqa: E402

GRAPH_HOST = "https://graph.facebook.com"
STATUS_FILE = "api-status.json"
VERSION_RE = re.compile(r"graph\.facebook\.com/(v\d+\.\d+)")
HTTP_TIMEOUT = 30  # segundos: chamada única e barata (/me); não é processo longo

# do menos para o mais grave (usado para escolher o pior resultado)
LEVELS = ("ok", "nao_verificado", "erro", "atencao", "critico")
EXIT_CODES = {"ok": 0, "atencao": 1, "critico": 2, "erro": 3, "nao_verificado": 3}

# Só se aplica quando a Meta manda um header `Sunset` com data: quantos dias antes do
# fim já vira "atenção". Ajustável por ZX_TPA_API_AVISO_DIAS; valor inválido volta ao padrão.
AVISO_DIAS_PADRAO = 60


def aviso_dias(env=None):
    raw = (os.environ if env is None else env).get("ZX_TPA_API_AVISO_DIAS", "")
    try:
        value = int(str(raw).strip())
    except ValueError:
        return AVISO_DIAS_PADRAO
    return value if value > 0 else AVISO_DIAS_PADRAO


# ---------------------------------------------------------------- versão em uso
def _read_env(path, key):
    try:
        text = tpa_paths.read_text_compat(path)
    except (OSError, ValueError):  # ValueError cobre arquivo com bytes que não são texto válido
        return ""
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("export "):
            line = line[len("export "):].lstrip()
        if line.startswith(key + "="):
            value = line.split("=", 1)[1].strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]  # dotenv aceita META_ACCESS_TOKEN="valor"
            return value
    return ""


def _version_key(version):
    major, minor = version.lstrip("v").split(".")
    return (int(major), int(minor))


def detect_versions(scripts_dirs):
    """{arquivo: versão} de todo .py que chama a Graph API com versão fixa.
    Só a primeira pasta que existir é usada; se ela não tiver versão fixa (ou não existir),
    devolve {} e a checagem sai como "não verificado": nunca se testa a versão de OUTRA cópia dos scripts."""
    for folder in scripts_dirs:
        folder = Path(folder)
        if not folder.is_dir():
            continue
        found = {}
        for py in sorted(folder.glob("*.py")):
            try:
                versions = _versions_in_code(py.read_text(encoding="utf-8", errors="replace"))
            except OSError:
                continue
            if versions:
                found[py.name] = sorted(versions, key=_version_key)[-1]
        # Para na primeira pasta que existe: se ela não tem versão fixa, o resultado é "não achei"
        # (nunca testar a versão do repo no lugar da que o projeto realmente usa).
        return found
    return {}


def _versions_in_code(text):
    """Versões citadas em código de verdade: ignora comentários e docstrings (uma versão antiga
    mencionada só em documentação não é versão em uso)."""
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        code = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))
        return set(VERSION_RE.findall(code))
    doc_nodes = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            body = getattr(node, "body", None)
            if body and isinstance(body[0], ast.Expr) and isinstance(getattr(body[0], "value", None), ast.Constant):
                doc_nodes.add(id(body[0].value))
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in doc_nodes:
            found.update(VERSION_RE.findall(node.value))
    return found


def pick_version(found):
    """A versão do coletor (fetch_metrics.py) manda; sem ele, a mais alta encontrada."""
    if not found:
        return None
    return found.get("fetch_metrics.py") or sorted(found.values(), key=_version_key)[-1]


# ---------------------------------------------------------------- HTTP
class _NoRedirect(HTTPRedirectHandler):
    """Não segue redirect: o urllib reenviaria o Authorization (o token) para o host do Location."""

    def redirect_request(self, *args, **kwargs):
        return None


def _http_get(url, token, timeout=HTTP_TIMEOUT):
    """GET com Bearer. Devolve (status, headers_em_minusculas, corpo). HTTPError também
    devolve headers/corpo (é nele que a Meta explica a depreciação)."""
    req = Request(url, headers={"Authorization": "Bearer " + token, "User-Agent": "zx-control-trafego-pago/check-api"})
    try:
        with build_opener(_NoRedirect).open(req, timeout=timeout) as resp:
            return resp.status, {k.lower(): v for k, v in resp.headers.items()}, resp.read().decode("utf-8", "replace")
    except HTTPError as exc:
        body = exc.read().decode("utf-8", "replace") if exc.fp else ""
        return exc.code, {k.lower(): v for k, v in exc.headers.items()}, body


# ---------------------------------------------------------------- análise
def _rank(level):
    return LEVELS.index(level)


# Para o código de saída com vários projetos: crítico > não foi possível checar > atenção > ok.
# (Um projeto sem checagem não pode ficar escondido atrás de um aviso de outro.)
_EXIT_ORDER = {"ok": 0, "atencao": 1, "nao_verificado": 2, "erro": 2, "critico": 3}


def _exit_rank(level):
    return _EXIT_ORDER[level]


def analyze_response(requested, status, headers, body, now=None, dias=None):
    """Lê a resposta da Meta e devolve (nível, [mensagens], headers_relevantes).
    Pura: não faz rede nem lê arquivo."""
    now = now or datetime.now(timezone.utc)
    dias = dias if dias is not None else aviso_dias()
    level = "ok"
    msgs = []
    relevant = {}

    def bump(new):
        nonlocal level
        if _exit_rank(new) > _exit_rank(level):
            level = new

    served = (headers.get("facebook-api-version") or "").strip()
    if served:
        relevant["facebook-api-version"] = served
        if served != requested:
            bump("critico")
            msgs.append(
                "A Meta respondeu com a versão %s, mas o sistema pediu %s: a versão pedida já saiu do ar e "
                "a Meta atendeu com outra. Atualize a versão da Graph API nos scripts (veja 'O que fazer')."
                % (served, requested)
            )

    for name, value in sorted(headers.items()):
        if name == "sunset":
            relevant[name] = value
            try:
                when = parsedate_to_datetime(value)
                if when.tzinfo is None:
                    when = when.replace(tzinfo=timezone.utc)
                left = (when - now).days
            except (TypeError, ValueError):
                bump("atencao")
                msgs.append("A Meta enviou o aviso 'Sunset: %s' (data ilegível). Trate como aviso de fim de versão." % value)
                continue
            if left < 0:
                bump("critico")
                msgs.append("A Meta informa que a versão %s encerrou em %s (Sunset)." % (requested, value))
            elif left <= dias:
                bump("atencao")
                msgs.append("A Meta informa que a versão %s encerra em %s (Sunset): faltam %d dias." % (requested, value, left))
            else:
                msgs.append("A Meta informa o fim da versão %s em %s (faltam %d dias)." % (requested, value, left))
        elif "deprecat" in name or name == "warning":
            relevant[name] = value
            bump("atencao")
            msgs.append("A Meta enviou o aviso '%s: %s'." % (name, value))

    error = None
    try:
        parsed = json.loads(body) if body else {}
        error = parsed.get("error") if isinstance(parsed, dict) else None
    except ValueError:
        error = None
    if isinstance(error, dict):
        text = str(error.get("message") or "")
        lowered = text.lower()
        token_error = (status in (401, 403) or error.get("code") == 190) and error.get("code") != 2635
        if token_error:  # token expirado pode citar "no longer": não é versão encerrada
            bump("erro")
            msgs.append("A Meta recusou o token (%s). Renove com: python3 setup/setup_meta_oauth.py --renew" % (text[:120] or status))
        elif "deprecat" in lowered or "no longer" in lowered or error.get("code") == 2635:
            bump("critico")
            msgs.append("A Meta devolveu erro de versão depreciada: %s" % text[:200])
        else:
            bump("erro")
            msgs.append("A Meta devolveu erro %s: %s" % (error.get("code") or status, text[:160]))
    elif status and status >= 300:  # 3xx não é seguido (o token não pode ir para outro host)
        bump("erro")
        msgs.append("A Meta respondeu HTTP %s." % status)

    return level, msgs, relevant


# ---------------------------------------------------------------- checagem de um projeto
def check_project(p, fetcher=None, now=None):
    """Roda a checagem de UM projeto, grava o arquivo de status e devolve o dict gravado."""
    fetcher = fetcher or _http_get
    now = now or datetime.now(timezone.utc)
    found = detect_versions([p.scripts_meta])  # só os scripts que o projeto de fato roda
    version = pick_version(found)
    result = {
        "checked_at": now.astimezone().isoformat(timespec="seconds"),
        "projeto": p.name,
        "versao_em_uso": version,
        "versao_servida": None,
        "status": "nao_verificado",
        "mensagens": [],
        "headers": {},
        "o_que_fazer": "",
    }
    differing = sorted(set(found.values()), key=_version_key)
    if len(differing) > 1:
        result["mensagens"].append(
            "Os scripts usam versões diferentes da Graph API (%s). Deixe todos na mesma." % ", ".join(
                "%s=%s" % (k, v) for k, v in sorted(found.items())
            )
        )

    token = _read_env(p.meta_env, "META_ACCESS_TOKEN")
    if not version:
        result["mensagens"].append(
            "Não encontrei a versão da Graph API nos scripts do projeto (%s). Rode o setup do projeto "
            "(Etapa 4) para instalar os scripts e tente de novo." % p.scripts_meta)
    elif not token:
        result["mensagens"].append(
            "Token Meta ausente em %s. Rode: python3 setup/setup_meta_oauth.py --renew" % p.meta_env
        )
    else:
        # Uma chamada leve por versão distinta em uso: a que a Meta já encerrou não pode ficar escondida
        # atrás da versão do coletor. Divergência entre scripts vale, no mínimo, atenção.
        worst = "ok"
        for v in differing:
            url = "%s/%s/me?fields=id" % (GRAPH_HOST, v)
            prefix = ("[%s] " % v) if len(differing) > 1 else ""
            try:
                status, headers, body = fetcher(url, token)
            except (URLError, OSError, ValueError, http.client.HTTPException) as exc:
                level = "erro"
                result["mensagens"].append(
                    "%sNão consegui falar com a Meta (%s)." % (prefix, str(exc) or exc.__class__.__name__))
            else:
                level, msgs, relevant = analyze_response(v, status, headers, body, now=now)
                result["mensagens"].extend(prefix + m for m in msgs)
                if v == version:
                    result["headers"] = relevant
                    result["versao_servida"] = relevant.get("facebook-api-version")
                if level == "ok" and not msgs and len(differing) == 1:
                    result["mensagens"].append(
                        "A Meta atendeu a versão %s sem nenhum aviso de depreciação." % v
                    )
            if _exit_rank(level) > _exit_rank(worst):
                worst = level
        if len(differing) > 1 and worst == "ok":
            worst = "atencao"
        result["status"] = worst

    if result["status"] in ("atencao", "critico"):
        result["o_que_fazer"] = (
            "Peça ao Claude Code ou ao Codex: \"atualize a versão da Graph API (GRAPH_BASE) em todos os scripts "
            "do projeto para a versão atual da Meta e rode o coletor de novo\". Confira a versão atual em "
            "https://developers.facebook.com/docs/graph-api/changelog"
        )
    elif result["status"] in ("erro", "nao_verificado"):
        result["o_que_fazer"] = "Resolva o item acima e rode a checagem de novo."

    result["gravado_em_disco"] = _write_status(p, result)  # só no retorno: o arquivo já foi escrito
    return result


def _write_status(p, result):
    """True se o arquivo de status foi gravado. Falha de gravação nunca passa em silêncio:
    o dashboard e o relatório leem esse arquivo, então um arquivo velho esconde o problema."""
    try:
        tpa_paths._atomic_write(p.dashboards / STATUS_FILE, json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    except (OSError, UnicodeError) as exc:  # UnicodeError: texto da Meta com caractere inválido
        print("⚠️  Não consegui gravar %s: %s (o dashboard e o relatório vão mostrar o resultado antigo)"
              % (p.dashboards / STATUS_FILE, exc), file=sys.stderr)
        return False
    return True


# ---------------------------------------------------------------- saída
ICONS = {"ok": "✅", "atencao": "🟡", "critico": "🔴", "erro": "⚠️ ", "nao_verificado": "⚪"}
LABELS = {
    "ok": "sem aviso da Meta",
    "atencao": "ATENÇÃO: a Meta avisou sobre a versão",
    "critico": "CRÍTICO: versão fora do ar ou encerrada",
    "erro": "não foi possível confirmar",
    "nao_verificado": "não verificado",
}


def render(result):
    lines = [
        "%s Projeto %s — Graph API %s: %s"
        % (ICONS[result["status"]], result["projeto"], result["versao_em_uso"] or "?", LABELS[result["status"]])
    ]
    lines.extend("   - " + m for m in result["mensagens"])
    if result["o_que_fazer"]:
        lines.append("   O que fazer: " + result["o_que_fazer"])
    return "\n".join(lines)


def schedule_help(p, script_path=None, python=None):
    """Linhas prontas para agendar a checagem toda segunda-feira, nos 3 sistemas."""
    script = str(Path(script_path or __file__).resolve())
    python = python or sys.executable or "python3"
    proj = p.name
    task = "ZXLab Meta API Check" + ("" if p.is_default else " - " + proj)
    cron = "17 9 * * 1 %s %s --projeto %s >> %s 2>&1" % (
        shlex.quote(python),
        shlex.quote(script),
        shlex.quote(proj),
        shlex.quote(str(p.logs / "api-check.cron.log")),
    )
    cron = cron.replace("%", "\\%")
    return [
        "Linux/WSL2 (cron — `crontab -e`, uma linha):",
        "  " + cron,
        "macOS (launchd): veja o modelo em docs/checagem-api-meta.md (StartCalendarInterval Weekday=1).",
        "Windows (Agendador de Tarefas, 1 linha no Prompt de Comando (cmd), sem administrador):",
        '  schtasks /Create /TN "%s" /SC WEEKLY /D MON /ST 09:17 /TR "\\"%s\\" \\"%s\\" --projeto \\"%s\\""'
        % (task, python, script, proj),
    ]


def main(argv=None):
    parser = argparse.ArgumentParser(description="Checa a versão da Graph API da Meta (só leitura)")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--projeto", help="nome do projeto (padrão: o projeto vigente)")
    group.add_argument("--todos", action="store_true", help="todos os projetos que têm token Meta")
    parser.add_argument("--agendamento", action="store_true",
                        help="mostra como agendar a checagem toda semana (use com --projeto para um cliente)")
    parser.add_argument("--json", action="store_true", help="imprime o resultado em JSON")
    args = parser.parse_args(argv)

    if args.projeto:
        os.environ["TPA_PROJECT"] = args.projeto
    if args.agendamento:
        try:
            p = tpa_paths.active_paths()
        except (tpa_paths.TpaError, OSError) as exc:
            print("❌ Não consegui resolver o projeto: %s" % exc, file=sys.stderr)
            return EXIT_CODES["erro"]
        try:
            p.logs.mkdir(parents=True, exist_ok=True)  # o cron redireciona a saída para esta pasta
        except OSError as exc:
            print("❌ Não consegui criar a pasta de logs %s (%s). A linha de agendamento abaixo falharia "
                  "no redirecionamento: corrija a permissão e rode de novo." % (p.logs, exc), file=sys.stderr)
            return EXIT_CODES["erro"]
        print("\n".join(schedule_help(p)))
        return 0

    try:
        if args.todos:
            base = tpa_paths.base_dir()
            projects = [q for _n, q in tpa_paths.list_projects(base) if q.meta_env.exists()]
            if not projects:
                print("Nenhum projeto com token Meta em %s." % base)
                return 3
        else:
            projects = [tpa_paths.active_paths()]
    except (tpa_paths.TpaError, OSError) as exc:
        print("❌ Não consegui resolver o projeto: %s" % exc, file=sys.stderr)
        return EXIT_CODES["erro"]

    worst = "ok"
    unsaved = False
    results = []
    for p in projects:
        try:
            result = check_project(p)
        except Exception as exc:  # um projeto com defeito não pode derrubar os demais nem sair como exit 1 (atenção)
            result = {"projeto": p.name, "versao_em_uso": None, "status": "erro", "gravado_em_disco": False,
                      "mensagens": ["A checagem falhou por um erro inesperado (%s)." % exc.__class__.__name__],
                      "o_que_fazer": "Rode de novo; se persistir, peça ao Claude Code ou ao Codex para investigar."}
            print(traceback.format_exc(), file=sys.stderr)
            result["checked_at"] = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
            result["gravado_em_disco"] = _write_status(p, result)  # o dashboard não pode ficar mostrando o "ok" antigo
        results.append(result)
        unsaved = unsaved or not result.get("gravado_em_disco", True)
        if _exit_rank(result["status"]) > _exit_rank(worst):
            worst = result["status"]
        if not args.json:
            print(render(result))
    if args.json:
        print(json.dumps(results if args.todos else results[0], indent=2, ensure_ascii=False))
    code = EXIT_CODES[worst]
    if unsaved and worst != "critico":
        code = 3
    return code


if __name__ == "__main__":
    sys.exit(main())
