---
name: meta-relatorio-email
description: "Configura, testa, agenda e diagnostica o relatório diário de tráfego pago Meta por e-mail. Triggers: instalar relatório por e-mail, receber resumo diário no e-mail, configurar SMTP do relatório, testar e-mail de métricas, agendar relatório Meta, relatório de tráfego não chegou no e-mail."
model: sonnet
effort: low
---

# Relatório Meta por e-mail

Usar o JSON que o coletor já gerou. Nunca chamar a Graph API nem recalcular métricas.

## Antes de começar

Confirmar que existe pelo menos um arquivo:

```bash
ls ~/.operacao-ia/dashboards/paid-traffic-*d.json
```

Se não existir, executar primeiro o coletor:

```bash
python3 ~/.operacao-ia/scripts/meta/fetch_metrics.py
```

## 1. Preencher a configuração

Abrir `~/.operacao-ia/config/meta.env` e preencher com os dados da própria conta:

```dotenv
REPORT_EMAIL_TO=
REPORT_EMAIL_FROM=
SMTP_HOST=
SMTP_PORT=587
SMTP_USER=
SMTP_PASSWORD=
SMTP_TLS=true
REPORT_WINDOW=
```

- Usar em `REPORT_EMAIL_TO` o endereço que receberá o relatório.
- Usar em `REPORT_EMAIL_FROM` o remetente autorizado pelo servidor SMTP.
- Deixar `REPORT_WINDOW` vazio para usar a menor janela do perfil; ou informar, por exemplo, `7`.
- No Gmail, usar `smtp.gmail.com`, porta `587`, TLS `true` e uma **senha de app** em `SMTP_PASSWORD`. A senha normal da conta costuma ser recusada.
- Nunca colar senha em conversa, commit ou arquivo do repositório. Salvar somente no `meta.env` local.

Confirmar a proteção do arquivo:

```bash
chmod 600 ~/.operacao-ia/config/meta.env
```

## 2. Ver antes de enviar

Para inspecionar apenas o conteúdo:

```bash
python3 scripts/report_formatter.py --format text
python3 scripts/report_formatter.py --format html
```

Para montar o e-mail completo sem abrir conexão:

```bash
python3 scripts/send_email_report.py --dry-run
```

Se o JSON estiver ausente ou tiver mais de 26 horas, o conteúdo avisará que o dado está indisponível ou defasado. Não tratar esse aviso como número atual.

## 3. Instalar e agendar

Executar a partir da pasta clonada:

```bash
python3 setup/setup_report_email.py
```

O instalador copia o formatter e o emissor para `~/.operacao-ia/scripts/meta/`, mostra um `--dry-run` e pede confirmação. Confirmar somente depois de revisar. O job roda todos os dias às 8h20, depois do coletor das 8h05.

Executar o instalador novamente é seguro: ele atualiza os arquivos e recarrega o mesmo job, sem duplicar.

## 4. Conferir e pedir na hora

Verificar se o job está carregado:

```bash
launchctl list | grep com.zxlab.meta-report-email
```

Enviar imediatamente:

```bash
python3 ~/.operacao-ia/scripts/meta/send_email_report.py
```

Consultar os logs:

```bash
tail -n 80 ~/.operacao-ia/logs/meta-report-email.stdout.log
tail -n 80 ~/.operacao-ia/logs/meta-report-email.stderr.log
```

## 5. Quando não chegar

1. Rodar o comando com `--dry-run` e corrigir todas as chaves listadas.
2. Conferir se `paid-traffic-{N}d.json` existe e se a coleta é recente.
3. Conferir `SMTP_HOST`, porta e `SMTP_TLS`.
4. Se aparecer erro de autenticação no Gmail, gerar uma senha de app e substituir somente `SMTP_PASSWORD`.
5. Verificar spam e se `REPORT_EMAIL_FROM` é aceito pelo servidor.
6. Rodar o envio imediato e consultar os dois logs.

Nunca exibir `SMTP_PASSWORD` durante o diagnóstico.

## 6. Desinstalar

```bash
launchctl unload ~/Library/LaunchAgents/com.zxlab.meta-report-email.plist
rm ~/Library/LaunchAgents/com.zxlab.meta-report-email.plist
```

Isso remove apenas o agendamento. Para remover também os scripts, apagar `send_email_report.py` somente se o relatório por e-mail não for mais usado; manter `report_formatter.py` se o WhatsApp ainda estiver ativo.
