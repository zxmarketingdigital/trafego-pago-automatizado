# MasterClass — Tráfego Pago Automatizado com Claude Code

> Roteiro da aula. Os `BUNNY_GUID_*` são preenchidos depois de gravar e cortar
> a aula — não preencha valores reais aqui.

## Promessa da aula

Sair do Ads Manager aberto o dia inteiro para uma **operação de tráfego pago
conduzida pelo Claude Code**: métricas coletadas sozinhas, um dashboard que
mostra só o que importa para o seu tipo de campanha, e skills que criam
campanha, escrevem briefing, analisam a semana e propõem onde colocar a verba.

Ao final o aluno tem: Meta conectado via MCP oficial, perfil de campanhas
configurado, 9 skills instaladas, dashboard local rodando e a coleta de
métricas agendada 3x por dia no próprio computador.

## Estrutura geral (duração estimada: 60min)

| # | Bloco | Etapas | Vídeo |
|---|-------|--------|-------|
| 1 | Hook + o que você vai construir | E0 | `BUNNY_GUID_E0` |
| 2 | Conectar o Meta pelo MCP oficial | E1 | `BUNNY_GUID_E1` |
| 3 | Perfil de campanhas: o setup se adapta a você | E2 | `BUNNY_GUID_E2` |
| 4 | Skills + agente orquestrador | E3 | `BUNNY_GUID_E3` |
| 5 | Primeira coleta de métricas | E4 | `BUNNY_GUID_E4` |
| 6 | Dashboard local | E5 | `BUNNY_GUID_E5` |
| 7 | Criar campanha pelo chat | E6 | `BUNNY_GUID_E6` |
| 8 | Briefing criativo | E7 | `BUNNY_GUID_E7` |
| 9 | Analyzer + otimizador de verba | E8 | `BUNNY_GUID_E8` |
| 10 | Automação da coleta | E9 | `BUNNY_GUID_E9` |
| 11 | Auditoria e fechamento | E10 | `BUNNY_GUID_E10` |

## Roteiro

### 1. Abertura (Etapa 0 — Diagnóstico da base)

Abrir pela dor concreta: gerir tráfego pago hoje é abrir o Ads Manager, exportar
planilha, calcular CPL na mão e decidir no feeling. O setup troca isso por uma
conversa com o Claude Code.

- **O que o aluno constrói:** a verificação do ambiente (Python, gh, Claude Code)
  e a estrutura de pastas em `~/.operacao-ia/`.
- **Por que importa:** todos os módulos seguintes gravam e leem dessas pastas.
- **Demo:** rodar `python3 setup/check_prerequisites.py` e depois
  `python3 setup/setup_base_s6.py`, mostrando o plano das 10 etapas.

### 2. Conectar o Meta (Etapa 1)

- **O que o aluno constrói:** a conexão OAuth com o MCP oficial do Meta
  (`mcp.facebook.com/ads`), com o token sincronizado para a coleta automática.
- **Por que importa:** sem isso nada funciona — é a única fonte de verdade para
  criar campanha, ler resultado e ajustar orçamento.
- **Demo:** autenticar pela Via A, listar as contas de anúncio e escolher a conta
  com `--set-account`. Mostrar a Via B (token de System User) como plano B para
  quem recebe erro de `redirect_uris` ou lista de contas vazia.

### 3. Perfil de campanhas (Etapa 2)

- **O que o aluno constrói:** o `meta_perfil.json` com objetivos, métricas-chave,
  metas numéricas, KPI primário e as regras de decisão (matar/manter/escalar).
- **Por que importa:** quem roda Lead não quer ver ROAS; quem roda alcance não
  quer CPL. Tudo o que vem depois se adapta a esse perfil.
- **Demo:** responder o questionário ao vivo com um exemplo de campanha de Lead e
  mostrar o resumo final. Reforçar: **1 conta de anúncios por instalação**.

### 4. Skills + agente orquestrador (Etapa 3)

- **O que o aluno constrói:** as 9 skills em `~/.claude/skills/` — orquestrador,
  criar campanha, briefing, coleta de métricas, analyzer, otimizador de verba e
  os bônus (CAPI, relatório por e-mail e por WhatsApp).
- **Por que importa:** cada tarefa de tráfego vira um comando no chat.
- **Demo:** chamar `/agente-trafego-pago` e mostrar o menu.

### 5. Primeira coleta de métricas (Etapa 4)

- **O que o aluno constrói:** os primeiros arquivos `paid-traffic-{N}d.json`,
  um por janela de análise.
- **Por que importa:** valida de uma vez que o MCP, o perfil e o formato de dados
  estão certos antes de montar o painel.
- **Demo:** rodar a coleta e mostrar o status verde/amarelo/vermelho de cada KPI.

### 6. Dashboard local (Etapa 5)

- **O que o aluno constrói:** o painel em `http://localhost:8888`, só com as
  métricas que ele escolheu.
- **Por que importa:** uma aba aberta substitui o vai-e-vem no Ads Manager.
- **Demo:** navegar pelos cards de KPI, pelas abas de janela (4d/7d/14d/30d) e
  pelo drill-down conta → campanha → conjunto → anúncio.

### 7. Criar campanha pelo chat (Etapa 6)

- **O que o aluno constrói:** uma campanha real criada pela skill
  `meta-campaign-launcher`, sempre em **PAUSED**.
- **Por que importa:** a campanha já sai montada para revisão — sem gastar nada
  até o aluno ativar.
- **Demo:** descrever a campanha em linguagem natural, subir um criativo e abrir
  o resultado no Ads Manager.

### 8. Briefing criativo (Etapa 7)

- **O que o aluno constrói:** um briefing completo (3 hooks de copy, 3 hooks
  visuais, CTA e especificações por posicionamento) salvo em
  `~/.operacao-ia/briefings/`.
- **Por que importa:** o designer ou editor recebe o briefing pronto.
- **Demo:** usar o exemplo "agência de marketing local / leads desqualificados /
  auditoria gratuita de 30 min" e mostrar o markdown gerado.

### 9. Analyzer + otimizador de verba (Etapa 8)

- **O que o aluno constrói:** a leitura da semana pelo `meta-performance-analyzer`
  (quem escalar, manter ou pausar) e o plano de realocação do
  `meta-budget-optimizer`.
- **Por que importa:** a decisão deixa de ser feeling e passa a seguir as regras
  que o próprio aluno definiu na Etapa 2.
- **Demo:** rodar o analyzer sobre os dados coletados e mostrar a proposta de
  nova divisão de verba.

### 10. Automação da coleta (Etapa 9)

- **O que o aluno constrói:** o agendamento no próprio computador que roda a
  coleta 3x por dia e mantém o dashboard no ar.
- **Por que importa:** o painel se atualiza sozinho, sem o aluno lembrar de rodar
  nada.
- **Demo:** mostrar o agendamento instalado e o horário da próxima coleta.

### 11. Auditoria e fechamento (Etapa 10)

- **O que o aluno constrói:** a auditoria técnica que confere todas as etapas.
- **Por que importa:** o aluno sai da aula sabendo que tudo está funcionando, não
  achando.
- **Demo:** rodar a auditoria, mostrar tudo verde e recapitular a rotina do dia a
  dia: abrir o dashboard, pedir a análise da semana e aplicar o plano de verba.
