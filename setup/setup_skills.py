#!/usr/bin/env python3
"""
Setup 6 — Etapa 4: Instalar Skills + Agente Orquestrador

Copia 6 SKILL.md para ~/.claude/skills/.

Idempotente e seguro:
- Se a skill já existe e tem conteúdo IGUAL ao do repo, pula sem tocar.
- Se já existe e foi MODIFICADA (customizada pelo aluno), faz backup
  para ~/.claude/skills/.s6-backup-{slug}-{timestamp}/ e instala a nova.
- Imprime um relatório no final dizendo quem foi instalado, atualizado,
  pulado ou backupado.
"""
import datetime as dt
import filecmp
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SKILLS_SRC = REPO_ROOT / "skills"
SKILLS_DST = Path.home() / ".claude" / "skills"
BACKUP_BASE = SKILLS_DST  # backups dentro da mesma raiz

EXPECTED = [
    "agente-trafego-pago",
    "meta-campaign-launcher",
    "meta-creative-brief",
    "meta-metrics-fetcher",
    "meta-performance-analyzer",
    "meta-budget-optimizer",
]


def dirs_equal(a: Path, b: Path) -> bool:
    """True se a árvore de a e b é idêntica em conteúdo."""
    if not (a.exists() and b.exists()):
        return False
    cmp = filecmp.dircmp(str(a), str(b))
    if cmp.left_only or cmp.right_only or cmp.diff_files or cmp.funny_files:
        return False
    # recursivo via subdirs
    for sub in cmp.common_dirs:
        if not dirs_equal(a / sub, b / sub):
            return False
    return True


def main():
    if not SKILLS_SRC.exists():
        print(f"❌ Pasta skills/ não encontrada em {SKILLS_SRC}")
        return 1

    SKILLS_DST.mkdir(parents=True, exist_ok=True)
    timestamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")

    installed = []
    updated = []
    skipped = []
    backupped = []

    for slug in EXPECTED:
        src = SKILLS_SRC / slug
        dst = SKILLS_DST / slug
        if not src.exists():
            print(f"❌ Skill faltando no repo: {slug}")
            return 1

        if not dst.exists():
            shutil.copytree(src, dst)
            installed.append(slug)
            continue

        if dirs_equal(src, dst):
            skipped.append(slug)
            continue

        # diff existe → backup e atualiza
        backup_dir = BACKUP_BASE / f".s6-backup-{slug}-{timestamp}"
        shutil.copytree(dst, backup_dir)
        shutil.rmtree(dst)
        shutil.copytree(src, dst)
        updated.append(slug)
        backupped.append(backup_dir)

    print("\n📦 Resumo da instalação de skills:")
    if installed: print(f"  ✅ Instaladas (novas): {', '.join(installed)}")
    if updated:   print(f"  🔄 Atualizadas (com diff vs versão local): {', '.join(updated)}")
    if skipped:   print(f"  ⏭  Já estavam idênticas (puladas): {', '.join(skipped)}")
    if backupped:
        print(f"\n💾 Backups das versões anteriores:")
        for b in backupped:
            print(f"   • {b}")
        print("   (apague depois se não precisar)")

    total = len(installed) + len(updated) + len(skipped)
    print(f"\n{total}/{len(EXPECTED)} skills no destino. Pronto para a Etapa 5.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
