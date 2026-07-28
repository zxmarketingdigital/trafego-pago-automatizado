---
name: meta-performance-analyzer
description: "Analisa performance das campanhas Meta usando o decide() personalizado do aluno (limiares scale_at/kill_at do perfil) e retorna ranking de ações: top 3 SCALE, top 3 KILL, top KEEP a monitorar. Lê paid-traffic-{N}d.json e meta_perfil.json. Use SEMPRE que o aluno disser: analisar campanhas meta, performance da semana, qual ad escalar, qual matar, relatorio meta, analise meta, analise trafego pago, performance meta ads."
model: sonnet
effort: high
---

# Meta Performance Analyzer

Diagnóstico semanal de tráfego pago Meta com decisões prontas.

## Inputs

1. Pergunte ao aluno qual janela analisar (default 7d). Se ele disser "essa semana" use 7d, "mês" use 30d, etc.
2. Leia:
   - `~/.operacao-ia/dashboards/paid-traffic-{N}d.json`
   - `~/.operacao-ia/config/meta_perfil.json`

Se o JSON não existe, oriente a rodar `meta-metrics-fetcher` primeiro.

## Análise

1. Para cada ad no JSON, leia `decide` e `decide_reason` (já calculado pelo fetcher)
2. Agrupe por decisão: SCALE / KILL / KEEP
3. Ordene cada grupo por `spend` desc (alta prioridade primeiro)
4. Compare KPI primário vs `target` por ad — calcule % delta
5. Identifique padrões: "todos os ads de público lookalike-X estão SCALE", "campanhas Reels superam Feed em CTR", etc.

## Output (markdown)

```markdown
# 📊 Análise Meta ADS — janela {N}d

**Conta:** act_xxxxx
**Período:** {since} → {until}
**Spend total:** R${spend_total}
**KPI primário:** {primary_kpi} (meta R${target})

## Status global do KPI primário
{primary_kpi}: R${value} vs meta R${target} — {🟢 / 🟡 / 🔴} ({delta_pct}%)

---

## 🟢 TOP 3 SCALE (escalar agora)

| Ad | Spend | {KPI} | vs meta | Razão |
|---|---|---|---|---|
| {ad_name 1} | R${spend} | R${kpi} | -25% | CPL bem abaixo + amostra |
| ... | ... | ... | ... | ... |

## 🔴 TOP 3 KILL (pausar)

| Ad | Spend | {KPI} | vs meta | Razão |
|---|---|---|---|---|
| {ad_name 1} | R${spend} | R${kpi} | +85% | CPL muito acima sem indício de melhora |
| ... | ... | ... | ... | ... |

## 🟡 KEEP (manter monitorando)

{lista resumida — 5-10 ads}

---

## Padrões observados

- {insight 1: ex. "Lookalike 1% supera Lookalike 3% em CPL"}
- {insight 2: ex. "Criativo vídeo tem CTR 40% maior que estático"}
- {insight 3: ex. "Sexta-feira tem CPL 30% mais alto — considerar reduzir budget"}

---

## Próximas ações sugeridas

1. Pausar os 3 ads do bloco KILL → economia estimada de R${spend_kill}/dia
2. Aumentar budget dos 3 SCALE em 30% → testar se mantém CPL
3. Replicar padrão {insight} em novas campanhas
```

## Regras

- Nunca recomende ação sem mostrar o número
- Se decide() está desabilitado no perfil (`decide_enabled: false`), faça análise descritiva sem dar veredito
- Se `spend < target × 1.2` para um ad, marque como "amostra insuficiente" — não classifique
- Inclua sempre o nome real do ad e ID curto (últimos 8 dígitos)
