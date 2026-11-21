#!/usr/bin/env python3
"""
meta_publicar.py — publica na Meta a partir do criativo aprovado (imagem/vídeo + copy).

Cria campanha, conjunto e anúncio pela Graph API, tudo NASCENDO PAUSADO. Nada gasta
até você ativar com confirmação (meta_acoes.py ativar ... --confirmar).

  python3 meta_publicar.py --exemplo > campanha.json     # modelo para preencher
  python3 meta_publicar.py campanha.json                 # só mostra o resumo (não cria nada)
  python3 meta_publicar.py campanha.json --confirmar     # sobe o criativo e cria tudo PAUSADO

Regras:
- SEM --confirmar: valida, resolve interesses (só leitura) e imprime o resumo
  (conta, orçamento, público, criativo). Nada é enviado nem criado.
- COM --confirmar: sobe imagem/vídeo, cria campanha → conjunto → criativo → anúncio,
  sempre com status PAUSED, e grava os IDs em <projeto>/logs/meta-acoes.jsonl.
- A conta de anúncios, a página e o pixel vêm SEMPRE do projeto vigente
  (<projeto>/config/meta.env). O arquivo de campanha não escolhe conta.
- Se uma etapa falhar no meio, nada é apagado automaticamente: o script lista o que
  já foi criado (tudo pausado) para você decidir.

Só biblioteca padrão. Python 3.8+.
"""
import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

import meta_acoes
from meta_acoes import AcaoErro, fmt_dinheiro, msg_erro, para_unidades_menores, parse_valor

SPEC_PADRAO = "campanha.json"
LIMITE_IMAGEM_MB = meta_acoes._env_pos_int("ZX_TPA_MAX_IMAGEM_MB", 30)
# O arquivo é lido por inteiro na memória para o envio: o teto protege computadores modestos.
LIMITE_VIDEO_MB = meta_acoes._env_pos_int("ZX_TPA_MAX_VIDEO_MB", 500)
# Quanto esperar a Meta processar o vídeo enviado, em segundos (e de quanto em quanto sondar).
VIDEO_TIMEOUT = meta_acoes._env_pos_int("ZX_TPA_VIDEO_TIMEOUT", 600)
VIDEO_SONDAGEM = meta_acoes._env_pos_int("ZX_TPA_VIDEO_SONDAGEM", 5)

EXT_IMAGEM = (".jpg", ".jpeg", ".png", ".gif")
EXT_VIDEO = (".mp4", ".mov")
GENEROS = {"todos": None, "homens": [1], "mulheres": [2]}

# objetivo da planilha do aluno -> (objective ODAX, optimization_goal, precisa de pixel, evento)
OBJETIVOS = {
    "trafego": ("OUTCOME_TRAFFIC", "LINK_CLICKS", False, None),
    "leads": ("OUTCOME_LEADS", "OFFSITE_CONVERSIONS", True, "LEAD"),
    "vendas": ("OUTCOME_SALES", "OFFSITE_CONVERSIONS", True, "PURCHASE"),
}

EXEMPLO = {
    "nome": "Campanha Exemplo - Leads",
    "objetivo": "leads",
    "orcamento_diario": "30",
    "evento_conversao": "LEAD",
    "publico": {
        "paises": ["BR"],
        "idade_min": 25,
        "idade_max": 55,
        "genero": "todos",
        "interesses": ["Marketing digital"],
    },
    "criativo": {
        "tipo": "imagem",
        "arquivo": "criativo-aprovado.png",
        "texto": "Texto principal do anúncio (a copy aprovada).",
        "titulo": "Título do anúncio",
        "descricao": "",
        "link": "https://seusite.com.br/pagina",
        "cta": "LEARN_MORE",
    },
}


# ---------------------------------------------------------------- validação
# Campos que os *_extra NÃO podem trocar: o resumo mostra os valores normalizados e a conta/página/pixel
# vêm do projeto. O que não está aqui (ex.: is_adset_budget_sharing_enabled, bid_amount) passa.
EXTRAS_PROIBIDAS = {
    "campanha_extra": {"status", "objective", "daily_budget", "lifetime_budget", "name"},
    "conjunto_extra": {"status", "daily_budget", "lifetime_budget", "campaign_id", "targeting", "promoted_object",
                       "optimization_goal", "name"},
    "targeting_extra": {"geo_locations", "age_min", "age_max", "genders", "flexible_spec"},
    "criativo_extra": {"object_story_spec", "name", "page_id", "instagram_actor_id", "instagram_user_id",
                       "object_story_id", "source_instagram_media_id"},
}


def _texto(valor, campo, obrigatorio=True, maximo=2000):
    valor = ("" if valor is None else str(valor)).strip()
    if obrigatorio and not valor:
        raise AcaoErro("Falta o campo '%s' no arquivo de campanha." % campo)
    if len(valor) > maximo:
        raise AcaoErro("O campo '%s' tem %d caracteres; o máximo aceito aqui é %d." % (campo, len(valor), maximo))
    return valor


def _inteiro(valor, campo, minimo, maximo):
    try:
        numero = int(valor)
    except (TypeError, ValueError):
        raise AcaoErro("O campo '%s' precisa ser um número inteiro." % campo)
    if not minimo <= numero <= maximo:
        raise AcaoErro("O campo '%s' precisa estar entre %d e %d." % (campo, minimo, maximo))
    return numero


def carrega_spec(caminho):
    caminho = Path(caminho).expanduser()
    try:
        bruto = meta_acoes.tpa_paths.read_text_compat(caminho)
    except OSError as exc:
        raise AcaoErro("Não consegui abrir %s: %s. Gere um modelo com: python3 meta_publicar.py --exemplo" % (caminho, exc))
    try:
        spec = json.loads(bruto)
    except ValueError as exc:
        raise AcaoErro("O arquivo %s não é um JSON válido (%s)." % (caminho, exc))
    if not isinstance(spec, dict):
        raise AcaoErro("O arquivo %s precisa conter um objeto JSON." % caminho)
    return spec, caminho.resolve().parent


def valida_spec(spec, base, moeda, pagina, pixel):
    """Valida tudo ANTES de qualquer chamada que escreva. Devolve o plano normalizado."""
    objetivo = str(spec.get("objetivo") or "").strip().lower()
    if objetivo not in OBJETIVOS:
        raise AcaoErro("objetivo '%s' não suportado. Use: %s." % (objetivo, ", ".join(sorted(OBJETIVOS))))
    odax, otimizacao, precisa_pixel, evento_padrao = OBJETIVOS[objetivo]
    if not pagina:
        raise AcaoErro(
            "Falta a página do Facebook do projeto. Preencha META_PAGE_ID em meta.env "
            "(o ID aparece em `ads_get_pages_for_business` ou nas configurações da página)."
        )
    if precisa_pixel and not pixel:
        raise AcaoErro(
            "O objetivo '%s' otimiza por conversão e precisa do pixel. Preencha META_PIXEL_ID em meta.env." % objetivo
        )
    valor = parse_valor(_texto(spec.get("orcamento_diario"), "orcamento_diario", maximo=20))
    orcamento = para_unidades_menores(valor, moeda)

    for bloco in ("publico", "criativo"):
        if not isinstance(spec.get(bloco), dict):
            raise AcaoErro("'%s' precisa ser um objeto JSON (veja o modelo com --exemplo)." % bloco)
    pub = spec.get("publico") or {}
    if not isinstance(pub.get("interesses") or [], list):
        raise AcaoErro("publico.interesses precisa ser uma lista de textos, por exemplo [\"Marketing digital\"].")
    paises = [str(p).strip().upper() for p in (pub.get("paises") or [])]
    if not paises or not all(re.fullmatch(r"[A-Z]{2}", p) for p in paises):
        raise AcaoErro("publico.paises precisa ser uma lista de códigos de 2 letras, por exemplo [\"BR\"].")
    idade_min = _inteiro(pub.get("idade_min", 18), "publico.idade_min", 13, 65)
    idade_max = _inteiro(pub.get("idade_max", 65), "publico.idade_max", 13, 65)
    if idade_min > idade_max:
        raise AcaoErro("publico.idade_min não pode ser maior que publico.idade_max.")
    genero = str(pub.get("genero") or "todos").strip().lower()
    if genero not in GENEROS:
        raise AcaoErro("publico.genero precisa ser: todos, homens ou mulheres.")
    interesses = [str(i).strip() for i in (pub.get("interesses") or []) if str(i).strip()]

    cr = spec.get("criativo") or {}
    tipo = str(cr.get("tipo") or "").strip().lower()
    if tipo not in ("imagem", "video"):
        raise AcaoErro("criativo.tipo precisa ser 'imagem' ou 'video'.")
    arquivo = _resolve_arquivo(cr.get("arquivo"), base, "criativo.arquivo")
    _confere_arquivo(arquivo, EXT_IMAGEM if tipo == "imagem" else EXT_VIDEO,
                     LIMITE_IMAGEM_MB if tipo == "imagem" else LIMITE_VIDEO_MB,
                     "ZX_TPA_MAX_IMAGEM_MB" if tipo == "imagem" else "ZX_TPA_MAX_VIDEO_MB")
    miniatura = None
    if tipo == "video":
        miniatura = _resolve_arquivo(cr.get("thumbnail"), base, "criativo.thumbnail (imagem de capa do vídeo)")
        _confere_arquivo(miniatura, EXT_IMAGEM, LIMITE_IMAGEM_MB, "ZX_TPA_MAX_IMAGEM_MB")
    link = _texto(cr.get("link"), "criativo.link", maximo=1500)
    if not re.match(r"https?://[^\s]+$", link):
        raise AcaoErro("criativo.link precisa começar com http:// ou https:// e não ter espaços.")
    cta = _texto(cr.get("cta") or "LEARN_MORE", "criativo.cta", maximo=40).upper()
    if not re.fullmatch(r"[A-Z_]+", cta):
        raise AcaoErro("criativo.cta precisa ser um código da Meta em maiúsculas, por exemplo LEARN_MORE.")

    nome = _texto(spec.get("nome"), "nome", maximo=200)
    evento = str(spec.get("evento_conversao") or evento_padrao or "").strip().upper()
    for extra in ("campanha_extra", "conjunto_extra", "targeting_extra", "criativo_extra"):
        if spec.get(extra) is not None and not isinstance(spec[extra], dict):
            raise AcaoErro("'%s' precisa ser um objeto JSON (ou ficar de fora)." % extra)
    for extra, proibidas in EXTRAS_PROIBIDAS.items():
        achadas = sorted(str(k) for k in (spec.get(extra) or {}) if str(k).lower() in proibidas)
        if achadas:
            raise AcaoErro(
                "'%s' não pode trazer %s: esses campos vêm do resto do arquivo (e aparecem no resumo) ou do projeto. "
                "Tudo nasce PAUSADO e só se ativa depois, com confirmação. Use o campo próprio do arquivo."
                % (extra, ", ".join("'%s'" % k for k in achadas))
            )
    return {
        "nome": nome, "objetivo": objetivo, "odax": odax, "otimizacao": otimizacao,
        "evento": evento if precisa_pixel else None, "orcamento": orcamento, "orcamento_valor": valor,
        "moeda": moeda, "pagina": pagina, "pixel": pixel if precisa_pixel else None,
        "paises": paises, "idade_min": idade_min, "idade_max": idade_max, "genero": genero,
        "interesses": interesses, "tipo": tipo, "arquivo": arquivo, "miniatura": miniatura,
        "texto": _texto(cr.get("texto"), "criativo.texto", maximo=2200),
        "titulo": _texto(cr.get("titulo"), "criativo.titulo", obrigatorio=False, maximo=255),
        "descricao": _texto(cr.get("descricao"), "criativo.descricao", obrigatorio=False, maximo=255),
        "link": link, "cta": cta,
        "campanha_extra": spec.get("campanha_extra") or {}, "conjunto_extra": spec.get("conjunto_extra") or {},
        "targeting_extra": spec.get("targeting_extra") or {}, "criativo_extra": spec.get("criativo_extra") or {},
    }


def _resolve_arquivo(valor, base, campo):
    valor = str(valor or "").strip()
    if not valor:
        raise AcaoErro("Falta o campo '%s' no arquivo de campanha." % campo)
    caminho = Path(valor).expanduser()
    return caminho if caminho.is_absolute() else (Path(base) / caminho)


def _confere_arquivo(caminho, extensoes, limite_mb, env_nome):
    if not caminho.is_file():
        raise AcaoErro("Arquivo não encontrado: %s" % caminho)
    if caminho.suffix.lower() not in extensoes:
        raise AcaoErro("%s: formato %s não aceito aqui (use %s)." % (caminho.name, caminho.suffix or "?", "/".join(extensoes)))
    tamanho = caminho.stat().st_size
    if tamanho <= 0:
        raise AcaoErro("%s está vazio." % caminho.name)
    if tamanho > limite_mb * 1024 * 1024:
        raise AcaoErro(
            "%s tem %.1f MB; o teto é %d MB (ajustável com a variável %s)." % (caminho.name, tamanho / 1048576.0, limite_mb, env_nome)
        )


# ---------------------------------------------------------------- resolução / resumo
def resolve_interesses(ctx, nomes):
    """Nome -> {id, name} via /search?type=adinterest (leitura). Falha se algum não existir."""
    achados = []
    for nome in nomes:
        try:
            resp = ctx.api.get("search", {"type": "adinterest", "q": nome, "limit": 5})
        except RuntimeError as exc:
            raise AcaoErro("Não consegui buscar o interesse '%s' na Meta: %s" % (nome, msg_erro(exc)))
        dados = resp.get("data") or []
        exato = next((d for d in dados if str(d.get("name", "")).lower() == nome.lower()), None)
        escolhido = exato or (dados[0] if dados else None)
        if not escolhido:
            raise AcaoErro("A Meta não tem o interesse '%s'. Troque por outro termo e rode de novo." % nome)
        achados.append({
            "id": str(escolhido["id"]), "name": escolhido.get("name") or nome,
            "aproximado": exato is None, "pedido": nome,
        })
    return achados


def monta_targeting(plano, interesses):
    alvo = {
        "geo_locations": {"countries": plano["paises"]},
        "age_min": plano["idade_min"],
        "age_max": plano["idade_max"],
    }
    if GENEROS[plano["genero"]]:
        alvo["genders"] = GENEROS[plano["genero"]]
    if interesses:
        alvo["flexible_spec"] = [{"interests": [{"id": i["id"], "name": i["name"]} for i in interesses]}]
    alvo.update(plano["targeting_extra"])
    return alvo


def mostra_resumo(ctx, plano, interesses, out=print):
    ctx.cabecalho(out)
    nome_gen = {"todos": "todos os gêneros", "homens": "homens", "mulheres": "mulheres"}[plano["genero"]]
    out("")
    out("RESUMO (nada foi criado ainda)")
    out(" Campanha:  %s · objetivo %s (%s)" % (plano["nome"], plano["objetivo"], plano["odax"]))
    out(" Orçamento: %s por dia · enviará daily_budget=%d" % (fmt_dinheiro(plano["orcamento_valor"], plano["moeda"]), plano["orcamento"]))
    out(" Otimiza:   %s%s" % (plano["otimizacao"], " · evento %s · pixel %s" % (plano["evento"], plano["pixel"]) if plano["pixel"] else ""))
    out(" Público:   %s · %d a %d anos · %s" % (", ".join(plano["paises"]), plano["idade_min"], plano["idade_max"], nome_gen))
    if interesses:
        out(" Interesses: %s" % ", ".join(
            "%s (%s)%s" % (i["name"], i["id"], " [APROXIMADO: você pediu '%s']" % i.get("pedido") if i.get("aproximado") else "")
            for i in interesses))
        if any(i.get("aproximado") for i in interesses):
            out(" ⚠️  Há interesse aproximado: confira o nome antes de confirmar ou use o nome exato da Meta.")
    out(" Página:    %s" % plano["pagina"])
    out(" Criativo:  %s · %s" % (plano["tipo"], plano["arquivo"]))
    if plano["miniatura"]:
        out("            capa: %s" % plano["miniatura"])
    out(" Anúncio:   “%s” · título “%s” · botão %s → %s" % (plano["texto"][:80] + ("…" if len(plano["texto"]) > 80 else ""),
                                                          plano["titulo"], plano["cta"], plano["link"]))
    for chave, rotulo in (("campanha_extra", "campanha"), ("conjunto_extra", "conjunto"),
                          ("targeting_extra", "público"), ("criativo_extra", "criativo")):
        if plano[chave]:
            out(" Extras:    %s: %s" % (rotulo, json.dumps(plano[chave], ensure_ascii=False)))
    out(" Status:    campanha, conjunto e anúncio nascem PAUSADOS (não gastam até você ativar).")


# ---------------------------------------------------------------- execução
def _post(ctx, caminho, params, **kw):
    try:
        resposta = ctx.api.post(caminho, params, **kw)
    except meta_acoes.SemResposta as exc:
        alvo = caminho.split("/")[-1]
        if alvo in ("adimages", "advideos"):
            dica = "o arquivo PODE ter sido enviado: confira a biblioteca de mídia da conta antes de reenviar"
        else:
            dica = ("esta etapa (%s) PODE ter sido criada na Meta: procure pelo nome \"%s\" no Gerenciador "
                    "(pausada, não gasta) antes de rodar de novo, para não duplicar" % (alvo, params.get("name", "")))
        raise meta_acoes.AcaoIncerta("%s. %s." % (meta_acoes.redige(msg_erro(exc), ctx.token), dica))
    except RuntimeError as exc:
        raise AcaoErro(meta_acoes.redige(msg_erro(exc), ctx.token))
    except OSError as exc:  # só o arquivo local (falha de rede já vira SemResposta): nada foi enviado
        raise AcaoErro("Não consegui ler o arquivo para enviar (%s). Nada foi enviado nesta etapa." % exc)
    if not isinstance(resposta, dict):
        raise AcaoErro("resposta inesperada da Meta em %s." % caminho)
    return resposta


def _cronometra(rotulo, inicio, out):
    out("   (%s levou %.0fs)" % (rotulo, time.monotonic() - inicio))


def sobe_imagem(ctx, arquivo, out):
    t0 = time.monotonic()
    resp = _post(ctx, "%s/adimages" % ctx.conta, {}, campo_arquivo="filename", arquivo=arquivo)
    imagens = resp.get("images") or {}
    primeira = next(iter(imagens.values()), None) if isinstance(imagens, dict) else None
    if not primeira or not primeira.get("hash"):
        raise AcaoErro("A Meta não devolveu o hash da imagem %s." % arquivo.name)
    _cronometra("envio da imagem", t0, out)
    return primeira["hash"]


def sobe_video(ctx, arquivo, out, sleep=time.sleep, relogio=time.monotonic):
    envio0 = relogio()
    resp = _post(ctx, "%s/advideos" % ctx.conta, {"title": arquivo.name}, campo_arquivo="source", arquivo=arquivo)
    t0 = relogio()  # o teto vale para o PROCESSAMENTO; o envio de um vídeo grande não conta
    video_id = str(resp.get("id") or "")
    if not video_id:
        raise AcaoErro("A Meta não devolveu o ID do vídeo %s." % arquivo.name)
    while True:
        try:
            info = ctx.api.get(video_id, {"fields": "status"})
        except RuntimeError as exc:
            raise AcaoErro("Não consegui conferir o processamento do vídeo %s: %s" % (video_id, msg_erro(exc)))
        estado = str(((info or {}).get("status") or {}).get("video_status") or "").lower()
        if estado == "ready":
            _cronometra("envio e processamento do vídeo", envio0, out)
            return video_id
        if estado == "error":
            raise AcaoErro("A Meta recusou o vídeo %s (status error). Confira formato e tamanho." % video_id)
        if relogio() - t0 > VIDEO_TIMEOUT:
            raise AcaoErro(
                "O vídeo %s ainda está processando após %ds de espera. Ele já está na conta (confira a biblioteca de mídia, não reenvie); rode de novo mais tarde "
                "ou aumente ZX_TPA_VIDEO_TIMEOUT." % (video_id, VIDEO_TIMEOUT)
            )
        sleep(VIDEO_SONDAGEM)


def publica(ctx, plano, interesses, out=print, sleep=time.sleep):
    """Executa as 6 etapas. Devolve (ids, erro|None); ids tem o que já foi criado."""
    ids = {}
    conta = ctx.conta
    try:
        if plano["tipo"] == "imagem":
            out("▶️  1/6 enviando a imagem…")
            hash_img = sobe_imagem(ctx, plano["arquivo"], out)
            ids["image_hash"] = hash_img
            spec_cri = {"link_data": {
                "link": plano["link"], "message": plano["texto"], "image_hash": hash_img,
                "call_to_action": {"type": plano["cta"], "value": {"link": plano["link"]}},
            }}
            if plano["titulo"]:
                spec_cri["link_data"]["name"] = plano["titulo"]
            if plano["descricao"]:
                spec_cri["link_data"]["description"] = plano["descricao"]
        else:
            out("▶️  1/6 enviando a capa e o vídeo…")
            capa = sobe_imagem(ctx, plano["miniatura"], out)
            video_id = sobe_video(ctx, plano["arquivo"], out, sleep=sleep)
            ids.update({"image_hash": capa, "video_id": video_id})
            spec_cri = {"video_data": {
                "video_id": video_id, "message": plano["texto"], "image_hash": capa,
                "call_to_action": {"type": plano["cta"], "value": {"link": plano["link"]}},
            }}
            if plano["titulo"]:
                spec_cri["video_data"]["title"] = plano["titulo"]
        spec_cri["page_id"] = plano["pagina"]

        out("▶️  2/6 criando a campanha (PAUSADA)…")
        camp = {"name": plano["nome"], "objective": plano["odax"], "status": "PAUSED", "special_ad_categories": []}
        camp.update(plano["campanha_extra"])
        camp["status"] = "PAUSED"
        ids["campaign_id"] = str(_post(ctx, "%s/campaigns" % conta, camp).get("id") or "")
        if not ids["campaign_id"]:
            raise AcaoErro("A Meta não devolveu o ID da campanha.")

        out("▶️  3/6 criando o conjunto de anúncios (PAUSADO)…")
        conj = {
            "name": "%s - Conjunto" % plano["nome"], "campaign_id": ids["campaign_id"], "status": "PAUSED",
            "daily_budget": str(plano["orcamento"]), "billing_event": "IMPRESSIONS",
            "optimization_goal": plano["otimizacao"], "bid_strategy": "LOWEST_COST_WITHOUT_CAP",
            "targeting": monta_targeting(plano, interesses),
        }
        if plano["pixel"]:
            conj["promoted_object"] = {"pixel_id": plano["pixel"], "custom_event_type": plano["evento"]}
        conj.update(plano["conjunto_extra"])
        conj["status"] = "PAUSED"
        ids["adset_id"] = str(_post(ctx, "%s/adsets" % conta, conj).get("id") or "")
        if not ids["adset_id"]:
            raise AcaoErro("A Meta não devolveu o ID do conjunto.")

        out("▶️  4/6 criando o criativo…")
        cri = {"name": "%s - Criativo" % plano["nome"], "object_story_spec": spec_cri}
        cri.update(plano["criativo_extra"])
        ids["creative_id"] = str(_post(ctx, "%s/adcreatives" % conta, cri).get("id") or "")
        if not ids["creative_id"]:
            raise AcaoErro("A Meta não devolveu o ID do criativo.")

        out("▶️  5/6 criando o anúncio (PAUSADO)…")
        anuncio = {
            "name": "%s - Anúncio" % plano["nome"], "adset_id": ids["adset_id"], "status": "PAUSED",
            "creative": {"creative_id": ids["creative_id"]},
        }
        ids["ad_id"] = str(_post(ctx, "%s/ads" % conta, anuncio).get("id") or "")
        if not ids["ad_id"]:
            raise AcaoErro("A Meta não devolveu o ID do anúncio.")
        return ids, None
    except AcaoErro as exc:
        return ids, exc
    except KeyboardInterrupt:
        return ids, meta_acoes.AcaoIncerta(
            "Interrompido (Ctrl+C). A etapa em andamento PODE ter sido criada: procure pelo nome \"%s\" no Gerenciador "
            "antes de rodar de novo." % plano["nome"]
        )


def confere_pausado(ctx, ids):
    """6/6: lê de volta e prova que os três nasceram PAUSED. Devolve lista de itens que NÃO estão."""
    fora = []
    for rotulo, chave in (("campanha", "campaign_id"), ("conjunto", "adset_id"), ("anúncio", "ad_id")):
        try:
            lido = ctx.api.get(ids[chave], {"fields": "id,status"})
            if str((lido or {}).get("status") or "").upper() != "PAUSED":
                fora.append("%s %s" % (rotulo, ids[chave]))
        except RuntimeError:
            fora.append("%s %s (não consegui conferir)" % (rotulo, ids[chave]))
    return fora


def executa(ctx, plano, interesses, confirmar, out=print, sleep=time.sleep, aceitar_aproximado=False):
    mostra_resumo(ctx, plano, interesses, out)
    if confirmar and not aceitar_aproximado and any(i.get("aproximado") for i in interesses):
        out("\n❌ Há interesse APROXIMADO (marcado acima). Nada foi criado. Use o nome exato que a Meta devolveu "
            "no arquivo, ou rode de novo com --aceitar-aproximado se for esse mesmo.")
        return 1
    if not confirmar:
        out("\n🔒 Nada foi criado. Para criar (tudo PAUSADO), rode o MESMO comando com --confirmar.")
        return 0
    out("")
    ids, erro = publica(ctx, plano, interesses, out, sleep)
    base = {"acao": "publicar", "nome": plano["nome"], "origem": "meta_publicar.py", "ids": ids}
    if erro:
        meta_acoes.registrar_seguro(
            ctx, dict(base, resultado="incerto" if isinstance(erro, meta_acoes.AcaoIncerta) else "erro", erro=str(erro)), out)
        out("\n❌ Parou no meio: %s" % erro)
        criados = {k: v for k, v in ids.items() if k != "image_hash"}
        if criados:
            out("   Já criado na Meta (tudo PAUSADO, nada gasta): %s" % ", ".join("%s=%s" % kv for kv in criados.items()))
            out("   Nada foi apagado. Pause/apague pelo Gerenciador, ou ajuste e rode de novo (vai criar uma campanha NOVA).")
        return 1
    out("✅ Criado: campanha %s · conjunto %s · anúncio %s" % (ids["campaign_id"], ids["adset_id"], ids["ad_id"]))
    out("▶️  6/6 conferindo que tudo nasceu pausado…")
    try:
        fora = confere_pausado(ctx, ids)
    except KeyboardInterrupt:
        meta_acoes.registrar_seguro(ctx, dict(base, resultado="incerto", verificado=False, erro="interrompido na conferência"), out)
        out("\n⚠️  Interrompido na conferência. Os IDs acima foram criados: confira no Gerenciador que estão PAUSADOS.")
        return 1
    _, gravou = meta_acoes.registrar_seguro(ctx, dict(base, resultado="ok", verificado=not fora), out)
    if not fora:
        out("\n   Conferido: tudo PAUSADO.")
    if not gravou:
        return 1
    if fora:
        out("⚠️  Não consegui confirmar o status PAUSADO de: %s. Confira no Gerenciador antes de qualquer ativação." % ", ".join(fora))
        return 1
    out("   Revise no Gerenciador de Anúncios. Para ativar (pede confirmação, mostra o orçamento):")
    out("   python3 meta_acoes.py ativar %s %s %s --confirmar" % (ids["campaign_id"], ids["adset_id"], ids["ad_id"]))
    out("\nRegistro: %s" % ctx.log_path)
    return 0


# ---------------------------------------------------------------- CLI
def _parser():
    ap = argparse.ArgumentParser(
        prog="meta_publicar.py",
        description="Publica campanha + conjunto + anúncio PAUSADOS na Meta a partir do criativo aprovado.",
    )
    ap.add_argument("spec", nargs="?", help="arquivo JSON da campanha (gere o modelo com --exemplo)")
    ap.add_argument("--exemplo", action="store_true", help="imprime um arquivo de campanha de exemplo e sai")
    ap.add_argument("--confirmar", action="store_true", help="cria de verdade (sem isso só mostra o resumo)")
    ap.add_argument("--aceitar-aproximado", action="store_true",
                    help="permite criar com interesse que não bate exatamente com o nome pedido")
    return ap


def main(argv=None, api=None, paths=None, out=print, sleep=time.sleep):
    args = _parser().parse_args(argv)
    if args.exemplo:
        out(json.dumps(EXEMPLO, ensure_ascii=False, indent=2))
        return 0
    try:
        if not args.spec:
            raise AcaoErro("Informe o arquivo da campanha (ex.: %s) ou use --exemplo." % SPEC_PADRAO)
        spec, base = carrega_spec(args.spec)
        ctx = meta_acoes.montar_contexto(api=api, paths=paths)
        plano = valida_spec(
            spec, base, ctx.moeda(),
            meta_acoes.ler_env(ctx.paths, "META_PAGE_ID"), meta_acoes.ler_env(ctx.paths, "META_PIXEL_ID"),
        )
        interesses = resolve_interesses(ctx, plano["interesses"])
        return executa(ctx, plano, interesses, args.confirmar, out, sleep, args.aceitar_aproximado)
    except AcaoErro as exc:
        out("❌ %s" % exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
