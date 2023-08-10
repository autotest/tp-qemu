from virttest import error_context, utils_net

from provider import hostdev
from provider.hostdev import utils as hostdev_utils
from provider.hostdev.dev_setup import hostdev_setup


@error_context.context_aware
def run(test, params, env):
    """
    Assign host devices to VM and do ping test.

    :param test: QEMU test object.
    :type  test: avocado_vt.test.VirtTest
    :param params: Dictionary with the test parameters.
    :type  params: virttest.utils_params.Params
    :param env: Dictionary with test environment.
    :type  env: virttest.utils_env.Env
    """
    ip_version = params["ip_version"]
    with hostdev_setup(params) as params:
        hostdev_driver = params.get("vm_hostdev_driver", "vfio-pci")
        assignment_type = params.get("hostdev_assignment_type")
        ext_host = params.get(
            "ext_host", utils_net.get_host_ip_address(ip_ver=ip_version)
        )
        available_pci_slots = hostdev_utils.get_pci_by_dev_type(
            assignment_type, "network", hostdev_driver
        )
        # Create all VMs first
        for vm in env.get_all_vms():
            vm_hostdevs = vm.params.objects("vm_hostdevs")
            pci_slots = []
            error_context.base_context(f"Setting hostdevs for {vm.name}", test.log.info)
            for dev in vm_hostdevs:
                pci_slot = available_pci_slots.pop(0)
                vm.params[f"vm_hostdev_host_{dev}"] = pci_slot
                pci_slots.append(pci_slot)
            vm.create(params=vm.params)
            vm.verify_alive()
            vm.params["vm_hostdev_slots"] = pci_slots

        # Login and ping
        for vm in env.get_all_vms():
            try:
                error_context.context("Log into guest via MAC address", test.log.info)
                for slot in vm.params["vm_hostdev_slots"]:
                    parent_slot = hostdev_utils.get_parent_slot(slot)
                    slot_manager = params[f"hostdev_manager_{parent_slot}"]
                    if type(slot_manager) is hostdev.PFDevice:
                        mac_addr = slot_manager.mac_addresses[0]
                    else:
                        slot_index = slot_manager.vfs.index(slot)
                        mac_addr = slot_manager.mac_addresses[slot_index]
                    session = hostdev_utils.ssh_login_from_mac(
                        vm, mac_addr, int(ip_version[-1])
                    )
                    if session:
                        error_context.context(
                            f"Ping {ext_host} from {vm.name}", test.log.info
                        )
                        s_ping, _ = utils_net.ping(
                            ext_host,
                            10,
                            session=session,
                            timeout=30,
                            force_ipv4=(ip_version == "ipv4"),
                        )
                        session.close()
                        if s_ping:
                            test.fail(f"Fail to ping {ext_host} from {vm.name}")
            finally:
                vm.destroy()
