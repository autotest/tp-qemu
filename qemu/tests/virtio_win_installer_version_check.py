import logging
import re

from avocado.utils import process
from virttest import error_context, utils_misc

LOG_JOB = logging.getLogger("avocado.test")


@error_context.context_aware
def run(test, params, env):
    """
    Windows installer version check:

    1) Check virtio-win pkg on host.
    2) Version check of rpm pkg, iso, iso volume label and installer.

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment
    """
    vm = env.get_vm(params["main_vm"])
    session = vm.wait_for_login()

    error_context.context("Check virtio-win-installer version.", LOG_JOB.info)
    pkg_status = process.getstatusoutput(params["rpm_install_chk_cmd"], shell=True)[0]
    if pkg_status:
        test.cancel(
            "Pls check the test env: whether virtio-win pkg is " "installed on host."
        )

    pkg_ver = (
        process.system_output(params["rpm_ver_chk_cmd"], shell=True).strip().decode()
    )

    iso_name = (
        process.system_output(params["iso_name_chk_cmd"], shell=True).strip().decode()
    )
    # /usr/share/virtio-win/virtio-win-1.9.xx.iso
    ver_pattern = r"\d.*\d"
    iso_ver = re.findall(ver_pattern, iso_name, re.I)[0]

    iso_label_name = session.cmd_output(params["iso_label_chk_cmd"]).strip()
    # virtio-win-1.9.xx
    iso_label_ver = re.findall(ver_pattern, iso_label_name, re.I)[0]

    vol_virtio_key = "VolumeName like '%virtio-win%'"
    vol_virtio = utils_misc.get_win_disk_vol(session, vol_virtio_key)
    installer_ver = session.cmd_output(params["installer_chk_cmd"] % vol_virtio).strip()
    if not pkg_ver == iso_ver == iso_label_ver == installer_ver:
        test.fail(
            "Installer version isn't the same with others,"
            "the package version is %s\n"
            "the iso name version is %s\n"
            "the iso label version is %s\n"
            "the installer version is %s\n",
            (pkg_ver, iso_ver, iso_label_ver, installer_ver),
        )

    if session:
        session.close()
