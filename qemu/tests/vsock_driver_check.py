import logging

from avocado.utils import linux_modules
from virttest import error_context

from provider.win_driver_utils import (
    get_driver_inf_path,
    install_driver_by_virtio_media,
)

LOG_JOB = logging.getLogger("avocado.test")


@error_context.context_aware
def run(test, params, env):
    """
    Vsock basic function test

    1. Enable vhost_vsock in host
    2. Boot guest with vhost-vsock-pci device
    3. Install vsock driver in guest
    4. Check vsock driver status in guest
    5. Check vsock provider in guest

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment
    """

    LOG_JOB.info("Enable vhost_vsock module in host")
    linux_modules.load_module("vhost_vsock")
    vm = env.get_vm(params["main_vm"])
    session = vm.wait_for_login()
    virtio_win_media_type = params["virtio_win_media_type"]
    driver_name = params["driver_name"]
    test_tool = params["test_tool"]

    LOG_JOB.info("Install vsock driver in guest")
    install_driver_by_virtio_media(
        session,
        test,
        devcon_path=params["devcon_path"],
        media_type=virtio_win_media_type,
        driver_name=driver_name,
        device_hwid=params["viosock_hwid"],
    )

    LOG_JOB.info("Check vsock driver status in guest")
    if session.cmd_status(params["vio_driver_chk_cmd"]):
        test.fail("Vsock driver status is not ready.")

    LOG_JOB.info("Check vsock provider in guest")
    path = get_driver_inf_path(session, test, virtio_win_media_type, driver_name)
    test_tool_path = path[: path.rfind("\\")] + "\\" + test_tool
    output = session.cmd_output("%s /e" % test_tool_path)
    if params["vsock_provider"] not in output:
        test.fail("Not find vsock provider in guest.")

    session.close()
