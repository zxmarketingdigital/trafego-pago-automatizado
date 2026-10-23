#!/usr/bin/env python3
"""
tpa_projeto.py — um projeto por cliente (uma conta Claude, várias contas de anúncio).

Cada projeto tem a própria pasta (config Meta, perfil, dashboards, logs, briefings),
a própria porta de dashboard e os próprios agendamentos. Trocar de projeto NUNCA
sobrescreve o outro. O projeto "default" é a pasta ~/.operacao-ia de sempre.

  python3 setup/tpa_projeto.py criar <nome>     cria o projeto e já o deixa ativo
  python3 setup/tpa_projeto.py trocar <nome>    muda o projeto ativo (default = o padrão)
  python3 setup/tpa_projeto.py listar           lista projetos, conta Meta e porta
  python3 setup/tpa_projeto.py atual            mostra o projeto ativo
  python3 setup/tpa_projeto.py caminho [nome]   imprime a pasta do projeto (uso: skills/scripts)

Para um comando isolado em outro projeto sem trocar o ativo:
  TPA_PROJECT=<nome> python3 setup/setup_meta_oauth.py --validate
"""
import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import tpa_paths  # noqa: E402


def _base():
    return tpa_paths.base_dir()


def _account(p):
    try:
        for line in p.meta_env.read_text(encoding="utf-8").splitlines():
            if line.startswith("META_AD_ACCOUNT_ID="):
                return line.split("=", 1)[1].strip() or "-"
    except OSError:
        pass
    return "-"


def _active(base):
    """(nome, origem) do projeto vigente para este terminal."""
    env_name = (os.environ.get("TPA_PROJECT") or "").strip()
    if env_name:
        return env_name, "variável TPA_PROJECT"
    pointed = tpa_paths.read_pointer(base)
    if pointed:
        return pointed, "projeto ativo"
    return tpa_paths.DEFAULT_NAME, "padrão"


def cmd_criar(args):
    base = _base()
    p = tpa_paths.create_project(args.nome, base, activate=True)
    print("✅ Projeto '%s' criado e ATIVO." % p.name)
    print("   Pasta : %s" % p.home)
    print("   Porta do dashboard: %d" % p.port)
    print()
    print("Agora rode o setup normalmente para este cliente (Etapas 0 a 10):")
    print("   python3 setup/setup_base_s6.py")
    print("   python3 setup/setup_meta_oauth.py --renew        # token da conta DESTE cliente")
    print("   python3 setup/setup_meta_oauth.py --set-account act_<id-do-cliente>")
    print()
    print("Os agendamentos (LaunchAgent/cron) criados na Etapa 9 ficam com o nome do projeto")
    print("e rodam sempre na pasta dele, mesmo depois de você trocar de projeto.")
    if os.environ.get("TPA_PROJECT"):
        print()
        print("⚠️  A variável TPA_PROJECT=%s está definida neste terminal e tem prioridade sobre o"
              " projeto ativo. Remova-a (unset TPA_PROJECT) para valer o projeto novo." % os.environ["TPA_PROJECT"])
    return 0


def cmd_trocar(args):
    base = _base()
    name = args.nome
    if name != tpa_paths.DEFAULT_NAME:
        tpa_paths.validate_name(name)
        if not tpa_paths.project_exists(name, base):
            raise tpa_paths.TpaError(
                "O projeto '%s' não existe. Veja os existentes: python3 setup/tpa_projeto.py listar"
                "   |   criar: python3 setup/tpa_projeto.py criar %s" % (name, name)
            )
    p = tpa_paths.Paths(name, base)
    p.port  # valida o projeto de destino ANTES de gravar o ponteiro
    tpa_paths.set_active(name, base)
    print("✅ Projeto ativo agora: %s" % name)
    print("   Pasta : %s" % p.home)
    print("   Conta Meta: %s   Porta: %s" % (_account(p), p.port))
    if os.environ.get("TPA_PROJECT"):
        print("⚠️  TPA_PROJECT=%s está definida neste terminal e tem prioridade. Rode: unset TPA_PROJECT"
              % os.environ["TPA_PROJECT"])
    return 0


def cmd_listar(_args):
    base = _base()
    try:
        ativo = tpa_paths.resolve().name
    except tpa_paths.TpaError as exc:
        # listar é a ferramenta de diagnóstico: mostra o problema e continua listando
        ativo = None
        print("⚠️  %s" % exc)
        print()
    print("Projetos (base: %s)" % base)
    print()
    print("  %-2s %-20s %-18s %-6s %s" % ("", "PROJETO", "CONTA META", "PORTA", "PASTA"))
    for name, p in tpa_paths.list_projects(base):
        marca = "*" if name == ativo else " "
        porta = "-"
        try:
            porta = str(p.port)
        except tpa_paths.TpaError:
            pass
        print("  %-2s %-20s %-18s %-6s %s" % (marca, name, _account(p), porta, p.home))
    print()
    print("* = projeto ativo neste terminal")
    return 0


def cmd_atual(_args):
    base = _base()
    p = tpa_paths.resolve()
    _name, origem = _active(base)
    print("Projeto ativo: %s  (%s)" % (p.name, origem))
    print("Pasta        : %s" % p.home)
    print("Conta Meta   : %s" % _account(p))
    print("Porta        : %s" % p.port)
    return 0


def cmd_caminho(args):
    base = _base()
    if args.nome:
        if args.nome != tpa_paths.DEFAULT_NAME:
            tpa_paths.validate_name(args.nome)
        if args.nome != tpa_paths.DEFAULT_NAME and not tpa_paths.project_exists(args.nome, base):
            raise tpa_paths.TpaError("O projeto '%s' não existe." % args.nome)
        print(tpa_paths.project_home(args.nome, base))
    else:
        print(tpa_paths.resolve().home)
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Gerencia projetos (um por cliente) do Tráfego Pago Automatizado"
    )
    sub = parser.add_subparsers(dest="cmd")
    c = sub.add_parser("criar", help="cria um projeto novo e o ativa")
    c.add_argument("nome")
    c.set_defaults(fn=cmd_criar)
    t = sub.add_parser("trocar", help="muda o projeto ativo")
    t.add_argument("nome")
    t.set_defaults(fn=cmd_trocar)
    sub.add_parser("listar", help="lista os projetos").set_defaults(fn=cmd_listar)
    sub.add_parser("atual", help="mostra o projeto ativo").set_defaults(fn=cmd_atual)
    k = sub.add_parser("caminho", help="imprime a pasta do projeto")
    k.add_argument("nome", nargs="?")
    k.set_defaults(fn=cmd_caminho)
    args = parser.parse_args(argv)
    if not args.cmd:
        parser.print_help()
        return 2
    try:
        return args.fn(args)
    except tpa_paths.TpaError as exc:
        print("❌ %s" % exc, file=sys.stderr)  # stdout é só o resultado (ex.: `caminho`)
        return 1


if __name__ == "__main__":
    sys.exit(main())
