.PHONY: all clean distclean verify package manifest verify-package

REPORT := main
SOURCE_ZIP := EcoHVAC_Guardian_LaTeX_Source.zip
SOURCE_FILES := main.tex metadata.tex preamble.tex references.bib Makefile latexmkrc README.md $(wildcard sections/*.tex) $(wildcard appendices/*.tex) $(wildcard figures/*.png)

all:
	latexmk -pdf -interaction=nonstopmode -halt-on-error -file-line-error $(REPORT).tex

clean:
	latexmk -c $(REPORT).tex

distclean:
	latexmk -C $(REPORT).tex

verify:
	@test -s $(REPORT).pdf
	@test -s $(REPORT).log
	@! grep -E "undefined references|Citation.*undefined|There were undefined references|There were undefined citations" $(REPORT).log

package: verify
	rm -f $(SOURCE_ZIP) SHA256SUMS
	zip -q $(SOURCE_ZIP) $(SOURCE_FILES)
	shasum -a 256 $(REPORT).pdf $(SOURCE_ZIP) $(SOURCE_FILES) > SHA256SUMS

manifest: package

verify-package:
	@test -s $(SOURCE_ZIP)
	@test -s SHA256SUMS
	shasum -a 256 -c SHA256SUMS
	unzip -tq $(SOURCE_ZIP)
