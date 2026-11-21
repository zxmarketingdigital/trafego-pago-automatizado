---
name: meta-api-checagem
description: "Checa se a versão da Graph API da Meta usada pelos scripts está perto de expirar ou recebeu aviso de descontinuação, e agenda essa checagem toda semana. Só leitura. Triggers: checar versão da API Meta, a API da Meta vai expirar, aviso de descontinuação Meta, versão da Graph API, verificar API Meta, agendar checagem semanal da API, meu fetch parou de funcionar depois de uma atualização da Meta, status da API Meta."
model: sonnet
effort: low
---

> **Pasta do projeto.** `~/.operacao-ia` neste arquivo é a pasta do projeto vigente. Instalação com um cliente só: é exatamente `~/.operacao-ia`. Com um projeto por cliente: o nome do projeto ativo está em `~/.operacao-ia/tpa-projetos/ativo` (ou na variável `TPA_PROJECT`, que tem prioridade) e a pasta dele é `~/.operacao-ia/tpa-projetos/<nome>/`. Nunca misture arquivos de dois projetos.

# Checagem da API da Meta

Funciona igual no Claude Code e no Codex, em macOS, Windows e Linux (no Windows use `python` no lugar de `python3`).

O script faz uma chamada de leitura (`GET /me`) e lê o que a própria Meta respondeu: versão servida, cabeçalhos de descontinuação e texto de erro. Não existe tabela de datas dentro dele e ele nunca altera a conta de anúncios.

## Rodar agora

Na pasta do repositório (onde o aluno clonou o projeto):

```bash
python3 scripts/check_api_version.py                 # projeto vigente
python3 scripts/check_api_version.py --projeto <nome>
python3 scripts/check_api_version.py --todos         # agência: todos os projetos com token
```

Mostre ao aluno o resumo que o script imprime. Resultado em `~/.operacao-ia/dashboards/api-status.json` (o dashboard e o relatório diário leem esse arquivo).

| Status | O que dizer e fazer |
|---|---|
| `ok` | "A Meta não avisou nada hoje." Não prometa que a versão não vai expirar. |
| `atencao` | A Meta avisou descontinuação ou há data de encerramento próxima. Proponha atualizar a versão da Graph API nos scripts e peça confirmação antes de editar. |
| `critico` | A versão pedida já saiu do ar. Proponha atualizar já e rodar `python3 ~/.operacao-ia/scripts/meta/fetch_metrics.py` depois. |
| `erro` | Token recusado ou falha: `python3 setup/setup_meta_oauth.py --renew`. |
| `nao_verificado` | Falta token ou rede: refazer a Etapa 1. |

## Agendar toda semana

```bash
python3 scripts/check_api_version.py --agendamento --projeto <nome>
```

Imprime a linha pronta para cron (Linux/WSL2) e para o Agendador de Tarefas (Windows); o modelo do launchd (macOS) está em `docs/checagem-api-meta.md`. Cole a linha por conta do aluno só depois de ele confirmar (mexe no agendador do sistema).

## Regras

- Só leitura: nada de criar, pausar ou editar campanha nesta skill.
- Nunca mostre token nem o conteúdo do `meta.env`.
- Atualizar a versão nos scripts é uma edição de código: mostre o diff e confirme com o aluno antes.
