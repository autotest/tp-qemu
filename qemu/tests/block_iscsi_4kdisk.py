"""Test to install the Windows OS on the 4k disk."""

from avocado.utils import process
from virttest import data_dir, utils_misc
from virttest.iscsi import Iscsi
from virttest.tests import unattended_install


def run(test, params, env):
    """
    Test to install the guest OS on the 4k disk.
    Steps:
        1) Setup iSCSI server with fileio backend and enable 4k sector.
        2) Discovery and login the above iSCSI target.
        3) Mount the iscsi disk and create raw image on it.
        4) Install a guest on the raw image as blk device and enable iothread .

    :param test:   QEMU test object.
    :param params: Dictionary with the test parameters.
    :param env:    Dictionary with test environment.
    """

    def _prepare():
        cmd_prepare = params["cmd_prepare"].format(dev_name)
        process.run(cmd_prepare, 600, shell=True)

    def _cleanup():
        if vm and vm.is_alive():
            vm.destroy()
        cmd_cleanup = params["cmd_cleanup"] % base_dir
        process.run(cmd_cleanup, 600, shell=True)

    try:
        vm = None
        params["image_size"] = params["emulated_image_size"]
        base_dir = data_dir.get_data_dir()
        iscsi = Iscsi.create_iSCSI(params, base_dir)
        iscsi.login()
        dev_name = utils_misc.wait_for(lambda: iscsi.get_device_name(), 60)
        if not dev_name:
            test.error("Can not get the iSCSI device.")

        test.log.info("Prepare env on: %s", dev_name)
        _prepare()
        test.log.info("Start to install ...")
        vm = env.get_vm(params["main_vm"])
        unattended_install.run(test, params, env)
        test.log.info("Install completed")
        vm.destroy()
        vm = None
    finally:
        _cleanup()
        iscsi.cleanup()
