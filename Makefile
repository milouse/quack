DEST = /usr

VERSION = $(shell sed -n "s/^VERSION = \"\(.*\)\"$$/\1/p" quack.py)

L10N_LANGS = es fr nb_NO
PO_FILES   = $(L10N_LANGS:%=po/%/LC_MESSAGES/quack.po)
MO_FILES   = $(PO_FILES:%.po=%.mo)
DEST_MO    = $(L10N_LANGS:%=$(DEST)/share/locale/%/LC_MESSAGES/quack.mo)


.PHONY: clean install lang uninstall

install: clean $(DEST_MO)
	install -d -m755 $(DEST)/bin
	install -d -m755 $(DEST)/share/licenses/quack
	install -D -m755 quack.py $(DEST)/bin/quack
	install -D -m644 LICENSE $(DEST)/share/licenses/quack/LICENSE

uninstall:
	rm -f $(DEST)/bin/quack
	rm -rf $(DEST)/share/licenses/quack
	rm -f $(DEST_MO)

clean:
	find $(PWD) -type d -name __pycache__ -print0 | \
		xargs -0r rm -r
	find $(PWD) -type d -empty ! -path "*/.git/*" -print0 | \
		xargs -0r rmdir -p --ignore-fail-on-non-empty
	rm -f $(MO_FILES)

po/quack.pot:
	mkdir -p po
	xgettext --language=Python \
		--keyword=_ --keyword=pgettext:1c,2 --keyword=npgettext:1c,2,3 \
		--copyright-holder="Quack volunteers" \
		--package-name=Quack --package-version=$(VERSION) \
		--msgid-bugs-address=bugs@depar.is --from-code=UTF-8 \
		--output=po/quack.pot quack.py
	sed -i -e "s/SOME DESCRIPTIVE TITLE./Quack Translation Effort/" \
		-e "s|Content-Type: text/plain; charset=CHARSET|Content-Type: text/plain; charset=UTF-8|" \
		-e "s|Copyright (C) YEAR|Copyright (C) 2018-$(shell date +%Y)|" \
		po/quack.pot

%.po: po/quack.pot
	mkdir -p $(@D)
	[ ! -f $@ ] && \
		msginit -l $(@:po/%/LC_MESSAGES/quack.po=%) \
			--no-translator -i $< -o $@ || true
	msgmerge --lang $(@:po/%/LC_MESSAGES/quack.po=%) \
		-o $@ $@ $<
	sed -i -e "s|Copyright (C) 2018-[0-9]*|Copyright (C) 2018-$(shell date +%Y)|" \
		-e "s|Id-Version: Quack [0-9.]*|Id-Version: Quack $(VERSION)|" \
		$@

po/%/LC_MESSAGES/quack.mo: po/%/LC_MESSAGES/quack.po
	msgfmt -o $@ $<

$(DEST)/share/locale/%/LC_MESSAGES/quack.mo: po/%/LC_MESSAGES/quack.mo
	install -D -m644 $< $@

lang: $(PO_FILES)
