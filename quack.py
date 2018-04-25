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


def print_info(message, symbol="::", color="blue"):
    print("{} {}".format(hilite(symbol, color, True),
                         hilite(message, bold=True)))


def question(message):
    return input("{} {} ".format(
        hilite("::", "blue"),
        hilite(message, bold=True))).lower()


class AurHelper:
    def __init__(self, config):
        self.config = config
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
        m = re.match("^aur/([a-z0-9-_]+)$", package)
        if m is None:
            return package
        return m[1]

    def current_version(self, package):
        for line in self.local_pkgs:
            m = re.match("^{} (.+)$".format(package), line)
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

    def list(self, with_version=False, with_devel=False):
        pkgs = []
        for p in self.local_pkgs:
            d = p.split(" ")
            if d[0] in self.all_pkgs:
                continue
            if self.is_devel(d[0]) and not with_devel:
                continue
            if with_version:
                pkgs.append(self.color_pkg_with_version(d[0], d[1]))
            else:
                pkgs.append(d[0])
        return pkgs

    def print_list(self, with_devel=False):
        print("\n".join(self.list(True, with_devel)))

    def list_garbage(self, post_transac=False):
        print_info(_("Orphaned packages"))
        p = subprocess.run(["pacman", "--color", USE_COLOR, "-Qdt"])
        if p.returncode == 1:
            print_info(_("no orphaned package found"),
                       symbol="==>", color="green")
        print_info(_("Pacman post transaction files"))
        ignore_pathes = [
            "/dev", "/home", "/lost+found", "/proc", "/root",
            "/run", "/sys", "/tmp", "/var/db", "/var/log",
            "/var/spool", "/var/tmp"
        ]
        cmd = ["find", "/", "("]
        for p in ignore_pathes:
            cmd.extend(["-path", p, "-o"])
        cmd.pop()
        if os.getuid() != 0:
            cmd.insert(0, "sudo")
        cmd += [")", "-prune", "-o", "-type", "f", "("]
        for p in ["*.pacsave", "*.pacorig", "*.pacnew"]:
            cmd.extend(["-name", p, "-o"])
        cmd.pop()
        cmd += [")", "-print"]
        subprocess.run(cmd)
        p = subprocess.run(
            cmd, check=True, stderr=subprocess.DEVNULL,
            stdout=subprocess.PIPE).stdout.decode().strip()
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

    def aur_dependencies(self, all_deps, git_name):
        aur_deps = []
        for d in all_deps:
            if d in self.all_pkgs:
                continue
            aur_deps.append(d)
        if len(aur_deps) == 0:
            return [], []
        ai = self.fetch_pkg_infos(aur_deps)
        if ai is None or len(ai) == 0:
            return [], []
        loc_deps = []
        for p in ai:
            if p["PackageBase"] != git_name:
                continue
            loc_deps.append(p["Name"])
            aur_deps.remove(p["Name"])
        return aur_deps, loc_deps

    def upgrade(self, with_devel=False):
        res = self.fetch_pkg_infos(self.list(False, with_devel))
        if res is None or len(res) == 0:
            return False
        upgradable_pkgs = []
        for p in res:
            cur_version = self.current_version(p["Name"])
            if cur_version == p["Version"]:
                continue
            ver_check = [cur_version, p["Version"]]
            ver_check.sort()
            if (with_devel is False or self.is_devel(p["Name"]) is None) \
               and ver_check[1] == cur_version:
                # Somehow we have a local version greater than upstream
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
            return False
        for p in packages:
            pcmd = ["cp", p, "/var/cache/pacman/pkg/{}".format(p)]
            if os.getuid() != 0:
                pcmd.insert(0, "sudo")
            subprocess.run(pcmd)

        return True

    def install(self, package):
        package = self.clean_pkg_name(package)
        no_pkg_err = _("{pkg} is NOT an AUR package").format(pkg=package)
        res = self.fetch_pkg_infos([package])
        if res is None or len(res) == 0:
            print_error(no_pkg_err)
        pkg_info = res[0]
        git_name = pkg_info["PackageBase"]
        deps = pkg_info["Depends"]
        with tempfile.TemporaryDirectory() as tmpdirname:
            os.chdir(tmpdirname)
            p = subprocess.run(["git", "clone",
                                "https://aur.archlinux.org/{}.git"
                                .format(git_name)])
            if p.returncode != 0:
                print_error(_("impossible to clone {pkg} from AUR")
                            .format(pkg=package))

            os.chdir(git_name)
            if not os.path.isfile("PKGBUILD"):
                print_error(no_pkg_err)

            print_info(_("Package {pkg} is ready to be built in {path}/{git}")
                       .format(pkg=package, path=tmpdirname, git=git_name))
            print_info(_("You should REALLY take time to inspect "
                         "its PKGBUILD."))
            check = question(_("When it's done, shall we continue?") +
                             " [y/N/q]")
            if check == "q":
                sys.exit()
            elif check != "y":
                return False
            p = subprocess.run(["makepkg", "-sr"])
            if p.returncode != 0:
                return False

            aur_deps, loc_deps = self.aur_dependencies(deps, git_name)
            if len(aur_deps) > 0:
                print("TODO: the following packages must be installed "
                      "first: {}".format(", ".join(aur_deps)))

            built_packages = []
            for f in os.listdir():
                if f.endswith(".pkg.tar.xz"):
                    built_packages.append(f)
            if len(built_packages) == 1:
                return self.pacman_install([built_packages[0]])
            print_info(_("The following packages have been built:"))
            i = 0
            for l in built_packages:
                i += 1
                print("[{}] {}".format(i, l))
            ps = question(_("Which one do you really want to install?") +
                          " [1…{}/A]".format(i))
            if ps == "a":
                return self.pacman_install(built_packages)
            final_pkgs = []
            try:
                for p in ps.split(" "):
                    pi = int(p)
                    if pi > len(built_packages):
                        raise ValueError
                    final_pkgs.append(built_packages[pi - 1])
            except ValueError:
                print_error(_("{str} is not a valid input")
                            .format(str=p))
            if len(final_pkgs) == 1 and \
               final_pkgs[0].startswith(package) and \
               len(loc_deps) > 0:
                for ld in loc_deps:
                    for bp in built_packages:
                        if bp == final_pkgs[0]:
                            continue
                        if not bp.startswith(ld):
                            continue
                        final_pkgs.append(bp)
                        break
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
                if len(obj[title]) != 0:
                    value = "  ".join(obj[title])
            else:
                value = str(obj[title])
        attr = hilite("{}: ".format(i18n_title.ljust(25)), bold=True)
        print(self.tw.fill(attr + value))

    def info(self, package):
        package = self.clean_pkg_name(package)
        if self.current_version(package) is not None:
            p = subprocess.run(["pacman", "--color", USE_COLOR,
                                "-Qi", package])
            sys.exit(p.returncode)
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

    aur = AurHelper(config)

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
        aur.print_list(args.devel)

    elif args.upgrade:
        if aur.upgrade(args.devel):
            aur.list_garbage(True)

    else:
        rcode = True
        for p in args.package:
            lr = aur.install(p)
            rcode = rcode and lr
        if rcode:
            aur.list_garbage(True)
