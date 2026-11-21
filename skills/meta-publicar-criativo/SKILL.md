---
name: meta-publicar-criativo
description: "Publica na Meta a partir do criativo aprovado (imagem ou vídeo + copy): cria campanha, conjunto e anúncio direto pela Graph API, tudo NASCENDO PAUSADO, com resumo (conta, orçamento, público, criativo) antes de criar e confirmação para criar e para ativar. Respeita o projeto (cliente) ativo. Use SEMPRE que o aluno disser: publicar criativo, subir criativo aprovado, publicar anúncio, criar campanha com esse criativo, subir esse vídeo nos anúncios, publicar na Meta, lançar esse anúncio, subir a arte aprovada."
model: sonnet
effort: medium
---

> **Pasta do projeto.** `~/.operacao-ia` neste arquivo e a pasta do projeto vigente. Instalacao com um cliente so: e exatamente `~/.operacao-ia`. Com um projeto por cliente: o nome do projeto ativo esta em `~/.operacao-ia/tpa-projetos/ativo` (ou na variavel `TPA_PROJECT`, que tem prioridade) e a pasta dele e `~/.operacao-ia/tpa-projetos/<nome>/`. Troque `~/.operacao-ia` por essa pasta em todos os caminhos abaixo e rode os scripts dessa pasta. Nunca misture arquivos de dois projetos.

# Meta Publicar Criativo

Transforma o criativo aprovado (arte ou vídeo + copy) em campanha, conjunto e anúncio na Meta, tudo PAUSADO. Funciona igual no Claude Code e no Codex, em Mac, Windows e Linux (no Windows use `python` no lugar de `python3`).

## Antes de tudo

1. Confira que existe `<pasta do projeto>/scripts/meta/meta_publicar.py`. Se não, rode (da pasta do repositório) `python3 setup/setup_acoes_meta.py`: ele só copia scripts e confere a conexão.
2. No `<pasta do projeto>/config/meta.env` precisam estar `META_PAGE_ID` (página do Facebook) e, para campanhas de leads ou vendas, `META_PIXEL_ID`. Se faltar, peça ao aluno o ID e grave você mesmo no meta.env (nunca mostre o token).

## Fluxo

1. **Reúna o criativo aprovado**: o arquivo (imagem `.jpg/.png` ou vídeo `.mp4/.mov`), a copy final (texto, título, link de destino e botão) e, para vídeo, uma imagem de capa. Se não houver capa, extraia um quadro com `ffmpeg` se ele estiver instalado; se não estiver, peça ao aluno uma imagem de capa (não instale nada sem avisar). Use a copy exatamente como o aluno aprovou.
2. **Pergunte o que faltar**: objetivo (`trafego`, `leads` ou `vendas`), orçamento diário, países, faixa de idade, gênero e interesses.
3. **Gere o modelo e preencha**: `python3 meta_publicar.py --exemplo > campanha.json` e edite com os dados do aluno (os caminhos dos arquivos são relativos à pasta do `campanha.json`).
4. **Mostre o resumo sem criar nada**: `python3 meta_publicar.py campanha.json`. Ele valida tudo, resolve os interesses na Meta (só leitura) e imprime conta, projeto, orçamento, público e criativo. Confira com o aluno o cabeçalho `Projeto:` e `Conta:`.
5. **Só crie com sim do aluno àquele resumo**: `python3 meta_publicar.py campanha.json --confirmar`. Sobe o criativo e cria campanha, conjunto, criativo e anúncio, sempre PAUSADOS, e lê de volta para provar que estão pausados.
6. **Ativar é outra confirmação**: o próprio comando imprime a linha `python3 meta_acoes.py ativar <campanha> <conjunto> <anuncio> --confirmar`. Rode-a primeiro sem `--confirmar`, mostre o plano (inclui o orçamento diário que passa a gastar) e só depois aplique com o sim do aluno.

## Regras

- A conta de anúncios, a página e o pixel vêm SEMPRE do projeto vigente; o `campanha.json` não escolhe conta.
- Se uma etapa falhar no meio, o script lista o que já foi criado (tudo pausado) e não apaga nada. Não tente consertar criando de novo sem avisar o aluno: isso cria uma campanha nova.
- Vídeo é processado pela Meta: o script espera até `ZX_TPA_VIDEO_TIMEOUT` segundos (padrão 600) e imprime quanto levou.
- Contas ou versões da API que exigem campos novos: use `campanha_extra`, `conjunto_extra`, `targeting_extra` ou `criativo_extra` no `campanha.json` para acrescentar os campos pedidos no erro da Meta. Eles aparecem no resumo. Não podem trocar status, orçamento, público, objetivo, página ou ligação entre itens (o comando recusa): esses campos têm lugar próprio no arquivo.
- Se um interesse não bate exatamente com o nome pedido, o resumo marca APROXIMADO e o comando não cria. Use o nome exato mostrado ou rode com `--aceitar-aproximado`.
- Se uma etapa terminar sem resposta (timeout), ela PODE ter sido criada: procure pelo nome no Gerenciador antes de rodar de novo, para não duplicar.
- Fora do escopo: formulário instantâneo (lead form), campanha de mensagens/WhatsApp, carrossel e catálogo. Para esses, use `meta-campaign-launcher`.
- Nunca mostre o token da Meta (fica em `meta.env`, fora do git).
