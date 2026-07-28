#!/usr/bin/env python3
"""
Setup 6 — Etapa 7 (Test): gera briefing criativo demo.

Instrui Claude a invocar `meta-creative-brief` com input padrão (ou aluno
fornece) e salvar markdown em ~/.operacao-ia/briefings/.
"""
import json
import sys
from datetime import datetime
from pathlib import Path

OPERACAO = Path.home() / ".operacao-ia"
BRIEFINGS = OPERACAO / "briefings"
PROGRESS = OPERACAO / "config" / "setup6_progress.json"


def update_progress(key, value):
    PROGRESS.parent.mkdir(parents=True, exist_ok=True)
    data = {}
    if PROGRESS.exists():
        try:
            data = json.loads(PROGRESS.read_text())
        except Exception:
            data = {}
    data[key] = value
    PROGRESS.write_text(json.dumps(data, indent=2))


def main():
    BRIEFINGS.mkdir(parents=True, exist_ok=True)
    today = datetime.now().strftime("%Y-%m-%d")

    print("🧪 Etapa 7 — Test Briefing")
    print("=" * 60)
    print()
    print("INSTRUÇÕES PRO CLAUDE:")
    print()
    print("Invoque `meta-creative-brief`. Pergunte ao aluno:")
    print('  1. Nicho do cliente (ex: "agência marketing local")')
    print('  2. Dor principal (ex: "leads desqualificados que não fecham")')
    print('  3. Oferta (ex: "auditoria gratuita 30min")')
    print()
    print("Se aluno não tiver cliente real, use exemplo:")
    print('  Nicho: "agência marketing local"')
    print('  Dor:  "leads desqualificados que não fecham"')
    print('  Oferta: "auditoria gratuita de 30 minutos"')
    print()
    print(f"Skill deve gravar markdown em:")
    print(f"  {BRIEFINGS}/<slug-nicho>-{today}.md")
    print()
    print("Após gerar:")
    print(f"  python3 setup/setup_e7_test_brief.py --mark-done <path-do-md>")
    print()
    print("=" * 60)
    return 0


def mark_done(path):
    update_progress("e7_test_completed", datetime.now().isoformat(timespec="seconds"))
    update_progress("e7_briefing_path", path)
    print(f"✅ E7 marcada como concluída. Briefing: {path}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "--mark-done":
        sys.exit(mark_done(sys.argv[2]))
    sys.exit(main())
