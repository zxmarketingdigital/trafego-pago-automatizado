"""run_fetch_win.py — equivalente Windows do run_fetch.sh (Agendador de Tarefas).

Roda no projeto onde esta cópia mora (tpa_paths.py ao lado): coleta as métricas
(fetch_metrics.py) e regera o HTML do dashboard (paid_traffic_dashboard.py).
Pensado para rodar com `pythonw.exe -X utf8` (sem janela; sem -X utf8 os scripts
gravam os JSON/HTML em cp1252). A saída vai para logs/fetch.log.
"""
import atexit
import datetime
import re
import runpy
import sys
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

_SEGREDO = re.compile(
    r"""((?:access_token|fb_exchange_token|client_secret)(?:\\*['"])?[ \t]*(?:[=:]|%3[Dd])[ \t]*(?:\\*['"])?)[^&\s'",}\\]+"""
)
# Sem \b de propósito: em %3DEAA... ou conta_EAA... não há fronteira de palavra antes do
# token. Mascarar a mais no log é aceitável; vazar não é.
_TOKEN_META = re.compile(r"EAA[A-Za-z0-9]{20,}")
_TOKEN_META_INCOMPLETO = re.compile(r"EAA[A-Za-z0-9]*\Z")


def _mascarar(text):
    return _TOKEN_META.sub("EAA***", _SEGREDO.sub(r"\1***", text))


class _LogMascarado:
    """Log que mascara token em tudo que passa por write()/print(): saída dos scripts,
    código do SystemExit, repr de erro de rede e traceback. A URL da Graph API traz o
    token. Escrita direta em sys.stdout.buffer ou no fileno não passa pela máscara.

    print(a, b) chega em vários write(), e chave e valor podem vir separados por um
    flush. Por isso a máscara roda sempre sobre a linha inteira e só vai para o arquivo
    o que ainda não foi gravado dela."""

    def __init__(self, f):
        self._f = f
        self._linha = ""
        self._gravado = ""

    def write(self, text):
        self._linha += text
        completas, fim, resto = self._linha.rpartition("\n")
        if fim:
            self._linha = completas + fim
            self._emitir()
            self._linha, self._gravado = resto, ""
        return len(text)

    def flush(self):
        """Grava também a linha ainda sem quebra: o Agendador mata a tarefa no tempo
        limite e o atexit não roda, então o que passou por flush já fica no log. Só o
        início de um token Meta espera o resto, porque ainda não dá para mascará-lo."""
        self._emitir(_TOKEN_META_INCOMPLETO)

    def fechar(self):
        self._emitir()

    def _emitir(self, reter=None):
        texto = _mascarar(self._linha)
        if reter:
            texto = reter.sub("", texto)
        novo = texto[len(self._gravado):] if texto.startswith(self._gravado) else texto
        self._gravado = texto
        # Log não pode derrubar a coleta: com disco cheio a linha se perde, mas os
        # scripts seguem e o código de saída continua avisando o Agendador.
        try:
            self._f.write(novo)
            self._f.flush()
        except (OSError, ValueError):
            pass

    def __getattr__(self, name):
        return getattr(self._f, name)


# <projeto>/scripts/meta -> <projeto>/logs; aberto antes de tudo para os erros irem ao log.
# Se o próprio log não abrir (sem permissão em logs/), a tarefa morre aqui com código 1 e o
# Agendador mostra esse código: sem log não há como auditar a coleta, então não seguimos.
log_dir = HERE.parent.parent / "logs"
log_dir.mkdir(parents=True, exist_ok=True)
log = _LogMascarado(open(log_dir / "fetch.log", "a", encoding="utf-8"))
sys.stdout = sys.stderr = log
atexit.register(log.fechar)

print(f"\n[{datetime.datetime.now():%Y-%m-%d %H:%M:%S}] fetch", flush=True)
if not sys.flags.utf8_mode:
    print("⚠️  rodando sem -X utf8: arquivos podem sair em cp1252", flush=True)
try:
    import tpa_paths  # noqa: E402
    print(f"projeto: {tpa_paths.active_paths().home}", flush=True)
except Exception as e:  # noqa: BLE001
    print(f"❌ tpa_paths: {e!r}", flush=True)
    sys.exit(1)
rc = 0
for script in ("fetch_metrics.py", "paid_traffic_dashboard.py"):
    sys.argv = [str(HERE / script)]
    try:
        runpy.run_path(str(HERE / script), run_name="__main__")
    except SystemExit as e:
        if e.code not in (None, 0):
            print(f"❌ {script} saiu com código {e.code}", flush=True)
            rc = 1
            break
    except Exception as e:  # noqa: BLE001
        print(f"❌ {script}: {e!r}", flush=True)
        traceback.print_exc()
        rc = 1
        break
sys.exit(rc)
