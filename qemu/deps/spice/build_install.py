#!/usr/bin/python

"""
Script to build and install packages from git in VMs
"""

import optparse
import os
import re
import subprocess
import sys


def run_subprocess_cmd(args):
    output = (
        subprocess.Popen(
            args,
            shell=False,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            close_fds=True,
        )
        .stdout.read()
        .strip()
    )
    return output


git_repo = {}
configure_options = {}
autogen_options = {}
prefix_defaults = {}

# Git repo associated with each packages
git_repo["spice-protocol"] = "git://git.freedesktop.org/git/spice/spice-protocol"
git_repo["spice-gtk"] = "git://anongit.freedesktop.org/spice/spice-gtk"
git_repo["spice-vd-agent"] = "git://git.freedesktop.org/git/spice/linux/vd_agent"
git_repo["xf86-video-qxl"] = "git://anongit.freedesktop.org/xorg/driver/xf86-video-qxl"
git_repo["virt-viewer"] = "https://git.fedorahosted.org/git/virt-viewer.git"
git_repo["spice-server"] = "git://anongit.freedesktop.org/spice/spice"

# options to pass
autogen_options["spice-gtk"] = (
    "--disable-gtk-doc --disable-werror --disable-vala  --enable-smartcard"
)
autogen_options["spice-vd-agent"] = "--libdir=/usr/lib64 --sysconfdir=/etc"
autogen_options["xf86-video-qxl"] = '--libdir="/usr/lib64"'
autogen_options["virt-viewer"] = "--with-spice-gtk --disable-update-mimedb"
autogen_options["spice-server"] = "--enable-smartcard"
prefix_defaults["spice-protocol"] = "/usr/local"
prefix_defaults["spice-vd-agent"] = "/usr"


usageMsg = "\nUsage: %prog -p package-to-build [options]\n\n"
usageMsg += "build_install.py lets you build any package from a git repo.\n"
usageMsg += "It downloads the git repo, builds and installs it.\n"
usageMsg += "You can pass options such as git repo, branch you want to build at,\n"
usageMsg += "specific commit to build at, build options to pass to autogen.sh\n"
usageMsg += "and which location to install the built binaries to.\n\n"
usageMsg += "The following aliases for SPICE are already set: "
usageMsg += "\n\tspice-protocol\t ->\t SPICE protocol "
usageMsg += "\n\tspice-gtk\t ->\t SPICE GTK "
usageMsg += "\n\tspice-vd-agent\t ->\t SPICE VD-Agent "
usageMsg += "\n\txf86-video-qxl\t ->\t QXL device driver"
usageMsg += "\n\tvirt-viewer\t ->\t Virt-Viewer"
usageMsg += "\n\tspice-server\t -> SPICE Server"

# Getting all parameters
parser = optparse.OptionParser(usage=usageMsg)
parser.add_option(
    "-p", "--package", dest="pkgName", help="Name of package to build. Required."
)
parser.add_option(
    "-g", "--gitRepo", dest="gitRepo", help="Repo to download and build package from"
)
parser.add_option(
    "-b", "--branch", dest="branch", default="master", help="Branch to checkout and use"
)
parser.add_option(
    "-d", "--destDir", dest="destDir", help="Destination Dir to store repo at"
)
parser.add_option("-c", "--commit", dest="commit", help="Specific commit to download")
parser.add_option(
    "-l", "--prefix", dest="prefix", help="Location to store built binaries/libraries"
)
parser.add_option(
    "-o",
    "--buildOptions",
    dest="buildOptions",
    help="Options to pass to autogen.sh while building",
)
parser.add_option(
    "--tarball",
    dest="tarballLocation",
    help="Option to build from tarball. Pass tarball location",
)


(options, args) = parser.parse_args()

if not options.pkgName:
    print("Missing required arguments")
    parser.print_help()
    sys.exit(1)

pkgName = options.pkgName
branch = options.branch
destDir = options.destDir
commit = options.commit
prefix = options.prefix
tarballLocation = options.tarballLocation

if options.buildOptions:
    autogen_options[pkgName] = options.buildOptions
if options.gitRepo:
    git_repo[pkgName] = options.gitRepo

f = open("/etc/redhat-release", "r")
rhelVersion = f.read()
print("OS: %s" % rhelVersion)
if re.findall("release 6", rhelVersion):
    if pkgName in ("spice-gtk", "virt-viewer"):
        autogen_options[pkgName] += " --with-gtk=2.0"
    if pkgName in ("xf86-video-qxl"):
        autogen_options[pkgName] += " --disable-kms"

if not tarballLocation:
    # If spice-gtk & not tarball, then disable spice controller
    if pkgName == "spice-gtk":
        autogen_options[pkgName] += " --disable-controller"

    ret = os.system("which git")
    if ret != 0:
        print("Missing git command!")
        sys.exit(1)

    # Create destination directory
    if destDir is None:
        basename = git_repo[pkgName].split("/")[-1]
        destDir = os.path.join("/tmp", basename)
        if os.path.exists(destDir):
            print("Deleting existing destination directory")
            subprocess.check_call(("rm -rf %s" % destDir).split())

    # If destination directory doesn't exist, create it
    if not os.path.exists(destDir):
        print("Creating directory %s for git repo %s" % (destDir, git_repo[pkgName]))
        os.makedirs(destDir)

    # Switch to the directory
    os.chdir(destDir)

    # If git repo already exists, reset. If not, initialize
    if os.path.exists(".git"):
        print(
            "Resetting previously existing git repo at %s for receiving git repo %s"
            % (destDir, git_repo[pkgName])
        )
        subprocess.check_call("git reset --hard".split())
    else:
        print(
            "Initializing new git repo at %s for receiving git repo %s"
            % (destDir, git_repo[pkgName])
        )
        subprocess.check_call("git init".split())

    # Fetch the contents of the repo
    print(
        "Fetching git [REP '%s' BRANCH '%s'] -> %s"
        % (git_repo[pkgName], branch, destDir)
    )
    subprocess.check_call(
        ("git fetch -q -f -u -t %s %s:%s" % (git_repo[pkgName], branch, branch)).split()
    )

    # checkout the branch specified, master by default
    print("Checking out branch %s" % branch)
    subprocess.check_call(("git checkout %s" % branch).split())

    # If a certain commit is specified, checkout that commit
    if commit is not None:
        print("Checking out commit %s" % commit)
        subprocess.check_call(("git checkout %s" % commit).split())
    else:
        print("Specific commit not specified")

    # Adding remote origin
    print("Adding remote origin")
    args = ("git remote add origin %s" % git_repo[pkgName]).split()
    output = run_subprocess_cmd(args)

    # Get the commit and tag which repo is at
    args = "git log --pretty=format:%H -1".split()
    print("Running 'git log --pretty=format:%H -1' to get top commit")
    top_commit = run_subprocess_cmd(args)

    args = "git describe".split()
    print("Running 'git describe' to get top tag")
    top_tag = run_subprocess_cmd(args)
    if top_tag is None:
        top_tag_desc = "no tag found"
    else:
        top_tag_desc = "tag %s" % top_tag
    print("git commit ID is %s (%s)" % (top_commit, top_tag_desc))

# If tarball is not specified
else:
    tarballName = tarballLocation.split("/")[-1]
    args = ("wget -O /tmp/%s %s" % (tarballName, tarballLocation)).split()
    output = run_subprocess_cmd(args)

    args = ("tar xf /tmp/%s -C /tmp" % tarballName).split()
    output = run_subprocess_cmd(args)

    tarballName = re.sub(".tar.bz2", "", tarballName)
    destDir = "/tmp/%s" % tarballName
    os.chdir(destDir)

# If prefix to be passed to autogen.sh is in the defaults, use that
if pkgName in prefix_defaults.keys() and options.prefix is None:
    prefix = prefix_defaults[pkgName]

# if no prefix is set, the use default PKG_CONFIG_PATH. If not, set to
# prefix's PKG_CONFIG_PATH
if prefix is None:
    env_vars = (
        "PKG_CONFIG_PATH=$PKG_CONFIG_PATH:/usr/local/share/pkgconfig:"
        "/usr/local/lib:/usr/local/lib/pkgconfig:/usr/local/lib/pkg-config:"
    )
else:
    env_vars = (
        "PKG_CONFIG_PATH=$PKG_CONFIG_PATH:%s/share/pkgconfig:%s/lib:"
        "/usr/local/share/pkgconfig:%s/lib/pkgconfig:%s/lib/pkg-config:"
        % (prefix, prefix, prefix, prefix)
    )

# Running autogen.sh with prefix and any other options
# Using os.system because subprocess.Popen would not work
# with autogen.sh properly. --prefix would not get set
# properly with it

cmd = destDir + "/autogen.sh"
if not os.path.exists(cmd):
    cmd = destDir + "/configure"
    if not os.path.exists(cmd):
        print("%s doesn't exist! Something's wrong!" % cmd)
        sys.exit(1)

if prefix is not None:
    cmd += ' --prefix="' + prefix + '"'
if pkgName in autogen_options.keys():
    cmd += " " + autogen_options[pkgName]

print("Running '%s %s'" % (env_vars, cmd))
ret = os.system(env_vars + " " + cmd)
if ret != 0:
    print("Return code: %s! Autogen.sh failed! Exiting!" % ret)
    sys.exit(1)

# Temporary workaround for building spice-vdagent
if pkgName == "spice-vd-agent":
    os.system(
        "sed -i '/^src_spice_vdagent_CFLAGS/ s/$/  -fno-strict-aliasing/g' Makefile.am"
    )
    os.system("sed -i '/(PCIACCESS_CFLAGS)/ s/$/  -fno-strict-aliasing/g' Makefile.am")

# Running 'make' to build and using os.system again
cmd = "make"
print("Running '%s %s'" % (env_vars, cmd))
ret = os.system("%s %s" % (env_vars, cmd))
if ret != 0:
    print("Return code: %s! make failed! Exiting!" % ret)
    sys.exit(1)

# Running 'make install' to install the built libraries/binaries
cmd = "make install"
print("Running '%s %s'" % (env_vars, cmd))
ret = os.system("%s %s" % (env_vars, cmd))
if ret != 0:
    print("Return code: %s! make install failed! Exiting!" % ret)
    sys.exit(ret)
