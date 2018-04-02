#!/usr/bin/env python3

import os
import sys
import gettext
import subprocess
from shutil import copyfile
from datetime import date
from quack import VERSION


QUACK_L10N_PATH = "./po"


def compile():
    for lang in os.listdir(QUACK_L10N_PATH):
        if lang == "quack.pot":
            continue
        i18nfile = os.path.join(QUACK_L10N_PATH, lang,
                                "LC_MESSAGES", "quack.po")
        if not os.path.isfile(i18nfile):
            print("{} not found".format(i18nfile))
            continue
        mofile = os.path.join(QUACK_L10N_PATH, lang,
                              "LC_MESSAGES", "quack.mo")
        subprocess.run(["msgfmt", "-o", mofile, i18nfile])


def get_potfile():
    if not os.path.isdir(QUACK_L10N_PATH):
        os.makedirs(QUACK_L10N_PATH)
    return os.path.join(QUACK_L10N_PATH, "quack.pot")


def init():
    potfile = get_potfile()
    if os.path.isfile(potfile):
        os.unlink(potfile)
    gtcmd = ["xgettext", "--language=Python", "--keyword=_",
             "--keyword=N_", "--copyright-holder=Quack volunteers",
             "--package-name=Quack",
             "--package-version={}".format(VERSION),
             "--msgid-bugs-address=bugs@depar.is",
             "--from-code=UTF-8", "--output={}".format(potfile),
             "quack.py"]
    subprocess.run(gtcmd)
    subprocess.run(["sed", "-i", "-e",
                    "s|SOME DESCRIPTIVE TITLE.|Quack Translation Effort|",
                    "-e", "s|Content-Type: text/plain; charset=CHARSET|"
                    "Content-Type: text/plain; charset=UTF-8|",
                    "-e", "s|Copyright (C) YEAR|Copyright (C) {}|"
                    .format(date.today().year),
                    potfile])


def create(lang):
    potfile = get_potfile()
    i18nfile = os.path.join(QUACK_L10N_PATH, lang, "LC_MESSAGES")
    if not os.path.isdir(i18nfile):
        os.makedirs(i18nfile)
    i18nfile = os.path.join(i18nfile, "quack.po")
    subprocess.run(["msginit", "-l", lang, "-i", potfile,
                    "-o", i18nfile])


def update(lang):
    potfile = get_potfile()
    i18nfile = os.path.join(QUACK_L10N_PATH, lang, "LC_MESSAGES",
                            "quack.po")
    if not os.path.isfile(i18nfile):
        print("{} not found".format(i18nfile))
        sys.exit(1)
    oldi18nfile = os.path.join(QUACK_L10N_PATH, lang,
                               "LC_MESSAGES", "quack.old.po")
    copyfile(i18nfile, oldi18nfile)
    subprocess.run(["msgmerge", "--lang", lang, "-o",
                    i18nfile, oldi18nfile, potfile])
    os.unlink(oldi18nfile)


if len(sys.argv) < 2 or not sys.argv[1] in globals():
    print("./generate_translations.py [ init | compile ]")
    print("./generate_translations.py [ create | update ] lang")
    sys.exit(1)

if len(sys.argv) == 3:
    globals()[sys.argv[1]](sys.argv[2])
    sys.exit(0)

globals()[sys.argv[1]]()
