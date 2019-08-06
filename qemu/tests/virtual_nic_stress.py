import logging
import aexpect

from virttest import error_context
from virttest import utils_net
from virttest import utils_test
from virttest import utils_misc


@error_context.context_aware
def run(test, params, env):
    """
    Do network stress test when under memory stress
    1) Boot a guest with vhost=on
    2) swapoff in guest
    3) flood ping from guest to host
    4) do stress test

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """

    def flood_ping(session, host_ip, os_type="linux"):
        """
        Do flood ping from guest to host

        :param session: session to send flood ping
        :param host_ip: the IP of the host
        """
        flood_minutes = int(params["flood_minutes"])
        logging.info("Flood ping for %s minutes" % flood_minutes)
        try:
            utils_net.ping(host_ip, flood=True,
                           session=session, timeout=flood_minutes * 60)
        except aexpect.ExpectProcessTerminatedError:
            if os_type == "windows":
                session.close()
                session = vm.wait_for_login(timeout=timeout)
                pass
        return session

    def load_stress():
        """
        Load background IO/CPU/Memory stress in guest

        """
        error_context.context("launch stress app in guest", logging.info)
        args = (test, params, env, params["stress_test"])
        bg_test = utils_test.BackgroundTest(
            utils_test.run_virt_sub_test, args)
        bg_test.start()
        if not utils_misc.wait_for(bg_test.is_alive, first=10,
                                   step=3, timeout=100):
            test.fail("background test start failed")

    def unload_stress(session):
        """
        Stop stress app

        :param session: guest session
        """
        error_context.context("stop stress app in guest", logging.info)
        cmd = params.get("stop_cmd")
        session.sendline(cmd)

    timeout = float(params.get("login_timeout", 240))
    vm = env.get_vm(params["main_vm"])
    host_ip = utils_net.get_host_ip_address(params)
    session = vm.wait_for_login(timeout=timeout)

    os_type = params["os_type"]
    if os_type == "linux":
        session.cmd("swapoff -a", timeout=300)

    error_context.context("Run memory heavy stress in guest", logging.info)
    if os_type == "linux":
        test_mem = params.get("memory", 256)
        stress_args = "--cpu 4 --io 4 --vm 2 --vm-bytes %sM" % int(test_mem)
        stress_test = utils_test.VMStress(vm, "stress", params, stress_args=stress_args)
        stress_test.load_stress_tool()
    else:
        load_stress()
    session = flood_ping(session, host_ip, os_type)
    if os_type == "linux":
        stress_test.unload_stress()
        stress_test.clean()
    else:
        unload_stress(session)

    error_context.context("Ping test after flood ping,"
                          " Check if the network is still alive",
                          logging.info)
    count = params["count"]
    timeout = float(count) * 2
    status, output = utils_net.ping(host_ip, count, session=session,
                                    timeout=timeout)
    if status != 0:
        test.fail("Ping failed, status: %s,"
                  " output: %s" % (status, output))

    session.close()
