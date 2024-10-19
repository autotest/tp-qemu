import json

from virttest import error_context, utils_net

from provider.hostdev import utils as hostdev_utils
from provider.hostdev.dev_setup import hostdev_setup


@error_context.context_aware
def run(test, params, env):
    """
    Passthrough some NICs to the VM and then perform a shutdown/reboot cycle.

    :param test: QEMU test object.
    :type  test: avocado_vt.test.VirtTest
    :param params: Dictionary with the test parameters.
    :type  params: virttest.utils_params.Params
    :param env: Dictionary with test environment.
    :type  env: virttest.utils_env.Env
    """

    def iface_check(vm, session):
        """
        Check that the VM has the expected number of interfaces.

        :param vm: The VM object on which to perform the life cycle operation.
        :type  vm: virttest.qemu_vm.VM
        :param session: The session object used to communicate with the VM.
        :type  session: aexpect.client.ShellSession

        :return: None
        """
        iface_info = json.loads(session.cmd_output_safe("ip -j link"))
        iface_info = [iface for iface in iface_info if iface["link_type"] == "ether"]
        phy_nics = vm.params["vm_hostdev_slots"]
        if len(iface_info) != len(phy_nics):
            test.fail(
                f"Unexpected number of interfaces: Assigned "
                f"{len(phy_nics)} but got {len(iface_info)}"
            )

    def lifecycle(cycle_type, method, vm, session):
        """
        Perform a life cycle operation on a VM.

        :param cycle_type: Type of life cycle operation. Accepts 'shutdown' or 'reboot'.
        :type  cycle_type: str
        :param method: The method used to perform the life cycle operation.
        :type  method: str
        :param vm: The VM object on which to perform the life cycle operation.
        :type  vm: virttest.qemu_vm.VM
        :param session: The session object used to communicate with the VM.
        :type  session: <session type>

        :return: None
        """
        if cycle_type == "shutdown":
            if method == "shell":
                session.sendline(vm.params.get("shutdown_command"))
            elif method == "system_powerdown":
                vm.monitor.system_powerdown()
        elif cycle_type == "reboot":
            session = vm.reboot(session, method, serial=True)
            iface_check(vm, session)
            status, _ = utils_net.ping(
                utils_net.get_host_ip_address(params), 10, timeout=30, session=session
            )
            if status:
                test.fail(
                    "Failed to ping from VM to host after reboot with "
                    "passthrough NIC card"
                )

    with hostdev_setup(params) as params:
        hostdev_driver = params.get("vm_hostdev_driver", "vfio-pci")
        assignment_type = params.get("hostdev_assignment_type")
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
            vm.create()
            vm.verify_alive()
            vm.params["vm_hostdev_slots"] = pci_slots

        for vm in env.get_all_vms():
            try:
                cycle_type = vm.params.get("lifecycle")
                test_method = vm.params.get("test_method")
                session = vm.wait_for_serial_login()
                iface_check(vm, session)
                lifecycle(cycle_type, test_method, vm, session)
            finally:
                vm.destroy()
