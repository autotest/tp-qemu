from virttest import error_context

from provider.hostdev.dev_setup import hostdev_setup
from provider.tdx import TDXHostCapability, TDXPassthroughNet


@error_context.context_aware
def run(test, params, env):
    """
    TDX VFIO passthrough test (hotplug only, single main_vm).

    1. Check host TDX capability
    2. Find VFIO-capable net device(s) (same IOMMU group); record setup_hostdev_slots
    3. Boot TDX VM without hostdev on cmdline (PF stays on host driver until hotplug)
    4. Bind PF(s) to vfio-pci (hostdev_setup), hotplug, verify lspci, unplug,
       verify gone
    5. Verify TDX in guest

    Sets ``pcie_extra_root_port`` to ``len(pci_list) + 2`` before ``vm.create``
    (virttest multi-PF vfio hotplug needs spare pcie-root-port slots).

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """
    error_context.context("Start TDX VFIO passthrough test", test.log.info)
    timeout = int(params.get("login_timeout", 360))
    guest_lspci_cmd = params.get("tdx_vfio_guest_lspci_cmd", "lspci -nn | grep -c '%s'")

    tdx_host_cap = TDXHostCapability(test, params)
    tdx_host_cap.validate_tdx_cap()
    tdx_passthrough_net = TDXPassthroughNet(test)
    pci_list, driver = tdx_passthrough_net.find_passthrough_net_device_for_tdx()
    params["setup_hostdev_slots"] = " ".join(pci_list)
    test.log.info("TDX VFIO hotplug: pci_list=%s driver=%s", pci_list, driver)
    params["pcie_extra_root_port"] = str(len(pci_list) + 2)

    vm = env.get_vm(params["main_vm"])
    vm_hostdevs = [f"hostdev{i + 1}" for i in range(len(pci_list))]

    error_context.base_context(f"Setting hostdevs for {vm.name}", test.log.info)
    error_context.context(
        "Boot TDX VM without hostdev (hotplug at runtime)", test.log.info
    )
    vm.create()
    vm.verify_alive()

    try:
        session = vm.wait_for_login(timeout=timeout)

        error_context.context(
            "Verify TDX enabled in guest before hotplug", test.log.info
        )
        session.cmd_output(params["tdx_guest_check"], timeout=240)
        test.log.info("TDX guest check passed (before hotplug)")

        with hostdev_setup(params) as params:
            for dev, pci in zip(vm_hostdevs, pci_list):
                vm.params[f"vm_hostdev_host_{dev}"] = pci

            error_context.context("Hotplug VFIO hostdev(s) at runtime", test.log.info)
            hotplug_order = []
            for dev in vm_hostdevs:
                dev_params = vm.params.object_params(dev)
                batch = vm.devices.hostdev_define_by_params(dev, dev_params)
                for qdev in batch:
                    out, _ = vm.devices.simple_hotplug(qdev, vm.monitor)
                    if out:
                        test.fail("Failed to hotplug %s at runtime: %s" % (dev, out))
                    hotplug_order.append(qdev)
            test.log.info(
                "VFIO hotplug done: %d PCI, %d qdev steps",
                len(vm_hostdevs),
                len(hotplug_order),
            )

            tdx_passthrough_net.verify_vfio_devices_in_guest_lspci(
                session, params, pci_list, guest_lspci_cmd, visible=True
            )

            error_context.context(
                "Hot-unplug VFIO hostdev(s) at runtime", test.log.info
            )
            for qdev in reversed(hotplug_order):
                out, _ = vm.devices.simple_unplug(qdev, vm.monitor)
                if out:
                    test.fail("Failed to hot-unplug VFIO hostdev at runtime: %s" % out)
            test.log.info("VFIO hostdev(s) hot-unplugged at runtime")

            tdx_passthrough_net.verify_vfio_devices_in_guest_lspci(
                session, params, pci_list, guest_lspci_cmd, visible=False
            )

            error_context.context(
                "Verify TDX enabled in guest after hot-unplug", test.log.info
            )
            session.cmd_output(params["tdx_guest_check"], timeout=240)
            test.log.info("TDX guest check passed (after hot-unplug)")
    finally:
        vm.destroy()
