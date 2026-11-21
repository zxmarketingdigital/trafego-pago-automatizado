# Checagem semanal da API da Meta

A Meta troca a versão da Graph API de tempos em tempos e deixa versões antigas de lado. Quando isso acontece sem você ver, o fetch das métricas começa a falhar ou a devolver dado diferente. `scripts/check_api_version.py` olha isso por você uma vez por semana. Só lê: nunca cria, pausa nem altera nada na sua conta.

## O que ele faz

1. Descobre a versão da Graph API que os seus scripts usam hoje (lê `fetch_metrics.py` e os demais; não existe versão chumbada no verificador).
2. Faz **uma** chamada leve (`GET /me?fields=id`) com o token do projeto para cada versão diferente que os scripts usam (normalmente é uma só). Se os scripts divergem entre si, o resultado é no mínimo `atencao`.
3. Lê o que a própria Meta respondeu: o cabeçalho `facebook-api-version` (a versão que ela de fato serviu), os cabeçalhos de aviso de descontinuação (`Deprecation`, `Sunset`, `Warning`) e o texto de erro.
4. Grava o resultado em `<projeto>/dashboards/api-status.json` e mostra um resumo claro.

Não há tabela de datas de expiração dentro do script: a fonte do aviso é a resposta da Meta.

## Resultados

| Status | Significa | O que fazer |
|---|---|---|
| `ok` | A Meta serviu a versão pedida e não avisou nada. | Nada. |
| `atencao` | A Meta mandou aviso de descontinuação, ou há uma data de encerramento (`Sunset`) em até 60 dias. | Peça ao Claude Code ou ao Codex: "atualizar a versão da API Meta nos scripts". |
| `critico` | A Meta serviu uma versão diferente da pedida (a pedida já foi encerrada) ou a data de encerramento já passou. | Atualize a versão agora e rode o fetch de novo. |
| `erro` | Token recusado ou falha na chamada. | `python3 setup/setup_meta_oauth.py --renew`. |
| `nao_verificado` | Sem token ou sem rede. | Configure o token (Etapa 1) e rode de novo. |

`ok` quer dizer que **hoje** a API não avisou nada; não é garantia de que a versão não vai encerrar. Por isso a checagem é semanal.

O prazo de 60 dias é só o ponto em que o aviso passa de "informativo" para "atenção". Para mudar: variável `ZX_TPA_API_AVISO_DIAS` (por exemplo `ZX_TPA_API_AVISO_DIAS=90`).

Código de saída: `0` ok, `1` atenção, `2` crítico, `3` erro ou não verificado. Dá para encadear em outros scripts.

## Onde o aviso aparece

- **Terminal**, ao rodar o script.
- **Dashboard** do projeto: faixa amarela (ou vermelha, se crítico) no topo.
- **Relatório diário** (texto, e-mail e WhatsApp): linha de aviso `API META: ...`.
- **Painel de agência:** coluna "API Meta" de cada cliente.

Tudo lê o mesmo arquivo `api-status.json`. Se a checagem nunca rodou, nada aparece e nada quebra.

## Rodar

```bash
python3 scripts/check_api_version.py                    # projeto vigente
python3 scripts/check_api_version.py --projeto cliente-a
python3 scripts/check_api_version.py --todos            # todos os projetos com token
python3 scripts/check_api_version.py --json             # saída para outros programas
```

## Agendar toda semana

O script imprime a linha já pronta para o seu projeto e o seu sistema:

```bash
python3 scripts/check_api_version.py --agendamento --projeto <nome>
```

Para uma agência com vários clientes, uma linha basta: use `--todos` no lugar de `--projeto <nome>`.

### Linux e WSL2 (cron)

`crontab -e` e uma linha (segunda-feira, 09:17):

```
17 9 * * 1 /usr/bin/python3 /CAMINHO/trafego-pago-automatizado/scripts/check_api_version.py --todos >> $HOME/.operacao-ia/api-check.cron.log 2>&1
```

### macOS (launchd)

Crie `~/Library/LaunchAgents/com.zxlab.meta-api-check.plist` (troque `/CAMINHO` e `SEU_USUARIO`):

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.zxlab.meta-api-check</string>
  <key>ProgramArguments</key>
  <array>
    <string>/usr/bin/python3</string>
    <string>/CAMINHO/trafego-pago-automatizado/scripts/check_api_version.py</string>
    <string>--todos</string>
  </array>
  <key>StartCalendarInterval</key>
  <dict><key>Weekday</key><integer>1</integer><key>Hour</key><integer>9</integer><key>Minute</key><integer>17</integer></dict>
  <key>StandardOutPath</key><string>/Users/SEU_USUARIO/.operacao-ia/api-check.log</string>
  <key>StandardErrorPath</key><string>/Users/SEU_USUARIO/.operacao-ia/api-check.log</string>
</dict>
</plist>
```

Depois: `launchctl load ~/Library/LaunchAgents/com.zxlab.meta-api-check.plist`.

### Windows (Agendador de Tarefas)

No Prompt de Comando (`cmd`, sem administrador), uma linha por semana (segunda, 09:17):

```
schtasks /Create /TN "ZXLab Meta API Check" /SC WEEKLY /D MON /ST 09:17 /TR "\"C:\Caminho\python.exe\" \"C:\Caminho\trafego-pago-automatizado\scripts\check_api_version.py\" --todos"
```

Para remover: `schtasks /Delete /TN "ZXLab Meta API Check" /F`.

## Segurança

O token é lido só do `meta.env` do projeto e nunca é impresso nem gravado no `api-status.json`. A única chamada feita é uma leitura (`GET`).
