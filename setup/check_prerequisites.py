#!/usr/bin/env python3
"""
Checagem de pré-requisitos do setup Tráfego Pago Automatizado — somente leitura.

Não cria pasta nem grava configuração: quem prepara a estrutura é a Etapa 0
(`setup/setup_base_s6.py`). Aqui só se confere se o computador tem o que o
setup precisa. Sai 0 quando está tudo pronto e 1 quando falta algo obrigatório.

Uso (da raiz do repositório ou de dentro de setup/):
    python3 setup/check_prerequisites.py
"""
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from setup_base_s6 import check_gh, check_python  # noqa: E402


def check_claude_cli():
    if shutil.which("claude"):
        print("✅ Claude Code instalado")
        return True
    print("❌ Claude Code não encontrado no PATH — instale em https://claude.com/claude-code")
    return False


def main():
    print("Pré-requisitos do setup Tráfego Pago Automatizado\n")
    resultados = [check_python(), check_gh(), check_claude_cli()]
    print()
    if all(resultados):
        print("Tudo pronto. Pode seguir com: python3 setup/setup_base_s6.py")
        return 0
    print("Corrija os itens marcados com ❌ antes de continuar.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
