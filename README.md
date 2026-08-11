# Tráfego Pago Automatizado com Claude Code

Conecte seu gerenciador de anúncios do Meta ao Claude Code e automatize a operação: mais de 5 habilidades que criam, gerenciam e otimizam campanhas, rastreamento por API e um dashboard que se atualiza sozinho 3x ao dia.

## Pré-requisitos

- macOS (recomendado) ou Windows via WSL2 (Windows Subsystem for Linux — ver "Limitações conhecidas" abaixo para o agendamento). Linux nativo também funciona.
- Python 3.9+
- Claude Code com MCP oficial Meta disponível (`mcp__meta-official__*`)
- Conta Meta Business + Ad Account ativa

## Instalação

```bash
git clone https://github.com/zxmarketingdigital/trafego-pago-automatizado
cd trafego-pago-automatizado
claude
```

Ao abrir o Claude, ele vai aguardar você digitar **`INICIAR SETUP`** para começar.

A partir daí o setup é guiado — 10 etapas, cada uma com explicação + execução + validação.

## O que será instalado

- **MCP oficial Meta** conectado via OAuth
- **5 skills + 1 agente orquestrador** em `~/.claude/skills/`:
  - `agente-trafego-pago` (orquestrador)
  - `meta-campaign-launcher`
  - `meta-creative-brief`
  - `meta-metrics-fetcher`
  - `meta-performance-analyzer`
  - `meta-budget-optimizer`
- **Perfil de campanhas personalizado** (`~/.operacao-ia/config/meta_perfil.json`) — métricas, metas e estratégia decide() escolhidas pelo aluno
- **Dashboard local** em `http://localhost:8888` com KPIs do perfil
- **2 LaunchAgents** (macOS) — fetch 3x/dia + dashboard server keep-alive

## Estrutura

```
zx-control-trafego-pago/
├─ CLAUDE.md            # roteiro de instalação (lido pelo Claude Code)
├─ setup/               # 9 scripts Python das etapas
├─ skills/              # 6 SKILL.md
├─ scripts/             # fetch_metrics, dashboard generator, server starter
├─ docs/                # template HTML do dashboard
└─ launchagents/        # 2 plists macOS
```

## Comandos pós-instalação

```
/agente-trafego-pago        menu completo
/meta-campaign-launcher     criar nova campanha
/meta-creative-brief        gerar briefing criativo
/meta-metrics-fetcher       atualizar dashboard agora
/meta-performance-analyzer  análise da semana
/meta-budget-optimizer      plano de realocação
```

## Limitações conhecidas

- **MCP oficial Meta com rollout gradual**: nem toda conta tem `is_ads_mcp_enabled=true`. Setup detecta e oferece fallback via System User Token (`setup_meta_oauth.py --renew`).
- **LaunchAgents só macOS**: Linux/Windows precisam de cron manual. Etapa 9 detecta SO e pula automaticamente. **No Windows, use WSL2** (Windows Subsystem for Linux — `wsl --install` no PowerShell como admin, depois rode todo o setup dentro do WSL2 como se fosse Linux). Dentro do WSL2, agende os dois jobs com `crontab -e`:
  ```
  5 8,13,19 * * * /bin/bash $HOME/.operacao-ia/scripts/meta/run_fetch.sh >> $HOME/.operacao-ia/logs/meta-fetch.cron.log 2>&1
  @reboot /bin/bash $HOME/.operacao-ia/scripts/meta/start_dashboard.sh
  ```
  O `@reboot` só dispara quando o WSL2 é iniciado (não junto com o Windows) — se preferir o dashboard sempre no ar, rode `bash ~/.operacao-ia/scripts/meta/start_dashboard.sh &` manualmente após abrir o WSL2, ou crie uma Tarefa Básica no Windows Task Scheduler que execute `wsl bash ~/.operacao-ia/scripts/meta/start_dashboard.sh` no logon.
- **Pixel ZX LAB hardcoded em demo**: aluno deve substituir pelo pixel próprio em E1 — setup pergunta.
- **Conflito com creative-roas-dashboard**: se aluno tem outro fetcher Meta rodando, E9 detecta e oferece pular meta-fetch.plist (evita duplicar chamadas API).
- **Decide() exige amostra ≥1.2× da meta**: ads com gasto baixo aparecem como "amostra insuficiente". Espere 24-72h pra acumular dados antes de decidir.
- **Token Meta persiste em `~/.operacao-ia/config/meta.env` (chmod 600)**: System User Tokens não expiram automaticamente. Se token for invalidado (troca de senha, desautorização), rode `python3 setup/setup_meta_oauth.py --renew`.
- **Uninstall disponível**: `python3 setup/setup_uninstall.py` reverte o setup. Opção [A] preserva skills, [B] remove tudo.

## Suporte

Suporte: https://suporte.zxlab.com.br/hub
