from virttest import error_context, utils_misc, utils_net, utils_test


@error_context.context_aware
def run(test, params, env):
    """
    Do network stress test when under memory stress
    1) Boot a guest with vhost=on
    2) swapoff in guest
    3) flood ping from host to guest
    4) do stress test

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """

    def flood_ping():
        """
        Do flood ping from host to guest

        """
        flood_minutes = int(params["flood_minutes"])
        test.log.info("Flood ping for %s minutes", flood_minutes)
        utils_net.ping(guest_ip, flood=True, timeout=flood_minutes * 60)

    def load_stress():
        """
        Load background IO/CPU/Memory stress in guest

        """
        error_context.context("launch stress app in guest", test.log.info)
        args = (test, params, env, params["stress_test"])
        bg_test = utils_test.BackgroundTest(utils_test.run_virt_sub_test, args)
        bg_test.start()
        if not utils_misc.wait_for(bg_test.is_alive, first=10, step=3, timeout=100):
            test.fail("background test start failed")

    def unload_stress(session):
        """
        Stop stress app

        :param session: guest session
        """
        error_context.context("stop stress app in guest", test.log.info)
        cmd = params.get("stop_cmd")
        session.sendline(cmd)

    timeout = float(params.get("login_timeout", 240))
    vm = env.get_vm(params["main_vm"])
    session = vm.wait_for_login(timeout=timeout)
    guest_ip = vm.get_address()

    os_type = params["os_type"]
    if os_type == "linux":
        session.cmd("swapoff -a", timeout=300)

    error_context.context("Run memory heavy stress in guest", test.log.info)
    if os_type == "linux":
        test_mem = params.get("memory", 256)
        stress_args = "--cpu 4 --io 4 --vm 2 --vm-bytes %sM" % int(test_mem)
        stress_test = utils_test.VMStress(vm, "stress", params, stress_args=stress_args)
        stress_test.load_stress_tool()
    else:
        load_stress()
    flood_ping()
    if os_type == "linux":
        stress_test.unload_stress()
        stress_test.clean()
    else:
        unload_stress(session)

    error_context.context(
        "Ping test after flood ping," " Check if the network is still alive",
        test.log.info,
    )
    count = params["count"]
    timeout = float(count) * 2
    status, output = utils_net.ping(guest_ip, count, timeout=timeout)
    if status != 0:
        test.fail("Ping failed, status: %s," " output: %s" % (status, output))

    session.close()
