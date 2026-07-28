---
name: meta-metrics-fetcher
description: "Atualiza seu dashboard de tráfego com os dados mais recentes da sua conta Meta. Roda automático 3x/dia, mas você pode forçar agora. Triggers: atualizar métricas meta, atualizar dashboard tráfego, refresh meta, puxar dados meta, atualizar paid traffic."
model: sonnet
effort: low
---

# meta-metrics-fetcher

Roda `~/.operacao-ia/scripts/meta/fetch_metrics.py` que coleta insights da sua conta Meta e gera os JSONs do dashboard.

## Fluxo

1. Valida que `~/.operacao-ia/config/meta.env` tem `META_ACCESS_TOKEN` e `META_AD_ACCOUNT_ID`. Se faltar, instrui:
   ```
   Token Meta inválido. Rode:
     python3 setup/setup_meta_oauth.py --renew
   ```

2. Lê janelas de `~/.operacao-ia/config/meta_perfil.json` (default 4d, 7d, 14d, 30d).

3. Pra cada janela, chama Graph API `act_<id>/insights?level=ad&time_range=...` com fields: spend, impressions, clicks, reach, frequency, cpm, ctr, cpc, actions, action_values.

4. Aplica `decide()` por ad usando limiares do perfil.

5. Grava `~/.operacao-ia/dashboards/paid-traffic-{N}d.json`.

## Como invocar

```bash
python3 ~/.operacao-ia/scripts/meta/fetch_metrics.py
```

Ou se rodando como script diário (LaunchAgent):
```bash
bash ~/.operacao-ia/scripts/meta/run_fetch.sh
```

(`run_fetch.sh` carrega `meta.env` antes de rodar — necessário fora de TTY).

## Output ao aluno

```
✅ Dashboard atualizado.

Janelas geradas: 4d, 7d, 14d, 30d
KPIs:
  - CPL R$22.50 (meta R$25 — verde, 10% abaixo)
  - CPM R$45.20 (meta R$50 — verde)
  - CTR 1.8% (meta 1.5% — verde)

Abra: http://localhost:8888
```

## Glossário

`docs/glossario.md`.
