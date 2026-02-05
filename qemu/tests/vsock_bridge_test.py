import logging

import aexpect
from virttest import error_context, utils_logfile, utils_misc

from provider.win_driver_utils import get_driver_inf_path

LOG_JOB = logging.getLogger("avocado.test")


def setup_openssh_service(session, params):
    """
    Setup openssh server

    :param session: QEMU test object
    :param params: Dictionary with the test parameters
    """

    LOG_JOB.info("Copy OpenSSH installer")
    openssh_src_path = utils_misc.set_winutils_letter(
        session, params["openssh_src_path"]
    )
    openssh_dst_path = params["openssh_dst_path"]
    session.cmd_status_output(
        "xcopy %s %s /s /e /i /y" % (openssh_src_path, openssh_dst_path)
    )

    LOG_JOB.info("Install OpenSSH")
    session.cmd_status_output(params["install_config_openssh"])


@error_context.context_aware
def run(test, params, env):
    """
    Vsock bridge service test

    1. Boot guest with vhost-vsock-pci device
    2. Install OpenSSH in VM
    3. Install vsock bridge service in VM
    4. Start OpenSSH and vsock bridge service in VM
    5. Connect VM via vsock bridge service

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment
    """

    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    session = vm.wait_for_login()

    test_tool = params["test_tool"]
    virtio_win_media_type = params["virtio_win_media_type"]
    driver_name = params["driver_name"]

    LOG_JOB.info("Install and start openssh server service in guest")
    setup_openssh_service(session, params)

    LOG_JOB.info("Install vstbridge service in guest")
    path = get_driver_inf_path(session, test, virtio_win_media_type, driver_name)
    test_tool_src_path = path[: path.rfind("\\")] + "\\" + test_tool
    session.cmd_output("xcopy %s C:\\" % test_tool_src_path)
    session.cmd_output("C:\\%s -i" % test_tool)
    session = vm.reboot(session)

    LOG_JOB.info("Start OpenSSH service after reboot VM")
    session.cmd_status_output(params["start_openssh_service"])

    LOG_JOB.info("Connect VM via vsock bridge service")
    vsock_dev = params["vsocks"].split()[0]
    guest_cid = vm.devices.get(vsock_dev).get_param("guest-cid")
    conn_cmd = params["conn_cmd"] % guest_cid
    vsock_session = aexpect.Expect(
        conn_cmd,
        auto_close=False,
        output_func=utils_logfile.log_line,
        output_params=("vsock_%s_%s" % (guest_cid, 22),),
    )
    try:
        if vsock_session.read_until_last_line_matches("yes/no"):
            vsock_session.sendline("yes")
        if vsock_session.read_until_last_line_matches("password"):
            vsock_session.sendline(params["password"])
        if params["expect_output"] not in vsock_session.get_output():
            test.fail("Connect to vsock bridge service failed")
        else:
            test.log.info("Connect to VM via vsock bridge successfully")
    except Exception as e:
        test.fail("Can not connect to VM via vsock bridge service due to %s" % e)

    vsock_session.close()
    session.close()
