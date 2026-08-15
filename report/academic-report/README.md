# EcoHVAC Guardian academic report

This directory is a portable LaTeX source package for the verified two-room Project 2 implementation.

## Required edit before submission

Replace the bracketed author/student-ID and course/instructor placeholders in `metadata.tex`. No identity was inferred or fabricated.

## Build

Requires a standard TeX Live installation with `latexmk`, `pdflatex`, and BibTeX.

```bash
cd report/academic-report
latexmk -pdf -interaction=nonstopmode -halt-on-error -file-line-error main.tex
# or
make
```

A clean reproducibility check is:

```bash
make distclean
make all
make verify
make package
make verify-package
```

`make package` recreates `EcoHVAC_Guardian_LaTeX_Source.zip` from the canonical source set and regenerates `SHA256SUMS` for the PDF, ZIP, and archived sources. `make verify-package` verifies every hash and tests the archive. Generated LaTeX intermediates are excluded from the archive and should not be committed.

The report uses only portable LaTeX packages and `listings`; it does not require shell escape or Python/Pygments. Figures in `figures/` are the five current Project 2 evidence captures. Legacy Project 1 media and `01-operate-dashboard.png` are intentionally excluded. The report does not replace the currently missing executed model notebook/accepted AutoML output or the unfinished Project 2 executive-pitch PPTX/PDF.

## Evidence boundary

The PDF documents the as-built two-room simulator. Five rooms appear only as future scalability analysis. The predictive model is trained on deterministic synthetic snapshots and is advisory; the report does not claim field calibration, autonomous maintenance, production security, or measured ROI.
