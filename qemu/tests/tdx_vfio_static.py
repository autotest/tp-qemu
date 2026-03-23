from virttest import error_context

from provider.hostdev import utils as hostdev_utils
from provider.hostdev.dev_setup import hostdev_setup
from provider.tdx import TDXHostCapability, TDXPassthroughNet


@error_context.context_aware
def run(test, params, env):
    """
    TDX VFIO passthrough test (static hostdev at boot).

    1. Check host TDX capability
    2. Find VFIO-capable net device(s) (same IOMMU group)
    3. Bind to vfio-pci (hostdev_setup), boot TDX VM with hostdev on cmdline
    4. Verify TDX and VFIO device(s) visible in guest (lspci)

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """
    error_context.context("Start TDX VFIO passthrough test", test.log.info)
    timeout = int(params.get("login_timeout", 360))
    guest_lspci_cmd = params.get("tdx_vfio_guest_lspci_cmd")

    tdx_host_cap = TDXHostCapability(test, params)
    tdx_host_cap.validate_tdx_cap()
    tdx_passthrough_net = TDXPassthroughNet(test)
    pci_list, driver = tdx_passthrough_net.find_passthrough_net_device_for_tdx()
    params["setup_hostdev_slots"] = " ".join(pci_list)
    error_context.base_context(f"Setting hostdev: {pci_list} {driver}", test.log.info)

    with hostdev_setup(params) as params:
        hostdev_driver = params.get("vm_hostdev_driver", "vfio-pci")
        assignment_type = params.get("hostdev_assignment_type")
        available_pci_slots = hostdev_utils.get_pci_by_dev_type(
            assignment_type, "network", hostdev_driver
        )
        vm = env.get_vm(params["main_vm"])
        vm_hostdevs_list = [f"hostdev{i + 1}" for i in range(len(pci_list))]
        vm.params["vm_hostdevs"] = " ".join(vm_hostdevs_list)
        vm_hostdevs = vm.params.objects("vm_hostdevs")
        pci_slots = []
        for dev, pci_slot in zip(vm_hostdevs, pci_list):
            if pci_slot not in available_pci_slots:
                test.fail(
                    f"Discovered slot {pci_slot} not in available vfio-pci slots"
                )
            vm.params[f"vm_hostdev_host_{dev}"] = pci_slot
            pci_slots.append(pci_slot)

        error_context.context(
            "Boot TDX VM with VFIO hostdev and iommufd (static)", test.log.info
        )
        vm.create()
        vm.verify_alive()
        try:
            session = vm.wait_for_login(timeout=timeout)

            error_context.context("Verify TDX enabled in guest", test.log.info)
            session.cmd_output(params["tdx_guest_check"], timeout=240)
            test.log.info("TDX guest check passed")

            tdx_passthrough_net.verify_vfio_devices_in_guest_lspci(
                session, params, pci_slots, guest_lspci_cmd, visible=True
            )
        finally:
            vm.destroy()
