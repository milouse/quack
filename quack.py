#!/usr/bin/env python3

import os
import re
import sys
import time
import shutil
import requests
import tempfile
import textwrap
import subprocess
from configparser import ConfigParser
from argparse import ArgumentParser, RawDescriptionHelpFormatter

import gettext
loc_po = os.path.join(os.path.dirname(os.path.realpath(__file__)), "po")
if os.path.exists(loc_po):
    QUACK_L10N_PATH = loc_po
else:
    QUACK_L10N_PATH = "/usr/share/locale"

# Explicit declaration to avoid flake8 fear.
gettext.bindtextdomain("quack", QUACK_L10N_PATH)
gettext.textdomain("quack")
_ = gettext.gettext


VERSION = "0.2"
USE_COLOR = "never"


def hilite(string, color=None, bold=False, underline=False):
    if USE_COLOR == "never":
        return string
    attr = []
    color_map = {
        "red": "31",
        "green": "32",
        "yellow": "33",
        "blue": "34",
        "magenta": "35",
        "cyan": "36"
    }
    if color in color_map:
        attr.append(color_map[color])
    if bold:
        attr.append('1')
    if underline:
        attr.append('4')
    return "\x1b[{}m{}\x1b[0m".format(";".join(attr), string)


def print_error(message, quit=True):
    print("{} {}".format(hilite(_("error:"), "red", True), message),
          file=sys.stderr)
    if quit:
        sys.exit(1)


def print_warning(message):
    print("{} {}".format(hilite(_("warning:"), "yellow", True),
                         message))


def print_info(message, symbol="::", color="blue"):
    print("{} {}".format(hilite(symbol, color, True),
                         hilite(message, bold=True)))


def question(message):
    return input("{} {} ".format(
        hilite("::", "blue", True),
        hilite(message, bold=True))).lower()


class AurHelper:
    def __init__(self, config, devel=False, dry_run=False):
        self.config = config
        self.with_devel = devel
        self.dry_run = dry_run
        self.temp_dir = None
        self.local_pkgs = subprocess.run(
            ["pacman", "-Q", "--color=never"],
            check=True, stderr=subprocess.DEVNULL,
            stdout=subprocess.PIPE).stdout.decode().strip().split("\n")
        self.all_pkgs = subprocess.run(
            ["pacman", "--color=never", "-Slq"] + self.config["repos"],
            check=True, stderr=subprocess.DEVNULL,
            stdout=subprocess.PIPE).stdout.decode().strip().split("\n")

        self.editor = "nano"
        if os.getenv("EDITOR") != "":
            self.editor = os.getenv("EDITOR")

    def is_devel(self, package):
        return re.search("-(?:bzr|cvs|git|hg|svn)$", package)

    def clean_pkg_name(self, package):
        m = re.search("^aur/([a-z0-9-_]+)$", package)
        if m is None:
            return package
        return m[1]

    def current_version(self, package):
        for line in self.local_pkgs:
            m = re.search("^{} (.+)$".format(re.escape(package)), line)
            if m is None:
                continue
            return m[1]
        return None

    def color_pkg_with_version(self, package, version):
        version = hilite(version, "green", True)
        if self.current_version(package) is not None:
            version += " {}".format(hilite(_("[installed]"),
                                           "cyan", True))
        return "{}{} {}".format(
            hilite("aur/", "magenta", True),
            hilite(package, bold=True),
            version)

    def list(self, with_version=False):
        pkgs = []
        for p in self.local_pkgs:
            d = p.split(" ")
            if d[0] in self.all_pkgs:
                continue
            if self.is_devel(d[0]) and not self.with_devel:
                continue
            if with_version:
                pkgs.append(self.color_pkg_with_version(d[0], d[1]))
            else:
                pkgs.append(d[0])
        return pkgs

    def print_list(self):
        print("\n".join(self.list(True)))

    def list_garbage(self, post_transac=False):
        print_info(_("Orphaned packages"))
        p = subprocess.run(["pacman", "--color", USE_COLOR, "-Qdt"])
        if p.returncode == 1:
            print_info(_("no orphaned package found"),
                       symbol="==>", color="green")
        print_info(_("Pacman post transaction files"))
        cmd = ["find"]
        if os.getuid() != 0:
            cmd.insert(0, "sudo")
        pac_pathes = ["/boot/", "/etc/", "/usr/"]
        cmd += pac_pathes + ["-type", "f", "("]
        for p in ["*.pacsave", "*.pacorig", "*.pacnew"]:
            cmd.extend(["-name", p, "-o"])
        cmd.pop()
        cmd += [")"]
        p = subprocess.run(
            cmd, stdout=subprocess.PIPE).stdout.decode().strip()
        if p == "":
            print_info(_("no transactional file found"),
                       symbol="==>", color="green")
        else:
            print(p)
        if post_transac:
            return
        print_info(_("Removed packages kept in cache"))
        cmd = ["paccache", "-du"]
        if USE_COLOR == 'never':
            cmd.insert(1, "--nocolor")
        subprocess.run(cmd)
        print_info(_("Old package versions kept in cache"))
        if USE_COLOR == 'never':
            cmd[2] = "-d"
        else:
            cmd[1] = "-d"
        subprocess.run(cmd)

    def fetch_pkg_infos(self, terms, req_type="info"):
        req = "https://aur.archlinux.org/rpc.php?v=5"
        if req_type == "info":
            params = ["arg[]={}".format(t) for t in terms]
            req = "{}&type=info&{}".format(req, "&".join(params))
        else:
            req = "{}&type=search&arg={}".format(req, " ".join(terms))
        raw_json = requests.get(req).json()
        # Ensure we get a list
        if "results" not in raw_json:
            return []
        return raw_json["results"]

    def extract_dependencies(self, pkg_info):
        pkg_info["AurDepends"] = []
        pkg_info["PackageBaseDepends"] = []
        if "Depends" not in pkg_info:
            pkg_info["Depends"] = []
        for d in pkg_info["Depends"]:
            if d in self.all_pkgs:
                continue
            pkg_info["AurDepends"].append(d)
        if len(pkg_info["AurDepends"]) == 0:
            return pkg_info
        ai = self.fetch_pkg_infos(pkg_info["AurDepends"])
        if ai is None or len(ai) == 0:
            return pkg_info
        for p in ai:
            if p["PackageBase"] != pkg_info["PackageBase"]:
                continue
            pkg_info["PackageBaseDepends"].append(p["Name"])
            pkg_info["AurDepends"].remove(p["Name"])
        return pkg_info

    def should_upgrade(self, package, current_version):
        if current_version == package["Version"]:
            return False
        # Yes I know about `vercmp`, but Array sort seems largely
        # sufficient to determine if 2 version number are different
        # or not, and it doesn't require another subprocess.
        # Ok, after test, array sorting failed to sort 1.9.1
        # and 1.11.1. We need to use vercmp.
        ver_check = subprocess.run(
            ["vercmp", current_version, package["Version"]],
            check=True, stdout=subprocess.PIPE).stdout.decode().strip()
        if ((self.with_devel is False
           or self.is_devel(package["Name"]) is None)
           and ver_check == 1):
            # Somehow we have a local version greater than upstream
            print_warning(
                _("Your system run a newer version of {pkg}")
                .format(pkg=package["Name"]))
            return False
        return True

    def upgrade(self):
        res = self.fetch_pkg_infos(self.list(False))
        if res is None or len(res) == 0:
            return False
        upgradable_pkgs = []
        for p in res:
            cur_version = self.current_version(p["Name"])
            if not self.should_upgrade(p, cur_version):
                continue
            upgradable_pkgs.append(p["Name"])
            print("{} - {} - {}".format(
                  hilite(p["Name"], bold=True),
                  hilite(cur_version, "red"),
                  hilite(p["Version"], "green")))
        if len(upgradable_pkgs) == 0:
            return False
        upcheck = question(_("Do you want to upgrade the "
                             "above packages?") + " [y/N]")
        if upcheck != "y":
            return False
        rcode = True
        for p in upgradable_pkgs:
            lr = self.install(p)
            rcode = rcode and lr
        return rcode

    def switch_to_temp_dir(self, package):
        no_pkg_err = _("{pkg} is NOT an AUR package").format(pkg=package)
        res = self.fetch_pkg_infos([package])
        if res is None or len(res) == 0:
            print_error(no_pkg_err)
        pkg_info = res[0]
        self.temp_dir = tempfile.TemporaryDirectory(prefix="quack_")
        p = subprocess.run(["git", "clone",
                            "https://aur.archlinux.org/{}.git"
                            .format(pkg_info["PackageBase"]),
                            self.temp_dir.name])
        if p.returncode != 0:
            self.close_temp_dir()
            print_error(_("impossible to clone {pkg} from AUR")
                        .format(pkg=package))
        os.chdir(self.temp_dir.name)
        if not os.path.isfile("PKGBUILD"):
            self.close_temp_dir()
            print_error(no_pkg_err)
        print_info(_("Package {pkg} is ready to be built in {path}")
                   .format(pkg=package, path=self.temp_dir.name))
        return pkg_info

    def close_temp_dir(self, success=True, should_exit=False):
        if self.temp_dir is not None:
            os.chdir(os.path.expanduser("~"))
            self.temp_dir.cleanup()
            self.temp_dir = None
        if should_exit:
            sys.exit()
        return success

    def pacman_install(self, packages):
        pacman_cmd = ["pacman", "--color", USE_COLOR, "--needed", "-U"]
        if os.getuid() != 0:
            pacman_cmd.insert(0, "sudo")
        p = subprocess.run(pacman_cmd + packages)
        if p.returncode != 0:
            # Strange, pacman failed. May be a sudo timeout. Keep a copy
            # of the pkgs
            for px in packages:
                shutil.copyfile(px, "/tmp/{}".format(px))
            print_info(_("A copy of the built packages "
                         "has been kept in /tmp."))
            return self.close_temp_dir(False)
        for p in packages:
            pcmd = ["cp", p, "/var/cache/pacman/pkg/{}".format(p)]
            if os.getuid() != 0:
                pcmd.insert(0, "sudo")
            subprocess.run(pcmd)
        return self.close_temp_dir()

    def build(self, package):
        package = self.clean_pkg_name(package)
        pkg_info = self.switch_to_temp_dir(package)
        print_info(_("You should REALLY take time to inspect its PKGBUILD."))
        check = question(_("When it's done, shall we continue?") + " [y/N/q]")
        if check == "q":
            return self.close_temp_dir(should_exit=True)
        elif check != "y":
            return self.close_temp_dir(False)
        pkg_info = self.extract_dependencies(pkg_info)
        if len(pkg_info["AurDepends"]) > 0:
            unsatisfied = []
            for d in pkg_info["AurDepends"]:
                pdata = re.split("[<>=]+", d)
                if pdata[0] not in self.list():
                    unsatisfied.append(pdata[0])
            if len(unsatisfied) > 0:
                print_warning("the following packages must be "
                              "installed first: {}"
                              .format(", ".join(unsatisfied)))
        if self.dry_run:
            print("[dry-run] makepkg -sr")
            buildable_pkgs = subprocess.run(
                ["makepkg", "--packagelist"], check=True,
                stdout=subprocess.PIPE).stdout.decode().split("\n")
            arch = subprocess.run(
                ["uname", "-m"], check=True,
                stdout=subprocess.PIPE).stdout.decode()
            allowed_pkgs = []
            for p in buildable_pkgs:
                if p.endswith("-any") or p.endswith("-" + arch):
                    allowed_pkgs.append(p + ".pkg.tar.xz")
            pkg_info["BuiltPackages"] = allowed_pkgs
            return pkg_info
        p = subprocess.run(["makepkg", "-sr"])
        if p.returncode != 0:
            return self.close_temp_dir(False)
        pkg_info["BuiltPackages"] = []
        for f in os.listdir():
            if f.endswith(".pkg.tar.xz"):
                pkg_info["BuiltPackages"].append(f)
        return pkg_info

    def install(self, package):
        pkg_info = self.build(package)
        if pkg_info is False:
            return False
        built_packages = pkg_info["BuiltPackages"]
        if len(built_packages) == 0:
            return self.close_temp_dir(False)
        if len(built_packages) == 1:
            if self.dry_run:
                print("[dry-run] pacman -U {}".format(built_packages[0]))
                return self.close_temp_dir(True)
            return self.pacman_install([built_packages[0]])
        print_info(_("The following packages have been built:"))
        i = 0
        for l in built_packages:
            i += 1
            print("[{}] {}".format(i, l))
        ps = question(_("Which one do you really want to install?") +
                      " [1…{}/A]".format(i))
        if ps == "a":
            if self.dry_run:
                print("[dry-run] pacman -U {}"
                      .format(" ".join(built_packages)))
                return self.close_temp_dir(True)
            return self.pacman_install(built_packages)
        final_pkgs = []
        try:
            for p in ps.split(" "):
                pi = int(p)
                if pi > len(built_packages):
                    raise ValueError
                final_pkgs.append(built_packages[pi - 1])
        except ValueError:
            print_error(_("{str} is not a valid input").format(str=p))
        if (len(final_pkgs) == 1 and final_pkgs[0].startswith(package) and
           len(pkg_info["PackageBaseDepends"]) > 0):
            for ld in pkg_info["PackageBaseDepends"]:
                for bp in built_packages:
                    if bp == final_pkgs[0]:
                        continue
                    if not bp.startswith(ld):
                        continue
                    final_pkgs.append(bp)
                    break
        if self.dry_run:
            print("[dry-run] pacman -U {}".format(" ".join(final_pkgs)))
            return self.close_temp_dir(True)
        return self.pacman_install(final_pkgs)

    def search(self, terms):
        res = self.fetch_pkg_infos(terms, "search")
        if res is None:
            return False
        for p in res:
            print("{}\n    {}".format(
                self.color_pkg_with_version(p["Name"], p["Version"]),
                p["Description"]))

    def info_line(self, title, obj, i18n_title):
        value = "--"
        if title in obj:
            if type(obj[title]) is list:
                if title in ["Depends", "MakeDepends"]:
                    new_list = []
                    for p in obj[title]:
                        if p in self.all_pkgs:
                            new_list.append(p)
                            continue
                        new_list.append(hilite(p, underline=True))
                    obj[title] = new_list
                if len(obj[title]) != 0:
                    value = "  ".join(obj[title])
            else:
                value = str(obj[title])
        attr = hilite("{}: ".format(i18n_title.ljust(25)), bold=True)
        print(self.tw.fill(attr + value))

    def info(self, package):
        package = self.clean_pkg_name(package)
        res = self.fetch_pkg_infos([package])[0]
        if res is None:
            return False
        self.tw = textwrap.TextWrapper(
            width=shutil.get_terminal_size((80, 20)).columns,
            subsequent_indent=27 * " ",
            break_on_hyphens=False,
            break_long_words=False)
        if "Maintainer" in res:
            res["Maintainer"] = "{0}  https://aur.archlinux.org/account/{0}" \
                .format(res["Maintainer"])
        res["LastModified"] = time.strftime(
            "%c %Z", time.gmtime(res["LastModified"]))
        res["AurPage"] = "https://aur.archlinux.org/packages/{}" \
            .format(res["Name"])
        self.info_line("Name",         res, _("Name"))
        self.info_line("Version",      res, _("Version"))
        self.info_line("Description",  res, _("Description"))
        self.info_line("URL",          res, _("URL"))
        self.info_line("License",      res, _("Licenses"))
        self.info_line("Provides",     res, _("Provides"))
        self.info_line("Depends",      res, _("Depends On"))
        self.info_line("MakeDepends",  res, _("Build Depends On"))
        self.info_line("Conflicts",    res, _("Conflicts With"))
        self.info_line("Maintainer",   res, _("Last Maintainer"))
        self.info_line("LastModified", res, _("Last Modified"))
        self.info_line("NumVotes",     res, _("Votes Number"))
        self.info_line("Popularity",   res, _("Popularity"))
        self.info_line("AurPage",      res, _("AUR Page"))
        self.info_line("Keywords",     res, _("Keywords"))
        print()  # pacman -Qi print one last line


if __name__ == "__main__":
    quack_desc = "Quack, the Qualitative and Usable Aur paCKage helper"
    parser = ArgumentParser(description=quack_desc,
                            usage="""%(prog)s -h
       %(prog)s [--color WHEN] -C
       %(prog)s [--color WHEN] -A [-l | -u | -s | -i] [--devel]
                 [package [package ...]]""", epilog="""
     _         _
  __(.)>    __(.)<  Quack Quack
~~\\___)~~~~~\\___)~~~~~~~~~~~~~~~~~~

""", formatter_class=RawDescriptionHelpFormatter)
    parser.add_argument("-v", "--version", action="store_true",
                        help=_("Display %(prog)s version information"
                               " and exit."))
    parser.add_argument("--color", help="Specify when to enable "
                        "coloring. Valid options are always, "
                        "never, or auto.", metavar="WHEN")
    cmd_group = parser.add_argument_group("Operations")
    cmd_group.add_argument("-C", "--list-garbage", action="store_true",
                           help="Find and list .pacsave, "
                           ".pacorig, .pacnew files")
    cmd_group.add_argument("-A", "--aur", action="store_true",
                           help="AUR related operations "
                           "(default to install package)")
    sub_group = parser.add_argument_group("AUR options")
    sub_group.add_argument("-l", "--list", action="store_true",
                           help="List locally installed AUR packages "
                           "and exit.")
    sub_group.add_argument("-u", "--upgrade", action="store_true",
                           help="Upgrade locally installed AUR packages.")
    sub_group.add_argument("-s", "--search", action="store_true",
                           help="Search AUR packages by name and exit.")
    sub_group.add_argument("-i", "--info", action="store_true",
                           help="Display information on an AUR package "
                           "and exit.")
    parser.add_argument("--devel", action="store_true",
                        help="Include devel packages "
                        "(which name has a trailing -svn, -git…) "
                        "for list and upgrade operations")
    parser.add_argument("--crazyfool", action="store_true",
                        help=_("Allow %(prog)s to be run as root"))
    parser.add_argument("-n", "--dry-run", action="store_true",
                        help=_("Download package info and try to "
                               "resolve dependencies, but do not build "
                               "or install anything"))
    parser.add_argument("package", nargs="*", default=[],
                        help="One or more package name to install, "
                        "upgrade, display information about. Only "
                        "usefull for the -A operation.")
    args = parser.parse_args()

    if args.version:
        print("{} - v{}".format(quack_desc, VERSION))
        sys.exit(0)

    config = {
        "color": "never",
        "repos": []
    }

    if os.path.isfile("/etc/pacman.conf"):
        pac_conf = ConfigParser(allow_no_value=True)
        pac_conf.read("/etc/pacman.conf")
        config["repos"] = pac_conf.sections()
        config["repos"].remove("options")
        if "options" in pac_conf and "Color" in pac_conf["options"]:
            if pac_conf["options"]["Color"] is None:
                USE_COLOR = "auto"
            else:
                USE_COLOR = pac_conf["options"]["Color"].lower()

    if args.color:
        ac = args.color.lower()
        if ac in ["never", "auto", "always"]:
            USE_COLOR = ac
    config["color"] = USE_COLOR

    if os.getuid() == 0 and not args.crazyfool:
        print_error(_("Do not run {quack_cmd} as root!")
                    .format(quack_cmd=sys.argv[0]))

    aur = AurHelper(config, args.devel, args.dry_run)

    if args.list_garbage:
        aur.list_garbage()
        sys.exit()

    package_less_subcommand = args.list or args.upgrade
    if package_less_subcommand is False and len(args.package) == 0:
        if args.info or args.search:
            print_error(
                _("no targets specified (use -h for help)\n"), False)
        else:
            print_error(
                _("no operation specified (use -h for help)\n"), False)
        parser.print_usage()
        sys.exit(1)

    if args.search:
        aur.search(args.package)

    elif args.info:
        aur.info(" ".join(args.package))

    elif args.list:
        aur.print_list()

    elif args.upgrade:
        if aur.upgrade():
            aur.list_garbage(True)

    else:
        rcode = True
        for p in args.package:
            lr = aur.install(p)
            rcode = rcode and lr
        if rcode:
            aur.list_garbage(True)
