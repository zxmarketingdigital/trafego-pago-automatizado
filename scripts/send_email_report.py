#!/usr/bin/env python3
"""Envia por SMTP o relatório compartilhado, sem expor credenciais."""

import argparse
import os
import smtplib
import ssl
import sys
from email.message import EmailMessage
from email.utils import formatdate
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from report_formatter import assemble_report, render_html, render_text


CONFIG_PATH = Path.home() / ".operacao-ia" / "config" / "meta.env"
REQUIRED_KEYS = (
    "REPORT_EMAIL_TO",
    "REPORT_EMAIL_FROM",
    "SMTP_HOST",
    "SMTP_USER",
    "SMTP_PASSWORD",
)


def _read_env_file(path: Path) -> Dict[str, str]:
    values: Dict[str, str] = {}
    if not path.exists():
        return values
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        values[key.strip()] = value
    return values


def _config_value(file_values: Dict[str, str], key: str, default: str = "") -> str:
    # A variável de ambiente permite override temporário sem editar o arquivo.
    return os.environ.get(key, file_values.get(key, default)).strip()


def _parse_bool(value: str, key: str) -> bool:
    normalized = value.strip().lower()
    if normalized in ("1", "true", "yes", "sim", "on"):
        return True
    if normalized in ("0", "false", "no", "não", "nao", "off"):
        return False
    raise ValueError(f"{key} deve ser true ou false")


def load_config() -> Tuple[Optional[Dict[str, object]], List[str]]:
    values = _read_env_file(CONFIG_PATH)
    resolved = {key: _config_value(values, key) for key in REQUIRED_KEYS}
    missing = [key for key in REQUIRED_KEYS if not resolved[key]]
    if missing:
        return None, missing

    port_raw = _config_value(values, "SMTP_PORT", "587")
    window_raw = _config_value(values, "REPORT_WINDOW")
    try:
        port = int(port_raw)
        if not 1 <= port <= 65535:
            raise ValueError
    except ValueError:
        raise ValueError("SMTP_PORT deve ser um número entre 1 e 65535")
    try:
        tls = _parse_bool(_config_value(values, "SMTP_TLS", "true"), "SMTP_TLS")
    except ValueError:
        raise
    window = None
    if window_raw:
        try:
            window = int(window_raw)
            if window < 1:
                raise ValueError
        except ValueError:
            raise ValueError("REPORT_WINDOW deve ser um número inteiro maior que zero")

    return {
        **resolved,
        "SMTP_PORT": port,
        "SMTP_TLS": tls,
        "REPORT_WINDOW": window,
    }, []


def build_message(config: Dict[str, object]) -> EmailMessage:
    report = assemble_report(window=config.get("REPORT_WINDOW"))
    message = EmailMessage()
    message["Subject"] = (
        f"Relatório Meta Ads — {report['window']} dias"
        + (" — DADO DEFASADO" if report.get("stale") else "")
    )
    message["From"] = str(config["REPORT_EMAIL_FROM"])
    message["To"] = str(config["REPORT_EMAIL_TO"])
    message["Date"] = formatdate(localtime=True)
    message.set_content(render_text(report))
    message.add_alternative(render_html(report), subtype="html")
    return message


def send_message(config: Dict[str, object], message: EmailMessage) -> None:
    host = str(config["SMTP_HOST"])
    port = int(config["SMTP_PORT"])
    with smtplib.SMTP(host, port, timeout=30) as smtp:
        smtp.ehlo()
        if config["SMTP_TLS"]:
            smtp.starttls(context=ssl.create_default_context())
            smtp.ehlo()
        smtp.login(str(config["SMTP_USER"]), str(config["SMTP_PASSWORD"]))
        smtp.send_message(message)


def main() -> int:
    parser = argparse.ArgumentParser(description="Envia o relatório Meta por e-mail")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="monta e imprime o e-mail completo sem conectar",
    )
    args = parser.parse_args()

    try:
        config, missing = load_config()
    except (OSError, ValueError) as exc:
        print(f"❌ Configuração de e-mail inválida: {exc}", file=sys.stderr)
        print(f"   Corrija {CONFIG_PATH}. Nada foi enviado.", file=sys.stderr)
        return 2
    if missing:
        print("❌ Configuração de e-mail incompleta. Chaves ausentes:", file=sys.stderr)
        for key in missing:
            print(f"   - {key}", file=sys.stderr)
        print(
            f"   Preencha {CONFIG_PATH} ou defina as chaves no ambiente. "
            "Nada foi enviado.",
            file=sys.stderr,
        )
        return 2

    try:
        message = build_message(config)
    except (OSError, ValueError) as exc:
        print(f"❌ Não foi possível montar o relatório: {exc}", file=sys.stderr)
        return 3

    if args.dry_run:
        print("=== DRY RUN: nenhuma conexão será aberta ===")
        print(message.as_string())
        return 0

    try:
        send_message(config, message)
    except smtplib.SMTPAuthenticationError:
        print("❌ O servidor SMTP recusou a autenticação.", file=sys.stderr)
        print(
            "   Se você usa Gmail, informe uma senha de app em SMTP_PASSWORD; "
            "a senha normal da conta geralmente não funciona.",
            file=sys.stderr,
        )
        print("   A senha configurada não foi exibida.", file=sys.stderr)
        return 4
    except (smtplib.SMTPException, OSError) as exc:
        # SMTP_PASSWORD nunca entra nesta mensagem nem em traceback.
        print(
            f"❌ Falha ao enviar pelo servidor SMTP: {type(exc).__name__}.",
            file=sys.stderr,
        )
        print("   Confira SMTP_HOST, SMTP_PORT, SMTP_TLS e a conexão.", file=sys.stderr)
        return 5

    print("✅ Relatório enviado por e-mail.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
