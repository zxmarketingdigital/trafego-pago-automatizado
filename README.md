# Tráfego Pago Automatizado com Claude Code

Conecte seu gerenciador de anúncios do Meta ao Claude Code e automatize a operação: mais de 5 habilidades que criam, gerenciam e otimizam campanhas, rastreamento por API e um dashboard que se atualiza sozinho 3x ao dia.

## Pré-requisitos

- macOS (recomendado), Windows 10/11 nativo ou Linux. No Windows, os comandos usam `python` em vez de `python3` (lá `python3` é o atalho da Microsoft Store).
- Python 3.9+
- Claude Code com MCP oficial Meta disponível (`mcp__meta-official__*`, endereço `mcp.facebook.com/ads`) — a Etapa 1 do setup conecta por OAuth automaticamente
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
- **Perfil de campanhas personalizado** (`~/.operacao-ia/config/meta_perfil.json`, ou a pasta do projeto do cliente) — métricas, metas e estratégia decide() escolhidas pelo aluno
- **Dashboard local** em `http://localhost:8888` com KPIs do perfil (um por projeto/cliente, cada um na sua porta)
- **2 LaunchAgents** (macOS) ou **2 tarefas no Agendador de Tarefas** (Windows) — fetch 3x/dia + dashboard server keep-alive

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
- **Windows nativo**: a Etapa 9 registra 2 tarefas no Agendador de Tarefas do usuário (sem admin): `ZXLab Meta Fetch` (08:05/13:05/19:05) e `ZXLab Meta Dashboard` (ao fazer logon, reinicia a cada 1 min), rodando `run_fetch_win.py` e `serve_dashboard_win.py` com `pythonw -X utf8`. Em projeto nomeado os nomes ganham ` - <nome>`. O uninstall ainda não remove essas tarefas: apague-as no Agendador ou com `Unregister-ScheduledTask -TaskName 'ZXLab Meta*'`.
- **LaunchAgents só macOS**: no Linux (e no WSL2, se preferir rodar o setup lá) agende com cron. Etapa 9 detecta SO e imprime as linhas prontas. Agende os dois jobs com `crontab -e`:
  ```
  5 8,13,19 * * * /bin/bash $HOME/.operacao-ia/scripts/meta/run_fetch.sh >> $HOME/.operacao-ia/logs/meta-fetch.cron.log 2>&1
  @reboot /bin/bash $HOME/.operacao-ia/scripts/meta/start_dashboard.sh
  ```
  (A Etapa 9 imprime essas linhas já prontas para o seu projeto. Em projeto nomeado, o caminho vira `$HOME/.operacao-ia/tpa-projetos/<nome>/scripts/meta/...` e cada linha termina com `# tpa:<nome>`; um projeto por vez, sem misturar.)
  O `@reboot` só dispara quando o WSL2 é iniciado (não junto com o Windows) — se preferir o dashboard sempre no ar, rode `bash ~/.operacao-ia/scripts/meta/start_dashboard.sh &` manualmente após abrir o WSL2, ou crie uma Tarefa Básica no Windows Task Scheduler que execute `wsl bash ~/.operacao-ia/scripts/meta/start_dashboard.sh` no logon.
- **Pixel ZX LAB hardcoded em demo**: aluno deve substituir pelo pixel próprio em E1 — setup pergunta.
- **Conflito com creative-roas-dashboard**: se aluno tem outro fetcher Meta rodando, E9 detecta e oferece pular meta-fetch.plist (evita duplicar chamadas API).
- **Decide() exige amostra ≥1.2× da meta**: ads com gasto baixo aparecem como "amostra insuficiente". Espere 24-72h pra acumular dados antes de decidir.
- **Token Meta persiste em `~/.operacao-ia/config/meta.env` (chmod 600)**: System User Tokens não expiram automaticamente. Se token for invalidado (troca de senha, desautorização), rode `python3 setup/setup_meta_oauth.py --renew`.
- **Uninstall disponível**: `python3 setup/setup_uninstall.py` reverte o setup. Opção [A] preserva skills, [B] remove tudo.
- **Vários clientes ou várias contas de anúncios: uma conta, um projeto por cliente.** Você usa o Tráfego Pago Automatizado em todos os seus clientes com a mesma conta do Claude, criando um projeto diferente para cada cliente; não precisa comprar nem instalar de novo por cliente. Cada projeto tem a própria pasta (configuração Meta, perfil de campanhas, dashboards, logs e briefings), a própria porta de dashboard (o primeiro projeto segue em `8888`; os novos usam `8889`, `8890`...) e os próprios agendamentos. Trocar de projeto nunca sobrescreve o outro. Quem já instalou e só atualiza (`git pull`) continua exatamente como está: o projeto padrão é a pasta `~/.operacao-ia` de sempre, sem migração e sem perder dado.
  Para configurar o segundo cliente, peça ao Claude ou rode:
  ```
  python3 setup/tpa_projeto.py criar <nome-do-cliente>
  ```
  e siga o setup normal (Etapas 0 a 10), usando o token e a conta de anúncios (`--set-account act_<id>`) daquele cliente. Comandos do dia a dia: `python3 setup/tpa_projeto.py listar` (projetos, conta e porta), `trocar <nome>` (muda o projeto ativo; `trocar default` volta ao padrão), `atual` e `caminho`. Para rodar um comando em outro projeto sem trocar o ativo: `TPA_PROJECT=<nome> python3 setup/setup_meta_oauth.py --validate`. `setup_meta_oauth.py --set-account` recusa trocar a conta já gravada num projeto (protege o cliente atual); para corrigir um id digitado errado use `--set-account act_<id> --substituir-conta`. A pasta base pode ser trocada com a variável `OPERACAO_IA_HOME`; o `config/config.json` (progresso do ZX Control) continua único e compartilhado.

## Suporte

Suporte: https://suporte.zxlab.com.br/hub
