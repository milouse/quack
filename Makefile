DEST = /usr

PKGNAME     = quack
PKGNAME_CAP = Quack
VERSION     = $(shell sed -n "s/^VERSION = \"\(.*\)\"$$/\1/p" $(PKGNAME).py)

L10N_PATH  = po
L10N_LANGS = fr nb_NO
PO_FILES   = $(L10N_LANGS:%=$(L10N_PATH)/%/LC_MESSAGES/$(PKGNAME).po)
PU_FILES   = $(PO_FILES:%.po=%.pu)
MO_FILES   = $(PO_FILES:%.po=%.mo)
DEST_MO    = $(L10N_LANGS:%=$(DEST)/share/locale/%/LC_MESSAGES/$(PKGNAME).dmo)
CLEAN_MO   = $(DEST_MO:%.dmo=%.cmo)


.PHONY: build clean install pot uninstall
.PRECIOUS: $(PO_FILES)

all: build

build: pot $(MO_FILES)

clean:
	rm -f $(MO_FILES)

install: build $(DEST_MO)
	install -d -m755 $(DEST)/bin
	install -d -m755 $(DEST)/share/licenses/$(PKGNAME)
	install -D -m755 $(PKGNAME).py $(DEST)/bin/$(PKGNAME)
	install -D -m644 LICENSE $(DEST)/share/licenses/$(PKGNAME)/LICENSE

uninstall: $(CLEAN_MO)
	rm $(DEST)/bin/$(PKGNAME)
	rm $(DEST)/share/licenses/$(PKGNAME)/LICENSE
	rmdir $(DEST)/share/licenses/$(PKGNAME)

pot:
	mkdir -p $(L10N_PATH)
	xgettext --language=Python --keyword=_ \
		--copyright-holder="$(PKGNAME_CAP) volunteers" \
		--package-name=$(PKGNAME_CAP) --package-version=$(VERSION) \
		--msgid-bugs-address=bugs@depar.is --from-code=UTF-8 \
		--output=$(L10N_PATH)/$(PKGNAME).pot $(PKGNAME).py
	sed -i -e "s/SOME DESCRIPTIVE TITLE./$(PKGNAME_CAP) Translation Effort/" \
		-e "s|Content-Type: text/plain; charset=CHARSET|Content-Type: text/plain; charset=UTF-8|" \
		-e "s|Copyright (C) YEAR|Copyright (C) $(shell date +%Y)|" \
		$(L10N_PATH)/$(PKGNAME).pot

po: pot $(PU_FILES)

%.mo: %.po
	msgfmt -o $@ $<

%.dmo:
	install -d -m755 $(@D)
	install -D -m644 $(@:$(DEST)/share/locale/%/LC_MESSAGES/$(PKGNAME).dmo=$(L10N_PATH)/%/LC_MESSAGES/$(PKGNAME).mo) \
		$(@:%.dmo=%.mo)

%.cmo:
	rm -f $(@:%.cmo=%.mo)

%.po:
	mkdir -p $(@D)
	msginit -l $(@:$(L10N_PATH)/%/LC_MESSAGES/$(PKGNAME).po=%) \
		-i $(L10N_PATH)/$(PKGNAME).pot -o $@

%.pu: %.po
	cp $< $<.old
	msgmerge --lang $(<:$(L10N_PATH)/%/LC_MESSAGES/$(PKGNAME).po=%) -o $< \
		$<.old $(L10N_PATH)/$(PKGNAME).pot
	rm $<.old
