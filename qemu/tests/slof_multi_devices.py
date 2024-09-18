"""
slof_multi_devices.py include following case:
 1. SLOF boot successfully when adding two pci-bridge to the guest.
 2. VM boot successfully with lots of virtio-net-pci devices.
"""

from virttest import env_process, error_context, utils_net

from provider import slof


@error_context.context_aware
def run(test, params, env):
    """
    Verify SLOF info with multi-devices.

    Step:
     1. Boot a guest by following ways:
      a. attach two pci-bridges
      b. multiple virtio-net-pci devices attached multiple pci-bridges
         by one to one.
     2. Check if any error info from output of SLOF.
     3. Guest could login sucessfully.
     4. Guest could ping external host ip.
     5. For virtio-net-pci scenario, check the number of NIC if equal to
        qemu command.

    :param test: Qemu test object.
    :param params: Dictionary with the test parameters.
    :param env: Dictionary with test environment.
    """
    if params["device_type"] == "pci-bridge":
        for id in range(1, int(params["pci_bridge_num"])):
            params["pci_controllers"] += " pci_bridge%d" % id
            params["type_pci_bridge%d" % id] = "pci-bridge"
    elif params["device_type"] == "virtio-net-pci":
        pci_num = int(params["pci_bridge_num"])
        nic_id = 0
        for pci_id in range(pci_num):
            params["pci_controllers"] += " pci_bridge%d" % pci_id
            params["type_pci_bridge%d" % pci_id] = "pci-bridge"
            nic_num_per_pci = int(params["nic_num_per_pci_bridge"])
            for i in range(nic_num_per_pci):
                params["nics"] = " ".join([params["nics"], "nic%d" % nic_id])
                params["nic_pci_bus_nic%d" % nic_id] = "pci_bridge%d" % pci_id
                nic_id += 1

    params["start_vm"] = "yes"
    env_process.preprocess_vm(test, params, env, params["main_vm"])
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    content, _ = slof.wait_for_loaded(vm, test)

    error_context.context("Check the output of SLOF.", test.log.info)
    slof.check_error(test, content)

    error_context.context("Try to log into guest '%s'." % vm.name, test.log.info)
    timeout = float(params.get("login_timeout", 240))
    session = vm.wait_for_login(timeout=timeout)
    test.log.info("log into guest '%s' successfully.", vm.name)

    error_context.context("Try to ping external host.", test.log.info)
    extra_host_ip = utils_net.get_host_ip_address(params)
    session.cmd("ping %s -c 5" % extra_host_ip)
    test.log.info("Ping host(%s) successfully.", extra_host_ip)

    if params["device_type"] == "virtio-net-pci":
        nic_num = int(str(session.cmd_output(params["nic_check_cmd"])))
        error_context.context(
            "Found %d ehternet controllers inside guest." % nic_num, test.log.info
        )
        if (pci_num * nic_num_per_pci) != nic_num:
            test.fail(
                "The number of ethernet controllers is not equal to %s "
                "inside guest." % (pci_num * nic_num_per_pci)
            )
        test.log.info(
            "The number of ehternet controllers inside guest is equal to "
            "qemu command line(%d * %d).",
            pci_num,
            nic_num_per_pci,
        )

    session.close()
    vm.destroy(gracefully=True)
