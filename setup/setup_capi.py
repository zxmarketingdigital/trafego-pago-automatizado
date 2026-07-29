#!/usr/bin/env python3
"""
Instalador opt-in do Bônus 1 — Meta CAPI.

Copia os dois scripts para ~/.operacao-ia/scripts/meta/, garante chmod 600 no
meta.env (quando ele existe), valida a configuração e roda a prova ao vivo.
"""

import argparse
import filecmp
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Tuple


REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_SRC_DIR = REPO_ROOT / "scripts"
OPERACAO = Path.home() / ".operacao-ia"
SCRIPT_DST_DIR = OPERACAO / "scripts" / "meta"
META_ENV = OPERACAO / "config" / "meta.env"
SCRIPT_NAMES = ("capi_events.py", "capi_verify.py")


def _copy_script(name: str) -> Tuple[bool, Path]:
    src = SCRIPT_SRC_DIR / name
    dst = SCRIPT_DST_DIR / name
    if not src.is_file():
        raise FileNotFoundError(f"Arquivo do bônus ausente no repositório: {src}")
    if dst.is_file() and filecmp.cmp(src, dst, shallow=False):
        # Mesmo quando não há cópia, restaura a permissão esperada.
        dst.chmod(0o700)
        return False, dst
    shutil.copy2(src, dst)
    dst.chmod(0o700)
    return True, dst


def _load_installed_config():
    sys.path.insert(0, str(SCRIPT_DST_DIR))
    try:
        from capi_events import load_config
    finally:
        sys.path.pop(0)
    return load_config()


def _validate_config() -> Tuple[bool, bool]:
    """Retorna (config_válida, emissão_habilitada), sem expor credenciais."""
    config = _load_installed_config()
    missing = []
    if not config.get("pixel_id"):
        missing.append("CAPI_PIXEL_ID")
    if not config.get("token"):
        missing.append("CAPI_TOKEN")
    if missing:
        print("❌ Configuração CAPI incompleta: " + " e ".join(missing))
        print(f"   Preencha {META_ENV} ou defina a mesma chave no ambiente.")
        print("   Nada foi enviado.")
        return False, bool(config.get("enabled"))
    if not str(config["pixel_id"]).isdigit():
        print(f"❌ CAPI_PIXEL_ID inválido em {META_ENV}: use somente dígitos.")
        print("   Nada foi enviado.")
        return False, bool(config.get("enabled"))
    if any(char.isspace() for char in str(config["token"])):
        print(f"❌ CAPI_TOKEN inválido em {META_ENV}: ele não pode conter espaços.")
        print("   Nada foi enviado.")
        return False, bool(config.get("enabled"))
    print("✅ CAPI_PIXEL_ID e CAPI_TOKEN presentes (token não exibido).")
    if config.get("test_event_code"):
        print("✅ CAPI_TEST_EVENT_CODE presente: envios irão para Eventos de Teste.")
    if not config.get("enabled"):
        print(
            "⚠️  CAPI_ENABLED está false/ausente: o emissor permanece desligado. "
            "O verificador read-only ainda será executado."
        )
    else:
        print("✅ CAPI_ENABLED=true: emissor liberado.")
    return True, bool(config.get("enabled"))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Instala e verifica o Bônus 1 — Meta CAPI"
    )
    parser.add_argument(
        "--hours",
        type=int,
        default=24,
        help="janela da verificação ao vivo (default: 24)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="pede saída JSON ao capi_verify.py",
    )
    args = parser.parse_args()
    if args.hours < 1:
        parser.error("--hours precisa ser maior que zero")

    SCRIPT_DST_DIR.mkdir(parents=True, exist_ok=True)
    installed = []
    unchanged = []
    try:
        for name in SCRIPT_NAMES:
            changed, dst = _copy_script(name)
            (installed if changed else unchanged).append(dst)
    except (OSError, FileNotFoundError) as exc:
        print(f"❌ Não foi possível instalar os scripts: {exc}")
        return 1

    for dst in installed:
        print(f"✅ Instalado/atualizado: {dst}")
    for dst in unchanged:
        print(f"⏭️  Já estava idêntico: {dst}")

    if META_ENV.exists():
        try:
            os.chmod(META_ENV, 0o600)
        except OSError as exc:
            print(f"❌ Não foi possível aplicar chmod 600 em {META_ENV}: {exc}")
            return 1
        print(f"✅ Permissão 600 confirmada em {META_ENV}")

    valid, _enabled = _validate_config()
    if not valid:
        return 1

    print(f"\n🔎 Rodando prova ao vivo das últimas {args.hours}h…")
    command = [
        sys.executable,
        str(SCRIPT_DST_DIR / "capi_verify.py"),
        "--hours",
        str(args.hours),
    ]
    if args.json:
        command.append("--json")
    result = subprocess.run(command, check=False)
    if result.returncode != 0:
        print(
            "\n❌ A instalação terminou, mas a verificação encontrou falha. "
            "Siga o próximo passo mostrado acima e rode este setup novamente."
        )
        return result.returncode
    print(
        "\n✅ Scripts instalados e verificação concluída. "
        "Se o veredito foi ESTIMADO, gere um evento e repita para obter a prova SERVER."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
