DEST = /usr

VERSION = $(shell sed -n "s/^VERSION = \"\(.*\)\"$$/\1/p" quack.py)

L10N_LANGS = fr nb_NO es de it
PO_FILES   = $(L10N_LANGS:%=po/%/LC_MESSAGES/quack.po)
MO_FILES   = $(PO_FILES:%.po=%.mo)
DEST_MO    = $(L10N_LANGS:%=$(DEST)/share/locale/%/LC_MESSAGES/quack.mo)


.PHONY: install lang uninstall uplang

install: $(DEST_MO)
	install -d -m755 $(DEST)/bin
	install -d -m755 $(DEST)/share/licenses/quack
	install -D -m755 quack.py $(DEST)/bin/quack
	install -D -m644 LICENSE $(DEST)/share/licenses/quack/LICENSE

uninstall:
	rm $(DEST)/bin/quack
	rm $(DEST)/share/licenses/quack/LICENSE
	rmdir $(DEST)/share/licenses/quack

po/quack.pot:
	mkdir -p po
	xgettext --language=Python --keyword=_ \
		--copyright-holder="Quack volunteers" \
		--package-name=Quack --package-version=$(VERSION) \
		--msgid-bugs-address=bugs@depar.is --from-code=UTF-8 \
		--output=po/quack.pot quack.py
	sed -i -e "s/SOME DESCRIPTIVE TITLE./Quack Translation Effort/" \
		-e "s|Content-Type: text/plain; charset=CHARSET|Content-Type: text/plain; charset=UTF-8|" \
		-e "s|Copyright (C) YEAR|Copyright (C) $(shell date +%Y)|" \
		po/quack.pot

%.po: po/quack.pot
	mkdir -p $(@D)
	msginit -l $(@:po/%/LC_MESSAGES/quack.po=%) \
		--no-translator -i $< -o $@

po/%/LC_MESSAGES/quack.mo: po/%/LC_MESSAGES/quack.po
	msgfmt -o $@ $<

$(DEST)/share/locale/%/LC_MESSAGES/quack.mo: po/%/LC_MESSAGES/quack.mo
	install -D -m644 $< $@

lang: $(PO_FILES)

%.po~:
	msgmerge --lang $(@:po/%/LC_MESSAGES/quack.po~=%) \
		-o $@ $(@:%~=%) po/quack.pot
	sed -i -e "s|Copyright (C) [0-9]*|Copyright (C) $(shell date +%Y)|" \
		-e "s|Id-Version: Quack [0-9.]*|Id-Version: Quack $(VERSION)|" \
		$@
	cp $@ $(@:%~=%) && rm $@

uplang: $(PO_FILES:%=%~)
