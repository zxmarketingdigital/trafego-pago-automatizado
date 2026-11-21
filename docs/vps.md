# Rodar o Tráfego Pago Automatizado numa VPS (Ubuntu)

Serve para quem quer o fetch das métricas rodando 24h e o dashboard no celular, sem deixar o computador ligado. O Claude Code e o Codex rodam o setup do mesmo jeito que no computador: a VPS é só outra máquina Linux.

> **Regra de ouro: o dashboard nunca fica numa porta aberta para a internet sem login.** Ele mostra gasto, contas e campanhas dos seus clientes. O servidor do projeto já escuta só em `127.0.0.1` (a própria VPS); o que este guia faz é colocar **uma porta de entrada com login** na frente dele. Não abra a porta 8888 (nem 8889, 8890...) no firewall.

## 1. O que você precisa

- VPS com Ubuntu 22.04 ou 24.04 (1 vCPU e 1 GB de RAM bastam para o dashboard e o fetch).
- Um usuário comum com `sudo` (não rode o projeto como `root`).
- Python 3.9+ (o Ubuntu já traz), `git` e `cron`:

```bash
sudo apt update && sudo apt install -y python3 git cron
sudo systemctl enable --now cron
```

- Claude Code **ou** Codex instalado na VPS e logado na sua conta (siga a instalação oficial da ferramenta que você usa). Se a VPS só tem terminal (sem navegador), faça o login que a ferramenta oferece para ambiente sem navegador.

## 2. Instalar o projeto

```bash
git clone https://github.com/zxmarketingdigital/trafego-pago-automatizado
cd trafego-pago-automatizado
claude        # ou: codex
```

Digite **`INICIAR SETUP`** e siga as etapas normalmente. Duas diferenças numa VPS sem navegador:

1. **Etapa 1 (conectar a Meta):** o login por OAuth abre o navegador. Numa VPS use a **Via B**, o token de usuário do sistema: gere em `business.facebook.com/settings/system-users` (permissões `ads_management`, `ads_read`, `business_management`) e rode `python3 setup/setup_meta_oauth.py --renew`. O token fica em `meta.env` com permissão 600.
2. **Etapa 9 (agendamento):** no Linux o setup não usa LaunchAgent. Ele imprime as linhas de `cron` prontas para o seu projeto. Cole-as com `crontab -e`:

```
5 8,13,19 * * * /bin/bash $HOME/.operacao-ia/scripts/meta/run_fetch.sh >> $HOME/.operacao-ia/logs/meta-fetch.cron.log 2>&1
@reboot /bin/bash $HOME/.operacao-ia/scripts/meta/start_dashboard.sh
```

Com vários clientes, a Etapa 9 imprime um par de linhas por projeto (cada um termina com `# tpa:<nome>`). Confira com `crontab -l`.

Depois adicione a checagem semanal da API da Meta (uma linha por projeto; veja [checagem-api-meta.md](checagem-api-meta.md)):

```bash
python3 scripts/check_api_version.py --agendamento --projeto <nome>
```

## 3. Ver o dashboard no celular com login

Escolha **uma** das três opções. A primeira é a recomendada.

### Opção A: Cloudflare Tunnel + Cloudflare Access (recomendada)

Não abre nenhuma porta na VPS: a VPS é que conecta na Cloudflare. O login é por e-mail (código enviado para o seu e-mail) ou pelo Google, e funciona no navegador do celular. Precisa de um domínio na Cloudflare (o plano gratuito serve).

1. Instale o `cloudflared` na VPS (instruções oficiais: `developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/`).
2. **Primeiro a proteção, depois o túnel.** No painel Cloudflare Zero Trust: `Access` > `Applications` > `Add an application` > `Self-hosted`, domínio `painel.seudominio.com`, e uma política `Allow` só com o seu e-mail (e o de quem mais precisar). Salve. Enquanto o túnel (passos abaixo) não existe, não há nada para proteger, e quando ele subir o login já estará valendo.
3. Crie o túnel apontando para o dashboard (porta do seu projeto, `8888` no padrão; confira com `python3 setup/tpa_projeto.py listar`):

```bash
cloudflared tunnel login
cloudflared tunnel create tpa-dashboard
cloudflared tunnel route dns tpa-dashboard painel.seudominio.com
```

4. Crie `~/.cloudflared/config.yml`:

```yaml
tunnel: tpa-dashboard
credentials-file: /home/SEU_USUARIO/.cloudflared/<ID-DO-TUNEL>.json
ingress:
  - hostname: painel.seudominio.com
    service: http://127.0.0.1:8888
  - service: http_status:404
```

5. Rode como serviço (sobe sozinho no boot):

```bash
sudo cloudflared service install
sudo systemctl enable --now cloudflared
```

6. Teste de fora da VPS: abrir `https://painel.seudominio.com` numa janela anônima do celular deve pedir login. Se mostrar o dashboard direto, **desligue o túnel** (`sudo systemctl stop cloudflared`) e revise a política do passo 2.

> Não use o túnel rápido (`cloudflared tunnel --url ...`, domínio `trycloudflare.com`): ele não tem login.

### Opção B: senha com Caddy (HTTPS + usuário e senha)

Precisa de um domínio apontando para o IP da VPS. O Caddy emite o certificado HTTPS sozinho.

```bash
sudo apt install -y caddy
caddy hash-password        # digita a senha e copia o hash que ele imprime
```

`/etc/caddy/Caddyfile`:

```
painel.seudominio.com {
    basicauth {
        seu-usuario COLE_AQUI_O_HASH
    }
    reverse_proxy 127.0.0.1:8888
}
```

```bash
sudo systemctl reload caddy
sudo ufw allow 22/tcp && sudo ufw allow 80/tcp && sudo ufw allow 443/tcp && sudo ufw enable
```

Só as portas 22, 80 e 443 ficam abertas; a 8888 continua fechada. Use uma senha longa e única. Sem HTTPS a senha viaja em texto puro, então nunca publique esta opção sem o domínio.

### Opção C: túnel SSH (sem domínio, só você)

Nada é publicado. No computador (ou num app de SSH no celular) abra:

```bash
ssh -N -L 8888:127.0.0.1:8888 SEU_USUARIO@IP_DA_VPS
```

e acesse `http://localhost:8888` no próprio aparelho. É a mais simples e a mais segura, mas só funciona com o túnel aberto.

## 4. Painel de todos os clientes (agência)

Com vários clientes, rode o painel consolidado na VPS. Ele precisa da **sua própria proteção**: cada endereço público é uma aplicação separada, e a que você criou para o dashboard (seção 3) não cobre este endereço novo.

1. Primeiro a proteção. Na Opção A: `Access` > `Applications` > `Add an application` > `Self-hosted` para `painel-agencia.seudominio.com`, política `Allow` só com o seu e-mail. Na Opção B: um bloco novo no `Caddyfile` com `basicauth`, igual ao do dashboard, apontando para `127.0.0.1:8887`.
2. Só depois acrescente o endereço no `config.yml` do túnel (`hostname: painel-agencia.seudominio.com`, `service: http://127.0.0.1:8887`) e rode `cloudflared tunnel route dns tpa-dashboard painel-agencia.seudominio.com`. Depois `sudo systemctl restart cloudflared` para o serviço ler o `config.yml` novo.
3. Teste numa janela anônima do celular: tem que pedir login. (Um erro 404 aqui quer dizer que o serviço ainda não leu a regra nova, não que a proteção falhou; nada fica exposto.)
4. Suba o painel:

```bash
python3 scripts/dashboard_agencia.py --servir --host-permitido painel-agencia.seudominio.com --protegido-por-acesso
```

Ele também escuta só em `127.0.0.1`. O `--host-permitido` é o endereço público que o túnel ou o Caddy usa. **O painel em si não tem login:** quem protege é o Cloudflare Access, o Caddy com senha ou o túnel SSH da seção 3. Sem uma dessas camadas, não use `--host-permitido`: o script se recusa a subir com ele enquanto você não acrescentar `--protegido-por-acesso`, que é só uma declaração sua (o script não consegue verificar o login): ela vale como confirmação de que os passos 1 a 3 acima foram feitos. Detalhes: skill `meta-dashboard-agencia`.

## 5. Checklist de segurança

- [ ] `ss -tlnp | grep -E '888[0-9]|8887'` mostra só `127.0.0.1`, nunca `0.0.0.0`.
- [ ] `sudo ufw status` não lista as portas dos dashboards.
- [ ] O endereço público pede login numa janela anônima.
- [ ] `~/.operacao-ia/config/meta.env` com permissão 600 (`ls -l`).
- [ ] Login por SSH com chave, não com senha.
- [ ] `crontab -l` mostra o fetch e a checagem semanal da API.

## Problemas comuns

- **Dashboard em branco:** o fetch ainda não rodou. Rode `bash ~/.operacao-ia/scripts/meta/run_fetch.sh` e recarregue.
- **O `cron` não roda:** `systemctl status cron` e confira o log `~/.operacao-ia/logs/meta-fetch.cron.log`.
- **Token recusado:** `python3 setup/setup_meta_oauth.py --renew`.
