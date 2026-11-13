#!/usr/bin/env python3
"""
Setup 6 — Etapa 0: Diagnóstico da Base
Verifica Python/gh (sem exigir nenhum setup anterior), garante config.json mínimo, cria estrutura de pastas, mostra plano das 10 etapas.
"""
import json
import os
import platform
import re
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import tpa_paths  # noqa: E402

_P = tpa_paths.active_paths()
OPERACAO = _P.home
CONFIG = _P.shared_config  # phase_completed é compartilhado entre os projetos

REQUIRED_DIRS = [
    _P.base / "config",
    _P.config_dir,
    _P.scripts_meta,
    _P.dashboards,
    _P.leads,
    _P.logs,
]

ETAPAS = [
    "E0  Boas-vindas + Diagnóstico",
    "E1  Conectar MCP oficial Meta (OAuth)",
    "E2  Questionário: Perfil de Campanhas",
    "E3  Instalar Skills + Agente Orquestrador",
    "E4  Primeira coleta de métricas",
    "E5  Dashboard local (localhost:%d)" % _P.port,
    "E6  Skill: Criar Campanha",
    "E7  Skill: Briefing Criativo",
    "E8  Skills: Analyzer + Budget Optimizer",
    "E9  LaunchAgents (fetch 3x/dia + server)",
    "E10 Auditoria técnica + Finalização",
]


def check_python():
    if sys.version_info < (3, 9):
        print(f"❌ Python 3.9+ requerido. Você tem {sys.version_info.major}.{sys.version_info.minor}")
        return False
    print(f"✅ Python {sys.version_info.major}.{sys.version_info.minor}")
    return True


def check_gh():
    if shutil.which("gh"):
        print("✅ gh CLI instalado")
        return True
    print("⚠️  gh CLI não encontrado (opcional, mas recomendado)")
    return True  # não bloqueia


class ConfigBackupError(OSError):
    """Nao foi possivel guardar copia de seguranca do config; o original NAO foi tocado."""


def backup_config_copy(path):
    """Copia o config para <nome>.bak-<AAAAmmdd-HHMMSS>[-N] (0600), sem sobrescrever backup existente.

    Confere que o destino existe com o mesmo tamanho. Em falha, o original fica intacto
    e levanta ConfigBackupError (so entao o chamador pode recriar o config).
    """
    path = Path(path)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = None
    try:
        n = 0
        while backup is None:
            candidate = path.with_name("%s.bak-%s%s" % (path.name, stamp, "-%d" % n if n else ""))
            try:
                # O_EXCL: a criacao e atomica; se outro processo pegou o nome, tenta o proximo sufixo.
                fd = os.open(str(candidate), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            except FileExistsError:
                n += 1
                continue
            backup = candidate
            with os.fdopen(fd, "wb") as dst, open(str(path), "rb") as src:
                shutil.copyfileobj(src, dst)
            os.chmod(str(backup), 0o600)  # backup nunca herda permissao aberta do original
        if not backup.is_file() or backup.stat().st_size != path.stat().st_size:
            raise OSError("copia de seguranca incompleta")
    except OSError as e:
        try:
            if backup is not None and backup.is_file():
                backup.unlink()
        except OSError:
            pass
        msg = ("Não consegui salvar uma cópia de segurança de %s: %s. "
               "Verifique a permissão da pasta e rode de novo." % (path, e))
        print("❌ " + msg)
        raise ConfigBackupError(msg) from e
    return backup


def parse_phase(value):
    """Interpreta phase_completed de forma tolerante: 5, 5.0, "5", "week5", "semana 5". Invalido = 0."""
    if isinstance(value, bool):
        return 0
    try:
        number = float(value)
    except OverflowError:
        number = float("inf") if value > 0 else 0.0  # inteiro gigante: maior que qualquer fase
    except (TypeError, ValueError):
        achou = re.search(r"\d+(?:\.\d+)?", str(value))
        number = float(achou.group()) if achou else 0
    if number != number or number == float("-inf"):
        return 0
    return number


REPLACE_TENTATIVAS = 5
REPLACE_ESPERA_S = 0.3


def recover_phase(raw):
    """Extrai phase_completed do TEXTO de um config.json corrompido (valor original, ex.: 5 ou "week5").

    Usado antes de recriar o config, para a fase do aluno nao voltar a 0. Nada achado = 0.
    """
    valor = _valor_bruto(r'"phase_completed"', raw)
    return 0 if valor is None else valor


def recover_setup6(raw):
    """Extrai setup6.phase_before do texto bruto (registro do uninstall). None = nao achado."""
    return _valor_bruto(r'"setup6"\s*:\s*\{[^{}]*?"phase_before"', raw)


def _valor_bruto(chave, raw):
    achou = re.search(chave + r'\s*:\s*(?:"((?:[^"\\\n]|\\.){0,500})"|(-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?))', raw or "")
    if not achou:
        return None
    if achou.group(1) is not None:
        try:
            return json.loads('"%s"' % achou.group(1))  # desescapa \u00ed etc.
        except ValueError:
            return achou.group(1)
    numero = float(achou.group(2))
    return int(numero) if numero.is_integer() else numero


def reparo_conservador(raw):
    """Tenta consertar so virgula sobrando antes de } ou ] (fora de strings).

    Devolve o dict completo (todas as chaves, inclusive de outros projetos) ou None.
    """
    saida, em_string, escape, i, n = [], False, False, 0, len(raw or "")
    while i < n:
        c = raw[i]
        if em_string:
            saida.append(c)
            if escape:
                escape = False
            elif c == "\\":
                escape = True
            elif c == '"':
                em_string = False
        elif c == '"':
            em_string = True
            saida.append(c)
        elif c == ",":
            j = i + 1
            while j < n and raw[j] in " \t\r\n":
                j += 1
            if not (j < n and raw[j] in "}]"):
                saida.append(c)
        else:
            saida.append(c)
        i += 1
    try:
        cfg = json.loads("".join(saida))
    except ValueError:
        return None
    return cfg if isinstance(cfg, dict) else None


def fase_ilegivel(raw):
    """True quando o texto tem phase_completed mas nao da para ler o valor (0 legitimo NAO conta)."""
    return '"phase_completed"' in (raw or "") and _valor_bruto(r'"phase_completed"', raw) is None


def minimo_recuperado(raw):
    """Config para substituir um corrompido.

    1o tenta o reparo conservador (preserva todas as chaves). Se nao der, recria o minimo
    com a fase e o registro do uninstall que der para ler do texto.
    """
    reparado = reparo_conservador(raw)
    if reparado is not None:
        print("✅ Consertei o config.json (vírgula sobrando) mantendo todas as configurações.")
        return reparado
    cfg = dict(MINIMO)
    cfg["phase_completed"] = recover_phase(raw)
    before = recover_setup6(raw)
    if before is not None:
        cfg["setup6"] = {"phase_before": before}
    if fase_ilegivel(raw):
        print("⚠️  Não consegui ler a sua fase (phase_completed) no arquivo antigo: ficou 0. "
              "Se ela era maior, confira a cópia de segurança.")
    return cfg


def read_raw_config(path):
    """Texto bruto do config (bytes invalidos viram U+FFFD); vazio se nao der para ler."""
    try:
        return Path(path).read_bytes().decode("utf-8", "replace")
    except OSError:
        return ""


def write_config_atomic(cfg, path=None):
    """Grava o config.json por arquivo temporario no mesmo diretorio + os.replace (0600, nunca truncado)."""
    destino = os.path.realpath(str(path or CONFIG))
    tmp = "%s.tmp-%d" % (destino, os.getpid())
    try:
        try:
            os.unlink(tmp)  # sobra de execucao interrompida
        except FileNotFoundError:
            pass
        with os.fdopen(os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w", encoding="utf-8") as f:
            # ensure_ascii=True: surrogate solto vindo do json.loads nao quebra a gravacao.
            f.write(json.dumps(cfg, indent=2, ensure_ascii=True))
            f.flush()
            os.fsync(f.fileno())
        for tentativa in range(REPLACE_TENTATIVAS):
            try:
                os.replace(tmp, destino)
                break
            except PermissionError:
                # Windows: antivirus/leitor segurando o config.json sem FILE_SHARE_DELETE.
                if tentativa == REPLACE_TENTATIVAS - 1:
                    raise
                time.sleep(REPLACE_ESPERA_S)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


MINIMO = {"phase_completed": 0, "origem": "trafego-pago-automatizado"}


def check_config():
    """Garante um config.json utilizavel. Este setup nao exige nenhum setup anterior.

    - Ausente: cria o minimo (0600).
    - Corrompido: guarda copia em config.json.bak-<timestamp> e recria o minimo,
      mantendo o phase_completed que der para ler do texto original.
    - Valido (instalacao anterior): aproveita como esta, sem alterar.
    """
    try:
        CONFIG.parent.mkdir(parents=True, exist_ok=True)
        if not CONFIG.exists():
            try:
                fd = os.open(str(CONFIG), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            except FileExistsError:
                fd = None  # criado em paralelo por outra execucao: cai na leitura abaixo
            if fd is not None:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    f.write(json.dumps(MINIMO, indent=2, ensure_ascii=False) + "\n")
                print("✅ Primeira instalação — config.json mínimo criado em %s" % CONFIG)
                return True
    except OSError as oe:
        print("❌ Não consegui criar o config.json (%s). Verifique a permissão da pasta %s e rode de novo." % (oe, CONFIG.parent))
        return False
    try:
        texto = tpa_paths.read_text_compat(CONFIG)
    except OSError as oe:
        # leitura bloqueada (ex.: antivirus no Windows) nao e corrupcao: nao toca no arquivo
        print("❌ Não consegui ler o config.json (%s). Feche programas que possam estar com ele aberto e rode de novo." % oe)
        return False
    try:
        cfg = json.loads(texto)
        if not isinstance(cfg, dict):
            raise ValueError("config.json não é um objeto JSON")
    except Exception as e:
        try:
            backup = backup_config_copy(CONFIG)  # ConfigBackupError: original fica intacto
            print("⚠️  config.json inválido (%s) — cópia guardada em %s" % (e, backup.name))
            minimo = minimo_recuperado(texto)  # texto ja lido: nunca reler o .bak (pode estar travado)
            write_config_atomic(minimo)
            print("✅ config.json regravado (phase_completed=%s)" % minimo.get("phase_completed", 0))
            print("   Se você tinha outras configurações nele, elas estão na cópia %s: "
                  "corrija o JSON dela e copie de volta para %s." % (backup.name, CONFIG))
        except ConfigBackupError:
            return False  # mensagem ja impressa; config original intacto
        except OSError as oe:
            print("❌ Não consegui recriar o config.json (%s). O original e a cópia de segurança foram preservados; verifique a permissão/espaço em disco e rode de novo." % oe)
            return False
        return True
    print("✅ Instalação anterior encontrada (phase_completed=%s) — aproveitando o que for válido" % cfg.get("phase_completed", 0))
    return True


def create_dirs():
    for d in REQUIRED_DIRS:
        d.mkdir(parents=True, exist_ok=True)
    print(f"✅ Estrutura criada em {OPERACAO}/")


def show_plan():
    print("\n" + "=" * 60)
    print("PLANO DAS 10 ETAPAS — Setup 6 Tráfego Pago Meta ADS")
    print("=" * 60)
    for e in ETAPAS:
        print(f"  {e}")
    print("=" * 60)


def main():
    print(f"\n🔍 Diagnóstico inicial — {platform.system()} {platform.release()}\n")
    tpa_paths.announce(_P)
    ok = all([check_python(), check_gh(), check_config()])
    if not ok:
        sys.exit(1)
    create_dirs()
    show_plan()
    print("\n✅ Etapa 0 concluída. Pronto para a Etapa 1 (Conectar MCP Meta).")


if __name__ == "__main__":
    main()
