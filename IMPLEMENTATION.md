# IMPLEMENTATION.md

## v0.2.0 — Fixes pós-demo (2026-05-06)

Refatoração pós-demo end-to-end. 9 fixes endereçando buracos detectados durante simulação aluno novato.

- **FIX 1 — Token persistente**: `setup_meta_oauth.py` ganha modo `--renew` (Via B System User Token), `--set-token`, `--validate` agora chama Graph API. `fetch_metrics.py:read_token()` lê só de `meta.env` (fonte de verdade). Novo `scripts/run_fetch.sh` wrapper carregado pelo plist.
- **FIX 2 — E6/E7/E8 testáveis**: novos `setup/setup_e6_test_campaign.py`, `setup_e7_test_brief.py`, `setup_e8_test_analyzer.py` que executam as skills com input padrão durante o setup, em vez de só descrever no CLAUDE.md.
- **FIX 3 — Skills context-aware**: `meta-campaign-launcher` lista páginas FB do BM, pixels da conta e audiências em vez de exigir IDs digitados. Suporte a vídeo via `/act_<id>/advideos` + thumbnail auto via ffmpeg.
- **FIX 4 — Decide presets**: `setup_perfil_campanhas.py` ganha 3 presets (CONSERVADOR/AGRESSIVO/PERSONALIZADO). `decide_preset` salvo em `meta_perfil.json`.
- **FIX 5 — Uninstall**: novo `setup/setup_uninstall.py` com opções A (manter skills) e B (remover tudo). Reverte `phase_completed` 6→5.
- **FIX 6 — Conflict detection**: `setup_launchagents.py` detecta outros fetchers Meta (creative-roas-dashboard, meta-capi-refund) e oferece pular `meta-fetch.plist`.
- **FIX 7 — Mensagens erro**: `fetch_metrics.py` quando sem token mostra diagnóstico + comando exato pra renovar.
- **FIX 8 — Linguagem comercial**: novo `docs/glossario.md` com termos técnicos traduzidos. Skills e perfil adotam tom comercial.
- **FIX 9 — Docs**: README ganha seção "Limitações conhecidas".

## v0.1.1 — Codex-review fixes (2026-05-06)

10 correções pós-review do Codex (5 ALTO + 3 MÉDIO + 2 BAIXO):

**ALTO**
- `scripts/fetch_metrics.py` — agregação reescrita: armazena counters raw (spend, leads, purchases, msgs, impressions, clicks, reach, purchase_value, installs) em ad/adset/campaign/conta. KPIs derivados via `sum/sum` em cada nível (CPL, CPA, ROAS, CTR, CPM, CPC, custo/msg, frequência) — nunca mais média ponderada de razões.
- `scripts/fetch_metrics.py` — fail-loud: exit code 2 se qualquer janela falha; falha total no `campaign_meta` interrompe o fetch (exit 2).
- `scripts/fetch_metrics.py` — busca `effective_status` + `daily_budget` + `lifetime_budget` + `bid_strategy` por campanha (necessário para `meta-budget-optimizer`).
- `scripts/fetch_metrics.py` — token Meta movido da query string para header `Authorization: Bearer` (limpa `access_token=` de URLs paginadas vindas do `.next`).
- `scripts/fetch_metrics.py` — `ACTION_TYPES` aceita variantes (lead + onsite_conversion.lead_grouped + leadgen.other + offsite_conversion.fb_pixel_lead; idem purchase + msg + install).
- `setup/setup_perfil_campanhas.py` — valida `target > 0` em todas as KPIs; valida limiares 0 < scale_at/kill_at <= 5.
- `setup/setup_perfil_campanhas.py` — modos `--template` / `--apply <json>` / `--show` para fluxo headless. Sem TTY → recusa interativo e instrui Claude.
- `setup/setup_meta_oauth.py` — modos `--set-account act_X` (grava idempotente em `meta.env`) e `--validate` (verifica token + `meta.env` preenchido).

**MÉDIO**
- `setup/setup_skills.py` — não destrói skills meta-* customizadas. Compara árvore via `filecmp.dircmp`; se diff existe, faz backup em `~/.claude/skills/.s6-backup-{slug}-{timestamp}/` antes de instalar.

**BAIXO**
- `docs/paid-traffic-dashboard-template.html` — wrapper `.table-wrap` com `overflow-x: auto` e `min-width: 720px` na tabela para evitar overflow horizontal com 9 KPIs.
- `zx-control-2-growth/docs/index.html` — badge S6 não conta painel id=0 (aulas) no numerador (filtra `id > 0`), mantém denominador 10.

## v0.1.0 — Lançamento inicial (2026-05-06)

Setup 6 do ZX Control 2.0 Growth — Tráfego Pago Meta ADS.

### Componentes entregues

- `CLAUDE.md` student-facing modelado em `zx-control-semana3` (header guard + boas-vindas + 8 regras + 10 etapas + finalização com CTA ZX Control)
- 9 setup scripts Python (`setup/setup_*.py`)
- 6 skills (`skills/{agente-trafego-pago,meta-*}/SKILL.md`)
- 3 scripts core (`scripts/fetch_metrics.py`, `paid_traffic_dashboard.py`, `start_dashboard.sh`)
- 1 dashboard HTML template (`docs/paid-traffic-dashboard-template.html`)
- 2 LaunchAgents (`launchagents/com.zxlab.meta-{fetch,dashboard-server}.plist`)

### Decisões técnicas

- MCP único = `mcp__meta-official__*` (sem fallback `meta_ads__*`)
- Skills todas `sonnet/high`
- Dashboard adapta colunas dinamicamente conforme `meta_perfil.json` do aluno
- decide() configurável por aluno (limiares `scale_at` e `kill_at` por KPI)
- Sem aulas teóricas — só mentoria de instalação técnica
