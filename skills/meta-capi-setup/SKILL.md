---
name: meta-capi-setup
description: "Configura e comprova o rastreamento server-side da Meta, incluindo token, deduplicação Pixel × CAPI, qualidade de correspondência e validação no Gerenciador de Eventos. Triggers: configurar CAPI Meta, instalar API de Conversões, rastreamento server-side, deduplicar Pixel e CAPI, validar eventos SERVER, melhorar qualidade de correspondência, testar CAPI."
model: sonnet
effort: medium
---

# Meta CAPI Setup

Você vai configurar a API de Conversões da Meta e terminar com uma prova ao vivo. Não peça para a pessoa colar token no chat e nunca mostre token, Pixel ID ou credenciais na resposta.

Antes de executar qualquer coisa, pergunte:

> Qual checkout recebe suas vendas?
>
> 1. Hotmart, Greenn, Kiwify ou outra plataforma com CAPI nativa  
> 2. Checkout próprio, Asaas, PayPal ou outra integração sem CAPI nativa  
> 3. Não sei

Se ela não souber, ajude a procurar no painel por “Pixel”, “API de Conversões”, “CAPI” ou “rastreamento server-side”. Só escolha o caminho depois da resposta.

## Caminho A — plataforma com CAPI nativa

Hotmart, Greenn, Kiwify e plataformas parecidas já enviam o evento pelo navegador e pelo servidor. Elas também cuidam da deduplicação. Aqui, não escreva integração própria.

1. Oriente a abrir as configurações de rastreamento/Pixel do produto no checkout.
2. Selecione o mesmo Pixel/dataset usado nas páginas e campanhas.
3. Ative “API de Conversões”, “envio server-side” ou opção equivalente.
4. Gere o token no Gerenciador de Eventos:
   - abra **Gerenciador de Eventos**;
   - selecione o Pixel;
   - entre em **Configurações**;
   - procure **API de Conversões**;
   - clique em **Gerar token de acesso**.
5. Cole o token diretamente no campo seguro do checkout e clique em **Validar token**, **Testar conexão** ou equivalente.

O erro mais comum é a opção ficar marcada, mas o token nunca ser validado. Visualmente parece ligado, porém a integração está morta. Nesse caso, a Meta recebe apenas o evento do navegador, que pode perder cerca de 30–40% dos sinais por iOS, Safari e bloqueadores. O público é calibrado com dados incompletos e a campanha tende a ficar mais cara.

Não desative o evento web. A plataforma precisa receber navegador + servidor para deduplicar os dois lados.

Depois da validação, preencha no computador:

```ini
# ~/.operacao-ia/config/meta.env
CAPI_PIXEL_ID=
CAPI_TOKEN=
CAPI_ENABLED=false
CAPI_TEST_EVENT_CODE=
```

Peça para a pessoa editar os valores vazios diretamente nesse arquivo, sem enviar o segredo pelo chat. Depois aplique:

```bash
chmod 600 ~/.operacao-ia/config/meta.env
python3 ~/.operacao-ia/scripts/meta/capi_verify.py --hours 24
```

Se os scripts ainda não estiverem instalados, a partir da raiz do repositório rode:

```bash
python3 setup/setup_capi.py --hours 24
```

O resultado que comprova a CAPI é:

```text
OK — eventos_server_capi
SERVER=N ... Esta é a prova objetiva de que a CAPI está entregando.
VEREDITO: CAPI COMPROVADA
```

Se aparecer `ESTIMADO`, não chame isso de falha: pode não haver volume suficiente. Faça uma compra de teste no checkout, espere os dados aparecerem e rode novamente. Se houver pelo menos 10 eventos BROWSER e SERVER continuar zero, o verificador mostra `FALHA`.

## Caminho B — checkout sem CAPI nativa

Aqui o backend que confirma o pagamento precisa enviar o evento. Faça nesta ordem.

### 1. Gere e guarde o token

No Gerenciador de Eventos:

1. selecione o Pixel;
2. abra **Configurações**;
3. vá a **API de Conversões**;
4. clique em **Gerar token de acesso**.

Abra `~/.operacao-ia/config/meta.env` e preencha localmente:

```ini
CAPI_PIXEL_ID=
CAPI_TOKEN=
CAPI_ENABLED=false
CAPI_TEST_EVENT_CODE=
```

Comece com `CAPI_ENABLED=false`. Assim nada é enviado antes de a deduplicação estar pronta. `CAPI_TEST_EVENT_CODE` é opcional: copie o código da aba **Eventos de Teste** quando quiser que o evento apareça ali.

Proteja o arquivo e instale os scripts:

```bash
chmod 600 ~/.operacao-ia/config/meta.env
python3 setup/setup_capi.py --hours 24
```

O setup é idempotente: rodar de novo atualiza os scripts sem criar cópias e preserva o arquivo de configuração.

### 2. Use o mesmo identificador nos dois lados

A Meta deduplica quando `event_name` e `event_id` são iguais no navegador e no servidor. Para uma compra, use o ID único e permanente da transação. Não gere um ID aleatório em cada lado.

Na página de obrigado, o Pixel deve receber:

```html
<script>
  const transactionId = "ID_DA_TRANSACAO_VINDO_DO_CHECKOUT";
  fbq(
    "track",
    "Purchase",
    { value: VALOR_DA_COMPRA, currency: "BRL" },
    { eventID: transactionId }
  );
</script>
```

Substitua os dois valores em maiúsculas por dados reais que a página já recebe do checkout. Não use o texto de exemplo em produção.

No webhook/backend que confirma o pagamento, use o mesmo ID:

```python
import sys
from pathlib import Path

sys.path.insert(0, str(Path.home() / ".operacao-ia" / "scripts" / "meta"))
from capi_events import send_capi_purchase

resultado = send_capi_purchase(
    email=pedido["email"],
    phone=pedido["telefone"],
    name=pedido["nome"],
    value=pedido["valor"],
    currency="BRL",
    transaction_id=pedido["id_transacao"],  # mesmo valor do eventID do navegador
    external_id=pedido.get("id_cliente", ""),
    product_name=pedido.get("produto", ""),
    event_source_url=pedido.get("pagina_obrigado", ""),
)
```

Adapte apenas os nomes dos campos (`pedido[...]`) ao formato do webhook. Chame a função somente depois de o pagamento estar confirmado. Ela nunca grava os dados do comprador em disco, faz o hash em memória e retorna um dicionário com `ok`, `events_received` ou a causa da falha.

Sem o mesmo identificador, a Meta pode contar uma venda do Pixel e a mesma venda da CAPI como duas compras. Isso infla o resultado e ensina o algoritmo com dados errados.

### 3. Ligue, gere um evento e prove

Depois de confirmar que os dois lados usam o mesmo ID, altere:

```ini
CAPI_ENABLED=true
```

Mantenha permissão 600:

```bash
chmod 600 ~/.operacao-ia/config/meta.env
```

Faça uma compra de teste ou reenvie um webhook de teste com um ID exclusivo. O retorno imediato deve conter `ok: true` e `events_received: 1`. Depois rode:

```bash
python3 ~/.operacao-ia/scripts/meta/capi_verify.py --hours 24
```

`SERVER > 0` prova a entrega da CAPI. `BROWSER > 0` prova separadamente o Pixel da página. Nunca conclua “Pixel ok” apenas porque `last_fired_time` está recente: qualquer evento SERVER também empurra esse horário.

## Qualidade de correspondência

Quanto mais sinais corretos, maior a chance de a Meta reconhecer a mesma pessoa nos dois ambientes. O emissor normaliza e aplica SHA-256 antes do envio:

| Chave | Dado usado | Por que ajuda |
|---|---|---|
| `em` | e-mail | costuma ser um identificador estável |
| `ph` | telefone com DDI | melhora o match quando o e-mail difere |
| `fn` / `ln` | primeiro nome e sobrenome | reforçam a combinação |
| `external_id` | ID estável do cliente | liga eventos repetidos ao mesmo comprador |
| `country` | país inferido pelo DDI | reduz ambiguidades geográficas |

Não invente uma nota de Event Match Quality. A Graph API não expõe esse score final de forma confiável. O `capi_verify.py` mostra apenas as `match_keys` que consegue medir com `aggregation=match_keys`. A nota final deve ser conferida em:

1. **Gerenciador de Eventos**;
2. Pixel/dataset correto;
3. evento `Purchase` ou `Lead`;
4. **Qualidade da correspondência de eventos**.

## Checklist final

- `CAPI_TOKEN` foi validado, não apenas colado.
- `SERVER > 0` no verificador.
- `BROWSER > 0` quando existe Pixel na página.
- navegador e servidor usam o mesmo `event_name + event_id`.
- `Purchase` ou `Lead` aparece após uma conversão real/de teste.
- `match_keys` aparecem no relatório.
- a nota final de qualidade foi conferida no Gerenciador de Eventos.
- nenhum token foi enviado no chat, commitado ou exibido em log.
