import os
import time

from avocado.utils import process
from virttest import data_dir, error_context, utils_net


@error_context.context_aware
def run(test, params, env):
    """
    1) Boot guest with "-net user" and virtio-net backend
    2) Set MTU value in guest
    3) Compile the script and execute
    4) After the script runs, check whether the guest status is alive.
    5) If the guest is alive, check the product for security breaches
    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """
    vm = env.get_vm(params["main_vm"])
    login_timeout = params.get_numeric("login_timeout", 360)
    vm.wait_for_login(timeout=login_timeout)
    exp_path = params["exp_path"]
    test_path = os.path.join(data_dir.get_deps_dir(), exp_path)
    vm.copy_files_to(test_path, "~")
    vm.destroy()

    params["nettype"] = "user"
    params["vhost"] = ""
    params = params.object_params(vm.name)
    vm.create(params=params)
    serial_session = vm.wait_for_serial_login(timeout=login_timeout)

    def mtu_test():
        test.log.info("Set mtu value and verfied")
        serial_session.cmd(params["fw_stop_cmd"], ignore_all_errors=True)
        guest_ifname = utils_net.get_linux_ifname(serial_session, vm.get_mac_address(0))
        if guest_ifname != "eth0":
            test.cancel("Guest device name is not expected")
        serial_session.cmd(params["set_mtu_cmd"] % guest_ifname)
        output = serial_session.cmd_output(params["check_mtu_cmd"] % guest_ifname)
        match_string = "mtu %s" % params["mtu_value"]
        if match_string not in output:
            test.fail("Guest mtu is not the expected value %s" % params["mtu_value"])

    def pkg_buffer_test():
        test.log.info("Compile the script and execute")
        serial_session.cmd("gcc -o ~/exp ~/exp.c")
        serial_session.sendline("~/exp")
        time.sleep(60)
        s = process.getstatusoutput(
            "ps -aux|grep /usr/bin/gnome-calculator |grep -v grep",
            timeout=60,
            shell=True,
        )[0]
        if s == 0:
            test.fail("Virtual machine has security issues")
        serial_session.send_ctrl("^c")
        test.log.info("send ctrl+c command to exit the current process.")
        vm.verify_kernel_crash()

    try:
        mtu_test()
        pkg_buffer_test()
    finally:
        serial_session.cmd(
            "rm -rf ~/exp ~/exp.c", timeout=login_timeout, ignore_all_errors=True
        )
        serial_session.close()
