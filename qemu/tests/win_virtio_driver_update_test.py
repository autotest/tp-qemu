import logging

from virttest import error_context
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
    cdrom_virtio_downgrade = params.get("cdrom_virtio_downgrade")

    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()

    if params.get("need_uninstall") == "yes":
        error_context.context("Uninstall virtio driver", logging.info)
        single_driver_install.run(test, params, env)
        # Need install driver after uninstallation.
        params["need_uninstall"] = False
        error_context.context("Install virtio driver", logging.info)
    else:
        error_context.context("Downgrade virtio driver", logging.info)
        new_params = params.copy()
        new_params["cdrom_virtio"] = cdrom_virtio_downgrade
        vm.create(params=new_params)
        vm.verify_alive()
        single_driver_install.run(test, new_params, env)
        error_context.context("Upgrade virtio driver to original",
                              logging.info)
    vm.create(params=params)
    vm.verify_alive()
    single_driver_install.run(test, params, env)
    vm.destroy()
