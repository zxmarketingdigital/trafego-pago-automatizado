#!/usr/bin/env python3
"""
Setup 6 — Etapa 3: Questionário Perfil de Campanhas

Modos:

  python3 setup_perfil_campanhas.py
    — Modo interativo (TTY). Faz perguntas e grava meta_perfil.json.

  python3 setup_perfil_campanhas.py --apply <perfil.json>
    — Modo headless. Lê JSON do path indicado, valida e grava.

  python3 setup_perfil_campanhas.py --template
    — Imprime um JSON template (stdout) que o Claude preenche junto
      com o aluno via chat e depois aplica com --apply.

  python3 setup_perfil_campanhas.py --show
    — Mostra o perfil salvo atualmente (se houver).

Quando invocado sem TTY (ex: subprocess do Claude) e sem flag, falha
imediatamente com instrução de usar --template + --apply.
"""
import argparse
import json
import os
import sys
from pathlib import Path

OPERACAO = Path.home() / ".operacao-ia"
PERFIL = OPERACAO / "config" / "meta_perfil.json"
META_ENV = OPERACAO / "config" / "meta.env"

OBJECTIVES = [
    ("LEAD_GENERATION", "Geração de Lead (form Meta ou redirect site)"),
    ("MESSAGES", "Conversa WhatsApp / Messenger / Instagram DM"),
    ("SALES", "Vendas (e-commerce / checkout)"),
    ("AWARENESS", "Reconhecimento (alcance / views)"),
    ("TRAFFIC", "Tráfego para site"),
    ("APP_INSTALL", "Instalações de App"),
]

KPIS_CATALOG = {
    "cpl":             {"label": "CPL (custo por lead)",       "better": "lower",  "format": "currency", "scale_at": 0.8, "kill_at": 1.5},
    "cpa":             {"label": "CPA (custo por venda)",      "better": "lower",  "format": "currency", "scale_at": 0.8, "kill_at": 1.5},
    "roas":            {"label": "ROAS",                        "better": "higher", "format": "ratio",    "scale_at": 0.8, "kill_at": 1.5},
    "cost_per_msg":    {"label": "Custo por mensagem",          "better": "lower",  "format": "currency", "scale_at": 0.8, "kill_at": 1.5},
    "cpm":             {"label": "CPM",                         "better": "lower",  "format": "currency", "scale_at": 0.8, "kill_at": 1.5},
    "ctr":             {"label": "CTR (taxa de clique)",        "better": "higher", "format": "percent",  "scale_at": 0.8, "kill_at": 1.5},
    "cpc":             {"label": "CPC",                         "better": "lower",  "format": "currency", "scale_at": 0.8, "kill_at": 1.5},
    "frequency":       {"label": "Frequência",                  "better": "lower",  "format": "ratio",    "scale_at": 0.8, "kill_at": 1.5},
    "cost_per_install":{"label": "Custo por instalação",        "better": "lower",  "format": "currency", "scale_at": 0.8, "kill_at": 1.5},
}

OBJECTIVE_KEYS = {k for k, _ in OBJECTIVES}


# ────────────────────────────── Validação ──────────────────────────────

def validate_perfil(perfil):
    """Valida um meta_perfil.json (dict). Devolve (ok, errors)."""
    errors = []

    objectives = perfil.get("objectives") or []
    if not objectives:
        errors.append("objectives vazio — escolha pelo menos 1")
    for o in objectives:
        if o not in OBJECTIVE_KEYS:
            errors.append(f"objective inválido: {o} (válidos: {sorted(OBJECTIVE_KEYS)})")

    kpis = perfil.get("kpis") or []
    if not kpis:
        errors.append("kpis vazio — escolha pelo menos 1")
    keys_seen = set()
    for k in kpis:
        key = k.get("key")
        if not key or key not in KPIS_CATALOG:
            errors.append(f"kpi.key inválido: {key}")
            continue
        if key in keys_seen:
            errors.append(f"kpi duplicado: {key}")
        keys_seen.add(key)
        target = k.get("target")
        try:
            target_f = float(target) if target is not None else 0
        except (ValueError, TypeError):
            target_f = 0
        if target_f <= 0:
            errors.append(f"kpi {key}: target deve ser > 0 (recebido: {target!r})")
        for thresh in ("scale_at", "kill_at"):
            v = k.get(thresh)
            if v is None:
                continue
            try:
                vf = float(v)
            except (ValueError, TypeError):
                errors.append(f"kpi {key}: {thresh} deve ser número")
                continue
            if vf <= 0 or vf > 5:
                errors.append(f"kpi {key}: {thresh}={vf} fora de range (0, 5]")

    primary = perfil.get("primary_kpi")
    if not primary:
        errors.append("primary_kpi não informado")
    elif primary not in keys_seen:
        errors.append(f"primary_kpi={primary} não está em kpis")

    windows = perfil.get("windows") or [4, 7, 14, 30]
    if not isinstance(windows, list) or not all(isinstance(w, int) and 1 <= w <= 90 for w in windows):
        errors.append("windows deve ser lista de inteiros entre 1 e 90")

    return (not errors, errors)


# ────────────────────────────── Helpers ────────────────────────────────

def read_ad_account():
    if META_ENV.exists():
        for line in META_ENV.read_text().splitlines():
            if line.startswith("META_AD_ACCOUNT_ID="):
                return line.split("=", 1)[1].strip()
    return ""


def normalize(perfil):
    """Aplica defaults e enriquece com label/format/better do catálogo."""
    perfil = dict(perfil)
    perfil.setdefault("windows", [4, 7, 14, 30])
    perfil.setdefault("decide_enabled", True)
    perfil.setdefault("ad_account_id", read_ad_account())

    new_kpis = []
    for k in perfil.get("kpis", []):
        key = k["key"]
        catalog = KPIS_CATALOG[key].copy()
        catalog["key"] = key
        catalog["target"] = float(k["target"])
        if "scale_at" in k: catalog["scale_at"] = float(k["scale_at"])
        if "kill_at"  in k: catalog["kill_at"]  = float(k["kill_at"])
        new_kpis.append(catalog)
    perfil["kpis"] = new_kpis
    return perfil


def show_summary(perfil):
    print("\n" + "=" * 60)
    print("RESUMO DO PERFIL")
    print("=" * 60)
    print(f"\n📌 Conta: {perfil.get('ad_account_id') or '(preenche depois)'}")
    print(f"📌 Objetivos: {', '.join(perfil['objectives'])}")
    print(f"\n📊 KPIs configurados:")
    for k in perfil["kpis"]:
        meta_fmt = (f"R${k['target']}" if k['format']=='currency'
                    else (f"{k['target']}%" if k['format']=='percent' else f"{k['target']}"))
        print(f"   • {k['label']:30s} meta {meta_fmt:>10s}  scale@{k['scale_at']}  kill@{k['kill_at']}")
    print(f"\n🎯 KPI primário: {perfil['primary_kpi']}")
    print(f"🔁 decide() ativo: {'sim' if perfil['decide_enabled'] else 'não'}")
    print(f"📅 Janelas: {perfil['windows']} dias")
    print("=" * 60)


def write_perfil(perfil):
    PERFIL.parent.mkdir(parents=True, exist_ok=True)
    PERFIL.write_text(json.dumps(perfil, indent=2, ensure_ascii=False))
    print(f"\n✅ Perfil salvo em {PERFIL}")


# ────────────────────────────── Modo interativo ────────────────────────

def ask_multi(prompt, options):
    print(f"\n{prompt}")
    for i, (k, label) in enumerate(options, 1):
        print(f"  [{i}] {label}")
    raw = input("\nDigite os números separados por vírgula (ex: 1,3): ").strip()
    chosen = []
    for tok in raw.split(","):
        tok = tok.strip()
        if not tok:
            continue
        try:
            idx = int(tok) - 1
            if 0 <= idx < len(options):
                chosen.append(options[idx][0])
        except ValueError:
            pass
    return chosen


def ask_kpis_interactive():
    print("\n" + "=" * 60)
    print("MÉTRICAS-CHAVE — quais você usa para julgar performance?")
    print("=" * 60)
    catalog_list = [(k, v["label"]) for k, v in KPIS_CATALOG.items()]
    keys = ask_multi("Selecione múltiplas:", catalog_list)
    if not keys:
        print("❌ Selecione pelo menos 1 KPI")
        return ask_kpis_interactive()
    kpis = []
    for key in keys:
        meta = KPIS_CATALOG[key].copy()
        meta["key"] = key
        print(f"\n→ {meta['label']}")
        while True:
            target_raw = input("   Sua meta numérica (deve ser > 0): ").strip()
            try:
                t = float(target_raw)
                if t <= 0:
                    print("   Meta deve ser maior que zero.")
                    continue
                meta["target"] = t
                break
            except ValueError:
                print("   Valor inválido. Digite só o número.")
        kpis.append(meta)
    return kpis


DECIDE_PRESETS = {
    "conservative": {"scale_at": 0.8, "kill_at": 1.5,
                     "label": "CONSERVADOR — banda larga, menos mexer"},
    "aggressive":   {"scale_at": 1.0, "kill_at": 1.0,
                     "label": "AGRESSIVO — sem zona neutra, decide na meta"},
}


def ask_decide_strategy_interactive(kpis):
    print("\n" + "=" * 60)
    print("ESTRATÉGIA decide() — quando matar/manter/escalar?")
    print("=" * 60)
    print()
    print("  [1] CONSERVADOR (recomendado)")
    print("      SCALE quando KPI 20% melhor que meta (scale@0.8)")
    print("      KILL  quando KPI 50% pior  que meta (kill@1.5)")
    print("      MANTER tudo no meio — boa pra evitar mexer demais")
    print()
    print("  [2] AGRESSIVO")
    print("      SCALE assim que atinge a meta (scale@1.0)")
    print("      KILL  assim que passa da meta  (kill@1.0)")
    print("      Sem zona neutra — toda mudança aciona ação")
    print()
    print("  [3] PERSONALIZADO")
    print("      Você define scale_at e kill_at por KPI")
    print()
    raw = input("Escolha [1-3] (default 1): ").strip() or "1"

    preset = None
    if raw == "1":
        preset = "conservative"
    elif raw == "2":
        preset = "aggressive"
    elif raw == "3":
        preset = "custom"
    else:
        print("Inválido — usando CONSERVADOR")
        preset = "conservative"

    if preset in ("conservative", "aggressive"):
        cfg = DECIDE_PRESETS[preset]
        for kpi in kpis:
            kpi["scale_at"] = cfg["scale_at"]
            kpi["kill_at"] = cfg["kill_at"]
        print(f"\n✅ Preset {cfg['label']} aplicado a todos os KPIs.")
        return kpis, True, preset

    # Custom: pergunta por KPI
    for kpi in kpis:
        print(f"\n→ {kpi['label']} ({'menor é melhor' if kpi['better']=='lower' else 'maior é melhor'})")
        try:
            sc = input("   SCALE quando atinge X% da meta (default 0.8): ").strip()
            if sc: kpi["scale_at"] = float(sc)
            kl = input("   KILL quando passa de X% da meta (default 1.5): ").strip()
            if kl: kpi["kill_at"] = float(kl)
        except ValueError:
            print("   Valor inválido — mantendo default")
    return kpis, True, "custom"


def ask_primary_kpi_interactive(kpis):
    if len(kpis) == 1: return kpis[0]["key"]
    print("\n" + "=" * 60)
    print("KPI PRIMÁRIO — qual decide primeiro em caso de conflito?")
    print("=" * 60)
    for i, k in enumerate(kpis, 1):
        print(f"  [{i}] {k['label']}")
    while True:
        raw = input(f"\nEscolha (1-{len(kpis)}): ").strip()
        try:
            idx = int(raw) - 1
            if 0 <= idx < len(kpis):
                return kpis[idx]["key"]
        except ValueError:
            pass
        print("Inválido")


def ask_windows_interactive():
    print("\n" + "=" * 60)
    print("JANELAS DE ANÁLISE")
    print("=" * 60)
    raw = input("Janelas (dias) separadas por vírgula [default 4,7,14,30]: ").strip()
    if not raw: return [4, 7, 14, 30]
    try:
        return sorted({int(x.strip()) for x in raw.split(",") if x.strip()})
    except ValueError:
        return [4, 7, 14, 30]


def run_interactive():
    print("\n📋 Etapa 3 — Questionário Perfil de Campanhas\n")
    objectives = ask_multi(
        "OBJETIVOS — quais campanhas você roda hoje? (multi-select)",
        OBJECTIVES,
    )
    if not objectives:
        print("❌ Selecione pelo menos 1 objetivo")
        return 1
    kpis = ask_kpis_interactive()
    kpis, decide_enabled, decide_preset = ask_decide_strategy_interactive(kpis)
    primary = ask_primary_kpi_interactive(kpis)
    windows = ask_windows_interactive()

    perfil = {
        "objectives": objectives,
        "kpis": [{"key": k["key"], "target": k["target"],
                  "scale_at": k["scale_at"], "kill_at": k["kill_at"]} for k in kpis],
        "primary_kpi": primary,
        "decide_enabled": decide_enabled,
        "decide_preset": decide_preset,
        "windows": windows,
        "ad_account_id": read_ad_account(),
    }
    perfil = normalize(perfil)
    ok, errs = validate_perfil(perfil)
    if not ok:
        print("\n❌ Perfil inválido:")
        for e in errs: print(f"   • {e}")
        return 1
    show_summary(perfil)
    if input("\nSalvar este perfil? [S/n]: ").strip().lower() in ("n", "no", "nao", "não"):
        print("Cancelado."); return 0
    write_perfil(perfil)
    return 0


# ────────────────────────────── Modo headless ──────────────────────────

TEMPLATE = {
    "objectives": ["LEAD_GENERATION"],
    "kpis": [
        {"key": "cpl", "target": 25.0, "scale_at": 0.8, "kill_at": 1.5}
    ],
    "primary_kpi": "cpl",
    "decide_enabled": True,
    "windows": [4, 7, 14, 30]
}


def cmd_template():
    print(json.dumps(TEMPLATE, indent=2, ensure_ascii=False))


def cmd_apply(path):
    p = Path(path).expanduser()
    if not p.exists():
        print(f"❌ Arquivo não existe: {p}"); return 1
    try:
        data = json.loads(p.read_text())
    except Exception as e:
        print(f"❌ JSON inválido: {e}"); return 1
    perfil = normalize(data)
    ok, errs = validate_perfil(perfil)
    if not ok:
        print("\n❌ Perfil inválido:")
        for e in errs: print(f"   • {e}")
        return 1
    show_summary(perfil)
    write_perfil(perfil)
    return 0


def cmd_show():
    if not PERFIL.exists():
        print("Sem perfil salvo."); return 0
    perfil = json.loads(PERFIL.read_text())
    show_summary(perfil)
    return 0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", metavar="JSON_PATH", help="Aplica perfil de um JSON")
    parser.add_argument("--template", action="store_true", help="Imprime JSON template")
    parser.add_argument("--show", action="store_true", help="Mostra perfil salvo")
    args = parser.parse_args()

    if args.template:
        cmd_template(); return 0
    if args.apply:
        return cmd_apply(args.apply)
    if args.show:
        return cmd_show()

    # Interativo só se TTY
    if not sys.stdin.isatty():
        print("⚠️  Sem TTY — não posso fazer perguntas interativas.\n")
        print("Use o fluxo headless (Claude faz as perguntas e gera o JSON):")
        print("  1. python3 setup/setup_perfil_campanhas.py --template > /tmp/perfil.json")
        print("  2. Edite /tmp/perfil.json com as respostas")
        print("  3. python3 setup/setup_perfil_campanhas.py --apply /tmp/perfil.json")
        return 2

    return run_interactive()


if __name__ == "__main__":
    sys.exit(main())
