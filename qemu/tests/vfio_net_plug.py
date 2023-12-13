from virttest import error_context
from virttest import utils_net

from provider.hostdev import utils as hostdev_utils
from provider.hostdev.dev_setup import hostdev_setup


@error_context.context_aware
def run(test, params, env):
    """
    Assign host devices to VM and do reboot test.

    :param test: QEMU test object.
    :type  test: avocado_vt.test.VirtTest
    :param params: Dictionary with the test parameters.
    :type  params: virttest.utils_params.Params
    :param env: Dictionary with test environment.
    :type  env: virttest.utils_env.Env
    """
    with hostdev_setup(params) as params:
        hostdev_driver = params.get('vm_hostdev_driver', 'vfio-pci')
        assignment_type = params.get('hostdev_assignment_type')
        ext_host = params.get('ext_host', utils_net.get_host_ip_address(params))
        plug_type = params.get('plug_type')
        reboot_times = params.get_numeric('reboot_times')
        available_pci_slots = hostdev_utils.get_pci_by_dev_type(
            assignment_type, 'network', hostdev_driver)

        vm = env.get_vm(params["main_vm"])  # type: virttest.qemu_vm.VM
        vm_hostdevs = vm.params.objects('vm_hostdevs')
        try:
            if plug_type == 'plug':
                vm.verify_alive()
                vm.wait_for_serial_login()
                error_context.base_context(f'Hot-plug all NICs for {vm.name}',
                                           test.log.info)
                for dev in vm_hostdevs:
                    dev_params = vm.params.object_params(dev)
                    pci_slot = available_pci_slots.pop(0)
                    host_dev = hostdev_utils.hostdev_define_by_params(
                        dev, dev_params, pci_slot)
                    vm.devices.simple_hotplug(host_dev, vm.monitor)
                error_context.context(f'Ping {ext_host} from {vm.name}',
                                      test.log.info)
                ping_s, _ = utils_net.ping(ext_host, 5, timeout=10)
                if ping_s:
                    test.fail(f'Failed to ping {ext_host} from {vm.name} using'
                              f' the plugged NIC')
            elif plug_type == 'unplug':
                vm.define()
                pci_slots = []
                for dev in vm_hostdevs:
                    pci_slot = available_pci_slots.pop(0)
                    hostdev_utils.insert_hostdev_to_vm(vm, dev, pci_slot)
                    pci_slots.append(pci_slot)
                vm.start()
                vm.verify_alive()
                vm.wait_for_serial_login()
                error_context.base_context(f'Hot-unplug all NICs for {vm.name}',
                                           test.log.info)
                for dev in vm_hostdevs:
                    host_dev = vm.devices.get(dev)
                    vm.devices.simple_unplug(host_dev, vm.monitor)
            for _ in range(reboot_times):
                vm.reboot(method='system_reset', serial=True)
        finally:
            error_context.context('Verify the VM is still alive without any '
                                  'faults', test.log.info)
            vm.verify_alive()
            vm.destroy()
