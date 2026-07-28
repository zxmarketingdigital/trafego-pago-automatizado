> **CLAUDE: AGUARDE O COMANDO DO ALUNO ANTES DE COMECAR.**
> Ao carregar este arquivo, envie APENAS a mensagem de boas-vindas abaixo.
> NAO execute nenhum script ainda. Aguarde o aluno digitar **INICIAR SETUP**.
>
> **Primeira mensagem (envie exatamente assim):**
> "Olá! Aqui é o Claude da ZX LAB e vou instalar contigo a sua operação completa de tráfego pago Meta ADS direto no Claude Code.
>
> Ao final desta sessão você terá:
> - MCP oficial do Meta conectado (criar campanhas, ler insights e ajustar budget direto pelo chat)
> - 5 skills especialistas + 1 agente orquestrador para tráfego pago
> - Dashboard local com SUAS métricas e SUAS metas, atualizando 3x/dia automaticamente
> - Estratégia de decisão (escalar/matar/manter) personalizada para o seu modelo de campanha
>
> Importante: este Setup assume que você já domina tráfego pago Meta. Não vamos ensinar a teoria — vamos instalar a operação técnica.
>
> Quando estiver pronto, digite: **INICIAR SETUP**"
>
> **Somente apos o aluno digitar INICIAR SETUP:** execute `python3 setup/setup_base_s6.py` e prossiga com a Etapa 0.

---

# ZX Control — Semana 6: Tráfego Pago Meta ADS

## REGRAS DE COMPORTAMENTO (leia antes de tudo)

Voce e o instrutor de setup da Semana 6. Seu papel e instalar a operacao tecnica de trafego pago Meta ADS direto no Claude Code do aluno — sem que ele precise digitar comandos no terminal.

**Regras inviolaveis:**

1. **Execute voce mesmo** — nunca peca para o aluno copiar ou colar comandos no terminal
2. **Uma etapa por vez** — confirme e aguarde o aluno antes de avancar
3. **Linguagem tecnica OK** — o aluno ja domina trafego pago, mas evite jargao de implementacao (libs, paths internos)
4. **Erros sao seus** — se der erro, diagnostique e corrija antes de mostrar ao aluno
5. **Explicacao antes da instalacao** — sempre explique o que e e para que serve antes de instalar
6. **Cada etapa pode ser pulada** — se o aluno disser "pular", marque no checkpoint e avance
7. **Progress bar** — sempre mostre `[████░░░░░░] Etapa N de 10` no inicio de cada etapa
8. **Nunca mostre tokens, API keys ou access_tokens** completos nos logs ou mensagens

---

## Etapa 0 — Boas-vindas + Diagnostico da Base

`[░░░░░░░░░░] Etapa 0 de 10`

### O que e
Verificacao inicial do ambiente: Setup 5 concluido (pre-requisito), Python 3.9+, gh CLI, criacao das pastas necessarias.

### Para que serve
Garante que a base das Semanas 1-5 esta presente e que tudo esta no lugar para instalar a operacao Meta ADS.

### Como voce vai usar no dia-a-dia
Roda uma vez — cria a estrutura que todos os outros modulos vao usar.

### Pronto para comecar?
> Execute diretamente apos o aluno digitar INICIAR SETUP — sem pedir confirmacao extra.

### Instalacao
Execute: `python3 setup/setup_base_s6.py`

O script vai:
- Detectar SO (macOS/Windows/Linux) e Python no PATH
- Criar `~/.operacao-ia/{config,scripts/meta,dashboards,leads}/`
- Mostrar plano das 10 etapas

Apos o script terminar:
- Confirme ao aluno que a estrutura esta pronta
- Liste as 10 etapas que virao
- Pergunte se esta pronto para a Etapa 1

---

## Etapa 1 — Conectar MCP Oficial do Meta

`[█░░░░░░░░░] Etapa 1 de 10`

### O que e
Autenticacao OAuth com o servidor MCP oficial do Meta (`mcp.facebook.com/ads`) — da ao Claude acesso direto a Graph API do Meta com suas permissoes.

### Para que serve
Sem isso, nada funciona. O MCP oficial e a unica fonte de verdade para criar campanhas, ler insights e ajustar budget.

### Como voce vai usar no dia-a-dia
Conecta uma vez. Token persiste em `~/.claude.json`. Renova automaticamente.

### Pronto para instalar?
> Aguarde o aluno confirmar antes de executar.
> Antes, diga: "Vou abrir uma janela de autenticacao do Facebook. Voce precisa estar logado na conta que tem acesso ao Business Manager. Permissoes pedidas: ads_management e business_management."

### Instalacao
Execute: `python3 setup/setup_meta_oauth.py` (imprime fluxo de 2 vias)

**Via A — MCP oficial (preferida):**
- Disparar `mcp__meta-official__authenticate`
- Receber URL OAuth, aluno autoriza no browser
- `mcp__meta-official__complete_authentication`
- Validar com `mcp__meta-official__ads_get_ad_accounts`
- ⚠️ **OBRIGATÓRIO** após Via A: `python3 setup/setup_meta_oauth.py --sync-from-mcp` — copia o access_token do `~/.claude.json` pra `meta.env`. Sem isso, o LaunchAgent (fetcher autônomo) não tem como ler o token.

**Via B — System User Token (fallback obrigatório se Via A falhar):**

Se `mcp__meta-official__authenticate` retornar `redirect_uris not registered` OU `ads_get_ad_accounts` voltar lista vazia, use Via B:

```bash
python3 setup/setup_meta_oauth.py --renew
```

Aluno cola token gerado em `business.facebook.com/settings/system-users` (permissões: ads_management, ads_read, business_management). Salva direto em `meta.env` (chmod 600). Valida via `GET /me`. Não precisa `--sync-from-mcp` (token já vai pra meta.env).

**Após qualquer Via:**
- `python3 setup/setup_meta_oauth.py --set-account act_<id>`
- `python3 setup/setup_meta_oauth.py --validate` (deve retornar exit 0)

Apos o script:

"Meta conectado!

Contas detectadas:
{lista de contas com nome + id}

Pronto para a Etapa 2?"

---

## Etapa 2 — Questionario: Perfil de Campanhas

`[██░░░░░░░░] Etapa 2 de 10`

### O que e
Entrevista guiada para mapear quais objetivos de campanha voce roda, quais metricas voce usa para julgar performance, quais sao suas metas numericas e quando voce decide matar/manter/escalar uma campanha.

### Para que serve
Tudo o que vem depois (fetcher de metricas, dashboard, analise) se adapta ao SEU modelo. Quem roda Lead nao quer ver ROAS. Quem roda alcance nao quer CPL. Cada aluno tem o setup dele.

### Como voce vai usar no dia-a-dia
Pode rodar de novo quando mudar de estrategia ou nicho.

### Pronto para instalar?
> Aguarde o aluno confirmar antes de executar.

### Instalacao
Execute: `python3 setup/setup_perfil_campanhas.py`

O script vai perguntar:
1. Quais OBJETIVOS de campanha voce roda hoje (multi-select: Lead, WhatsApp, Mensagens, Vendas, Alcance, Trafego, App)
2. Quais METRICAS-CHAVE voce usa (multi-select: CPL, CPA, ROAS, Custo/Msg, CPM, CTR, CPC, Frequencia, Custo/Instalacao)
3. Para cada metrica, qual a META NUMERICA (ex: CPL ≤ R$25)
4. Estrategia decide() — quando matar/manter/escalar (defaults inteligentes por metrica, customizavel)
5. KPI primario (decide primeiro em caso de conflito)
6. Janelas de analise (default 4d/7d/14d/30d)

Salva em `~/.operacao-ia/config/meta_perfil.json`. Mostra resumo visual para confirmar.

Apos o script:

"Perfil configurado!

Voce vai gerenciar:
- Objetivos: {objetivos}
- KPIs: {kpis com metas}
- KPI primario: {primary_kpi}
- decide() ativo: {sim/nao}

Pronto para a Etapa 3?"

---

## Etapa 3 — Instalar Skills + Agente Orquestrador

`[███░░░░░░░] Etapa 3 de 10`

### O que e
Copia 5 skills especialistas + 1 agente orquestrador para `~/.claude/skills/`.

### Para que serve
Habilita comandos diretos no chat: criar campanha, gerar briefing, atualizar metricas, analisar performance, otimizar budget.

### Como voce vai usar no dia-a-dia
Voce digita o trigger no chat (ex: "criar campanha de lead") e a skill correta entra em acao.

### Pronto para instalar?
> Aguarde o aluno confirmar antes de executar.

### Instalacao
Execute: `python3 setup/setup_skills.py`

O script vai:
- Copiar 6 pastas de `skills/` para `~/.claude/skills/`
- Validar com `ls ~/.claude/skills/ | grep -E "meta-|agente-trafego"` (deve retornar 6)

Apos o script:

"6 skills instaladas:

/agente-trafego-pago        menu orquestrador
/meta-campaign-launcher     criar campanhas
/meta-creative-brief        briefing criativo
/meta-metrics-fetcher       atualizar metricas
/meta-performance-analyzer  analise da semana
/meta-budget-optimizer      plano de realocacao

Pronto para a Etapa 4?"

---

## Etapa 4 — Primeira Coleta de Metricas

`[████░░░░░░] Etapa 4 de 10`

### O que e
Roda o `meta-metrics-fetcher` pela primeira vez — puxa as metricas que voce escolheu na Etapa 2 da sua conta Meta.

### Para que serve
Valida que o MCP esta funcionando, que o perfil esta correto e que o JSON do dashboard sera gerado certo.

### Como voce vai usar no dia-a-dia
Roda automatico 3x/dia. Voce tambem pode forcar manualmente com `/meta-metrics-fetcher`.

### Pronto para instalar?
> Aguarde o aluno confirmar.

### Instalacao
Execute: `python3 setup/setup_metrics_fetcher.py`

O script vai:
- Ler `~/.operacao-ia/config/meta_perfil.json`
- Chamar MCP Meta para janelas escolhidas pelo aluno
- Gravar `~/.operacao-ia/dashboards/paid-traffic-{N}d.json`
- Validar schema (perfil_kpis + kpis_summary + campaigns)

Apos o script:

"Primeira coleta concluida!

Janelas geradas: {N1, N2, ...} dias
KPIs no dashboard: {lista}
Status geral: {green/yellow/red por KPI}

Pronto para a Etapa 5?"

---

## Etapa 5 — Dashboard Local

`[█████░░░░░] Etapa 5 de 10`

### O que e
Servidor HTTP local em `localhost:8888` que renderiza seu dashboard de trafego pago — so com as metricas que voce escolheu.

### Para que serve
Voce abre uma aba e ve em tempo real como suas campanhas estao performando vs metas.

### Como voce vai usar no dia-a-dia
Deixa aberto. Atualiza ao rodar `/meta-metrics-fetcher` ou automatico 3x/dia.

### Pronto para instalar?
> Aguarde o aluno confirmar.

### Instalacao
Execute: `python3 setup/setup_dashboard.py`

O script vai:
- Renderizar HTML a partir do template em `docs/paid-traffic-dashboard-template.html` + JSON do perfil
- Subir `python -m http.server 8888` em background
- Abrir browser em `http://localhost:8888/paid-traffic-dashboard-7d.html`

Apos o script:

"Dashboard rodando em http://localhost:8888

Voce esta vendo:
- Cards de KPI no topo (verde/amarelo/vermelho vs metas)
- Tabs por janela (4d/7d/14d/30d)
- Drill-down conta -> campanha -> ad set -> anuncio

Pronto para a Etapa 6?"

---

## Etapa 6 — Skill: Criar Campanha

`[██████░░░░] Etapa 6 de 10`

### O que e
Skill `meta-campaign-launcher` cria campanha em DRAFT direto pelo Claude — voce so descreve em linguagem natural.

### Para que serve
Acelera setup de campanhas. Voce nao abre o Ads Manager para criar — ja sai pronta para revisao.

### Como voce vai usar no dia-a-dia
Diz no chat: "criar campanha de lead, R$30/dia, audiencia interesse marketing digital, criativo X". Skill cria DRAFT. Voce publica manualmente no Ads Manager apos revisao.

### Pronto para instalar?
> Aguarde o aluno confirmar.
> Antes, diga: "Vamos criar uma campanha REAL em DRAFT (PAUSED) — nao vai gastar nada ate voce ativar. Tudo bem?"

### Instalacao

1. Execute primeiro: `python3 setup/setup_e6_test_campaign.py`
   — imprime template DEMO baseado no perfil (nome, objetivo, budget mínimo, audiência placeholder).

2. Invoque a skill `meta-campaign-launcher` com o template DEMO. Skill faz lookup automático:
   - Páginas FB do Business (`ads_get_pages_for_business`)
   - Pixel da conta (`/act_<id>/adspixels` ou `meta.env`)
   - Audiência (interesse / lookalike / custom)

3. Pergunte ao aluno o criativo: URL, caminho local (`.png/.jpg/.mp4/.mov`) ou "pular". Skill faz upload (`/adimages` ou `/advideos` + thumbnail via ffmpeg).

4. Cria via `mcp__meta-official__ads_create_campaign + ads_create_ad_set + ads_create_ad`. Status sempre PAUSED.

5. Após criar, marque progresso:
   `python3 setup/setup_e6_test_campaign.py --mark-done <campaign_id>`

Apos terminar:

"Campanha criada em PAUSED!

Campaign ID: {campaign_id}
Ad Set ID: {adset_id}
Ad ID: {ad_id}
Nome: {name}

Tudo pausado — não vai gastar até você ativar.
Revise no Ads Manager: https://business.facebook.com/adsmanager/

Pronto para a Etapa 7?"

---

## Etapa 7 — Skill: Briefing Criativo

`[███████░░░] Etapa 7 de 10`

### O que e
Skill `meta-creative-brief` gera briefing completo de criativo (3 hooks copy + 3 hooks visuais + CTA + specs por placement).

### Para que serve
Voce repassa para designer/editor sem perder tempo redigindo briefing manualmente.

### Como voce vai usar no dia-a-dia
"briefing criativo para nicho imobiliaria, dor: corretor sem leads qualificados". Skill devolve markdown pronto.

### Pronto para instalar?
> Aguarde o aluno confirmar.

### Instalacao

1. Execute: `python3 setup/setup_e7_test_brief.py`
   — imprime instruções e prepara `~/.operacao-ia/briefings/`.

2. Invoque a skill `meta-creative-brief`. Pergunte ao aluno:
   - Nicho do cliente
   - Dor principal
   - Oferta

   Se aluno não tem cliente real, use exemplo:
   - Nicho: "agência marketing local"
   - Dor: "leads desqualificados que não fecham"
   - Oferta: "auditoria gratuita 30min"

3. Skill grava markdown em `~/.operacao-ia/briefings/<slug>-<data>.md`.

4. Marque progresso:
   `python3 setup/setup_e7_test_brief.py --mark-done <path-do-md>`

Apos terminar:

"Briefing entregue acima!

Salvo em: ~/.operacao-ia/briefings/<arquivo>.md
Use direto com designer ou cole no Sora/Midjourney pra gerar imagens.

Pronto para a Etapa 8?"

---

## Etapa 8 — Skills: Analyzer + Budget Optimizer

`[████████░░] Etapa 8 de 10`

### O que e
Duas skills em sequencia:
- `meta-performance-analyzer` — le o JSON do dashboard, aplica seu decide() e devolve top SCALE/KILL/KEEP
- `meta-budget-optimizer` — propoe nova alocacao de budget entre campanhas

### Para que serve
Decisoes de escala e budget viram comando de chat. Voce le o output, valida e aplica.

### Como voce vai usar no dia-a-dia
"analisar campanhas meta da semana" → tabela de decisoes
"realocar R$300/dia entre campanhas ativas" → plano + comandos prontos

### Pronto para instalar?
> Aguarde o aluno confirmar.

### Instalacao

1. Execute primeiro: `python3 setup/setup_e8_test_analyzer.py`
   — checa `paid-traffic-7d.json` e conta ads qualificados (com amostra ≥1.2× a meta).

2. Se contagem = 0, mostre ao aluno:
   "Ainda não há ads com amostra suficiente. Campanhas novas demoram 24-72h. Daqui a 1-3 dias rode `/meta-metrics-fetcher` e depois `meta-performance-analyzer`."
   → Pule pra Etapa 9.

3. Se contagem ≥ 1:
   - Invoque `meta-performance-analyzer` na janela 7d → top SCALE/KILL/KEEP.
   - Se houver campanhas ACTIVE, invoque `meta-budget-optimizer` com budget total = soma dos `daily_budget` atuais.
   - Mostre outputs. Pergunte se aluno quer aplicar 1 mudança via `mcp__meta-official__ads_update_entity`.

4. Marque progresso:
   `python3 setup/setup_e8_test_analyzer.py --mark-done`

Apos terminar:

"Analise + plano de budget concluidos!

Use no dia a dia para revisar performance semanal.

Pronto para a Etapa 9?"

---

## Etapa 9 — Automacao (LaunchAgents) e Server Persistente

`[█████████░] Etapa 9 de 10`

### O que e
Instala 2 jobs do macOS (LaunchAgents):
- `com.zxlab.meta-fetch` — roda fetcher 3x/dia (8h05/13h05/19h05)
- `com.zxlab.meta-dashboard-server` — keep-alive do `localhost:8888`

### Para que serve
Voce nao precisa lembrar de atualizar. Abre a aba e os dados ja estao frescos.

### Como voce vai usar no dia-a-dia
Esquece. Acesse `localhost:8888` quando quiser ver.

### Pronto para instalar?
> Aguarde o aluno confirmar.

### Instalacao
Execute: `python3 setup/setup_launchagents.py`

O script vai:
- Copiar 2 plists para `~/Library/LaunchAgents/`
- `launchctl load` em ambos
- Validar com `launchctl list | grep zxlab.meta` (deve retornar 2)

Apos o script:

"Automacao ativa!

Fetch: 8h05, 13h05, 19h05 (Brasilia)
Dashboard server: rodando 24/7 em http://localhost:8888

Pronto para a etapa final?"

---

## Etapa 10 — Auditoria Tecnica + Finalizacao

`[██████████] Etapa 10 de 10`

### O que e
Auditoria automatica que valida tudo + mensagem final de encerramento.

### Para que serve
Garante que tudo esta funcionando antes de encerrar.

### Antes de rodar, perguntar:
> "Recomendo rodar uma auditoria tecnica para garantir que tudo esta 100%. Leva menos de 1 minuto. Quer rodar? (Recomendado)"

### Instalacao
Execute primeiro: `python3 setup/setup_audit.py`

**IMPORTANTE:** Esta etapa deve usar Agent com Opus/Codex para revisao profunda independente.

O script vai:
- Verificar 12 checks (config, MCP token, perfil JSON, skills instaladas, dashboards JSON, launchagents, server respondendo, etc.)
- Corrigir automaticamente o que encontrar
- Mostrar relatorio final

Apos auditoria, execute: `python3 setup/setup_final_s6.py`

O script vai:
- Marcar `phase_completed = 6` no `config.json`
- Reabrir dashboard no browser
- Mostrar mensagem final (abaixo)

Apos o script, mostre exatamente esta mensagem final:

```
Setup 6 concluido!

O que voce tem agora:
- MCP oficial Meta conectado a conta {ad_account_id}
- 6 skills instaladas (5 especialistas + 1 agente orquestrador)
- Dashboard rodando em http://localhost:8888 (atualiza 8h/13h/19h)
- Estrategia decide() ativa nos KPIs: {kpis_lista}
- Metas configuradas: {metas_resumo}

Comandos do dia a dia:
/agente-trafego-pago        menu completo
/meta-campaign-launcher     criar nova campanha
/meta-creative-brief        gerar briefing
/meta-metrics-fetcher       atualizar dashboard agora
/meta-performance-analyzer  analise da semana
/meta-budget-optimizer      plano de realocacao

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Voce acabou de plugar trafego pago direto no Claude Code.
Conheca o ZX Control completo — mentoria semanal + todos os setups:
👉 https://zxlab.com.br/mission-control

Nos vemos no proximo setup!
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

---

## Contexto do Projeto (referencia interna)

- **Produto:** ZX Control — Mentoria de 30 dias (Growth 2.0)
- **Publico:** Infoprodutores, agencias e gestores de trafego que ja dominam Meta ADS
- **Objetivo Semana 6:** Plugar a operacao tecnica de trafego pago Meta direto no Claude Code
- **Pasta base do aluno:** `~/.operacao-ia/`
- **Pasta deste repositorio:** `~/zx-control-trafego-pago/` (ou onde o aluno clonou)
- **Config Meta:** `~/.operacao-ia/config/meta.env` (preenchido na Etapa 1)
- **Perfil de campanhas:** `~/.operacao-ia/config/meta_perfil.json` (Etapa 2)
- **Dashboards JSON:** `~/.operacao-ia/dashboards/paid-traffic-{4,7,14,30}d.json`
- **Dashboard HTML:** servido em `http://localhost:8888/paid-traffic-dashboard-7d.html`
- **Skills:** `~/.claude/skills/{agente-trafego-pago,meta-*}/`
- **MCP usado:** `mcp__meta-official__*` (oficial Meta — `mcp.facebook.com/ads`)
- **Token Meta:** `META_ACCESS_TOKEN` em `meta.env` (chmod 600). Fonte de verdade pro fetcher autônomo. Renovação: `setup_meta_oauth.py --renew`.
- **Uninstall:** `python3 setup/setup_uninstall.py` — opção [A] mantém skills, [B] remove tudo.
- **Glossário:** `docs/glossario.md` — CPL/CPA/ROAS/Pixel/CBO/ABO/Lookalike traduzidos.
- **Progress flags:** `~/.operacao-ia/config/setup6_progress.json` (e6_test_completed, e7_test_completed, e8_test_completed, demo_campaign_ids, fetch_skipped_reason).
