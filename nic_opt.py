import logging

from virttest import utils_net
from virttest import utils_test
from virttest import error_context


@error_context.context_aware
def run(test, params, env):
    """
    NIC option check test.

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """

    def test_netperf():
        """
        Netperf stress test for nic option.
        """
        netperf_client = params.get("netperf_client", "main_vm")
        netperf_server = params.get("netperf_server", "localhost")
        sub_type = params.get("sub_type", "netperf_stress")
        params["netperf_client"] = netperf_client
        params["netperf_server"] = netperf_server
        error_context.context("Run netperf stress test, client: %s, server: %s" %
                              (netperf_client, netperf_server), logging.info)
        utils_test.run_virt_sub_test(test, params, env, sub_type)

    def test_ping():
        """
        Ping test for nic option.
        :return:
        """
        package_sizes = [int(i) for i in params.get("ping_package_sizes").split()]
        if params["os_type"] == "windows":
            ifname = utils_net.get_windows_nic_attribute(session=session,
                                                         key="netenabled", value=True,
                                                         target="netconnectionID")
        else:
            ifname = utils_net.get_linux_ifname(session,
                                                vm.get_mac_address())
        dest = utils_net.get_host_ip_address(params)

        for size in package_sizes:
            error_context.context("Test ping from '%s' to host '%s' on guest '%s'"
                                  " with package size %d. " %
                                  (ifname, dest, vm.name, size), logging.info)
            status, output = utils_test.ping(dest=dest, count=10,
                                             interface=ifname,
                                             packetsize=size,
                                             session=session,
                                             timeout=30)
            if status:
                test.fail("%s ping %s unexpected, output %s" % (vm.name, dest, output))
            if params["os_type"] == "windows":
                # windows guest get loss=0 when ping failed sometime, need further check
                loss = utils_test.get_loss_ratio(output)
                if not loss and "TTL" in output:
                    pass
                else:
                    test.fail("Guest ping test hit unexpected loss, error_info: %s" % output)

    login_timeout = float(params.get("login_timeout", 240))
    check_type = params.get("check_type").strip()
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    session = vm.wait_for_serial_login(timeout=login_timeout)

    if params["os_type"] == "windows":
        error_context.context("Verify if netkvm.sys is enabled in guest", logging.info)
        session = utils_test.qemu.windrv_check_running_verifier(session, vm,
                                                                test, "netkvm",
                                                                timeout=120)
    if check_type:
        func_name = "test_" + check_type
        if func_name not in locals():
            test.cancel("Function to test %s doesn't exist." % check_type)
        else:
            func = locals()[func_name]
            func()
    session.close()
