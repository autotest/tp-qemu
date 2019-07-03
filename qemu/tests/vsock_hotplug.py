import re
import logging
import time

from avocado.utils import linux_modules

from virttest import utils_vsock
from virttest import utils_misc
from virttest import error_context
from virttest.qemu_devices import qdevices

from qemu.tests import vsock_test
from qemu.tests import vsock_negative_test


@error_context.context_aware
def run(test, params, env):
    """
    Hotplug/unhotplug virtio-vsock device

    1. Boot guest without virtio-vsock-pci device
    2. Hotplug virtio-vsock device
    3. Check device inside guest(lspci/dmesg)
    4. Transfer data from guest to host
    5. Unplug virtio-vsock device
    6. Cancel the nc-sock process on host
    7. Reboot guest

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment
    """

    linux_modules.load_module('vhost_vsock')
    vm = env.get_vm(params['main_vm'])
    session = vm.wait_for_login()
    guest_cid = utils_vsock.get_guest_cid(3)
    vsock_id = 'hotplugged_vsock'
    vsock_params = {'id': vsock_id, 'guest-cid': guest_cid}
    if '-mmio:' in params.get('machine_type'):
        dev_vsock = qdevices.QDevice('vhost-vsock-device', vsock_params)
    elif params.get('machine_type').startswith("s390"):
        dev_vsock = qdevices.QDevice("vhost-vsock-ccw", vsock_params)
    else:
        dev_vsock = qdevices.QDevice('vhost-vsock-pci', vsock_params)
    vm.devices.simple_hotplug(dev_vsock, vm.monitor)
    error_context.context('Check vsock device exist in guest lspci and '
                          'dmesg output.', logging.info)
    addr_pattern = params['addr_pattern']
    device_pattern = params['device_pattern']
    lspci_cmd = 'lspci'
    time.sleep(10)
    lspci_output = session.cmd_output(lspci_cmd)
    device_str = re.findall(r'%s\s%s' % (addr_pattern, device_pattern),
                            lspci_output)
    if not device_str:
        test.fail('lspci failed, no device "%s"' % device_pattern)
    else:
        address = re.findall(addr_pattern, device_str[0])[0]
        chk_dmesg_cmd = 'dmesg'
        output = re.findall(address, session.cmd_output(chk_dmesg_cmd))
        if not output:
            test.fail('dmesg failed, no info related to %s' % address)
        else:
            error_msg = ''
            for o in output:
                if re.search(r'fail|error', o, re.I):
                    error_msg += '%s' % o
                    break
            if error_msg:
                test.fail("dmesg check failed: %s" % error_msg)
    # Transfer data from guest to host
    try:
        nc_vsock_bin = vsock_test.compile_nc_vsock(test, vm, session)
        tmp_file = "/tmp/vsock_file_%s" % utils_misc.generate_random_string(6)
        rec_session = vsock_test.send_data_from_guest_to_host(
            session, nc_vsock_bin, guest_cid, tmp_file, file_size=10000)
        vsock_negative_test.check_data_received(test, rec_session, tmp_file)
        vm.devices.simple_unplug(dev_vsock, vm.monitor)
        vsock_negative_test.kill_host_receive_process(test, rec_session)
        vsock_test.check_guest_nc_vsock_exit(test, session)
    finally:
        session.cmd_output("rm -f %s" % tmp_file)
        session.close()
    vm.reboot()
