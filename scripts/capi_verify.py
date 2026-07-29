#!/usr/bin/env python3
"""
Prova ao vivo do tracking Pixel + CAPI no dataset Meta.

Uso:
  python3 capi_verify.py [--hours N] [--json]

SERVER em /stats?aggregation=event_source é a evidência objetiva de CAPI.
last_fired_time mede qualquer fonte e, sozinho, não prova Pixel de navegador.
"""

import argparse
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from capi_events import GRAPH_BASE, USER_AGENT, _redact, load_config


# Abaixo deste piso, ausência de uma fonte pode ser apenas baixa amostra.
MIN_TRAFFIC_VERDICT = 10
# A agregação `match_keys` do /stats devolve os nomes EXPANDIDOS ("email", "phone"),
# que NÃO são os mesmos nomes das chaves do payload de envio da CAPI ("em", "ph").
# Aceitar só as chaves curtas fazia o verificador esconder justamente os dois sinais
# mais fortes do match — e o comprador concluía que não estava enviando e-mail nem
# telefone quando estava. Por isso mapeamos os dois vocabulários para uma chave canônica.
MATCH_KEY_ALIASES = {
    "em": "em", "email": "em",
    "ph": "ph", "phone": "ph",
    "fn": "fn", "first_name": "fn",
    "ln": "ln", "last_name": "ln",
    "external_id": "external_id",
    "country": "country",
    "ct": "ct", "city": "ct",
    "st": "st", "state": "st",
    "zp": "zp", "zip": "zp",
    "db": "db", "date_of_birth": "db",
    "ge": "ge", "gender": "ge",
}

MATCH_KEY_LABELS = {
    "em": "e-mail",
    "ph": "telefone",
    "fn": "primeiro nome",
    "ln": "sobrenome",
    "external_id": "identificador externo",
    "country": "país",
    "ct": "cidade",
    "st": "estado",
    "zp": "CEP",
    "db": "data de nascimento",
    "ge": "gênero",
}

# Ordem de força do sinal para casar a pessoa (mais forte primeiro). É essa ordem que
# o comprador precisa ver: e-mail e telefone valem muito mais que país.
MATCH_KEY_STRENGTH = [
    "em", "ph", "external_id", "fn", "ln", "ct", "st", "zp", "db", "ge", "country",
]

# Sinais de cookie do navegador. Aparecem na mesma agregação, mas NÃO são dado que a
# CAPI envia — são do Pixel. Reportar junto com os hasheados confundiria o diagnóstico.
BROWSER_SIGNAL_KEYS = {"fr_cookie", "true_fr_cookie", "c_user_cookie", "fbp", "fbc"}


def _parse_utc(value: Any) -> Optional[datetime]:
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, tz=timezone.utc)
    text = str(value).strip()
    if text.isdigit():
        return datetime.fromtimestamp(int(text), tz=timezone.utc)
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    if re.search(r"[+-]\d{4}$", text):
        text = text[:-5] + text[-5:-2] + ":" + text[-2:]
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _graph_get(path: str, params: Dict[str, Any], token: str) -> Dict[str, Any]:
    """GET com token somente no header, nunca na query string."""
    query = urllib.parse.urlencode(params)
    url = f"{GRAPH_BASE}/{path.lstrip('/')}"
    if query:
        url += "?" + query
    request = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "User-Agent": USER_AGENT,
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            body = exc.read().decode("utf-8", errors="replace")
        except Exception:
            body = str(exc)
        raise RuntimeError(
            _redact(f"Graph API HTTP {exc.code}: {body[:500]}", token)
        ) from None
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Falha de rede ao consultar a Graph API: {exc.reason}") from None
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Resposta inválida da Graph API: {exc}") from None
    if "error" in payload:
        raise RuntimeError(
            _redact(
                "Graph API recusou a consulta: "
                + json.dumps(payload["error"], ensure_ascii=False),
                token,
            )
        )
    return payload


def _bucket_is_recent(bucket: Dict[str, Any], cutoff: datetime) -> bool:
    start = _parse_utc(bucket.get("start_time"))
    if start is None:
        return False
    return start >= cutoff


def _count_value_rows(
    stats: Dict[str, Any], cutoff: datetime
) -> Tuple[Dict[str, int], int]:
    counts: Dict[str, int] = {}
    buckets = 0
    for bucket in stats.get("data", []):
        if not isinstance(bucket, dict) or not _bucket_is_recent(bucket, cutoff):
            continue
        buckets += 1
        for row in bucket.get("data", []):
            if not isinstance(row, dict):
                continue
            value = row.get("value")
            if value in (None, ""):
                continue
            try:
                count = int(row.get("count", 0) or 0)
            except (TypeError, ValueError):
                count = 0
            key = str(value)
            counts[key] = counts.get(key, 0) + max(0, count)
    return counts, buckets


def _match_key_names(
    stats: Dict[str, Any], cutoff: datetime
) -> Tuple[Dict[str, int], Dict[str, int], int]:
    """Separa os sinais hasheados (PII que a CAPI envia) dos sinais de cookie do Pixel.

    Devolve (chaves_de_match, sinais_de_navegador, buckets). Os counts importam: uma
    chave presente em 1 evento de 200 não é a mesma coisa que presente em todos, e sem
    o número o comprador não tem como saber a diferença.
    """
    raw_counts, buckets = _count_value_rows(stats, cutoff)
    keys: Dict[str, int] = {}
    browser_signals: Dict[str, int] = {}
    for raw_value, count in raw_counts.items():
        # A API pode devolver uma chave só ("email") ou uma combinação ("em,ph").
        for token in re.split(r"[^a-z_]+", raw_value.lower()):
            if not token:
                continue
            if token in BROWSER_SIGNAL_KEYS:
                browser_signals[token] = browser_signals.get(token, 0) + count
                continue
            canon = MATCH_KEY_ALIASES.get(token)
            if canon:
                keys[canon] = keys.get(canon, 0) + count
    return keys, browser_signals, buckets


def _check(name: str, status: str, detail: str, action: str = "") -> Dict[str, str]:
    return {"check": name, "status": status, "detail": detail, "action": action}


def _check_pixel_activity(
    last_fired: Optional[datetime],
    browser: int,
    server: int,
    buckets: int,
    hours: int,
) -> Dict[str, str]:
    total = browser + server
    if last_fired is None:
        return _check(
            "pixel_vivo",
            "ESTIMADO",
            (
                "last_fired_time não foi informado. Isso não prova falha sem volume; "
                f"BROWSER={browser}, SERVER={server}, buckets={buckets}."
            ),
            "Dispare um evento e confira novamente.",
        )
    age_hours = max(
        0.0, (datetime.now(timezone.utc) - last_fired).total_seconds() / 3600
    )
    if age_hours <= hours:
        return _check(
            "pixel_vivo",
            "OK",
            (
                f"last_fired_time recente ({age_hours:.1f}h atrás): o dataset recebeu "
                "algum evento. Atenção: SERVER também atualiza esse horário; esta "
                "checagem não prova o Pixel de navegador."
            ),
        )
    detail = (
        f"last_fired_time está há {age_hours:.1f}h, fora da janela de {hours}h; "
        f"BROWSER={browser}, SERVER={server}."
    )
    if total >= MIN_TRAFFIC_VERDICT:
        detail += " As métricas recentes divergem do timestamp; confirme no Events Manager."
    else:
        detail += " Não há amostra suficiente para declarar falha."
    return _check(
        "pixel_vivo",
        "ESTIMADO",
        detail,
        "Gere tráfego de teste e rode a verificação outra vez.",
    )


def _check_browser(browser: int, server: int, buckets: int) -> Dict[str, str]:
    total = browser + server
    if browser > 0:
        return _check(
            "eventos_browser",
            "OK",
            f"BROWSER={browser} na janela ({buckets} bucket(s)); o Pixel de navegador está chegando.",
        )
    if total >= MIN_TRAFFIC_VERDICT:
        return _check(
            "eventos_browser",
            "FALHA",
            (
                f"BROWSER=0 e SERVER={server} (total={total}). Há tráfego real, mas "
                "nenhum evento do navegador."
            ),
            "Revise o Pixel/fbq da página. Não use last_fired_time como prova isolada.",
        )
    return _check(
        "eventos_browser",
        "ESTIMADO",
        (
            f"BROWSER=0 e SERVER={server} (total={total}), abaixo do piso de "
            f"{MIN_TRAFFIC_VERDICT}; volume insuficiente para declarar falha."
        ),
        "Abra a página com o Pixel ativo, gere tráfego e rode novamente.",
    )


def _check_server(browser: int, server: int, buckets: int) -> Dict[str, str]:
    total = browser + server
    if server > 0:
        return _check(
            "eventos_server_capi",
            "OK",
            (
                f"SERVER={server} na janela ({buckets} bucket(s)). Esta é a prova "
                "objetiva de que a CAPI está entregando."
            ),
        )
    if total >= MIN_TRAFFIC_VERDICT:
        return _check(
            "eventos_server_capi",
            "FALHA",
            (
                f"SERVER=0 e BROWSER={browser} (total={total}). Há tráfego real, mas "
                "nenhum evento server-side."
            ),
            "Valide o token no checkout ou corrija o envio do backend.",
        )
    return _check(
        "eventos_server_capi",
        "ESTIMADO",
        (
            f"SERVER=0 e BROWSER={browser} (total={total}), abaixo do piso de "
            f"{MIN_TRAFFIC_VERDICT}; ainda não há prova suficiente."
        ),
        "Envie um evento de teste/compra e rode novamente.",
    )


def _check_ratio(browser: int, server: int) -> Dict[str, str]:
    total = browser + server
    if browser > 0 and server > 0:
        ratio = server / browser
        status = "OK" if total >= MIN_TRAFFIC_VERDICT else "ESTIMADO"
        suffix = (
            "Há volume para leitura direcional."
            if status == "OK"
            else f"Total={total}, abaixo do piso de {MIN_TRAFFIC_VERDICT}."
        )
        return _check(
            "proporcao_server_browser",
            status,
            (
                f"SERVER/BROWSER={ratio:.2f} ({server}/{browser}). {suffix} Essa "
                "proporção não prova deduplicação: PageView e Purchase podem ter "
                "volumes naturalmente diferentes."
            ),
            "" if status == "OK" else "Repita com mais volume.",
        )
    if total >= MIN_TRAFFIC_VERDICT:
        missing = "SERVER" if server == 0 else "BROWSER"
        return _check(
            "proporcao_server_browser",
            "FALHA",
            f"Não há proporção calculável: {missing}=0 com total={total}.",
            f"Restaure a fonte {missing} antes de confiar na medição.",
        )
    return _check(
        "proporcao_server_browser",
        "ESTIMADO",
        (
            f"Sem proporção confiável: BROWSER={browser}, SERVER={server}, total={total} "
            f"abaixo do piso de {MIN_TRAFFIC_VERDICT}."
        ),
        "Repita com mais volume.",
    )


def _check_conversions(event_counts: Dict[str, int]) -> Dict[str, str]:
    found = {
        name: count
        for name, count in event_counts.items()
        if name.lower() in {"purchase", "lead"} and count > 0
    }
    if found:
        detail = ", ".join(f"{name}={count}" for name, count in sorted(found.items()))
        return _check(
            "eventos_conversao",
            "OK",
            f"Evento(s) de conversão presente(s) na janela: {detail}.",
        )
    measured = sum(event_counts.values())
    return _check(
        "eventos_conversao",
        "ESTIMADO",
        (
            f"Nenhum Purchase/Lead na janela (eventos medidos={measured}). Isso pode "
            "significar apenas que ainda não houve conversão; não é falha."
        ),
        "Faça uma conversão de teste ou confira depois da primeira venda/lead.",
    )


def _check_match_quality(
    match_keys: Dict[str, int],
    total_events: int,
    browser_signals: Optional[Dict[str, int]] = None,
) -> Dict[str, str]:
    browser_signals = browser_signals or {}
    if match_keys:
        # Ordena pela força do sinal, não pela ordem do dicionário: o comprador precisa
        # ver primeiro se e-mail e telefone estão indo, que é o que move o match.
        labels = [
            f"{MATCH_KEY_LABELS[key]} ({key}) em {match_keys[key]} evento(s)"
            for key in MATCH_KEY_STRENGTH
            if key in match_keys
        ]
        fortes = [k for k in ("em", "ph") if k in match_keys]
        if fortes:
            veredito = (
                "Os sinais fortes estão presentes ("
                + " e ".join(MATCH_KEY_LABELS[k] for k in fortes)
                + ")."
            )
            status = "OK"
            acao = ""
        else:
            veredito = (
                "ATENÇÃO: nem e-mail nem telefone apareceram. São os dois sinais que mais "
                "elevam a correspondência — sem eles o Meta tem dificuldade de reconhecer "
                "a mesma pessoa no navegador e no servidor."
            )
            status = "ESTIMADO"
            acao = (
                "Inclua e-mail e telefone no user_data dos eventos server-side "
                "(o capi_events.py já normaliza e aplica SHA-256 nos dois)."
            )
        detalhe = "Sinais de correspondência na janela: " + "; ".join(labels) + ". " + veredito
        if browser_signals:
            total_cookie = sum(browser_signals.values())
            detalhe += (
                f" (Além disso, {total_cookie} sinal(is) de cookie do navegador — "
                f"{', '.join(sorted(browser_signals))} — que vêm do Pixel, não da CAPI.)"
            )
        detalhe += (
            " A Graph API não fornece um score EMQ final confiável; confira a nota em "
            "Gerenciador de Eventos → Qualidade da correspondência."
        )
        return _check("qualidade_correspondencia", status, detalhe, acao)
    return _check(
        "qualidade_correspondencia",
        "ESTIMADO",
        (
            f"Nenhuma match_key apareceu na agregação (eventos medidos={total_events}). "
            "Não foi inventado score de EMQ."
        ),
        (
            "Envie email/telefone/nome/external_id e confira a nota final no "
            "Gerenciador de Eventos."
        ),
    )


def verify(hours: int) -> Dict[str, Any]:
    config = load_config()
    pixel_id = str(config.get("pixel_id", ""))
    token = str(config.get("token", ""))
    missing = []
    if not pixel_id:
        missing.append("CAPI_PIXEL_ID")
    if not token:
        missing.append("CAPI_TOKEN")
    if missing:
        raise RuntimeError(
            "Configuração ausente: "
            + " e ".join(missing)
            + f". Preencha {config['config_path']} ou use variável de ambiente."
        )
    if not pixel_id.isdigit():
        raise RuntimeError(
            f"CAPI_PIXEL_ID inválido em {config['config_path']}: use somente dígitos."
        )

    pixel_data = _graph_get(pixel_id, {"fields": "last_fired_time"}, token)
    source_stats = _graph_get(
        f"{pixel_id}/stats", {"aggregation": "event_source"}, token
    )
    event_stats = _graph_get(f"{pixel_id}/stats", {"aggregation": "event"}, token)
    match_stats = _graph_get(
        f"{pixel_id}/stats", {"aggregation": "match_keys"}, token
    )

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=hours)
    source_counts, source_buckets = _count_value_rows(source_stats, cutoff)
    source_counts = {key.upper(): value for key, value in source_counts.items()}
    event_counts, event_buckets = _count_value_rows(event_stats, cutoff)
    match_keys, browser_signals, match_buckets = _match_key_names(match_stats, cutoff)
    browser = source_counts.get("BROWSER", 0)
    server = source_counts.get("SERVER", 0)
    last_fired = _parse_utc(pixel_data.get("last_fired_time"))

    checks = [
        _check_pixel_activity(
            last_fired, browser, server, source_buckets, hours
        ),
        _check_browser(browser, server, source_buckets),
        _check_server(browser, server, source_buckets),
        _check_ratio(browser, server),
        _check_conversions(event_counts),
        _check_match_quality(match_keys, sum(event_counts.values()), browser_signals),
    ]
    has_failures = any(item["status"] == "FALHA" for item in checks)
    capi_proven = server > 0
    if capi_proven and not has_failures:
        verdict = "CAPI COMPROVADA"
    elif capi_proven:
        verdict = "CAPI COMPROVADA, MAS HÁ OUTRA FALHA DE TRACKING"
    elif has_failures:
        verdict = "FALHA COMPROVADA"
    else:
        verdict = "AINDA INCONCLUSIVO"

    return {
        "verdict": verdict,
        "blocked": has_failures,
        "capi_proven": capi_proven,
        "hours": hours,
        "generated_at": now.isoformat(timespec="seconds"),
        "counts": {
            "browser": browser,
            "server": server,
            "events": event_counts,
            "match_keys": match_keys,
            "source_buckets": source_buckets,
            "event_buckets": event_buckets,
            "match_key_buckets": match_buckets,
        },
        "checks": checks,
        "note": (
            "last_fired_time pode ser atualizado por SERVER. A saúde do Pixel de "
            "navegador depende da contagem BROWSER."
        ),
    }


def _error_result(hours: int, cause: str) -> Dict[str, Any]:
    now = datetime.now(timezone.utc)
    return {
        "verdict": "FALHA NA VERIFICAÇÃO",
        "blocked": True,
        "capi_proven": False,
        "hours": hours,
        "generated_at": now.isoformat(timespec="seconds"),
        "counts": {
            "browser": 0,
            "server": 0,
            "events": {},
            "match_keys": {},
            "source_buckets": 0,
            "event_buckets": 0,
            "match_key_buckets": 0,
        },
        "checks": [
            _check(
                "consulta_graph_api",
                "FALHA",
                cause,
                "Confira CAPI_PIXEL_ID, CAPI_TOKEN, permissões e conexão; rode novamente.",
            )
        ],
        "note": (
            "A consulta falhou de forma fechada; nenhum sucesso foi inferido sem "
            "resposta válida da Graph API."
        ),
    }


def _print_human(result: Dict[str, Any]) -> None:
    icons = {"OK": "✅", "ESTIMADO": "⚠️", "FALHA": "⛔"}
    print(f"\nVERIFICAÇÃO META — janela de {result['hours']}h")
    print("=" * 62)
    for item in result["checks"]:
        print(f"\n{icons[item['status']]} {item['status']} — {item['check']}")
        print(f"   {item['detail']}")
        if item.get("action"):
            print(f"   → Próximo passo: {item['action']}")
    print("\n" + "=" * 62)
    print(f"VEREDITO: {result['verdict']}")
    if "note" in result:
        print("Nota crítica: " + result["note"])


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Prova a entrega Pixel (BROWSER) e CAPI (SERVER) na Meta"
    )
    parser.add_argument(
        "--hours",
        type=int,
        default=24,
        help="janela de análise em horas (default: 24)",
    )
    parser.add_argument("--json", action="store_true", help="saída JSON para máquina")
    args = parser.parse_args()
    if args.hours < 1:
        parser.error("--hours precisa ser maior que zero")

    try:
        result = verify(args.hours)
    except Exception as exc:
        config = load_config()
        result = _error_result(
            args.hours, _redact(str(exc), str(config.get("token", "")))
        )

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        _print_human(result)
    return 2 if result["blocked"] else 0


if __name__ == "__main__":
    sys.exit(main())
