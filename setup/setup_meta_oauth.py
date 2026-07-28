#!/usr/bin/env python3
"""
Setup 6 — Etapa 2: Conectar conta Meta (Facebook ADS)

Fluxo de 2 vias:

  Via A (default): Claude tenta `mcp__meta-official__authenticate`.
  Via B (fallback): aluno cola System User Token gerado em
    business.facebook.com/settings/system-users (permissões:
    ads_management, ads_read, business_management).

O token vai pra `~/.operacao-ia/config/meta.env` (chmod 600). Esta é a
fonte de verdade pro fetcher autônomo (LaunchAgent).

Modos:

  python3 setup_meta_oauth.py
    — Imprime instruções pro Claude executar Via A.

  python3 setup_meta_oauth.py --renew
    — Pula direto pro fluxo de colar token (Via B). Útil quando token
      expirou.

  python3 setup_meta_oauth.py --set-token <TOKEN>
    — Grava META_ACCESS_TOKEN em meta.env (chmod 600).

  python3 setup_meta_oauth.py --set-account act_123456789
    — Grava META_AD_ACCOUNT_ID em meta.env.

  python3 setup_meta_oauth.py --validate
    — Valida token chamando GET /me/businesses.
      Exit 0 = OK; 1 = sem token; 2 = sem ad_account; 3 = token inválido.
"""
import argparse
import json
import os
import re
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

OPERACAO = Path.home() / ".operacao-ia"
META_ENV = OPERACAO / "config" / "meta.env"
GRAPH_BASE = "https://graph.facebook.com/v21.0"

TEMPLATE = """# Setup 6 — Tráfego Pago Meta ADS
# Gerado por setup_meta_oauth.py

META_ACCESS_TOKEN={access_token}
META_AD_ACCOUNT_ID={ad_account_id}
META_BUSINESS_ID=
META_PAGE_ID=
META_PIXEL_ID=

SUPABASE_URL=
SUPABASE_SERVICE_KEY=

OPERACAO_IA_HOME=~/.operacao-ia
"""


def read_env(key):
    if not META_ENV.exists():
        return ""
    for line in META_ENV.read_text().splitlines():
        if line.startswith(f"{key}="):
            return line.split("=", 1)[1].strip()
    return ""


def read_token():
    """Lê access_token de meta.env (fonte de verdade) ou env var."""
    return read_env("META_ACCESS_TOKEN") or os.environ.get("META_ACCESS_TOKEN") or None


def _scan_mcp_block(block, source_prefix=""):
    """Procura entry MCP com nome contendo 'meta' e extrai token."""
    if not isinstance(block, dict):
        return None, None
    for name, cfg in block.items():
        if "meta" not in name.lower():
            continue
        if not isinstance(cfg, dict):
            continue
        token = (cfg.get("access_token")
                 or cfg.get("token")
                 or (cfg.get("env") or {}).get("META_ACCESS_TOKEN"))
        if token:
            label = f"{source_prefix}{name}" if source_prefix else name
            return token, label
    return None, None


def extract_token_from_claude_json():
    """Best-effort: extrai access_token do ~/.claude.json (MCP oficial Meta).

    Cobre 3 shapes:
      - top-level mcpServers/mcp_servers/mcp
      - project-scoped projects[<path>].mcpServers (Claude Code project-local MCP)
      - top-level projects (fallback raro)

    Retorna (token, source) ou (None, None).
    """
    cj = Path.home() / ".claude.json"
    if not cj.exists():
        return None, None
    try:
        data = json.loads(cj.read_text())
    except Exception:
        return None, None

    # Shape 1: top-level
    for key in ("mcpServers", "mcp_servers", "mcp"):
        token, src = _scan_mcp_block(data.get(key, {}))
        if token:
            return token, src

    # Shape 2: project-scoped
    projects = data.get("projects", {})
    if isinstance(projects, dict):
        for proj_path, proj_cfg in projects.items():
            if not isinstance(proj_cfg, dict):
                continue
            for key in ("mcpServers", "mcp_servers", "mcp"):
                token, src = _scan_mcp_block(
                    proj_cfg.get(key, {}),
                    source_prefix=f"projects[{proj_path}]/",
                )
                if token:
                    return token, src

    return None, None


def read_account_from_env():
    return read_env("META_AD_ACCOUNT_ID")


def write_kv(key, value):
    """Grava ou substitui um KEY=VALUE em meta.env preservando o resto."""
    META_ENV.parent.mkdir(parents=True, exist_ok=True)
    if META_ENV.exists():
        lines = META_ENV.read_text().splitlines()
        out = []
        replaced = False
        for line in lines:
            if line.startswith(f"{key}="):
                out.append(f"{key}={value}")
                replaced = True
            else:
                out.append(line)
        if not replaced:
            out.append(f"{key}={value}")
        META_ENV.write_text("\n".join(out) + "\n")
    else:
        # Cria template novo, deixando outros campos vazios
        defaults = {"META_ACCESS_TOKEN": "", "META_AD_ACCOUNT_ID": ""}
        defaults[key] = value
        META_ENV.write_text(TEMPLATE.format(
            access_token=defaults["META_ACCESS_TOKEN"],
            ad_account_id=defaults["META_AD_ACCOUNT_ID"],
        ))
    # chmod 600 — token é segredo
    try:
        os.chmod(META_ENV, 0o600)
    except OSError:
        pass


def write_token(token):
    if not token or len(token) < 50:
        print("❌ Token inválido (vazio ou muito curto).")
        return 1
    if " " in token or "\n" in token:
        print("❌ Token contém espaço ou quebra de linha.")
        return 1
    write_kv("META_ACCESS_TOKEN", token)
    masked = token[:8] + "…" + token[-4:]
    print(f"✅ META_ACCESS_TOKEN gravado em {META_ENV} ({masked})")
    print(f"   Permissões: chmod 600 (somente seu usuário lê)")
    return 0


def write_account(ad_account_id):
    if not re.match(r"^act_\d+$", ad_account_id):
        print(f"❌ ad_account_id inválido: {ad_account_id} (esperado: act_<dígitos>)")
        return 1
    write_kv("META_AD_ACCOUNT_ID", ad_account_id)
    print(f"✅ META_AD_ACCOUNT_ID={ad_account_id} gravado em {META_ENV}")
    return 0


def graph_get(path, token):
    url = f"{GRAPH_BASE}/{path.lstrip('/')}"
    headers = {
        "Authorization": f"Bearer {token}",
        "User-Agent": "zx-control-trafego-pago/setup",
    }
    req = Request(url, headers=headers)
    with urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def validate_token_via_graph(token):
    """Chama GET /me; retorna (ok, mensagem)."""
    try:
        data = graph_get("me?fields=id,name", token)
        return True, f"id={data.get('id')} name={data.get('name', '')}"
    except HTTPError as e:
        body = e.read().decode("utf-8", errors="ignore")[:200]
        return False, f"HTTP {e.code}: {body}"
    except URLError as e:
        return False, f"Sem rede: {e.reason}"
    except Exception as e:
        return False, f"Erro: {e}"


def cmd_validate():
    token = read_token()
    if not token:
        print("❌ Sem META_ACCESS_TOKEN. Rode `setup_meta_oauth.py --renew`.")
        return 1
    masked = token[:8] + "…" + token[-4:] if len(token) > 16 else "***"
    print(f"🔑 Token presente em meta.env ({masked}, len={len(token)})")
    ok, msg = validate_token_via_graph(token)
    if not ok:
        print(f"❌ Token inválido no Graph API: {msg}")
        print("   Rode: python3 setup/setup_meta_oauth.py --renew")
        return 3
    print(f"✅ Token válido — {msg}")
    acct = read_account_from_env()
    if not acct or "XXXXX" in acct:
        print("⚠️  META_AD_ACCOUNT_ID não preenchido em meta.env")
        return 2
    print(f"✅ META_AD_ACCOUNT_ID={acct}")
    return 0


def cmd_renew():
    """Fluxo Via B — aluno cola System User Token."""
    print("🔄 Renovação de token (Via B — System User Token)")
    print("=" * 60)
    print()
    print("PASSO A PASSO:")
    print()
    print("1. Abra: https://business.facebook.com/settings/system-users")
    print("2. Selecione (ou crie) um System User com role 'Admin'")
    print("3. Clique em 'Gerar novo token'")
    print("4. Selecione o app correto e marque permissões:")
    print("     ✓ ads_management")
    print("     ✓ ads_read")
    print("     ✓ business_management")
    print("5. Token gerado é PERMANENTE (não expira automaticamente)")
    print("6. Copie o token e cole abaixo")
    print()
    print("=" * 60)
    print()
    try:
        token = input("Cole o token aqui (ou ENTER pra cancelar): ").strip()
    except (EOFError, KeyboardInterrupt):
        print("\nCancelado.")
        return 1
    if not token:
        print("Cancelado.")
        return 1
    rc = write_token(token)
    if rc != 0:
        return rc
    print()
    print("Validando token no Graph API…")
    ok, msg = validate_token_via_graph(token)
    if not ok:
        print(f"❌ Token rejeitado: {msg}")
        print("   Token foi gravado mas Graph API não aceita.")
        print("   Verifique permissões no Business Manager.")
        return 3
    print(f"✅ Token validado — {msg}")
    print()
    print("Próximo passo:")
    print("  python3 setup/setup_meta_oauth.py --set-account act_<seu_id>")
    return 0


def cmd_sync_from_mcp():
    """Extrai access_token de ~/.claude.json (MCP oficial Meta) e grava em meta.env.

    Necessário após Via A — fetch_metrics.py (LaunchAgent) lê só de meta.env.
    """
    token, source = extract_token_from_claude_json()
    if not token:
        print("❌ Token não encontrado em ~/.claude.json (MCP oficial Meta).")
        print("   Confirme que rodou `mcp__meta-official__authenticate` + `complete_authentication`.")
        print("   Se Via A falhou, use Via B: python3 setup/setup_meta_oauth.py --renew")
        return 1
    rc = write_token(token)
    if rc != 0:
        return rc
    print(f"   Origem: ~/.claude.json (MCP={source})")
    print()
    print("Validando token no Graph API…")
    ok, msg = validate_token_via_graph(token)
    if not ok:
        print(f"⚠️  Token gravado mas Graph rejeitou: {msg}")
        print("   Token pode estar expirado ou sem permissões. Tente Via B (--renew).")
        return 3
    print(f"✅ Token validado — {msg}")
    return 0


def cmd_instructions():
    if not OPERACAO.exists():
        print("❌ Rode setup_base_s6.py (E0) primeiro.")
        return 1

    print("📡 Etapa 1 — Conectar conta Meta")
    print("=" * 60)
    print()
    print("INSTRUÇÕES PARA O CLAUDE (executar via tool calls):")
    print()
    print("VIA A — MCP oficial Meta (preferida):")
    print("  1. mcp__meta-official__authenticate")
    print("     → recebe callback_url; mostre ao aluno e peça pra autorizar")
    print("  2. Aguarde o aluno colar a URL final do browser")
    print("  3. mcp__meta-official__complete_authentication(callback_url=<url>)")
    print("  4. mcp__meta-official__ads_get_ad_accounts")
    print("     → liste contas com is_ads_mcp_enabled=true (se >1, aluno escolhe)")
    print()
    print("  5. python3 setup/setup_meta_oauth.py --sync-from-mcp")
    print("     → ⚠️  OBRIGATÓRIO após Via A: copia token do ~/.claude.json")
    print("       pra meta.env. Sem isso, fetcher autônomo (LaunchAgent) falha.")
    print()
    print("⚠️  Se Via A falhar com 'redirect_uris not registered' OU lista vazia:")
    print()
    print("VIA B — System User Token (fallback):")
    print("  python3 setup/setup_meta_oauth.py --renew")
    print("  → guia o aluno a gerar token manual no Business Manager")
    print("  → grava direto em meta.env (não precisa --sync-from-mcp)")
    print()
    print("APÓS QUALQUER VIA:")
    print("  python3 setup/setup_meta_oauth.py --set-account act_XXXXXXXX")
    print("  python3 setup/setup_meta_oauth.py --validate")
    print("    → exit 0 = tudo OK")
    print()
    print("=" * 60)
    print()
    print("⚠️  NUNCA exiba o access_token completo. Mostre só prefix+sufix.")
    return 0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--set-account", metavar="ACT_ID",
                        help="Grava META_AD_ACCOUNT_ID em meta.env")
    parser.add_argument("--set-token", metavar="TOKEN",
                        help="Grava META_ACCESS_TOKEN em meta.env (chmod 600)")
    parser.add_argument("--renew", action="store_true",
                        help="Fluxo Via B — aluno cola System User Token")
    parser.add_argument("--sync-from-mcp", action="store_true",
                        help="Copia token do ~/.claude.json (MCP oficial) pra meta.env")
    parser.add_argument("--validate", action="store_true",
                        help="Valida token + meta.env (Graph API GET /me)")
    args = parser.parse_args()

    if args.set_account:
        return write_account(args.set_account)
    if args.set_token:
        return write_token(args.set_token)
    if args.renew:
        return cmd_renew()
    if args.sync_from_mcp:
        return cmd_sync_from_mcp()
    if args.validate:
        return cmd_validate()
    return cmd_instructions()


if __name__ == "__main__":
    sys.exit(main())
