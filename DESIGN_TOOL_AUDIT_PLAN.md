# Design Tool Audit Plan

## Tujuan
Memilih subset tool design yang aman dan relevan untuk meningkatkan portfolio website LZ-ArtWork.

## Tahap
1. Audit read-only repo resmi.
2. Nilai relevansi, kompatibilitas Termux, dependency, dan risiko.
3. Pilih maksimal 3 tool.
4. Install hanya setelah approval eksplisit.
5. Terapkan pada salinan draft, bukan produksi.
6. Verifikasi visual dan teknis.

## Hasil audit
- Prioritas 1: `impeccable` — audit visual dan anti-pattern.
- Prioritas 2: `taste-skill` — anti-slop dan design language.
- Tahap polish: `emil-design-eng` — detail interaction/animation.
- Penpot: wireframe/prototype manual, tidak perlu instal Termux.
- Ditunda: `ui-ux-pro-max` (overkill), `GSAP` (animasi implementasi), `hyperframes` (Puppeteer/FFmpeg berat).

## Batasan
- Jangan install semua tool.
- Jangan mengubah config produksi.
- Jangan mengubah aset tanpa approval.
- Jangan mengganti gaya artistik Rya dengan template generik.
- Portfolio eksternal tetap approval-gated.
- Instalasi skill menunggu approval eksplisit Rya.
