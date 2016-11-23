"""
rv_build_install.py - Builds and installs packages specified from @spice/nightly
                      copr repository
                      https://copr.fedorainfracloud.org/coprs/g/spice/nightly/

Requires: connected binaries remote-viewer, Xorg, gnome session

"""
import logging

from autotest.client.shared import error
from virttest import utils_spice


class InstallPackages(object):
    def __init__(self, params, env):
        self.params = params
        self.env = env

        self.connect()
    # __init__()

    def connect(self):
        """
        Connects to VM and powers it on and gets session information
        """
        vm_name = self.params.get("vm_name")
        self.vm = self.env.get_vm(self.params[vm_name + "_vm"])
        self.vm.verify_alive()
        self.vm_root_session = self.vm.wait_for_login(
            timeout=int(self.params.get("login_timeout", 360)),
            username="root", password="123456")

        logging.info("VM %s is up and running" % vm_name)
    # connect()

    def setup(self):
        remove_pkgs = self.params.get("remove_pkgs")
        if remove_pkgs:
            logging.info("Removing packages: '%s'" % remove_pkgs)
            self.vm_root_session.cmd("yum -y remove %s" % remove_pkgs)

        utils_spice.deploy_epel_repo(self.vm_root_session, self.params)

        # yum-plugin-copr for epel https://copr.fedorainfracloud.org/coprs/alonid/yum-plugin-copr/
        logging.info("Installing yum-plugin-copr for epel")
        self.vm_root_session.cmd("yum -y install https://copr-be.cloud.fedoraproject.org/results/alonid/yum-plugin-copr/epel-7-x86_64/00110045-yum-plugin-copr/yum-plugin-copr-1.1.31-508.el7.centos.noarch.rpm")

        # enable spice/nightly copr https://copr.fedorainfracloud.org/coprs/g/spice/nightly/
        logging.info("Enabling @spice/nightly copr repository")
        self.vm_root_session.cmd("yum -y copr enable @spice/nightly")
    # setup()

    def pkg_install(self):
        install_pkgs = self.params.get("install_pkgs")
        if not install_pkgs:
            raise error.TestFail("No package specified for installation")

        logging.info("Installing packages from @spice/nightly copr: '%s'" % install_pkgs)
        output = self.vm_root_session.cmd("yum -y install %s" % install_pkgs, timeout=300)
        logging.info(output)
    # pkg_install()

    def finish(self):
        utils_spice.clear_interface(self.vm)
    # finish()

    def install(self):
        self.setup()
        self.pkg_install()
        self.finish()
    # run()
#InstallPackages


def run(test, params, env):
    """
    Build and install packages from git on the client or guest VM

    Supported configurations:
    install_pkgs: name of the package to install
    remove_pkgs: name of the packages to remove before installing

    :param test: QEMU test object.
    :param params: Dictionary with the test parameters.
    :param env: Dictionary with test environment.
    """

    pkg = InstallPackages(params, env)
    pkg.install()
# run()
