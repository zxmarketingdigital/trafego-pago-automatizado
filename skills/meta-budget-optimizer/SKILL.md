---
name: meta-budget-optimizer
description: "Realoca budget entre campanhas Meta com base na eficiência do KPI primário do aluno. Recebe orçamento total diário e devolve plano de redistribuição (campanha-por-campanha) + comandos prontos via mcp__meta-official__ads_update_entity. Use SEMPRE que o aluno disser: realocar budget meta, otimizar verba, escalar orcamento, redistribuir gasto, plano de budget, otimizar budget meta, alocar verba meta."
model: sonnet
effort: high
---

# Meta Budget Optimizer

Plano de realocação de budget entre campanhas ativas baseado em performance.

## Inputs

1. Pergunte ao aluno:
   - Orçamento total diário disponível (em reais)
   - Janela de referência para análise (default 7d)
   - Aceita zerar campanhas em KILL? (sim/não)
2. Leia `paid-traffic-{N}d.json` + `meta_perfil.json`

## Algoritmo

1. Filtre campanhas com `effective_status` ACTIVE e `spend > 0`
2. Para cada campanha, calcule `efficiency`:
   - **better=lower** (ex CPL): `efficiency = target / kpi_value × qualified_factor`
   - **better=higher** (ex ROAS): `efficiency = kpi_value / target × qualified_factor`
   - `qualified_factor` = 1.0 padrão; ajuste para 0.5 se objetivo é LEAD e qualified_rate < 0.3
3. Normalize eficiências para somar 1.0
4. Distribua orçamento total proporcional à eficiência
5. Aplique guard-rails:
   - Mínimo R$10/dia por campanha (se não está em KILL)
   - Máximo +50% vs budget atual (evitar choque)
   - Campanhas KILL → R$1/dia (ou pausar se aluno autorizou)

## Output

```markdown
# 💰 Plano de Realocação — Budget total R${total_budget}/dia

**Conta:** act_xxxxx
**Janela analisada:** {N}d
**KPI primário:** {primary_kpi} (meta R${target})

## Plano por campanha

| Campanha | Atual | Sugerido | Δ | KPI atual | Razão |
|---|---|---|---|---|---|
| Lookalike 1% Lead | R$50 | R$80 | +60% | R$18 | Eficiência alta, escalar |
| Interesse Marketing | R$40 | R$45 | +12% | R$22 | Mantém |
| Lookalike 3% Lead | R$30 | R$10 | -67% | R$45 | Acima da meta, reduzir |
| Reativação Custom | R$30 | R$1 | -97% | R$120 | KILL — pausar manualmente |

**Totais:** R$150 → R$136 (sobra R$14 para teste de novo criativo)

## Comandos para aplicar

```bash
# Lookalike 1% Lead
mcp__meta-official__ads_update_entity(
  entity_id="120210xxxxx",
  entity_type="campaign",
  daily_budget=8000  # em centavos
)

# ... (um por campanha alterada)
```

## Recomendações

1. Aplique 1 mudança por dia para isolar efeito
2. Re-rode `/meta-metrics-fetcher` 24h após cada mudança
3. Se KPI piorar em 2 dias seguidos, reverta
```

## Regras

- Nunca aplique automaticamente — só gere os comandos prontos
- Sempre confirme com o aluno antes de invocar `ads_update_entity`
- Se campanha tem CBO (Campaign Budget Optimization), edite o budget do campaign; se ABO, edite ad set
- Mostre sempre o delta percentual + razão por trás
