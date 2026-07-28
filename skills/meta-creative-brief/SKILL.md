---
name: meta-creative-brief
description: "Gera briefing pronto pro designer/editor — 3 ângulos de copy, 3 ideias visuais, CTA, formato por placement (Feed, Reels, Stories). Você diz nicho + dor + oferta, eu entrego o documento. Triggers: briefing criativo, gerar briefing, criar briefing, briefing meta, briefing facebook."
model: sonnet
effort: medium
---

# meta-creative-brief

Gera markdown de briefing criativo pro designer/editor sem você redigir nada manualmente.

## Input necessário

Pergunte ao aluno (linguagem comercial):
1. **Nicho do cliente** (ex: "imobiliária", "agência marketing local")
2. **Dor principal** (ex: "corretor sem leads qualificados")
3. **Oferta** (ex: "agendamento gratuito de consultoria 30min")
4. **Tom de voz** (opcional: profissional/casual/provocativo)

## Output

Markdown estruturado:

```markdown
# Briefing Criativo — {nicho}

## Contexto
- Dor: {dor}
- Oferta: {oferta}
- Tom: {tom}

## 3 Hooks de Copy
1. {hook provocativo} — apela pra urgência/medo de perder
2. {hook social proof} — mostra quem já usou e funcionou
3. {hook benefício direto} — fala o que o cliente ganha

## 3 Hooks Visuais
1. {ideia 1} — ex: "antes/depois com tempo cronometrado"
2. {ideia 2} — ex: "depoimento em vídeo de 15s"
3. {ideia 3} — ex: "tela de WhatsApp com mensagem real"

## CTA
- Principal: {ex: "Quero agendar agora"}
- Alternativa: {ex: "Ver como funciona"}

## Especificações por placement

### Reels / Stories (9:16 — 1080×1920)
- Vídeo 15-30s, hook nos primeiros 3s
- Texto grande (>60pt) — gente assiste sem som
- Legenda burned-in obrigatória

### Feed / Discovery (1:1 — 1080×1080)
- Estática ou vídeo 6-15s
- Texto sobre imagem com contraste forte
- Logo/marca no canto

### Stories / Status (9:16 — 1080×1920)
- Mais leve, próximo do conteúdo orgânico
- CTA "Arrastar pra cima" (link sticker)
```

Salva em `~/.operacao-ia/briefings/{slug-nicho}-{YYYY-MM-DD}.md`.

## Glossário

`docs/glossario.md` — termos técnicos traduzidos.
