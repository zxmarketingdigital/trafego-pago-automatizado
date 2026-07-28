# PLAN.md — Arquitetura interna Setup 6

Documento técnico para mantenedor (Rafael Castro). Aluno não precisa ler.

## Princípio de design

Setup é **personalizado pelo aluno via questionário (E2)**. Tudo o que vem depois (fetcher, dashboard, analyzer, optimizer) lê `~/.operacao-ia/config/meta_perfil.json` e se adapta.

Aluno que roda Lead vê CPL. Aluno que roda venda vê ROAS. Aluno de WhatsApp vê custo/msg. Sem código duplicado — apenas dados de configuração.

## Fluxo de dados

```
Aluno (E2)
  └→ meta_perfil.json {kpis, targets, decide_thresholds}
       └→ fetch_metrics.py → paid-traffic-{N}d.json (campos dinâmicos)
            └→ paid_traffic_dashboard.py → paid-traffic-dashboard-{N}d.html
            └→ meta-performance-analyzer (skill) → markdown decide()
            └→ meta-budget-optimizer (skill) → plano realocação
```

## Schema meta_perfil.json

```json
{
  "objectives": ["LEAD_GENERATION", "MESSAGES"],
  "kpis": [
    {"key":"cpl","label":"CPL","target":25,"better":"lower","format":"currency","scale_at":0.8,"kill_at":1.5}
  ],
  "primary_kpi": "cpl",
  "decide_enabled": true,
  "windows": [4,7,14,30],
  "ad_account_id": "act_..."
}
```

## Schema paid-traffic-{N}d.json

```json
{
  "generated_at": "ISO timestamp",
  "window_days": 7,
  "ad_account_id": "act_...",
  "currency": "BRL",
  "perfil_kpis": ["cpl","ctr"],
  "primary_kpi": "cpl",
  "kpis_summary": {
    "cpl": {"value":20.4,"target":25,"delta_pct":-18.4,"status":"green"}
  },
  "campaigns": [...]
}
```

## Decisão `decide()`

Lê `kpis[].scale_at` e `kpis[].kill_at` do perfil. Calcula em função de `better`:

- **lower** (CPL/CPA/CPM): SCALE se `metric ≤ target × scale_at`; KILL se `metric > target × kill_at`
- **higher** (ROAS/CTR): SCALE se `metric ≥ target × (2-scale_at)`; KILL se `metric < target × (2-kill_at)`

Sempre exige amostra mínima (`spend ≥ target × 1.2`) — caso contrário retorna `KEEP-amostra`.

## MCP usado

Único: `mcp__meta-official__*` — sem fallback. Tools principais:
- `authenticate` / `complete_authentication` (OAuth)
- `ads_get_ad_accounts`
- `ads_get_ad_entities`
- `ads_insights_*`
- `ads_create_campaign / ads_create_ad_set / ads_create_ad`
- `ads_update_entity`

## LaunchAgents

- `com.zxlab.meta-fetch.plist` — `StartCalendarInterval` 8h05/13h05/19h05 BRT, roda `python3 ~/.operacao-ia/scripts/meta/fetch_metrics.py`
- `com.zxlab.meta-dashboard-server.plist` — `KeepAlive=true`, roda `python3 -m http.server 8888 --directory ~/.operacao-ia/dashboards/`

## Versões

- v0.1.0 — Implementação inicial completa
