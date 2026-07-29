---
name: meta-relatorio-whatsapp
description: "Configura, testa, agenda e diagnostica o relatório diário de tráfego pago Meta no WhatsApp pela Cloud API oficial ou Evolution API. Triggers: instalar relatório no WhatsApp, receber resumo diário no WhatsApp, configurar WhatsApp Cloud API, usar Evolution no relatório, testar mensagem de métricas, relatório de tráfego não chegou no WhatsApp."
model: sonnet
effort: low
---

# Relatório Meta no WhatsApp

Usar o mesmo relatório do e-mail, já calculado pelo coletor. Nunca chamar a Graph API de anúncios nem recalcular métricas.

## Antes de começar

Confirmar que existe pelo menos um arquivo:

```bash
ls ~/.operacao-ia/dashboards/paid-traffic-*d.json
```

Se não existir, executar primeiro:

```bash
python3 ~/.operacao-ia/scripts/meta/fetch_metrics.py
```

## 1. Escolher o provider

### Cloud API oficial — padrão recomendado

- Usa a infraestrutura oficial da Meta, sem servidor próprio.
- É a melhor escolha para quem já tem Business Manager e app Meta.
- Para **texto livre**, só entrega dentro da janela de 24 horas após o destinatário mandar uma mensagem ao número da Cloud API.
- Para o relatório diário deste bônus, mandar um “oi” ao próprio número uma vez por dia mantém a janela aberta.
- Para automatizar sem esse “oi”, usar um template aprovado pela Meta. O emissor padrão deste bônus envia texto livre; um template exige configurar o template aprovado e trocar o tipo do payload para `template`.

Não esconder essa limitação. Se estiver fora da janela, explicar que o sistema não está necessariamente quebrado: a Meta bloqueou texto livre pela regra das 24 horas.

### Evolution API

- Não tem a janela de 24 horas de texto livre.
- Exige uma instância Evolution própria, conectada e disponível em um servidor.
- Escolher somente se a pessoa já mantém essa infraestrutura.

## 2. Preencher a configuração

Abrir `~/.operacao-ia/config/meta.env`. Nunca pedir que a pessoa cole token ou chave na conversa.

Para Cloud API:

```dotenv
REPORT_WHATSAPP_PROVIDER=cloud_api
WHATSAPP_PHONE_NUMBER_ID=
WHATSAPP_TOKEN=
REPORT_WHATSAPP_TO=
REPORT_WINDOW=
```

Para Evolution:

```dotenv
REPORT_WHATSAPP_PROVIDER=evolution
EVOLUTION_URL=
EVOLUTION_API_KEY=
EVOLUTION_INSTANCE=
REPORT_WHATSAPP_TO=
REPORT_WINDOW=
```

Em `REPORT_WHATSAPP_TO`, usar somente o número com DDI e DDD. Deixar `REPORT_WINDOW` vazio para usar a menor janela do perfil; ou informar, por exemplo, `7`.

> **Atenção ao formato do número.** O WhatsApp normaliza o número antes de entregar, e a
> normalização pode não ser a que você espera: um celular brasileiro informado como
> `55` + DDD + `9XXXXXXXX` (13 dígitos) pode ser entregue como `55` + DDD + `XXXXXXXX`
> (12 dígitos, sem o nono dígito), dependendo de como a conta foi registrada. Isso é
> normal e não é erro.
>
> A consequência prática é uma só: **se a mensagem não chegar, teste o número nos dois
> formatos** (com e sem o nono dígito) antes de suspeitar da configuração. E se você for
> procurar a conversa no histórico do seu WhatsApp, procure pelo número normalizado — pelo
> outro formato ela parece não existir.

Proteger o arquivo:

```bash
chmod 600 ~/.operacao-ia/config/meta.env
```

## 3. Ver antes de enviar

Para ver somente o formato curto:

```bash
python3 scripts/report_formatter.py --format whatsapp
```

Para validar o provider e ver a mensagem exata sem rede:

```bash
python3 scripts/send_whatsapp_report.py --dry-run
```

O destino aparece mascarado, com apenas os quatro últimos dígitos. A mensagem fica abaixo de 1.200 caracteres; quando necessário, a cauda é resumida e isso aparece no texto.

## 4. Instalar e agendar

Executar a partir da pasta clonada:

```bash
python3 setup/setup_report_whatsapp.py
```

O instalador copia o formatter compartilhado e o emissor para `~/.operacao-ia/scripts/meta/`, mostra o `--dry-run` e pede confirmação. Confirmar somente depois de revisar. O job roda todos os dias às 8h20, depois do coletor das 8h05.

Executar o instalador novamente atualiza e recarrega o mesmo job, sem duplicar.

## 5. Conferir e pedir na hora

Verificar o job:

```bash
launchctl list | grep com.zxlab.meta-report-whatsapp
```

Enviar imediatamente:

```bash
python3 ~/.operacao-ia/scripts/meta/send_whatsapp_report.py
```

Consultar os logs:

```bash
tail -n 80 ~/.operacao-ia/logs/meta-report-whatsapp.stdout.log
tail -n 80 ~/.operacao-ia/logs/meta-report-whatsapp.stderr.log
```

## 6. Quando não chegar

1. Rodar `--dry-run` e corrigir exatamente as chaves listadas.
2. Conferir se o JSON existe e se a coleta tem menos de 26 horas.
3. Na Cloud API, mandar um “oi” ao número e tentar novamente. Fora da janela de 24 horas, usar template aprovado ou escolher Evolution.
4. Na Cloud API, conferir o Phone Number ID e se o token continua válido.
5. Na Evolution, conferir URL, nome da instância e se ela está conectada.
6. Rodar o envio imediato e consultar os dois logs.

Nunca mostrar token, API key nem o número completo durante o diagnóstico.

## 7. Desinstalar

```bash
launchctl unload ~/Library/LaunchAgents/com.zxlab.meta-report-whatsapp.plist
rm ~/Library/LaunchAgents/com.zxlab.meta-report-whatsapp.plist
```

Isso remove apenas o agendamento. Para remover também os scripts, apagar `send_whatsapp_report.py` somente se não for mais usado; manter `report_formatter.py` se o e-mail ainda estiver ativo.
