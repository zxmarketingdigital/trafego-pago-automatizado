#!/usr/bin/env python3
"""
Emissor de eventos server-side para a API de Conversões da Meta.

Configuração (variáveis de ambiente têm prioridade sobre o arquivo):
  ~/.operacao-ia/config/meta.env
  CAPI_PIXEL_ID=
  CAPI_TOKEN=
  CAPI_ENABLED=false
  CAPI_TEST_EVENT_CODE=

O módulo não grava leads nem payloads em disco. E-mail, telefone, nome, país e
external_id são normalizados e hasheados em memória antes do envio.
"""

import hashlib
import json
import os
import re
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Tuple


GRAPH_BASE = "https://graph.facebook.com/v21.0"
META_ENV = Path.home() / ".operacao-ia" / "config" / "meta.env"
CONFIG_KEYS = (
    "CAPI_PIXEL_ID",
    "CAPI_TOKEN",
    "CAPI_ENABLED",
    "CAPI_TEST_EVENT_CODE",
)
USER_AGENT = "trafego-pago-automatizado/capi-events-1.0"


def _read_env_file(path: Path = META_ENV) -> Dict[str, str]:
    """Lê KEY=VALUE sem executar o arquivo como shell."""
    values: Dict[str, str] = {}
    if not path.exists():
        return values
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key not in CONFIG_KEYS:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        values[key] = value
    return values


def load_config(path: Path = META_ENV) -> Dict[str, Any]:
    """Carrega config local; env vars permitem override em deploy/container."""
    values = _read_env_file(path)
    for key in CONFIG_KEYS:
        if key in os.environ:
            values[key] = os.environ[key].strip()
    enabled = values.get("CAPI_ENABLED", "").strip().lower() == "true"
    return {
        "pixel_id": values.get("CAPI_PIXEL_ID", "").strip(),
        "token": values.get("CAPI_TOKEN", "").strip(),
        "enabled": enabled,
        "test_event_code": values.get("CAPI_TEST_EVENT_CODE", "").strip(),
        "config_path": str(path),
    }


def _ts() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _token_preview(token: str) -> str:
    """Mostra no máximo os seis primeiros caracteres, nunca o token inteiro."""
    if not token:
        return "(vazio)"
    if len(token) < 6:
        return "***…"
    return token[:6] + "…"


def _redact(text: Any, token: str = "") -> str:
    """Mascara token literal, Authorization e formatos legados em erros."""
    if text is None:
        return ""
    safe = str(text)
    if token:
        safe = safe.replace(token, _token_preview(token))

    def mask_match(match: re.Match) -> str:
        return match.group(1) + _token_preview(match.group(2))

    safe = re.sub(
        r"(?i)(Authorization\s*:\s*Bearer\s+)([^\s,\"']+)",
        mask_match,
        safe,
    )
    safe = re.sub(r"(?i)(access_token=)([^&\s,\"']+)", mask_match, safe)
    safe = re.sub(
        r'(?i)("access_token"\s*:\s*")([^"]+)',
        mask_match,
        safe,
    )
    return safe


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _norm_email(email: str) -> str:
    return (email or "").strip().lower()


def _norm_phone(phone: str) -> str:
    """Mantém só dígitos e inclui o DDI 55 quando o número é brasileiro."""
    digits = re.sub(r"\D", "", phone or "")
    if not digits:
        return ""
    if digits.startswith("55") and len(digits) >= 12:
        return digits
    if len(digits) in (10, 11):
        return "55" + digits
    return digits


_DDI_COUNTRY = [
    ("55", "br"),
    ("351", "pt"),
    ("44", "gb"),
    ("34", "es"),
    ("39", "it"),
    ("33", "fr"),
    ("49", "de"),
    ("1", "us"),
    ("54", "ar"),
    ("56", "cl"),
    ("57", "co"),
    ("52", "mx"),
    ("598", "uy"),
    ("595", "py"),
    ("591", "bo"),
]


def _infer_country(normalized_phone: str) -> str:
    """Infere o país pelo DDI. O público principal do produto usa BR."""
    if not normalized_phone:
        return "br"
    for ddi, iso in sorted(_DDI_COUNTRY, key=lambda item: -len(item[0])):
        if normalized_phone.startswith(ddi):
            return iso
    return "br"


def _split_name(full_name: str) -> Tuple[str, str]:
    parts = (full_name or "").strip().split()
    if not parts:
        return "", ""
    if len(parts) == 1:
        return parts[0].lower(), ""
    return parts[0].lower(), parts[-1].lower()


def build_user_data(
    email: str = "",
    phone: str = "",
    name: str = "",
    external_id: str = "",
) -> Dict[str, Any]:
    """Monta user_data somente com valores normalizados e SHA-256."""
    user_data: Dict[str, Any] = {}
    normalized_email = _norm_email(email)
    normalized_phone = _norm_phone(phone)
    first_name, last_name = _split_name(name)
    stable_id = (external_id or "").strip().lower() or normalized_email

    if normalized_email:
        user_data["em"] = [_sha256(normalized_email)]
    if normalized_phone:
        user_data["ph"] = [_sha256(normalized_phone)]
    if first_name:
        user_data["fn"] = [_sha256(first_name)]
    if last_name:
        user_data["ln"] = [_sha256(last_name)]
    if stable_id:
        user_data["external_id"] = [_sha256(stable_id)]
    if normalized_phone:
        user_data["country"] = [_sha256(_infer_country(normalized_phone))]
    return user_data


def _safe_event_time(event_time: Optional[int]) -> int:
    now = int(time.time())
    if event_time is None:
        return now
    measured = int(event_time)
    # A Meta rejeita eventos futuros ou antigos demais. Ajustar aqui evita que um
    # relógio ruim derrube o webhook do comprador.
    if measured > now + 60 or measured < now - 7 * 24 * 3600:
        return now
    return measured


def build_event_payload(
    *,
    event_name: str,
    event_id: str,
    email: str = "",
    phone: str = "",
    name: str = "",
    external_id: str = "",
    event_time: Optional[int] = None,
    action_source: str = "website",
    event_source_url: str = "",
    custom_data: Optional[Dict[str, Any]] = None,
    test_event_code: str = "",
) -> Dict[str, Any]:
    """Monta um payload CAPI sem incluir token ou PII em texto puro."""
    event: Dict[str, Any] = {
        "event_name": str(event_name or "").strip(),
        "event_time": _safe_event_time(event_time),
        "action_source": str(action_source or "website"),
        "user_data": build_user_data(email, phone, name, external_id),
    }
    if event_id:
        # Dedup exige o mesmo event_name + event_id no Pixel e no servidor.
        event["event_id"] = str(event_id)
    if event_source_url:
        event["event_source_url"] = str(event_source_url)
    if custom_data:
        event["custom_data"] = dict(custom_data)

    payload: Dict[str, Any] = {"data": [event]}
    if test_event_code:
        payload["test_event_code"] = str(test_event_code)
    return payload


def build_purchase_payload(
    *,
    email: str,
    phone: str,
    name: str,
    value: float,
    currency: str = "BRL",
    transaction_id: str,
    external_id: str = "",
    event_time: Optional[int] = None,
    product_name: str = "",
    event_source_url: str = "",
    test_event_code: str = "",
) -> Dict[str, Any]:
    """Monta Purchase usando transaction_id como event_id de deduplicação."""
    custom_data: Dict[str, Any] = {
        "value": round(float(value or 0), 2),
        "currency": (currency or "BRL").upper(),
        "order_id": str(transaction_id),
    }
    if product_name:
        custom_data["content_name"] = str(product_name)
    return build_event_payload(
        event_name="Purchase",
        event_id=str(transaction_id),
        email=email,
        phone=phone,
        name=name,
        external_id=external_id,
        event_time=event_time,
        event_source_url=event_source_url,
        custom_data=custom_data,
        test_event_code=test_event_code,
    )


def _config_error(config: Dict[str, Any]) -> Optional[str]:
    missing = []
    if not config.get("pixel_id"):
        missing.append("CAPI_PIXEL_ID")
    if not config.get("token"):
        missing.append("CAPI_TOKEN")
    if not missing:
        return None
    names = " e ".join(missing)
    return (
        f"Configuração ausente: {names}. Preencha {config['config_path']} "
        "ou defina a mesma chave como variável de ambiente. Nada foi enviado."
    )


def send_capi_event(
    *,
    event_name: str,
    event_id: str,
    email: str = "",
    phone: str = "",
    name: str = "",
    external_id: str = "",
    event_time: Optional[int] = None,
    action_source: str = "website",
    event_source_url: str = "",
    custom_data: Optional[Dict[str, Any]] = None,
    timeout: int = 15,
) -> Dict[str, Any]:
    """Envia um evento CAPI; em qualquer falha retorna dict e não lança exceção."""
    token = ""
    try:
        config = load_config()
        token = str(config.get("token", ""))
        config_error = _config_error(config)
        if config_error:
            print(f"[{_ts()}] [capi] {config_error}")
            return {"ok": False, "skipped": True, "error": config_error}

        if not config["enabled"]:
            error = (
                f"CAPI desligada: defina CAPI_ENABLED=true em {config['config_path']} "
                "somente depois de alinhar o event_id do Pixel e do servidor. Nada foi enviado."
            )
            print(f"[{_ts()}] [capi] {error}")
            return {"ok": False, "skipped": True, "error": error}

        if not str(config["pixel_id"]).isdigit():
            error = (
                f"CAPI_PIXEL_ID inválido em {config['config_path']}: use somente dígitos. "
                "Nada foi enviado."
            )
            print(f"[{_ts()}] [capi] {error}")
            return {"ok": False, "skipped": True, "error": error}

        if not str(event_name or "").strip():
            error = "event_name está vazio. Nada foi enviado."
            print(f"[{_ts()}] [capi] {error}")
            return {"ok": False, "skipped": True, "error": error}

        if not str(event_id or "").strip():
            error = (
                "event_id está vazio. Nada foi enviado para evitar conversão sem deduplicação."
            )
            print(f"[{_ts()}] [capi] {error}")
            return {"ok": False, "skipped": True, "error": error}

        payload = build_event_payload(
            event_name=event_name,
            event_id=str(event_id),
            email=email,
            phone=phone,
            name=name,
            external_id=external_id,
            event_time=event_time,
            action_source=action_source,
            event_source_url=event_source_url,
            custom_data=custom_data,
            test_event_code=str(config.get("test_event_code", "")),
        )
        if not payload["data"][0]["user_data"]:
            error = (
                "Nenhum dado de correspondência informado. Passe email, phone, name ou "
                "external_id. Nada foi enviado."
            )
            print(f"[{_ts()}] [capi] {error}")
            return {"ok": False, "skipped": True, "error": error}

        # O token fica no header para não aparecer em URL, histórico ou proxy log.
        url = f"{GRAPH_BASE}/{config['pixel_id']}/events"
        request = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "User-Agent": USER_AGENT,
            },
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=timeout) as response:
            status = response.getcode()
            body = json.loads(response.read().decode("utf-8"))

        received = int(body.get("events_received", 0) or 0)
        if received < 1:
            error = "A Meta respondeu sem confirmar events_received. Confira o Events Manager."
            print(f"[{_ts()}] [capi] {error}")
            return {
                "ok": False,
                "status": status,
                "event_id": str(event_id),
                "error": error,
                "response": body,
            }

        print(
            f"[{_ts()}] [capi] {event_name} confirmado pela Meta: "
            f"events_received={received}, event_id={event_id}"
        )
        return {
            "ok": True,
            "status": status,
            "event_id": str(event_id),
            "events_received": received,
            "response": body,
        }
    except urllib.error.HTTPError as exc:
        try:
            body = exc.read().decode("utf-8", errors="replace")
        except Exception:
            body = str(exc)
        error = _redact(f"Graph API HTTP {exc.code}: {body[:500]}", token)
        print(f"[{_ts()}] [capi] FALHA: {error}")
        return {
            "ok": False,
            "status": getattr(exc, "code", 0),
            "event_id": str(event_id),
            "error": error,
        }
    except Exception as exc:
        error = _redact(str(exc), token)
        print(f"[{_ts()}] [capi] FALHA: {error}")
        return {"ok": False, "event_id": str(event_id), "error": error}


def send_capi_purchase(
    *,
    email: str,
    phone: str,
    name: str,
    value: float,
    currency: str = "BRL",
    transaction_id: str,
    external_id: str = "",
    event_time: Optional[int] = None,
    product_name: str = "",
    event_source_url: str = "",
    timeout: int = 15,
) -> Dict[str, Any]:
    """Atalho para Purchase; transaction_id é o event_id dos dois canais."""
    try:
        custom_data: Dict[str, Any] = {
            "value": round(float(value or 0), 2),
            "currency": (currency or "BRL").upper(),
            "order_id": str(transaction_id),
        }
        if product_name:
            custom_data["content_name"] = str(product_name)
        return send_capi_event(
            event_name="Purchase",
            event_id=str(transaction_id),
            email=email,
            phone=phone,
            name=name,
            external_id=external_id,
            event_time=event_time,
            event_source_url=event_source_url,
            custom_data=custom_data,
            timeout=timeout,
        )
    except Exception as exc:
        # O webhook do comprador não pode cair por um valor inesperado no evento.
        error = _redact(str(exc))
        print(f"[{_ts()}] [capi] FALHA ao montar Purchase: {error}")
        return {"ok": False, "event_id": str(transaction_id), "error": error}
