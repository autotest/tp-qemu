import time

from virttest import env_process, error_context, utils_misc, utils_net


@error_context.context_aware
def run(test, params, env):
    """
    Memory leak check after nic hotplug/hotunplug
    1) Boot a guest
    2) Check free memory
    3) Hotplug nic 100 times(windows) or add 300 vlan(linux)
    4) Hotunplug nic 100 times(windows) or del 300 vlan(linux)
    5) Check free memory again

    :param test: kvm test object.
    :param params: Dictionary with test parameters.
    :param env: Dictionary with the test environment.
    """

    params["start_vm"] = "yes"
    env_process.preprocess_vm(test, params, env, params["main_vm"])

    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    timeout = int(params.get("login_timeout", 360))
    os_type = params.get("os_type")
    if os_type == "windows":
        session = vm.wait_for_login(timeout=timeout)
    else:
        session = vm.wait_for_serial_login(timeout=timeout)

    free_mem_before_nichotplug = utils_misc.get_free_mem(session, os_type)
    test.log.info(
        "Guest free memory before nic hotplug: %d", free_mem_before_nichotplug
    )

    if os_type == "windows":
        error_context.context("Add network devices through monitor cmd", test.log.info)
        pci_model = params.get("pci_model")
        netdst = params.get("netdst", "virbr0")
        nettype = params.get("nettype", "bridge")
        for i in range(1, 100):
            nic_name = "hotadded%s" % i
            vm.hotplug_nic(
                nic_model=pci_model,
                nic_name=nic_name,
                netdst=netdst,
                nettype=nettype,
                queues=params.get("queues"),
            )
            time.sleep(3)
            vm.hotunplug_nic(nic_name)
            time.sleep(3)
    else:
        session.cmd_output_safe("swapoff -a")
        mac = vm.get_mac_address()
        guest_nic = utils_net.get_linux_ifname(session, mac)
        for i in range(1, 300):
            session.cmd_output_safe(
                "ip link add link %s name %s.%s type vlan id %s"
                % (guest_nic, guest_nic, i, i)
            )
        time.sleep(3)
        for i in range(1, 300):
            session.cmd_output_safe("ip link delete %s.%s" % (guest_nic, i))

    free_mem_after_nichotplug = utils_misc.get_free_mem(session, os_type)
    test.log.info("Guest free memory after nic hotplug: %d", free_mem_after_nichotplug)

    mem_reduced = free_mem_before_nichotplug - free_mem_after_nichotplug
    if (os_type == "windows" and mem_reduced > 1024) or (
        os_type == "linux" and mem_reduced > 200
    ):
        test.error(
            "There might be memory leak after hotplug nic. "
            "Memory reduced %d" % mem_reduced
        )
    error_context.context("Memory reduced = %d" % mem_reduced, test.log.info)

    session.close()
