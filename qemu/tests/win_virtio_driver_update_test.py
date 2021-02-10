import logging

from virttest import error_context
from virttest import utils_misc
from virttest import data_dir
from virttest import utils_test

from qemu.tests import single_driver_install


@error_context.context_aware
def run(test, params, env):
    """
    Virtio driver test for windows guest.
    1) boot guest with virtio device.
    2) enable and check driver verifier in guest.
    3) Uninstall and install driver:
    3.1) uninstall driver.
    3.2) install driver.
    3) Downgrade and upgrade driver:
    3.1) downgrade virtio driver to specified version.
    3.2) run subtest. (optional)
    3.3) upgrade virtio driver to original version.
    4) clear the driver verifier.

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment
    """

    def change_virtio_media(cdrom_virtio):
        """
        change iso for virtio-win
        :param cdrom_virtio: iso file
        """
        virtio_iso = utils_misc.get_path(data_dir.get_data_dir(),
                                         cdrom_virtio)
        logging.info("Changing virtio iso image to '%s'", virtio_iso)
        vm.change_media("drive_virtio", virtio_iso)

    vm = env.get_vm(params["main_vm"])
    timeout = int(params.get("login_timeout", 360))
    driver = params["driver_name"]
    error_context.context("Enable driver verifier in guest.", logging.info)
    session = vm.wait_for_login(timeout=timeout)
    session = utils_test.qemu.windrv_check_running_verifier(session, vm,
                                                            test, driver,
                                                            timeout)
    session.close()
    if params.get("need_uninstall") != "yes":
        error_context.context("Downgrade virtio driver", logging.info)
        change_virtio_media(params["cdrom_virtio_downgrade"])
        single_driver_install.run(test, params, env)
        # vm is rebooted in single driver install function
        error_context.context("Upgrade virtio driver to original",
                              logging.info)
        change_virtio_media(params["cdrom_virtio"])

    single_driver_install.run(test, params, env)
    vm.destroy()
