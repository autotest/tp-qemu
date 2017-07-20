import time
import logging


from virttest import test_setup
from virttest import error_context
from virttest import utils_misc


@error_context.context_aware
def run(test, params, env):
    """
    SR-IOV devices Guest-Lifecycle test:
    1) Bring up VFs on the host, by following instructions How To in Setup.
    2) Try to boot up guest(s) with VF(s).
    3) Suspend the guest along with the pass-through device.
    4) Resume the guest, and check for errors.
    5) Reboot the guest.

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """

    device_driver = params.get("device_driver", "pci-assign")
    serial_login = params.get("serial_login", "no")
    pci_assignable = test_setup.PciAssignable(
        driver=params.get("driver"),
        driver_option=params.get("driver_option"),
        host_set_flag=params.get("host_set_flag", 0),
        kvm_params=params.get("kvm_default"),
        vf_filter_re=params.get("vf_filter_re"),
        pf_filter_re=params.get("pf_filter_re"),
        device_driver=device_driver)

    devices = []
    device_type = params.get("device_type", "vf")
    if device_type == "vf":
        device_num = pci_assignable.get_vfs_count()
        if device_num == 0:
            msg = " No VF device found even after running SR-IOV setup"
            test.cancel(msg)
    elif device_type == "pf":
        device_num = len(pci_assignable.get_pf_vf_info())
    else:
        msg = "Unsupport device type '%s'." % device_type
        msg += " Please set device_type to 'vf' or 'pf'."
        test.error(msg)

    msg = "Try to boot up guest(s) with VF(s)."
    error_context.context(msg, logging.info)
    timeout = int(params.get("login_timeout", 30))

    for vm_name in params["vms"].split(" "):
        params["start_vm"] = "yes"
        vm = env.get_vm(vm_name)
        session = vm.wait_for_serial_login(
            timeout=int(params.get("login_timeout", 720)))
        rc, output = session.cmd_status_output(
            "ip li| grep -i 'BROADCAST'|awk '{print $2}'| sed 's/://'")
        if not rc:
            iface_probed = output.splitlines()
            logging.info("probed VF Interface(s) in guest: %s",
                         iface_probed)
        adapter_list_before = session.get_command_output("lspci -nn").strip()
        error_context.base_context("Suspending the VM", logging.info)
        vm.pause()
        error_context.context("Verify the status of VM is"
                              "'paused'", logging.info)
        vm.verify_status("paused")

        error_context.context("Verify the session has"
                              "no response", logging.info)
        if session.is_responsive():
            msg = "Session is still responsive after suspend"
            logging.error(msg)
            test.fail(msg)
        session.close()

        time.sleep(20)
        error_context.base_context("Resuming the"
                                   "VM", logging.info)
        vm.resume()
        error_context.context("Verify the status of VM is"
                              "'running'", logging.info)
        vm.verify_status("running")

        error_context.context("Re-login the guest", logging.info)
        session = vm.wait_for_serial_login(
            timeout=int(params.get("login_timeout", 360)))

        error_context.context("Verify Host and guest kernel "
                              "no error and call trace", logging.info)
        vm.verify_kernel_crash()
        utils_misc.verify_host_dmesg()

        error_context.context("Rebooting Guest", logging.info)
        logging.info("Adapter details before "
                     "reboot are %s" % adapter_list_before)
        session.cmd('reboot & exit', timeout=10, ignore_all_errors=True)
        session = vm.wait_for_serial_login(
            timeout=int(params.get("login_timeout", 720)))
        adapter_list_after = session.get_command_output("lspci -nn").strip()
        logging.info("Adapter details after reboot "
                     "are %s " % adapter_list_after)
        if adapter_list_before != adapter_list_after:
            test.fail("Mismatch in adapter list, after reboot.")
        session.close()
