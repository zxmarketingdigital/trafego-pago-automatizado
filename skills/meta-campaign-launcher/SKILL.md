---
name: meta-campaign-launcher
description: "Cria sua campanha pronta no Facebook/Instagram sem você abrir o Gerenciador de Anúncios. Você só me diz: o que quer vender, quanto pode investir por dia, pra quem mostrar. Eu monto tudo e deixo PAUSADA — você revisa e ativa quando quiser. Triggers: criar campanha meta, nova campanha, lançar campanha, criar anúncio, criar campanha facebook, criar campanha instagram."
model: sonnet
effort: high
---

# meta-campaign-launcher

Cria campanha Meta ADS em DRAFT (PAUSED) via MCP oficial. Aluno só conversa em linguagem comercial — skill descobre IDs (página FB, pixel, audiência) automaticamente.

## Fluxo

### 1. Lookup automático de contexto

ANTES de pedir input ao aluno, descobre:

1. **Conta de anúncios**: lê `META_AD_ACCOUNT_ID` de `~/.operacao-ia/config/meta.env`. Se vazio, pede pro aluno rodar `setup_meta_oauth.py --set-account`.

2. **Páginas FB do Business**: chama `mcp__meta-official__ads_get_pages_for_business(business_id)`. `business_id` vem de `mcp__...__ads_get_ad_accounts → business.id`. Se >1, mostra lista numerada.

3. **Pixel**: lê `META_PIXEL_ID` de `meta.env`. Se vazio, chama `GET /act_<id>/adspixels?fields=id,name` (via `mcp__meta-official` ou curl direto). Se >1, lista pra aluno escolher e grava no `meta.env`.

4. **Audiência**: pergunta tipo:
   - **Interesse** (segmentação fria): aluno digita interesses (ex: "marketing digital, agências")
   - **Lookalike** (parecido com compradores): chama `GET /act_<id>/customaudiences?fields=id,name,subtype` filtra `LOOKALIKE`
   - **Custom** (lista do seu CRM): lista `customaudiences` filtra `CUSTOM`

### 2. Perguntas ao aluno (linguagem comercial)

```
Vamos criar sua campanha. Te pergunto 4 coisas e monto tudo.

1) O QUE você quer? (escolha o objetivo)
   [1] Captar leads — pessoa preenche form pra ser contatada
       Indicador-chave: CPL (custo por lead)

   [2] Levar pra conversa — abre WhatsApp/DM ao clicar
       Indicador-chave: custo por conversa iniciada

   [3] Vender direto — clica e compra (Hotmart/checkout)
       Indicador-chave: ROAS ou CPA

2) QUANTO investir POR DIA? (mín. R$10)

3) PRA QUEM mostrar?
   [1] Por interesse (você define)
   [2] Lookalike (parecido com seus compradores)
   [3] Custom (sua lista do CRM)

4) QUAL CRIATIVO?
   - Cole URL pública (ex: https://...)
   - OU caminho de arquivo local (ex: ~/Desktop/criativo.mp4)
   - OU diga "pular" pra criar com placeholder
```

### 3. Suporte a criativo local (imagem ou vídeo)

Detecta extensão:

- **`.png`/`.jpg`/`.jpeg`**: upload via `curl POST /act_<id>/adimages -F filename=@path -F access_token=$TOKEN` (token de `meta.env`). Pega `image_hash` do response.

- **`.mp4`/`.mov`**: `curl POST /act_<id>/advideos -F source=@path -F access_token=$TOKEN`. Pega `video_id`. Auto-extrai thumbnail:
  ```bash
  ffmpeg -i <video> -ss 00:00:02 -vframes 1 -y /tmp/thumb.jpg
  ```
  Upload thumb como image (passo anterior). Monta `creative.object_story_spec.video_data = {video_id, image_hash}`.

- **URL pública** (http/https): passa direto em `image_url` ou `link` do creative spec.

- **"pular"**: usa placeholder image_hash do BM (ou cria sem creative — campanha em DRAFT exige só estrutura).

### 4. Image-from-chat (limitação clara)

Se aluno disser "essa imagem aqui no chat" / "use a foto que mandei":
> "Salve a imagem no chat (clique direito → Salvar imagem) em `~/Desktop/criativo.png` e me diga o caminho. Ou cole URL pública."

NÃO tente automatizar — instrua aluno a fornecer caminho/URL.

### 5. Criação no Meta

Sequência de tool calls:

1. `mcp__meta-official__ads_create_campaign(name, objective, status="PAUSED")`
2. `mcp__meta-official__ads_create_ad_set(campaign_id, daily_budget, audience_spec, page_id, optimization_goal, billing_event, status="PAUSED")`
3. `mcp__meta-official__ads_create_ad(adset_id, creative={...}, status="PAUSED")`

### 6. Output ao aluno

```
✅ Campanha criada em PAUSED!

Nome: {name}
Campaign ID: {campaign_id}
Ad Set ID: {adset_id}
Ad ID: {ad_id}

Tudo PAUSADO — não vai gastar até você ativar.

Revise no Ads Manager: https://business.facebook.com/adsmanager/
```

Salva IDs em `~/.operacao-ia/config/setup6_progress.json` campo `demo_campaign_ids`.

## Glossário (linka aqui ao mencionar termo técnico)

`docs/glossario.md` — termos como CPL/CPA/ROAS/Pixel/CBO/ABO/Lookalike traduzidos.
