DEST=/usr
PKGNAME=quack

.PHONY: install uninstall

all: install

install:
	install -d -m755	$(DEST)/bin
	install -d -m755	$(DEST)/share/licenses/$(PKGNAME)
	install -D -m755 $(PKGNAME).py $(DEST)/bin/$(PKGNAME)
	install -D -m644 LICENSE $(DEST)/share/licenses/$(PKGNAME)/LICENSE

uninstall:
	rm $(DEST)/bin/$(PKGNAME)
	rm $(DEST)/share/licenses/$(PKGNAME)/LICENSE
	rmdir $(DEST)/share/licenses/$(PKGNAME)
