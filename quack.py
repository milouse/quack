#!/usr/bin/env python3

import os
import re
import sys
import glob
import time
import shutil
import requests
import tempfile
import textwrap
import subprocess
from configparser import ConfigParser
from xdg.BaseDirectory import xdg_cache_home
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


VERSION = "0.11"
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
    if color and color in color_map:
        attr.append(color_map[color])
    if bold:
        attr.append("1")
    if underline:
        attr.append("4")
    return "\x1b[{}m{}\x1b[0m".format(";".join(attr), string)


def print_error(message, quit=True):
    print("{} {}".format(hilite(_("error:"), "red", True), message),
          file=sys.stderr)
    if quit:
        sys.exit(1)


def print_warning(message):
    print("{} {}".format(hilite(_("warning:"), "yellow", True),
                         message))


def print_info(message, symbol="::", color="blue", bold=True):
    print("{} {}".format(hilite(symbol, color, True),
                         hilite(message, bold=bold)))


def question(message):
    return input("{} {} ".format(
        hilite("::", "blue", True),
        hilite(message, bold=True))).lower()


class AurHelper:
    def __init__(self, config, opts={}):
        self.config = config
        self.with_devel = opts.get("with_devel", False)
        self.dry_run = opts.get("dry_run", False)
        self.force = opts.get("force", False)
        self.jail_type = opts.get("jail_type", "docker")
        if self.jail_type == "docker" \
           and not self.check_command_presence("docker"):
            print_warning("Docker is not installed on your system.")
            self.jail_type = None
        self.is_child = opts.get("is_child", False)
        self.editor = os.getenv("EDITOR", "nano")
        self.temp_dir = None
        self.chroot_dir = None
        self.docker_image_built = False
        self.local_pkgs = subprocess.run(
            ["pacman", "-Q", "--color=never"],
            check=True, text=True,
            stderr=subprocess.DEVNULL,
            stdout=subprocess.PIPE
        ).stdout.strip().split("\n")
        self.all_pkgs = subprocess.run(
            ["pacman", "--color=never", "-Slq"] + self.config["repos"],
            check=True, text=True,
            stderr=subprocess.DEVNULL,
            stdout=subprocess.PIPE
        ).stdout.strip().split("\n")

    def is_devel(self, package):
        return re.search("-(?:bzr|cvs|git|hg|svn)$", package) is not None

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

    def sudo_wrapper(self, command):
        if os.getuid() == 0:
            return command
        command.insert(0, "sudo")
        # Command may contains only "sudo" in case we are just checking sudo
        # timeout.
        if len(command) > 1 and command[1] in ["docker", "pacman"]:
            # Some people authorize docker or pacman in their sudoers
            check_sudo_cmd = ["sudo", "-n", command[1], "--version"]
        else:
            check_sudo_cmd = ["sudo", "-n", "true"]
        check_sudo = subprocess.run(check_sudo_cmd,
                                    stdout=subprocess.DEVNULL,
                                    stderr=subprocess.DEVNULL)
        if check_sudo.returncode == 0:
            return command
        print_warning(_("You are going to run a `sudo' command and a "
                        "password will be prompted. Press Enter to "
                        "continue."))
        input()
        return command

    def check_command_presence(self, command):
        sentinel = subprocess.run(["which", command],
                                  stdout=subprocess.DEVNULL,
                                  stderr=subprocess.DEVNULL)
        return sentinel.returncode == 0

    def list_installed(self, with_version=False):
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
        print("\n".join(self.list_installed(True)))

    def list_transac_files(self):
        bkp_reg = re.compile(r"^%BACKUP%$", re.M)
        result = []
        for filepath in glob.glob("/var/lib/pacman/local/*/files"):
            with open(filepath, "r") as f:
                content = f.read()
                match = bkp_reg.search(content)
                if match is None:
                    continue
                f.seek(match.start())
                tail = f.read()
            for line in tail.split("\n"):
                ldata = [part.strip() for part in line.split("\t")]
                if ldata[0] in ["", "%BACKUP%"]:
                    continue
                basefile = "/" + ldata[0]
                if not os.path.exists(basefile):
                    continue
                for suffix in [".pacsave", ".pacorig", ".pacnew"]:
                    transacfile = basefile + suffix
                    if os.path.exists(transacfile):
                        result.append(transacfile)
        return result

    def list_garbage(self, post_transac=False, deep_search=False):
        print_info(_("Orphaned packages"), bold=False)
        p = subprocess.run(["pacman", "--color", USE_COLOR, "-Qdt"])
        if p.returncode == 1:
            print_info(_("0 orphaned package found"),
                       symbol="==>", color="green")
        print()
        print_info(_("Pacman post transaction files"), bold=False)
        if deep_search:
            cmd = ["find"]
            pac_pathes = ["/boot/", "/etc/", "/usr/"]
            cmd += pac_pathes + ["-type", "f", "("]
            for p in ["*.pacsave", "*.pacorig", "*.pacnew"]:
                cmd.extend(["-name", p, "-o"])
            cmd.pop()  # Remove the last "-o"
            cmd = self.sudo_wrapper(cmd + [")"])
            p = subprocess.run(
                cmd, text=True, capture_output=True
            ).stdout.strip()
        else:
            p = "\n".join(self.list_transac_files())
        if p == "":
            print_info(_("0 transactional file found"),
                       symbol="==>", color="green")
        else:
            print(p)
        if post_transac:
            return
        self.list_cached_packages()
        if not self.check_command_presence("docker"):
            return
        self.list_docker_garbage("container")
        self.list_docker_garbage("image")

    def list_cached_packages(self):
        if not self.check_command_presence("paccache"):
            return
        print()
        print_info(_("Removed packages kept in cache"), bold=False)
        cmd = ["paccache", "-du"]
        if USE_COLOR == "never":
            cmd.insert(1, "--nocolor")
        # Remove unnecessary empty line
        # Also we do not use capture_output as for strange reason
        # it loses the ANSI colors.
        p = subprocess.run(
            cmd, text=True, stdout=subprocess.PIPE
        ).stdout.strip()
        print(p + "\n")
        print_info(_("Old package versions kept in cache"), bold=False)
        if USE_COLOR == "never":
            cmd[2] = "-d"
        else:
            cmd[1] = "-d"
        # Remove unnecessary empty line here too.
        p = subprocess.run(
            cmd, text=True, stdout=subprocess.PIPE
        ).stdout.strip()
        print(p)

    def get_docker_images_list(self):
        images = subprocess.run(
            self.sudo_wrapper(
                ["docker", "image", "ls", "packaging", "--quiet"]
            ),
            check=True, text=True,
            stderr=subprocess.DEVNULL,
            stdout=subprocess.PIPE
        ).stdout.strip()
        if images == "":
            return []
        return images.split("\n")

    def get_docker_containers_list(self):
        containers = subprocess.run(
            self.sudo_wrapper(
                ["docker", "container", "ls", "--all",
                 "--filter", "ancestor=packaging",
                 "--filter", "status=exited", "--quiet"]
            ),
            check=True, text=True,
            stderr=subprocess.DEVNULL,
            stdout=subprocess.PIPE
        ).stdout.strip()
        if containers == "":
            return []
        return containers.split("\n")

    def list_docker_garbage(self, docker_type):
        plural_type = docker_type + "s"
        if docker_type == "image":
            context = "female"
        else:
            context = "male"
        # Count images
        number = len(
            getattr(self, "get_docker_{}_list".format(plural_type))()
        )
        print()
        print_info(_("Docker {item}").format(item=plural_type), bold=False)
        if context == "female":
            message = gettext.npgettext(
                "female", "{n} docker {item} found",
                "{n} docker {items} found", number
            )
        else:
            message = gettext.npgettext(
                "male", "{n} docker {item} found",
                "{n} docker {items} found", number
            )
        print_info(
            message.format(n=number, item=docker_type, items=plural_type),
            symbol="==>", color="green"
        )

    def cleanup_garbage(self):
        if self.check_command_presence("paccache"):
            print_info(_("Removing packages kept in cache…"), bold=False)
            subprocess.run(["paccache", "-r"])
        else:
            print_warning(_("paccache is not installed on your system. "
                            "It's provided in the pacman-contrib package."))

        if not self.check_command_presence("docker"):
            return
        # Remove first containers to avoid error when deleting images and avoid
        # to use force flag.
        self.cleanup_docker_garbage("container")
        # Now remove safely related images
        self.cleanup_docker_garbage("image")

    def cleanup_docker_garbage(self, docker_type):
        plural_type = docker_type + "s"
        if docker_type == "image":
            context = "female"
        else:
            context = "male"
        print()
        print_info(
            _("Removing leftover docker {item}").format(item=plural_type),
            bold=False
        )
        objects = getattr(self, "get_docker_{}_list".format(plural_type))()
        if len(objects) == 0:
            if context == "female":
                message = gettext.pgettext(
                    "female", "no candidate {item}s found for removing"
                )
            else:
                message = gettext.pgettext(
                    "male", "no candidate {item}s found for removing"
                )
            print_info(message.format(item=docker_type),
                       symbol="==>", color="green")
            return
        subprocess.run(
            self.sudo_wrapper(["docker", docker_type, "rm"] + objects)
        )
        number = len(objects)
        if context == "female":
            message = gettext.npgettext(
                "female", "finished: {n} {item} removed",
                "finished: {n} {items} removed", number
            )
        else:
            message = gettext.npgettext(
                "male", "finished: {n} {item} removed",
                "finished: {n} {items} removed", number
            ).format(n=number, item=docker_type, items=plural_type)
        print_info(
            message.format(n=number, item=docker_type, items=plural_type),
            symbol="==>", color="green"
        )

    def fetch_pkg_infos(self, terms, req_type="info"):
        req = "https://aur.archlinux.org/rpc?v=5"
        if req_type == "info":
            params = ["arg[]={}".format(t) for t in terms]
            req = "{}&type=info&{}".format(req, "&".join(params))
        else:
            req = "{}&type=search&arg={}".format(req, " ".join(terms))
        raw_json = requests.get(req).json()
        # Ensure we get a list
        if "results" not in raw_json:
            return []
        return sorted(raw_json["results"], key=lambda p: p["Name"])

    def handle_aur_dependencies(self, pkg_info):
        assert isinstance(self.temp_dir, tempfile.TemporaryDirectory)
        must_install = []
        for d in pkg_info["ExtDepends"]:
            ai = pkg_info.get("ExtDependsData", {}).get(d)
            if ai is None:
                print_warning(_("{pkg} is not an AUR package, maybe a "
                                "group or a virtual package.").format(pkg=d))
                continue
            pkgball = os.path.basename(ai["TargetCachePath"])
            destball = os.path.join(self.temp_dir.name, pkgball)
            if ai["FastForward"] is False:
                print_warning(_("The following package must be installed "
                                "first: {pkg}.").format(pkg=ai["Name"]))
                aur = AurHelper(self.config, {
                    "jail_type": self.jail_type,
                    "dry_run": self.dry_run,
                    "is_child": True
                })
                if aur.build(d) is None:
                    aur.close_temp_dir()
                    self.close_temp_dir(should_exit=True)
                assert isinstance(aur.temp_dir, tempfile.TemporaryDirectory)
                shutil.copyfile(
                    os.path.join(aur.temp_dir.name, pkgball),
                    destball
                )
                aur.close_temp_dir()
            else:
                shutil.copyfile(ai["TargetCachePath"], destball)
            if self.jail_type is None or d in pkg_info["ExtDepends"]:
                must_install.append((d, destball))

        # Go back to the parent dir
        os.chdir(self.temp_dir.name)

        for pkgdata in must_install:
            pkgball = os.path.basename(pkgdata[1])
            if self.dry_run:
                print("[dry-run] pacman -U {} --needed --noconfirm"
                      .format(pkgball))
                print("[dry-run] pacman -D --asdeps {}".format(pkgdata[0]))
            else:
                success = self.pacman_install([pkgball])
                if not success:
                    self.close_temp_dir()
                    print_error(_("An error occured while installing "
                                  "the dependency {pkg}.")
                                .format(pkg=pkgdata[0]))
                p = subprocess.run(
                    self.sudo_wrapper(["pacman", "-D", "--asdeps", pkgdata[0]])
                )
                if p.returncode != 0:
                    print_warning(_("An error occured while marking the "
                                    "package {pkg} as non-explicitely "
                                    "installed.").format(pkg=pkgdata[0]))

    def extract_dependencies(self, pkg_info):
        pkg_info["ExtDepends"] = []
        pkg_info["ExtDependsData"] = {}
        pkg_info["PackageBaseDepends"] = []
        for kind in ["MakeDepends", "Depends"]:
            for d in pkg_info.get(kind, []):
                pname = re.split("[<>=]+", d)[0]
                # self.all_pkgs contains only official packages
                if pname in self.all_pkgs:
                    continue
                ai = self.prepare_pkg_info(pname)
                if ai is None:
                    # It may happen for some virtual packages or group, which
                    # will normally be resolved by pacman itself
                    continue
                if ai["Name"] in pkg_info["ExtDepends"]:
                    # It has already be processed, for exemple as a dependency
                    # of one of its previous dependencies. Do not process it
                    # twice.
                    continue
                if ai["PackageBase"] == pkg_info["PackageBase"]:
                    # The dependency will be build in the same main package
                    # build process. Thus no need to treat it specially.
                    pkg_info["PackageBaseDepends"].append(ai["Name"])
                    continue
                pkg_info["ExtDepends"].append(ai["Name"])
                pkg_info["ExtDependsData"][ai["Name"]] = ai
                # Now we must look deeper for dependencies, among the newly
                # created external dependencies array. Official packages will
                # never depends on an external package, thus we don't have to
                # look further for official packages.
                ai = self.extract_dependencies(ai)
                for subp in ai["ExtDepends"]:
                    pkg_info["ExtDepends"].insert(0, subp)
                    pdata = ai["ExtDependsData"][subp]
                    pdata["FastForward"] = True
                    pkg_info["ExtDependsData"][subp] = pdata
        self.handle_aur_dependencies(pkg_info)
        return pkg_info

    def should_upgrade(self, package, current_version):
        # Always offer to upgrade devel packages
        if self.with_devel and self.is_devel(package["Name"]):
            return True
        if current_version == package["Version"]:
            return False
        # Yes I know about `vercmp`, but Array sort seems largely
        # sufficient to determine if 2 version number are different
        # or not, and it doesn't require another subprocess.
        # Ok, after test, array sorting failed to sort 1.9.1
        # and 1.11.1. We need to use vercmp.
        ver_check = subprocess.run(
            ["vercmp", current_version, package["Version"]],
            check=True, text=True, capture_output=True
        ).stdout.strip()
        if ver_check == "1":
            # Somehow we have a local version greater than upstream
            print_warning(
                _("Your system run a newer version of {pkg}.")
                .format(pkg=package["Name"]))
            return False
        return True

    def post_install(self, success):
        if success:
            self.list_garbage(True)
        return success

    def upgrade(self):
        res = self.fetch_pkg_infos(self.list_installed(False))
        if len(res) == 0:
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
        return self.post_install(rcode)

    def switch_to_temp_dir(self, pkg_info):
        self.temp_dir = tempfile.TemporaryDirectory(prefix="quack_")
        p = subprocess.run(["git", "clone",
                            "https://aur.archlinux.org/{}.git"
                            .format(pkg_info["PackageBase"]),
                            self.temp_dir.name])
        if p.returncode != 0:
            self.close_temp_dir()
            print_error(_("Impossible to clone {pkg} from AUR.")
                        .format(pkg=pkg_info["Name"]))
        os.chdir(self.temp_dir.name)
        if not os.path.isfile("PKGBUILD"):
            self.close_temp_dir()
            print_error(_("{pkg} is NOT an AUR package.")
                        .format(pkg=pkg_info["Name"]))

    def check_package_integrity(self, package):
        p = subprocess.run(["makepkg", "--verifysource"])
        if p.returncode == 0:
            return
        self.close_temp_dir()
        print_error(_("Integrity file check fails."))

    def prepare_temp_config_files(self):
        if not os.path.exists("/tmp/pacman.tmp.conf"):
            shutil.copyfile("/etc/pacman.conf", "/tmp/pacman.tmp.conf")
            subprocess.run(["sed", "-i", "s/^IgnorePkg/#IgnorePkg/",
                            "/tmp/pacman.tmp.conf"])
        if not os.path.exists("/tmp/makepkg.tmp.conf"):
            shutil.copyfile("/etc/makepkg.conf", "/tmp/makepkg.tmp.conf")

    def build_docker_image(self):
        if self.docker_image_built:
            return
        assert isinstance(self.temp_dir, tempfile.TemporaryDirectory)
        dockercontent = """FROM archlinux/archlinux

RUN echo 'Server = https://mirrors.gandi.net/archlinux/$repo/os/$arch' > /etc/pacman.d/mirrorlist && \
    pacman -Syu --noconfirm && \
    pacman -S --noconfirm base-devel devtools pacman-contrib namcap

RUN groupadd package && \
    useradd -m -d /home/package -c 'Package Creation User' -s /usr/bin/bash -g package package && \
    echo 'package ALL=(ALL) NOPASSWD: ALL' >> /etc/sudoers

USER package
WORKDIR /home/package/pkg
ENTRYPOINT ["/usr/bin/sh", "roadmap.sh"]
"""
        with open("Dockerfile.quack", "w") as f:
            f.write(dockercontent)
        p = subprocess.run(self.sudo_wrapper(
            ["docker", "build", "-t", "packaging", "-f", "Dockerfile.quack",
             self.temp_dir.name]))
        if p.returncode == 0:
            self.docker_image_built = True
            return
        self.close_temp_dir()
        print_error(_("Error while creating docker container."))

    def build_docker_roadmap(self, pkg_info):
        assert isinstance(self.temp_dir, tempfile.TemporaryDirectory)
        roadmap = ["#!/usr/bin/env sh", "set -e",
                   "sudo pacman -Syu --noconfirm"]
        # Allow one to provides is own operations before building the
        # package. It may by usefull to install other invisible dependencies.
        myfile = os.path.join(self.temp_dir.name, "my.roadmap.sh")
        if os.path.exists(myfile):
            with open(myfile, "r") as f:
                for line in f.readlines():
                    paccmd = line.strip()
                    if not paccmd.startswith("#"):
                        roadmap.append(paccmd)
        for d in pkg_info["ExtDepends"]:
            ai = pkg_info.get("ExtDependsData", {}).get(d)
            if ai is None:
                # It may happen for some virtual packages or group, which will
                # normally be resolved by pacman itself
                continue
            pkgball = os.path.basename(ai["TargetCachePath"])
            paccmd = "sudo pacman -U {} --noconfirm".format(pkgball)
            if paccmd not in roadmap:
                roadmap.append(paccmd)
        roadmap.append("exec makepkg -s --noconfirm --skipinteg")
        roadmap_content = "\n".join(roadmap)
        if self.dry_run:
            print(roadmap_content)
        with open(os.path.join(self.temp_dir.name, "roadmap.sh"), "w") as f:
            f.write(roadmap_content + "\n")

    def prepare_chroot_dir(self):
        chroot_home = os.path.join(xdg_cache_home, "quack", "chroot")
        if not os.path.isdir(chroot_home):
            os.makedirs(chroot_home, mode=0o700, exist_ok=True)
        self.chroot_dir = tempfile.TemporaryDirectory(dir=chroot_home)
        self.prepare_temp_config_files()
        os.environ["CHROOT"] = self.chroot_dir.name
        # Prevent sudo timeout
        self.sudo_wrapper([])
        # Create chroot dir
        p = subprocess.run(["mkarchroot", "-C", "/tmp/pacman.tmp.conf",
                            "-M", "/tmp/makepkg.tmp.conf",
                            "{}/root".format(self.chroot_dir.name),
                            "base-devel"])
        if p.returncode != 0:
            self.close_temp_dir()
            print_error(_("Error while creating the chroot dir in {folder}.")
                        .format(folder=self.chroot_dir.name))
        # Make sure chroot is up to date
        subprocess.run(["arch-nspawn", "{}/root".format(self.chroot_dir.name),
                        "pacman", "-Syu"])

    def close_temp_dir(self, success=True, should_exit=False):
        os.chdir(os.path.expanduser("~"))
        if self.temp_dir is not None:
            try:
                self.temp_dir.cleanup()
            except PermissionError:
                print_error(_("A permission error occured while deleting "
                              "the quack temp dir {folder}")
                            .format(foder=self.temp_dir.name))
            self.temp_dir = None
        if self.chroot_dir is not None:
            # Chroot requires sudo removal. Thus first do this
            subprocess.run(
                self.sudo_wrapper(["rm", "-r", self.chroot_dir.name]))
            # Then we recreate the temp dir to avoid a crash when cleaning it
            os.mkdir(self.chroot_dir.name)
            self.chroot_dir.cleanup()
            self.chroot_dir = None
            if "CHROOT" in os.environ:
                del os.environ["CHROOT"]
        if not should_exit or self.is_child:
            return success
        if success:
            sys.exit()
        sys.exit(1)

    def pacman_install(self, packages, backup=True):
        if backup:
            for p in packages:
                pcmd = self.sudo_wrapper(
                    ["cp", p, "/var/cache/pacman/pkg/{}".format(p)])
                subprocess.run(pcmd)
        pacman_cmd = self.sudo_wrapper(["pacman", "--color", USE_COLOR, "-U"])
        if not self.force:
            pacman_cmd.insert(-1, "--needed")
        p = subprocess.run(pacman_cmd + packages)
        return p.returncode == 0

    def prepare_pkg_info(self, package):
        res = self.fetch_pkg_infos([package])
        if len(res) == 0:
            return None
        pkg_info = res[0]
        pkg_info["FastForward"] = False
        pkg_info["CARCH"] = subprocess.run(
            ["uname", "-m"],
            check=True, text=True, capture_output=True
        ).stdout.strip()
        pkg_file = "/var/cache/pacman/pkg/{}-{}-{}.pkg.tar.zst".format(
            pkg_info["PackageBase"], pkg_info["Version"], pkg_info["CARCH"])
        pkg_info["TargetCachePath"] = pkg_file
        if not (self.force or self.is_devel(package)) and \
           os.path.isfile(pkg_file):
            pkg_info["BuiltPackages"] = [pkg_file]
            pkg_info["FastForward"] = True
            print_info(_("Package {pkg} is already built as {pkgfile}.")
                       .format(pkg=package, pkgfile=pkg_file))
        return pkg_info

    def build_dry_run(self, pkg_info):
        buildable_pkgs = subprocess.run(
            ["makepkg", "--packagelist"],
            check=True, text=True, capture_output=True
        ).stdout.split("\n")
        allowed_pkgs = []
        for p in buildable_pkgs:
            if p.endswith("-any") or p.endswith("-" + pkg_info["CARCH"]):
                allowed_pkgs.append(p + ".pkg.tar.zst")
        pkg_info["BuiltPackages"] = allowed_pkgs
        if self.jail_type == "docker":
            print("[dry-run] build docker image")
            print("[dry-run] roadmap.sh content >>>>")
            self.build_docker_roadmap(pkg_info)
            print("<<<<")
            print("[dry-run] docker run")
        else:
            print("[dry-run] makepkg -sr --skipinteg")
        return pkg_info

    def build(self, package):
        package = self.clean_pkg_name(package)
        pkg_info = self.prepare_pkg_info(package)
        if pkg_info is None:
            print_error(_("{pkg} is NOT an AUR package.").format(pkg=package))
        assert isinstance(pkg_info, dict)
        if pkg_info["FastForward"] is True:
            return pkg_info
        self.switch_to_temp_dir(pkg_info)
        assert isinstance(self.temp_dir, tempfile.TemporaryDirectory)
        print_info(_("Package {pkg} is ready to be built in {path}")
                   .format(pkg=hilite(package, "yellow", True),
                           path=self.temp_dir.name), bold=False)
        if not self.dry_run:
            print_info(_("You should REALLY take time to inspect its "
                         "PKGBUILD"), bold=False)
            check = question(_("When it's done, shall we continue?") +
                             " [y/N/q]")
            lc = str(check).lower()
            if self.is_child and lc != "y":
                return None
            if lc == "q":
                return self.close_temp_dir(should_exit=True)
            elif lc != "y":
                return self.close_temp_dir(False)
        pkg_info = self.extract_dependencies(pkg_info)
        # Run check in current environment to handle all possible requirements
        # (gpg keys...). We check this early because neither docker or chroot
        # build are able to do it in their striped down environments. It's
        # interesting too to check that everything will be fine in dry run.
        self.check_package_integrity(package)
        if self.dry_run:
            return self.build_dry_run(pkg_info)
        dependencies_packages = set(glob.glob("*.pkg.tar.zst"))
        returncode = 1
        if self.jail_type is None:
            # Thus avoid integrity check as it has already be done.
            returncode = subprocess.run(
                ["makepkg", "-sr", "--skipinteg"]
            ).returncode
        elif self.jail_type == "chroot":
            self.prepare_chroot_dir()
            assert isinstance(self.chroot_dir, tempfile.TemporaryDirectory)
            returncode = subprocess.run(
                ["makechrootpkg", "-c", "-r", self.chroot_dir.name]
            ).returncode
        elif self.jail_type == "docker":
            self.build_docker_image()
            self.build_docker_roadmap(pkg_info)
            returncode = subprocess.run(self.sudo_wrapper(
                ["docker", "run", "--rm", "--mount",
                 "type=bind,source={},destination={}".format(
                     self.temp_dir.name, "/home/package/pkg"
                 ), "packaging"])).returncode
        else:
            self.close_temp_dir()
            print_error(_("Jail type {type} is not known.")
                        .format(self.jail_type))
        if returncode != 0:
            self.close_temp_dir(False)
            print_error(_("Unexpected build error for {pkg}.")
                        .format(pkg=package))
        all_pkgs = set(glob.glob("*.pkg.tar.zst"))
        pkg_info["BuiltPackages"] = list(all_pkgs - dependencies_packages)
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
            return self.close_temp_dir(
                self.pacman_install(
                    [built_packages[0]], not pkg_info["FastForward"]
                )
            )
        print_info(_("The following packages have been built:"))
        pkg_idx = 0
        for line in built_packages:
            pkg_idx += 1
            print("[{}] {}".format(pkg_idx, line))
        ps = question(_("Which one do you really want to install?") +
                      " [1…{}/A]".format(pkg_idx))
        if str(ps).lower() == "a":
            if self.dry_run:
                print("[dry-run] pacman -U {}"
                      .format(" ".join(built_packages)))
                return self.close_temp_dir(True)
            return self.close_temp_dir(
                self.pacman_install(
                    built_packages, not pkg_info["FastForward"]
                )
            )
        final_pkgs = []
        p = _("<nothing>")
        try:
            for p in ps.split(" "):
                pi = int(p)
                if pi > len(built_packages):
                    raise ValueError
                final_pkgs.append(built_packages[pi - 1])
        except ValueError:
            print_error(_("{str} is not a valid input.").format(str=p))
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
        return self.close_temp_dir(
            self.pacman_install(final_pkgs, not pkg_info["FastForward"])
        )

    def install_list(self, packages):
        rcode = True
        for p in packages:
            lr = self.install(p)
            rcode = rcode and lr
        return self.post_install(rcode)

    def search(self, terms):
        res = self.fetch_pkg_infos(terms, "search")
        if len(res) == 0:
            return False
        for p in res:
            outdated = ""
            if "OutOfDate" in p and p["OutOfDate"] is not None:
                outdated = " " + hilite(_("[outdated]"), "red", True)
            print("{}{}\n    {}".format(
                self.color_pkg_with_version(p["Name"], p["Version"]),
                outdated, p["Description"]))

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
            elif obj[title] is not None:
                value = str(obj[title])
        attr = hilite("{}: ".format(i18n_title.ljust(25)), bold=True)
        print(self.tw.fill(attr + value))

    def info(self, package):
        package = self.clean_pkg_name(package)
        res = self.prepare_pkg_info(package)
        if res is None:
            print_error(_("{pkg} is NOT an AUR package.").format(pkg=package))
        self.tw = textwrap.TextWrapper(
            width=shutil.get_terminal_size((80, 20)).columns,
            subsequent_indent=27 * " ",
            break_on_hyphens=False,
            break_long_words=False)
        assert isinstance(res, dict)
        if "Maintainer" in res:
            res["Maintainer"] = "{0}  https://aur.archlinux.org/account/{0}" \
                .format(res["Maintainer"])
        res["LastModified"] = time.strftime(
            "%c %Z", time.gmtime(res["LastModified"]))
        if "OutOfDate" in res and res["OutOfDate"] is not None:
            ood = time.strftime("%c %Z", time.gmtime(res["OutOfDate"]))
            res["OutOfDate"] = hilite(
                _("Since {date}").format(date=ood), "red", True)
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
        self.info_line("OutOfDate",    res, _("Out of Date"))
        self.info_line("NumVotes",     res, _("Votes Number"))
        self.info_line("Popularity",   res, _("Popularity"))
        self.info_line("AurPage",      res, _("AUR Page"))
        self.info_line("Keywords",     res, _("Keywords"))
        print()  # pacman -Qi print one last line


if __name__ == "__main__":
    quack_desc = "Quack, the Qualitative and Usable Aur paCKage helper"
    parser = ArgumentParser(description=quack_desc,
                            usage="""%(prog)s -h
       %(prog)s -A [--devel] package [package ...]
       %(prog)s -A (-l, -u) [--devel]
       %(prog)s -A (-s, -i) package [package ...]
       %(prog)s -C [-c]""", epilog="""
     _         _
  __(.)>    __(.)<  Quack Quack
~~\\___)~~~~~\\___)~~~~~~~~~~~~~~~~~~

""", formatter_class=RawDescriptionHelpFormatter)
    parser.add_argument("-v", "--version", action="store_true",
                        help=_("Display %(prog)s version information"
                               " and exit"))
    parser.add_argument(
        "--color", metavar="WHEN", choices=["always", "never", "auto"],
        help=_("Specify when to enable coloring")
    )
    parser.add_argument("--crazyfool", action="store_true",
                        help=_("Allow %(prog)s to be run as root"))

    cmd_group = parser.add_argument_group(_("Commands"))
    cmd_group.add_argument(
        "-A", "--aur", action="store_true", default=True,
        help=_("AUR related actions (default)")
    )
    cmd_group.add_argument(
        "-C", "--list-garbage", action="store_true", default=False,
        help=_("Find and list .pacsave, .pacorig or .pacnew files")
    )

    sub_group = parser.add_argument_group(
        _("AUR actions"),
        _("Install action is implicit, when no other action is passed to "
          "the -A, --aur command")
    )
    sub_group.add_argument("-i", "--info", action="store_true",
                           help=_("Display information on an AUR package "
                                  "and exit"))
    sub_group.add_argument("-l", "--list", action="store_true",
                           help=_("List locally installed AUR packages "
                                  "and exit"))
    sub_group.add_argument("-s", "--search", action="store_true",
                           help=_("Search AUR packages by name and exit"))
    sub_group.add_argument("-u", "--upgrade", action="store_true",
                           help=_("Upgrade installed AUR packages"))
    sub_group = parser.add_argument_group(
        _("Install and Upgrade options"))
    sub_group.add_argument("--force", action="store_true",
                           help=_("Force install or upgrade action"))
    sub_group.add_argument("-n", "--dry-run", action="store_true",
                           help=_("Download package info and try to "
                                  "resolve dependencies, but do not build "
                                  "or install anything"))
    sub_group.add_argument(
        "-j", "--jail", default="docker", choices=["docker", "chroot", "none"],
        help=_("Run install and upgrade action in a docker (by default) or a "
               "chroot jail. Use --jail=none or --no-jail to prevent the use "
               "of a jail"))
    sub_group.add_argument("-J", "--no-jail", action="store_true",
                           help=_("Prevent install and upgrade action to "
                                  "be run in a jail"))
    sub_group = parser.add_argument_group(
        _("List, Install and Upgrade options"))
    sub_group.add_argument("--devel", action="store_true",
                           help=_("Include devel packages "
                                  "(which name has a trailing -svn, -git…)"))
    sub_group = parser.add_argument_group(
        _("Install, Info and Search options"))
    sub_group.add_argument("package", nargs="*", default=[],
                           help=_("One or more package name to install, "
                                  "look for, or display information about"))

    sub_group = parser.add_argument_group(_("Cleanup actions"))
    sub_group.add_argument(
        "-c", "--clean", action="store_true",
        help=_("Actually cleanup things instead of just listing them")
    )
    sub_group.add_argument(
        "-d", "--deep", action="store_true",
        help=_("Make a deep search of transactional files instead of a "
               "quick search (use find instead of pacman db).")
    )

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

    opts = {"with_devel": args.devel,
            "dry_run": args.dry_run,
            "force": args.force}

    aur = AurHelper(config, opts)

    if args.list_garbage:
        if args.clean:
            aur.cleanup_garbage()
        else:
            aur.list_garbage(deep_search=args.deep)
        sys.exit()

    package_less_subcommand = args.list or args.upgrade
    if package_less_subcommand is False and len(args.package) == 0:
        print_error(_("No package specified (use -h for help)"), False)
        print()
        parser.print_usage()
        sys.exit(1)

    if args.search:
        aur.search(args.package)

    elif args.info:
        aur.info(" ".join(args.package))

    elif args.list:
        aur.print_list()

    else:
        if args.no_jail:
            aur.jail_type = None
        else:
            aur.jail_type = args.jail

        if args.upgrade:
            sys.exit(int(not aur.upgrade()))

        sys.exit(int(not aur.install_list(args.package)))
