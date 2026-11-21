#!/usr/bin/env python3
"""
meta_acoes.py — pausar, ativar e ajustar orçamento na Meta, COM CONFIRMAÇÃO.

Até aqui o sistema só recomendava (decide(), plano de budget). Este script aplica,
mas nunca de surpresa:

  python3 meta_acoes.py listar [--nivel campanha|conjunto|anuncio] [--campanha ID] [--status ACTIVE|PAUSED]
  python3 meta_acoes.py pausar  <id> [<id> ...] [--confirmar]
  python3 meta_acoes.py ativar  <id> [<id> ...] [--confirmar]
  python3 meta_acoes.py orcamento <id> <valor diário> [--confirmar]
  python3 meta_acoes.py historico [--ultimas N]
  python3 meta_acoes.py desfazer <id-da-mudança> | --ultima [--confirmar]

Regras:
- SEM --confirmar o comando só mostra o plano (antes → depois) e NÃO altera nada.
- COM --confirmar aplica, lê de volta para provar que a Meta aceitou e grava uma
  linha em <projeto>/logs/meta-acoes.jsonl (auditoria e desfazer).
- Trabalha SEMPRE no projeto vigente (um cliente = um projeto, ver tpa_paths.py) e
  recusa qualquer ID que não pertença à conta de anúncios desse projeto.
- O token vem de <projeto>/config/meta.env e nunca é impresso.

Só biblioteca padrão. Python 3.8+.
"""
import argparse
import http.client
import json
import os
import re
import sys
import uuid
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import tpa_paths

LOG_NAME = "meta-acoes.jsonl"
ID_RE = re.compile(r"[0-9]{5,25}")
NIVEIS = ("campanha", "conjunto", "anuncio")
NIVEL_ROTULO = {"campanha": "CAMPANHA", "conjunto": "CONJUNTO", "anuncio": "ANÚNCIO"}
STATUS_ROTULO = {"ACTIVE": "ATIVA", "PAUSED": "PAUSADA"}

# Moedas SEM centavos na Meta: o orçamento é enviado na unidade da própria moeda.
# Todas as demais usam centavos (valor × 100). O plano sempre imprime o inteiro que
# será enviado, para o aluno conferir antes de confirmar.
MOEDAS_SEM_CENTAVOS = {
    "BIF", "CLP", "DJF", "GNF", "ISK", "JPY", "KMF", "KRW", "PYG", "RWF",
    "UGX", "VND", "VUV", "XAF", "XOF", "XPF",
}
SIMBOLOS = {"BRL": "R$", "USD": "US$", "EUR": "€", "GBP": "£"}

# effective_status de filho cujo pai está pausado: ativar o filho não faz entregar.
PAI_PAUSADO = {"CAMPAIGN_PAUSED": "a campanha", "ADSET_PAUSED": "o conjunto"}


def _env_pos_int(nome, padrao, env=None):
    """Inteiro > 0 vindo do ambiente; ausente, inválido, zero ou negativo cai no padrão."""
    env = os.environ if env is None else env
    try:
        valor = int(str(env.get(nome, "")).strip())
    except ValueError:
        return padrao
    return valor if valor > 0 else padrao


# Teto (segundos) das chamadas de escrita/upload à Meta. Sobrescreva sem editar o
# arquivo: ZX_TPA_HTTP_TIMEOUT=900. O tempo de cada upload é impresso ao terminar.
HTTP_TIMEOUT = _env_pos_int("ZX_TPA_HTTP_TIMEOUT", 600)


class AcaoErro(Exception):
    """Erro esperado (entrada inválida, conta errada, API recusou): mensagem pronta para o aluno."""


class AcaoIncerta(AcaoErro):
    """A etapa PODE ter sido executada na Meta mesmo com a resposta perdida (nunca vira 'nada mudou')."""


# ---------------------------------------------------------------- valores
def parse_valor(texto):
    """'80', '80,50', '1.500,00', 'R$ 80' -> Decimal. Recusa o ambíguo ('1.500')."""
    bruto = str(texto).strip().lower()
    bruto = re.sub(r"^(r\$|us\$|\$|€|£)\s*", "", bruto).strip()
    if not re.fullmatch(r"[0-9][0-9.,]*", bruto):
        raise AcaoErro("Valor inválido: %r. Escreva só o número, por exemplo 80 ou 80,50." % (texto,))
    tipos = {c for c in bruto if c in ".,"}
    frac = ""
    if not tipos:
        inteiro = bruto
    elif len(tipos) == 2:
        pos = max(bruto.rfind("."), bruto.rfind(","))
        dec = bruto[pos]
        mil = "," if dec == "." else "."
        if bruto.count(dec) != 1:
            raise AcaoErro("Valor inválido: %r. Escreva por exemplo 1500 ou 1500,50." % (texto,))
        partes = bruto[:pos].split(mil)
        if not partes[0] or not all(len(p) == 3 for p in partes[1:]):
            raise AcaoErro("Valor inválido: %r. Escreva por exemplo 1500 ou 1500,50." % (texto,))
        inteiro, frac = "".join(partes), bruto[pos + 1:]
    else:
        sep = next(iter(tipos))
        if bruto.count(sep) > 1:
            partes = bruto.split(sep)
            if not all(len(p) == 3 for p in partes[1:]):
                raise AcaoErro("Valor inválido: %r. Escreva por exemplo 1500 ou 1500,50." % (texto,))
            inteiro = "".join(partes)
        else:
            inteiro, frac = bruto.split(sep)
            if len(frac) == 3:
                raise AcaoErro(
                    "O valor %r é ambíguo (1.500 pode ser mil e quinhentos ou um e meio). "
                    "Escreva 1500 ou 1500,00." % (texto,)
                )
            if len(frac) not in (1, 2):
                raise AcaoErro("Valor inválido: %r. Use até 2 casas decimais." % (texto,))
    try:
        valor = Decimal(inteiro + ("." + frac if frac else ""))
    except InvalidOperation:
        raise AcaoErro("Valor inválido: %r." % (texto,))
    if valor <= 0:
        raise AcaoErro("O orçamento diário precisa ser maior que zero.")
    return valor


def fator_moeda(moeda):
    return 1 if (moeda or "").upper() in MOEDAS_SEM_CENTAVOS else 100


def para_unidades_menores(valor, moeda):
    """Decimal na moeda -> inteiro enviado à Meta (centavos, ou a própria unidade)."""
    bruto = valor * fator_moeda(moeda)
    if bruto != bruto.to_integral_value():
        raise AcaoErro("A moeda %s não aceita tantas casas decimais: %s." % (moeda, valor))
    return int(bruto)


def de_unidades_menores(inteiro, moeda):
    return Decimal(int(inteiro)) / fator_moeda(moeda)


def fmt_dinheiro(valor, moeda):
    moeda = (moeda or "BRL").upper()
    sem = moeda in MOEDAS_SEM_CENTAVOS
    quantum = Decimal(1) if sem else Decimal("0.01")
    texto = ("{:,.0f}" if sem else "{:,.2f}").format(Decimal(valor).quantize(quantum))
    texto = texto.replace(",", "§").replace(".", ",").replace("§", ".")
    return "%s %s" % (SIMBOLOS.get(moeda, moeda), texto)


def fmt_status(valor):
    return STATUS_ROTULO.get(str(valor).upper(), str(valor))


# ---------------------------------------------------------------- .env / conta
def ler_env(paths, chave):
    """Valor de CHAVE em <projeto>/config/meta.env (sem executar o arquivo)."""
    try:
        texto = tpa_paths.read_text_compat(paths.meta_env)
    except OSError:
        return ""
    for linha in texto.splitlines():
        linha = linha.strip()
        if linha.startswith("export "):
            linha = linha[7:].lstrip()
        if linha.startswith(chave + "="):
            valor = linha.split("=", 1)[1].strip()
            if len(valor) >= 2 and valor[0] == valor[-1] and valor[0] in ("'", '"'):
                valor = valor[1:-1]
            return valor
    return ""


def normaliza_conta(conta):
    conta = str(conta or "").strip()
    if not conta:
        return ""
    return conta if conta.startswith("act_") else "act_" + conta


def so_digitos_conta(conta):
    return normaliza_conta(conta).replace("act_", "", 1)


def redige(texto, token=""):
    """Nunca deixa token vazar em mensagem de erro."""
    texto = str(texto)
    if token:
        texto = texto.replace(token, "***")
    return re.sub(r"(?i)(access_token=|bearer\s+)[^\s&\"',]+", r"\1***", texto)


def msg_erro(exc):
    """Extrai a mensagem útil de um erro da Graph API ('Graph API 400: {...}')."""
    texto = str(exc)
    achou = re.search(r'"error_user_msg"\s*:\s*"((?:[^"\\]|\\.)*)"', texto) or re.search(
        r'"message"\s*:\s*"((?:[^"\\]|\\.)*)"', texto
    )
    if achou:
        try:
            return json.loads('"%s"' % achou.group(1))
        except ValueError:
            return achou.group(1)
    return texto


# ---------------------------------------------------------------- API
def _fm():
    """fetch_metrics (importado sob demanda): reaproveita GET autenticado e a versão da Graph API."""
    import fetch_metrics

    return fetch_metrics


def _multipart(campos, campo_arquivo=None, arquivo=None):
    """Corpo multipart/form-data. O arquivo é lido por inteiro (o teto vem de MAX_UPLOAD_MB)."""
    fronteira = "----tpa" + uuid.uuid4().hex
    partes = []
    for chave, valor in campos.items():
        partes.append(
            ("--%s\r\nContent-Disposition: form-data; name=\"%s\"\r\n\r\n%s\r\n" % (fronteira, chave, valor)).encode("utf-8")
        )
    if arquivo is not None:
        nome = os.path.basename(str(arquivo)).replace('"', "")
        partes.append(
            (
                "--%s\r\nContent-Disposition: form-data; name=\"%s\"; filename=\"%s\"\r\n"
                "Content-Type: application/octet-stream\r\n\r\n" % (fronteira, campo_arquivo, nome)
            ).encode("utf-8")
        )
        partes.append(Path(arquivo).read_bytes())
        partes.append(b"\r\n")
    partes.append(("--%s--\r\n" % fronteira).encode("utf-8"))
    return b"".join(partes), "multipart/form-data; boundary=%s" % fronteira


class SemResposta(RuntimeError):
    """Falha de rede/timeout DEPOIS de enviar o POST: a Meta pode ter aplicado a mudança."""


class GraphApi(object):
    """GET (reaproveita fetch_metrics.graph_get) e POST na Graph API. O token só vai no header."""

    def __init__(self, token):
        self.token = token

    def get(self, caminho, params=None):
        try:
            return _fm().graph_get(caminho, params or {}, self.token)
        except RuntimeError as exc:
            raise RuntimeError(redige(exc, self.token))
        except (URLError, OSError, http.client.HTTPException, ValueError) as exc:
            raise RuntimeError(redige("Sem resposta da Meta: %s" % exc, self.token))

    def post(self, caminho, params, campo_arquivo=None, arquivo=None):
        base = _fm().GRAPH_BASE
        url = "%s/%s" % (base, str(caminho).lstrip("/"))
        campos = {
            k: (v if isinstance(v, str) else json.dumps(v, ensure_ascii=False))
            for k, v in (params or {}).items()
        }
        if arquivo is not None:
            corpo, tipo = _multipart(campos, campo_arquivo, arquivo)
        else:
            from urllib.parse import urlencode

            corpo, tipo = urlencode(campos).encode("utf-8"), "application/x-www-form-urlencoded"
        req = Request(
            url,
            data=corpo,
            method="POST",
            headers={
                "User-Agent": "zx-control-trafego-pago/acoes",
                "Authorization": "Bearer %s" % self.token,
                "Content-Type": tipo,
            },
        )
        try:
            with urlopen(req, timeout=HTTP_TIMEOUT) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except HTTPError as exc:
            try:
                corpo_erro = exc.read().decode("utf-8", errors="ignore")
            except Exception:  # o corpo do erro também pode se perder (IncompleteRead, timeout)
                corpo_erro = ""
            msg = redige("Graph API %s: %s" % (exc.code, corpo_erro[:600]), self.token)
            if exc.code >= 500:  # o gateway pode ter falhado DEPOIS de a Meta aplicar
                raise SemResposta(msg)
            raise RuntimeError(msg)
        except Exception as exc:  # rede, IncompleteRead, JSON inválido: a Meta pode ter aplicado
            raise SemResposta(redige("Sem resposta da Meta: %s" % exc, self.token))


# ---------------------------------------------------------------- contexto
class Contexto(object):
    def __init__(self, paths, conta, api, token=""):
        self.paths = paths
        self.conta = normaliza_conta(conta)
        self.api = api
        self.token = token
        self._info = None

    @property
    def log_path(self):
        return Path(self.paths.logs) / LOG_NAME

    def info_conta(self):
        """{'name':..., 'currency':...} da conta (uma chamada só)."""
        if self._info is None:
            try:
                self._info = self.api.get(self.conta, {"fields": "name,currency"}) or {}
            except RuntimeError as exc:
                raise AcaoErro("Não consegui ler a conta %s na Meta: %s" % (self.conta, msg_erro(exc)))
        return self._info

    def moeda(self):
        moeda = str(self.info_conta().get("currency") or "").upper()
        if not moeda:
            raise AcaoErro("A Meta não informou a moeda da conta %s; nada foi alterado." % self.conta)
        return moeda

    def cabecalho(self, out=print):
        info = self.info_conta()
        out("📁 Projeto: %s  (%s)" % (self.paths.name, self.paths.home))
        nome = info.get("name") or ""
        out("🏦 Conta: %s%s · moeda %s" % (self.conta, " (%s)" % nome if nome else "", info.get("currency") or "?"))


def montar_contexto(api=None, paths=None):
    paths = paths or tpa_paths.active_paths()
    token = ler_env(paths, "META_ACCESS_TOKEN")  # só do projeto ativo: nunca do ambiente do shell
    conta = ler_env(paths, "META_AD_ACCOUNT_ID")
    if not conta:
        try:
            conta = json.loads(Path(paths.perfil).read_text(encoding="utf-8")).get("ad_account_id", "")
        except (OSError, ValueError):
            conta = ""
    if api is None:
        if not token:
            raise AcaoErro(
                "Sem token da Meta neste projeto (%s). Rode: python3 setup/setup_meta_oauth.py --renew" % paths.meta_env
            )
        api = GraphApi(token)
    if not conta:
        raise AcaoErro(
            "Sem conta de anúncios neste projeto (%s). Rode: python3 setup/setup_meta_oauth.py --set-account act_<id>"
            % paths.meta_env
        )
    return Contexto(paths, conta, api, token)


# ---------------------------------------------------------------- log
def registrar(ctx, entrada):
    """Acrescenta uma linha ao log de auditoria do projeto. Devolve o id da mudança."""
    entrada = dict(entrada)
    entrada.setdefault("mudanca", uuid.uuid4().hex[:8])
    entrada.setdefault("quando", datetime.now().astimezone().isoformat(timespec="seconds"))
    entrada.setdefault("projeto", ctx.paths.name)
    entrada.setdefault("conta", ctx.conta)
    ctx.log_path.parent.mkdir(parents=True, exist_ok=True)
    prefixo = ""
    try:  # fim de linha íntegro: uma escrita interrompida antes não pode colar nesta
        if ctx.log_path.exists() and ctx.log_path.stat().st_size:
            with ctx.log_path.open("rb") as rb:
                rb.seek(-1, os.SEEK_END)
                prefixo = "" if rb.read(1) == b"\n" else "\n"
    except OSError:
        prefixo = ""
    with ctx.log_path.open("a", encoding="utf-8") as fh:
        fh.write(prefixo + json.dumps(entrada, ensure_ascii=False) + "\n")
        fh.flush()
        os.fsync(fh.fileno())
    return entrada["mudanca"]


def registrar_seguro(ctx, entrada, out=print):
    """registrar() que nunca derruba o lote: se o log não grava, imprime o registro na tela.

    Devolve (id da mudança, gravou_ok)."""
    try:
        return registrar(ctx, entrada), True
    except OSError as exc:
        mudanca = "sem-registro"
        out("⚠️  Não consegui gravar o registro em %s (%s). Guarde esta linha para auditar/desfazer:" % (ctx.log_path, exc))
        out("    " + redige(json.dumps(entrada, ensure_ascii=False), ctx.token))
        return mudanca, False


def ler_log(ctx):
    """Linhas válidas do log. Linha corrompida (inclusive bytes UTF-8 quebrados) é ignorada; falha de leitura é erro explícito."""
    if not ctx.log_path.exists():
        return []
    try:
        bruto = ctx.log_path.read_bytes()
    except OSError as exc:
        raise AcaoErro("Não consegui ler o registro %s (%s). Nada foi alterado." % (ctx.log_path, exc))
    linhas = []
    for parte in bruto.split(b"\n"):
        try:
            item = json.loads(parte.decode("utf-8"))
        except ValueError:  # inclui UnicodeDecodeError e JSON inválido
            continue
        if isinstance(item, dict):
            linhas.append(item)
    return linhas


# ---------------------------------------------------------------- entidades
CAMPOS_BASE = "id,name,status,effective_status,account_id"
# Um campo que só existe em cada tipo de objeto: a Graph API recusa campo inexistente,
# e é assim que o script descobre se o ID é de campanha, conjunto ou anúncio.
CAMPOS_NIVEL = {
    "campanha": CAMPOS_BASE + ",daily_budget,lifetime_budget,objective",
    "conjunto": CAMPOS_BASE + ",daily_budget,lifetime_budget,campaign_id,optimization_goal",
    "anuncio": CAMPOS_BASE + ",campaign_id,adset_id",
}


def valida_id(valor):
    valor = str(valor).strip()
    if not ID_RE.fullmatch(valor):
        raise AcaoErro("ID inválido: %r. Use o número do ID mostrado por `listar` (só dígitos)." % (valor,))
    return valor


def busca_entidade(ctx, entidade_id, nivel=None):
    """Lê a entidade na Meta, descobre o nível e garante que é da conta DO PROJETO."""
    entidade_id = valida_id(entidade_id)
    tentativas = [nivel] if nivel else list(NIVEIS)
    ultimo = None
    for tentativa in tentativas:
        try:
            no = ctx.api.get(entidade_id, {"fields": CAMPOS_NIVEL[tentativa]})
        except RuntimeError as exc:
            if "nonexisting field" in str(exc).lower():
                ultimo = exc
                continue
            raise AcaoErro("A Meta recusou a leitura do ID %s: %s" % (entidade_id, msg_erro(exc)))
        no = dict(no or {})
        no["nivel"] = tentativa
        conta_no = str(no.get("account_id") or "")
        if conta_no and conta_no != so_digitos_conta(ctx.conta):
            raise AcaoErro(
                "O ID %s pertence à conta act_%s, e o projeto '%s' usa %s. Nada foi alterado. "
                "Confira se está no projeto do cliente certo (python3 setup/tpa_projeto.py atual)."
                % (entidade_id, conta_no, ctx.paths.name, ctx.conta)
            )
        if not conta_no:
            raise AcaoErro(
                "A Meta não informou a conta do ID %s; por segurança nada foi alterado." % entidade_id
            )
        return no
    if nivel:
        raise AcaoErro("O ID %s não é de um(a) %s." % (entidade_id, nivel))
    raise AcaoErro(
        "Não reconheci o ID %s como campanha, conjunto ou anúncio (%s)." % (entidade_id, msg_erro(ultimo) if ultimo else "?")
    )


def _rotulo(no):
    return "%s %s \"%s\"" % (NIVEL_ROTULO[no["nivel"]], no["id"], no.get("name") or "")


def _orcamento_atual(no):
    bruto = no.get("daily_budget")
    return int(bruto) if str(bruto or "").isdigit() and int(bruto) > 0 else None


# ---------------------------------------------------------------- planos
def planeja_status(ctx, entidade_id, novo, nivel=None):
    no = busca_entidade(ctx, entidade_id, nivel)
    atual = str(no.get("status") or "").upper()
    if atual not in ("ACTIVE", "PAUSED"):
        raise AcaoErro(
            "%s está com status %s e só aceito mexer em ATIVA/PAUSADA. Nada foi alterado." % (_rotulo(no), atual or "?")
        )
    plano = {
        "tipo": "status", "id": no["id"], "nivel": no["nivel"], "nome": no.get("name") or "",
        "campo": "status", "antes": atual, "depois": novo, "avisos": [],
        "noop": atual == novo, "rotulo": _rotulo(no),
    }
    if novo == "ACTIVE" and not plano["noop"]:
        pai = PAI_PAUSADO.get(str(no.get("effective_status") or "").upper())
        if pai and no["nivel"] != "campanha":
            plano["avisos"].append(
                "%s pai está pausado(a): este item ficará ATIVO mas só entrega quando %s também for ativado(a)." % (pai, pai)
            )
        if no["nivel"] != "campanha":
            plano["pais_pausados"] = _pais_pausados(ctx, no)
        gasto = _orcamento_atual(no)
        if gasto:
            plano["avisos"].append(
                "Ativar começa a gastar: orçamento diário atual %s." % fmt_dinheiro(de_unidades_menores(gasto, ctx.moeda()), ctx.moeda())
            )
    return plano


def _pais_pausados(ctx, no):
    """Pais (conjunto/campanha) com status PAUSED. O effective_status de um item que ele próprio está
    PAUSED é 'PAUSED' (nunca 'ADSET_PAUSED'), então o pai precisa ser lido de verdade."""
    achados = []
    for chave, nivel in (("adset_id", "conjunto"), ("campaign_id", "campanha")):
        pai_id = str(no.get(chave) or "")
        if not pai_id or no["nivel"] == nivel:
            continue
        try:
            pai = ctx.api.get(pai_id, {"fields": "id,name,status"}) or {}
        except RuntimeError:
            continue  # sem leitura do pai: sem aviso (o aviso é um extra, nunca bloqueia)
        if str(pai.get("status") or "").upper() == "PAUSED":
            achados.append({"id": pai_id, "nivel": nivel, "nome": pai.get("name") or ""})
    return achados


def avisa_pais_pausados(planos):
    """Avisa quando ativar um item cujo pai continua pausado, a menos que o pai também esteja sendo ativado agora."""
    ativando = {p["id"] for p in planos if p.get("depois") == "ACTIVE" and p.get("campo") == "status"}
    for p in planos:
        if p["noop"]:
            continue
        for pai in p.get("pais_pausados") or []:
            if pai["id"] not in ativando:
                p["avisos"].append(
                    "%s %s \"%s\" está PAUSADO(A): este item ficará ATIVO mas só entrega quando ele(a) também for ativado(a)."
                    % (NIVEL_ROTULO[pai["nivel"]].lower(), pai["id"], pai["nome"])
                )


def planeja_orcamento(ctx, entidade_id, valor_texto, nivel=None):
    moeda = ctx.moeda()
    valor = parse_valor(valor_texto)
    novo = para_unidades_menores(valor, moeda)
    no = busca_entidade(ctx, entidade_id, nivel)
    if no["nivel"] == "anuncio":
        raise AcaoErro("Anúncio não tem orçamento próprio: ajuste no conjunto (ou na campanha). Nada foi alterado.")
    atual = _orcamento_atual(no)
    if atual is None:
        raise AcaoErro(
            "%s não tem orçamento DIÁRIO próprio (a campanha usa orçamento de campanha/CBO, ou o orçamento é vitalício). "
            "Ajuste no nível que tem o orçamento diário. Nada foi alterado." % _rotulo(no)
        )
    return {
        "tipo": "orcamento", "id": no["id"], "nivel": no["nivel"], "nome": no.get("name") or "",
        "campo": "daily_budget", "antes": atual, "depois": novo, "moeda": moeda, "avisos": [],
        "noop": atual == novo, "rotulo": _rotulo(no),
    }


def planeja_desfazer(ctx, mudanca_id):
    registros = ler_log(ctx)
    alvo = next((r for r in registros if r.get("mudanca") == mudanca_id), None)
    if not alvo:
        raise AcaoErro("Não achei a mudança %r no log do projeto %s (%s)." % (mudanca_id, ctx.paths.name, ctx.log_path))
    if alvo.get("acao") not in ("status", "orcamento") or alvo.get("resultado") != "ok":
        raise AcaoErro("A mudança %s não é um status/orçamento aplicado com sucesso; não há o que desfazer." % mudanca_id)
    if any(r.get("desfaz") == mudanca_id and r.get("resultado") == "ok" and r.get("verificado") is True for r in registros):
        raise AcaoErro("A mudança %s já foi desfeita antes." % mudanca_id)
    no = busca_entidade(ctx, alvo["entidade_id"], alvo.get("nivel"))
    campo = alvo["campo"]
    atual = str(no.get("status") or "").upper() if campo == "status" else _orcamento_atual(no)
    if atual is None:
        raise AcaoErro(
            "%s não tem mais orçamento diário próprio (talvez a campanha tenha passado a CBO); "
            "não consigo desfazer por aqui. Nada foi alterado." % _rotulo(no)
        )
    plano = {
        "tipo": alvo["acao"], "id": no["id"], "nivel": no["nivel"], "nome": no.get("name") or "",
        "campo": campo, "antes": atual, "depois": alvo["antes"], "moeda": alvo.get("moeda"),
        "avisos": [], "noop": atual == alvo["antes"], "rotulo": _rotulo(no), "desfaz": mudanca_id,
    }
    if atual != alvo["depois"]:
        plano["avisos"].append(
            "O valor atual (%s) não é o que a mudança %s deixou (%s): alguém mexeu depois. Revise antes de confirmar."
            % (_fmt_valor(plano, atual), mudanca_id, _fmt_valor(plano, alvo["depois"]))
        )
    return plano


def _fmt_valor(plano, valor):
    if valor is None:
        return "?"
    if plano["campo"] == "status":
        return fmt_status(valor)
    return fmt_dinheiro(de_unidades_menores(valor, plano.get("moeda") or "BRL"), plano.get("moeda") or "BRL")


def mostra_plano(planos, out=print):
    out("")
    out("PLANO (nada foi alterado ainda)")
    for i, p in enumerate(planos, 1):
        out(" %d. %s" % (i, p["rotulo"]))
        if p["noop"]:
            out("    já está assim (%s): nada a fazer." % _fmt_valor(p, p["antes"]))
        elif p["campo"] == "status":
            out("    status: %s → %s" % (fmt_status(p["antes"]), fmt_status(p["depois"])))
        else:
            variacao = (Decimal(p["depois"]) - Decimal(p["antes"])) / Decimal(p["antes"]) * 100
            out(
                "    orçamento diário: %s → %s  (%+.0f%%) · enviará daily_budget=%d"
                % (_fmt_valor(p, p["antes"]), _fmt_valor(p, p["depois"]), variacao, p["depois"])
            )
        for aviso in p["avisos"]:
            out("    ⚠️  %s" % aviso)


# ---------------------------------------------------------------- aplicação
def aplica_plano(ctx, plano, origem, out=print):
    """POST + leitura de volta + log. Devolve True se a Meta confirmou o valor novo."""
    nivel = plano["nivel"]
    corpo = {plano["campo"]: plano["depois"] if plano["campo"] == "status" else str(plano["depois"])}
    base = {
        "acao": plano["tipo"], "nivel": nivel, "entidade_id": plano["id"], "nome": plano["nome"],
        "campo": plano["campo"], "antes": plano["antes"], "depois": plano["depois"], "origem": origem,
    }
    if plano.get("moeda"):
        base["moeda"] = plano["moeda"]
    if plano.get("desfaz"):
        base["desfaz"] = plano["desfaz"]
    incerto = None
    try:
        resposta = ctx.api.post(plano["id"], corpo)
        if not (isinstance(resposta, dict) and resposta.get("success") is True):
            incerto = "resposta inesperada da Meta: %s" % json.dumps(resposta)[:200]
    except SemResposta as exc:
        incerto = msg_erro(exc)
    except KeyboardInterrupt:
        mudanca, _ = registrar_seguro(ctx, dict(base, resultado="incerto", erro="interrompido (Ctrl+C)"), out)
        out("\n⚠️  Interrompido. %s PODE ter sido alterado: confira com `python3 meta_acoes.py listar` (ou peça ao Claude Code/Codex pelo MCP da Meta) antes de repetir. (registro %s)"
            % (plano["rotulo"], mudanca))
        raise
    except RuntimeError as exc:
        registrar_seguro(ctx, dict(base, resultado="erro", erro=redige(msg_erro(exc), ctx.token)), out)
        out("❌ %s: a Meta recusou (%s). Nada mudou neste item." % (plano["rotulo"], msg_erro(exc)))
        return False
    atual, leu = None, False
    try:
        lido = ctx.api.get(plano["id"], {"fields": CAMPOS_NIVEL[nivel]})
        atual = str(lido.get("status") or "").upper() if plano["campo"] == "status" else _orcamento_atual(lido)
        leu = True
    except KeyboardInterrupt:
        mudanca, _ = registrar_seguro(ctx, dict(base, resultado="incerto", erro="interrompido (Ctrl+C) na conferência"), out)
        out("\n⚠️  Interrompido na conferência. A Meta já tinha respondido ao pedido: %s provavelmente FOI alterado. "
            "Confira com `python3 meta_acoes.py listar` (ou peça ao Claude Code/Codex pelo MCP da Meta). (registro %s)" % (plano["rotulo"], mudanca))
        raise
    except RuntimeError:
        leu = False
    verificado = leu and atual == plano["depois"]
    if incerto and not verificado:
        mudanca, _ = registrar_seguro(ctx, dict(base, resultado="incerto", erro=redige(incerto, ctx.token)), out)
        if leu and atual == plano["antes"]:
            out("⚠️  %s: %s. A leitura logo depois ainda mostra o valor anterior, mas a Meta pode aplicar com atraso: "
                "confira com `python3 meta_acoes.py listar` (ou peça ao Claude Code/Codex pelo MCP da Meta) antes de repetir. (registro %s)" % (plano["rotulo"], incerto, mudanca))
        else:
            out("⚠️  %s: %s e não consegui confirmar o estado lendo de volta. A mudança PODE ter sido aplicada: "
                "confira com `python3 meta_acoes.py listar` (ou peça ao Claude Code/Codex pelo MCP da Meta) antes de repetir. (registro %s)" % (plano["rotulo"], incerto, mudanca))
        return False
    mudanca, gravou = registrar_seguro(ctx, dict(base, resultado="ok", verificado=verificado), out)
    if verificado:
        out("✅ %s: %s (confirmado na Meta · mudança %s)" % (plano["rotulo"], _resumo(plano), mudanca))
    else:
        out("⚠️  %s: a Meta respondeu sucesso, mas não consegui confirmar o valor lendo de volta. Confira com `python3 meta_acoes.py listar` (ou peça ao Claude Code/Codex pelo MCP da Meta). (mudança %s)"
            % (plano["rotulo"], mudanca))
    return verificado and gravou


def _resumo(plano):
    return "%s → %s" % (_fmt_valor(plano, plano["antes"]), _fmt_valor(plano, plano["depois"]))


def executa(ctx, planos, confirmar, origem, out=print):
    """Mostra o plano; só aplica com confirmar=True. Devolve o código de saída."""
    ctx.cabecalho(out)
    avisa_pais_pausados(planos)
    mostra_plano(planos, out)
    pendentes = [p for p in planos if not p["noop"]]
    if not pendentes:
        out("\nNada a alterar.")
        return 0
    if not confirmar:
        out("\n🔒 Nada foi alterado. Para aplicar, rode o MESMO comando com --confirmar.")
        return 0
    out("\n▶️  Aplicando (--confirmar)…")
    falhas = 0
    for plano in pendentes:
        if not aplica_plano(ctx, plano, origem, out):
            falhas += 1
    out("\nRegistro: %s" % ctx.log_path)
    return 1 if falhas else 0


# ---------------------------------------------------------------- listar / histórico
def _pagina(api, caminho, params):
    """Todas as páginas de uma edge (cursor 'after')."""
    itens, params = [], dict(params)
    while True:
        pag = api.get(caminho, params)
        itens.extend(pag.get("data", []))
        proximo = (pag.get("paging") or {}).get("cursors", {}).get("after")
        if not (pag.get("paging") or {}).get("next") or not proximo:
            return itens
        params["after"] = proximo


def lista(ctx, nivel, campanha=None, status=None, out=print):
    ctx.cabecalho(out)
    moeda = ctx.moeda()
    campos = {
        "campanha": "id,name,status,effective_status,daily_budget",
        "conjunto": "id,name,status,effective_status,daily_budget,campaign_id",
        "anuncio": "id,name,status,effective_status,adset_id,campaign_id",
    }[nivel]
    borda = {"campanha": "campaigns", "conjunto": "adsets", "anuncio": "ads"}[nivel]
    if campanha and nivel == "campanha":
        raise AcaoErro("--campanha só faz sentido para listar conjuntos ou anúncios.")
    pai = busca_entidade(ctx, valida_id(campanha), "campanha")["id"] if campanha else ctx.conta
    try:
        itens = _pagina(ctx.api, "%s/%s" % (pai, borda), {"fields": campos, "limit": 200})
    except RuntimeError as exc:
        raise AcaoErro("A Meta recusou a listagem: %s" % msg_erro(exc))
    if status:
        def _bate(i):
            ef = str(i.get("effective_status") or i.get("status")).upper()
            return ef == status or (status == "PAUSED" and ef.endswith("_PAUSED"))

        itens = [i for i in itens if _bate(i)]
    out("")
    if not itens:
        out("Nenhum(a) %s encontrado(a)." % nivel)
        return 0
    out("%-20s %-9s %-16s %-14s %s" % ("ID", "STATUS", "EFETIVO", "ORÇ./DIA", "NOME"))
    for item in itens:
        orc = _orcamento_atual(item)
        out(
            "%-20s %-9s %-16s %-14s %s"
            % (
                item.get("id"), fmt_status(item.get("status")), item.get("effective_status") or "-",
                fmt_dinheiro(de_unidades_menores(orc, moeda), moeda) if orc else "-", item.get("name") or "",
            )
        )
    out("\n%d %s. Use o ID com: pausar, ativar ou orcamento." % (len(itens), nivel if len(itens) == 1 else nivel + "(s)"))
    return 0


def historico(ctx, ultimas, out=print):
    registros = ler_log(ctx)
    out("📁 Projeto: %s · log: %s" % (ctx.paths.name, ctx.log_path))
    if not registros:
        out("Nenhuma mudança registrada ainda.")
        return 0
    for r in list(reversed(registros))[:ultimas]:
        if r.get("acao") == "publicar":
            ids = r.get("ids") or {}
            criados = ", ".join("%s=%s" % (k, v) for k, v in ids.items() if k in ("campaign_id", "adset_id", "ad_id"))
            out("%s  %s  publicar  \"%s\"  %s  [%s]" % (r.get("mudanca"), r.get("quando"), r.get("nome") or "", criados or "nada criado", r.get("resultado")))
            continue
        plano = {"campo": r.get("campo"), "moeda": r.get("moeda")}
        antes, depois = _fmt_valor(plano, r.get("antes")), _fmt_valor(plano, r.get("depois"))
        extra = " · desfaz %s" % r["desfaz"] if r.get("desfaz") else ""
        out(
            "%s  %s  %-9s %s %s  %s → %s  [%s%s]"
            % (r.get("mudanca"), r.get("quando"), r.get("acao"), NIVEL_ROTULO.get(r.get("nivel"), "?"),
               r.get("entidade_id"), antes, depois, r.get("resultado"), extra)
        )
    return 0


# ---------------------------------------------------------------- CLI
def _parser():
    ap = argparse.ArgumentParser(
        prog="meta_acoes.py",
        description="Pausar, ativar e ajustar orçamento na Meta com plano antes→depois e --confirmar.",
    )
    sub = ap.add_subparsers(dest="cmd", required=True)

    def com_confirmar(p):
        p.add_argument("--confirmar", action="store_true", help="aplica de verdade (sem isso só mostra o plano)")
        p.add_argument("--nivel", choices=NIVEIS, help="força o tipo do ID (o padrão é detectar sozinho)")

    p = sub.add_parser("listar", help="lista campanhas, conjuntos ou anúncios com ID, status e orçamento")
    p.add_argument("--nivel", choices=NIVEIS, default="campanha")
    p.add_argument("--campanha", help="só os conjuntos/anúncios desta campanha")
    p.add_argument("--status", choices=["ACTIVE", "PAUSED"], help="filtra por status efetivo")
    for nome, ajuda in (("pausar", "pausa campanhas/conjuntos/anúncios"), ("ativar", "ativa campanhas/conjuntos/anúncios")):
        p = sub.add_parser(nome, help=ajuda)
        p.add_argument("ids", nargs="+")
        com_confirmar(p)
    p = sub.add_parser("orcamento", help="ajusta o orçamento DIÁRIO de uma campanha ou conjunto")
    p.add_argument("id")
    p.add_argument("valor", help="valor diário na moeda da conta, ex.: 80 ou 80,50")
    com_confirmar(p)
    p = sub.add_parser("historico", help="mostra as mudanças aplicadas neste projeto")
    p.add_argument("--ultimas", type=int, default=20)
    p = sub.add_parser("desfazer", help="reverte uma mudança registrada (também pede --confirmar)")
    p.add_argument("mudanca", nargs="?", help="id da mudança (veja em `historico`)")
    p.add_argument("--ultima", action="store_true", help="desfaz a última mudança aplicada")
    p.add_argument("--confirmar", action="store_true")
    return ap


def main(argv=None, api=None, paths=None, out=print):
    args = _parser().parse_args(argv)
    try:
        ctx = montar_contexto(api=api, paths=paths)
        if args.cmd == "listar":
            return lista(ctx, args.nivel, args.campanha, args.status, out)
        if args.cmd == "historico":
            return historico(ctx, max(1, args.ultimas), out)
        if args.cmd in ("pausar", "ativar"):
            novo = "PAUSED" if args.cmd == "pausar" else "ACTIVE"
            ids = list(dict.fromkeys(args.ids))
            ctx.info_conta()
            planos = [planeja_status(ctx, i, novo, args.nivel) for i in ids]
            return executa(ctx, planos, args.confirmar, "meta_acoes.py " + args.cmd, out)
        if args.cmd == "orcamento":
            plano = planeja_orcamento(ctx, args.id, args.valor, args.nivel)
            return executa(ctx, [plano], args.confirmar, "meta_acoes.py orcamento", out)
        if args.cmd == "desfazer":
            if bool(args.mudanca) == bool(args.ultima):
                raise AcaoErro("Informe o id da mudança OU use --ultima (veja os ids em `historico`).")
            alvo = args.mudanca
            if args.ultima:
                candidatas = [
                    r for r in ler_log(ctx)
                    if r.get("acao") in ("status", "orcamento") and r.get("resultado") == "ok" and not r.get("desfaz")
                ]
                desfeitas = {r.get("desfaz") for r in ler_log(ctx) if r.get("desfaz") and r.get("resultado") == "ok" and r.get("verificado") is True}
                candidatas = [r for r in candidatas if r["mudanca"] not in desfeitas]
                if not candidatas:
                    raise AcaoErro("Não há mudança aplicada pendente de desfazer neste projeto.")
                alvo = candidatas[-1]["mudanca"]
            ctx.info_conta()
            plano = planeja_desfazer(ctx, alvo)
            return executa(ctx, [plano], args.confirmar, "meta_acoes.py desfazer", out)
    except AcaoErro as exc:
        out("❌ %s" % exc)
        return 1
    return 1


if __name__ == "__main__":
    sys.exit(main())
