---
name: meta-dashboard-agencia
description: "Painel consolidado de todos os clientes (versão agência): lista e soma gasto, resultado, custo por resultado, CPA e ROAS de cada projeto/conta Meta, com total por moeda. Triggers: painel de todos os clientes, dashboard da agência, resumo de todas as contas, quanto gastei em todos os clientes, comparar clientes, visão geral dos projetos, consolidado de contas Meta, ROAS por cliente."
model: sonnet
effort: low
---

> **Pasta do projeto.** `~/.operacao-ia` é a pasta base. Cada cliente é um projeto em `~/.operacao-ia/tpa-projetos/<nome>/` (o projeto padrão é a própria base). Este painel lê todos eles, só leitura.

# Painel de clientes (agência)

Funciona igual no Claude Code e no Codex, em macOS, Windows e Linux (no Windows use `python`). Usa os JSONs que o coletor de cada projeto já gerou; não recalcula nada que o coletor calculou.

## Rodar

Na pasta do repositório:

```bash
python3 scripts/dashboard_agencia.py                    # resumo no terminal, janela de 7 dias
python3 scripts/dashboard_agencia.py --janela 30        # outra janela
python3 scripts/dashboard_agencia.py --atualizar        # roda o coletor de cada projeto antes (só leitura)
python3 scripts/dashboard_agencia.py --saida html       # grava ~/.operacao-ia/dashboard-agencia/index.html
python3 scripts/dashboard_agencia.py --servir           # grava e serve em http://127.0.0.1:8887
python3 scripts/dashboard_agencia.py --projetos a,b     # só alguns clientes
```

Mostre a tabela ao aluno: gasto, resultado, custo por resultado, CPA e ROAS por cliente, e o total por moeda.

## Como ler

- Moedas diferentes nunca são somadas: há um total por moeda.
- Resultado e custo por resultado só são somados entre clientes com o mesmo KPI (lead com lead, compra com compra).
- "dado defasado" = a última coleta tem mais de 26 horas: rode com `--atualizar` ou confira o agendamento daquele projeto.
- "sem coleta na janela" = o projeto ainda não rodou o coletor para essa janela.
- A coluna "API Meta" vem da checagem semanal (`meta-api-checagem`).

## Regras

- `--atualizar` chama a API da Meta uma conta por vez (leitura). Avise quantos clientes serão atualizados antes de rodar.
- O servidor local escuta só em `127.0.0.1`. Para ver de fora (VPS, celular) use túnel com login, nunca abra a porta: veja `docs/vps.md`.
- Nunca mostre token nem o conteúdo de `meta.env`.
