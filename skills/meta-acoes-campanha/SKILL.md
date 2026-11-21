---
name: meta-acoes-campanha
description: "Pausa, ativa e ajusta o orçamento diário de campanhas, conjuntos e anúncios da Meta por comando, SEMPRE mostrando o plano antes→depois e só aplicando com confirmação (--confirmar). Grava cada mudança num registro para auditar e desfazer. Respeita o projeto (cliente) ativo. Use SEMPRE que o aluno disser: pausar campanha, ativar campanha, pausar conjunto, pausar anúncio, ajustar orçamento, aumentar orçamento, diminuir orçamento, escalar budget, mudar verba diária, desfazer mudança, histórico de mudanças, o que eu mudei nas campanhas."
model: sonnet
effort: medium
---

> **Pasta do projeto.** `~/.operacao-ia` neste arquivo e a pasta do projeto vigente. Instalacao com um cliente so: e exatamente `~/.operacao-ia`. Com um projeto por cliente: o nome do projeto ativo esta em `~/.operacao-ia/tpa-projetos/ativo` (ou na variavel `TPA_PROJECT`, que tem prioridade) e a pasta dele e `~/.operacao-ia/tpa-projetos/<nome>/`. Troque `~/.operacao-ia` por essa pasta em todos os caminhos abaixo e rode os scripts dessa pasta. Nunca misture arquivos de dois projetos.

# Meta Ações de Campanha (pausar, ativar, orçamento)

Aplica na Meta o que as outras skills só recomendam, sem nunca agir de surpresa. Funciona igual no Claude Code e no Codex, em Mac, Windows e Linux (no Windows use `python` no lugar de `python3`).

## Antes de tudo

Confira que o comando existe no projeto vigente: `<pasta do projeto>/scripts/meta/meta_acoes.py`. Se não existir, rode você mesmo (a partir da pasta do repositório) `python3 setup/setup_acoes_meta.py` e continue. Esse setup só copia scripts e confere a conexão: não altera nada na conta Meta.

## Regra de ouro

1. **Sempre rode primeiro SEM `--confirmar`** e mostre o plano ao aluno (antes → depois, conta, projeto).
2. **Só rode com `--confirmar` depois que o aluno disser sim àquele plano**, na mesma conversa. Um sim antigo ou de outro plano não vale.
3. Confira o cabeçalho: `Projeto:` e `Conta:` têm que ser os do cliente certo. Se não forem, pare e use `python3 setup/tpa_projeto.py atual`.
4. O comando recusa IDs de outra conta de anúncios. Se recusar, não tente contornar.

## Comandos (rode da pasta `<projeto>/scripts/meta`)

```bash
python3 meta_acoes.py listar [--nivel campanha|conjunto|anuncio] [--campanha ID] [--status ACTIVE|PAUSED]
python3 meta_acoes.py pausar <id> [<id> ...] [--confirmar]
python3 meta_acoes.py ativar <id> [<id> ...] [--confirmar]
python3 meta_acoes.py orcamento <id> <valor diário> [--confirmar]
python3 meta_acoes.py historico [--ultimas N]
python3 meta_acoes.py desfazer <id-da-mudança> | --ultima [--confirmar]
```

- O ID é o número que o `listar` mostra; o tipo (campanha, conjunto ou anúncio) é detectado sozinho.
- `orcamento` mexe no orçamento **diário** de quem o tem: conjunto (ABO) ou campanha com orçamento de campanha. Se a campanha usa CBO, o orçamento está na campanha; se é ABO, está no conjunto. Anúncio não tem orçamento.
- O valor é na moeda da conta (`80` ou `80,50`). O plano mostra o número exato que será enviado. Valores ambíguos como `1.500` são recusados: escreva `1500` ou `1500,00`.
- Depois de aplicar, o script lê o valor de volta na Meta e só escreve "confirmado na Meta" se bateu. Sem essa linha, confira no Gerenciador.
- Cada mudança fica em `<pasta do projeto>/logs/meta-acoes.jsonl` com um id curto. `desfazer` reverte para o valor anterior (e avisa se alguém mexeu depois).

## Ao ativar

Ativar começa a gastar. Se o item estiver dentro de campanha ou conjunto pausado, ele só entrega quando o pai também for ativado: o plano avisa. Para ativar uma campanha recém-publicada, ative a campanha, o conjunto e o anúncio no mesmo comando.

## Aplicando recomendações de outras skills

Quando `meta-budget-optimizer` ou `meta-performance-analyzer` recomendarem mudanças, converta cada linha em um comando acima, mostre o plano completo e peça um único sim para o conjunto. Prefira 1 mudança relevante por dia para isolar o efeito.

## Nunca

- Nunca rode com `--confirmar` sem plano mostrado e aprovado.
- Nunca mostre o token da Meta (fica em `meta.env`, fora do git).
- Nunca invente IDs: use os do `listar`.
