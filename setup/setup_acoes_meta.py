#!/usr/bin/env python3
"""
Instalador opt-in — Ações na Meta com confirmação (pausar/ativar/orçamento e publicar).

Copia meta_acoes.py e meta_publicar.py para <projeto>/scripts/meta/ (padrão: ~/.operacao-ia),
garante o fetch_metrics.py ao lado (eles reaproveitam o cliente da Graph API dele) e confere
o meta.env do projeto sem mostrar nenhum valor. Nada na conta Meta é alterado por este setup.

    python3 setup/setup_acoes_meta.py            (no Windows: python setup/setup_acoes_meta.py)
    python3 setup/setup_acoes_meta.py --testar   (também lista suas campanhas, só leitura)
"""
import argparse
import filecmp
import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_SRC_DIR = REPO_ROOT / "scripts"
sys.path.insert(0, str(SCRIPT_SRC_DIR))
import tpa_paths  # noqa: E402

_P = tpa_paths.active_paths()
SCRIPT_DST_DIR = _P.scripts_meta
META_ENV = _P.meta_env
SCRIPT_NAMES = ("meta_acoes.py", "meta_publicar.py", "fetch_metrics.py")


def _copy_script(name):
    src = SCRIPT_SRC_DIR / name
    dst = SCRIPT_DST_DIR / name
    if not src.is_file():
        raise FileNotFoundError("Arquivo ausente no repositório: %s" % src)
    if dst.is_file() and filecmp.cmp(str(src), str(dst), shallow=False):
        dst.chmod(0o700)
        return False, dst
    shutil.copy2(str(src), str(dst))
    dst.chmod(0o700)
    return True, dst


def _chave_preenchida(chave):
    try:
        texto = tpa_paths.read_text_compat(META_ENV)
    except OSError:
        return False
    for linha in texto.splitlines():
        linha = linha.strip()
        if linha.startswith("export "):
            linha = linha[7:].lstrip()
        if linha.startswith(chave + "="):
            return bool(linha.split("=", 1)[1].strip().strip("'\""))
    return False


def main():
    ap = argparse.ArgumentParser(description="Instala as ações na Meta com confirmação (pausar/ativar/orçamento/publicar)")
    ap.add_argument("--testar", action="store_true", help="lista suas campanhas (só leitura) para provar a conexão")
    args = ap.parse_args()

    tpa_paths.announce(_P)
    SCRIPT_DST_DIR.mkdir(parents=True, exist_ok=True)
    tpa_paths.sync_helper(SCRIPT_DST_DIR)
    try:
        for name in SCRIPT_NAMES:
            mudou, dst = _copy_script(name)
            print("%s %s: %s" % ("✅ Instalado/atualizado" if mudou else "⏭️  Já estava idêntico", name, dst))
    except (OSError, FileNotFoundError) as exc:
        print("❌ Não foi possível instalar os scripts: %s" % exc)
        return 1

    if META_ENV.exists():
        try:
            os.chmod(str(META_ENV), 0o600)
        except OSError:
            pass
    faltando = [c for c in ("META_ACCESS_TOKEN", "META_AD_ACCOUNT_ID") if not _chave_preenchida(c)]
    if faltando:
        print("❌ Falta em %s: %s" % (META_ENV, ", ".join(faltando)))
        print("   Rode: python3 setup/setup_meta_oauth.py --renew   e depois   --set-account act_<id>")
        return 1
    print("✅ Token e conta de anúncios presentes (valores não exibidos).")
    for chave, uso in (("META_PAGE_ID", "publicar anúncios"), ("META_PIXEL_ID", "publicar campanhas de leads/vendas")):
        if not _chave_preenchida(chave):
            print("⚠️  %s vazio em %s: necessário só para %s." % (chave, META_ENV, uso))

    if args.testar:
        print("\n🔎 Lendo suas campanhas (só leitura)…")
        resultado = subprocess.run([sys.executable, str(SCRIPT_DST_DIR / "meta_acoes.py"), "listar"], check=False)
        if resultado.returncode != 0:
            return resultado.returncode

    print(
        "\nPronto. Nada na sua conta foi alterado. Comandos (rode a partir de %s):\n"
        "  python3 meta_acoes.py listar\n"
        "  python3 meta_acoes.py pausar <id> [--confirmar]\n"
        "  python3 meta_acoes.py orcamento <id> <valor> [--confirmar]\n"
        "  python3 meta_publicar.py campanha.json [--confirmar]\n"
        "Sem --confirmar o comando só mostra o plano. No Windows use `python` no lugar de `python3`.\n"
        "Funciona igual no Claude Code e no Codex." % SCRIPT_DST_DIR
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
