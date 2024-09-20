import ctypes
import os
import re

from avocado.utils import crypto, process
from virttest import error_context, utils_misc, utils_test

from provider import win_dev


@error_context.context_aware
def run(test, params, env):
    """
    vhost is no longer disabled when guest does not use MSI-X.
    The vhostforce flag is no longer required.

    1) Start guest with different NIC option
    2) Check virtio device's irq number,irq number should be greater than one.
    3) Disable msi of guest
    4) Reboot guest,check if msi is disabled and irq number should be equal to 1.
    5) Check network and vhost process (transfer data).
    6) Check md5 value of both sides.

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """

    def irq_check(session, device_name, devcon_folder):
        hwid = win_dev.get_hwids(session, device_name, devcon_folder, login_timeout)[0]
        get_irq_cmd = params["get_irq_cmd"] % (devcon_folder, hwid)
        irq_list = re.findall(r":\s+(\d+)", session.cmd_output(get_irq_cmd), re.M)
        if not irq_list:
            test.error("device %s's irq checked fail" % device_name)
        return irq_list

    def get_file_md5sum(file_name, session, timeout):
        """
        return: Return the md5sum value of the guest.
        """
        test.log.info("Get md5sum of the file:'%s'", file_name)
        s, o = session.cmd_status_output("md5sum %s" % file_name, timeout=timeout)
        if s != 0:
            test.error("Get file md5sum failed as %s" % o)
        return re.findall(r"\w{32}", o)[0]

    tmp_dir = params["tmp_dir"]
    filesize = int(params.get("filesize"))
    dd_cmd = params["dd_cmd"]
    delete_cmd = params["delete_cmd"]
    file_md5_check_timeout = int(params.get("file_md5_check_timeout"))
    login_timeout = int(params.get("login_timeout", 360))
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    session = vm.wait_for_serial_login()

    if params.get("os_type") == "linux":
        error_context.context("Check the pci msi in guest", test.log.info)
        pci_id = session.cmd_output_safe("lspci |grep Eth |awk {'print $1'}").strip()
        status = session.cmd_output_safe("lspci -vvv -s %s|grep MSI-X" % pci_id).strip()
        enable_status = re.search(r"Enable\+", status, re.M | re.I)
        if enable_status.group() == "Enable+":
            error_context.context("Disable pci msi in guest", test.log.info)
            utils_test.update_boot_option(vm, args_added="pci=nomsi")
            session_msi = vm.wait_for_serial_login(timeout=login_timeout)
            pci_id = session_msi.cmd_output_safe(
                "lspci |grep Eth |awk {'print $1'}"
            ).strip()
            status = session_msi.cmd_output_safe(
                "lspci -vvv -s %s|grep MSI-X" % pci_id
            ).strip()
            session_msi.close()
            change_status = re.search(r"Enable\-", status, re.M | re.I)
            if change_status.group() != "Enable-":
                test.fail("virtio device's statuts is not correct")
        elif enable_status.group() != "Enable+":
            test.fail("virtio device's statuts is not correct")
    else:
        driver = params.get("driver_name")
        driver_verifier = params.get("driver_verifier", driver)

        device_name = params["device_name"]
        devcon_folder = utils_misc.set_winutils_letter(session, params["devcon_folder"])
        error_context.context("Boot guest with %s device" % driver, test.log.info)
        session = utils_test.qemu.windrv_check_running_verifier(
            session, vm, test, driver_verifier, login_timeout
        )
        error_context.context("Check %s's irq number" % device_name, test.log.info)
        irq_list = irq_check(session, device_name, devcon_folder)
        irq_nums = len(irq_list)
        if (
            not irq_nums > 1
            and max(ctypes.c_int32(int(irq)).value for irq in irq_list) < 0
        ):
            test.fail("%s's irq is not correct." % device_name)
        if params.get("msi_cmd"):
            error_context.context("Disable MSI in guest", test.log.info)
            hwid_msi = win_dev.get_hwids(
                session, device_name, devcon_folder, login_timeout
            )[0]
            session.cmd(params["msi_cmd"] % (hwid_msi, 0))
            session = vm.reboot(session=session)
            error_context.context("Check %s's irq number" % device_name, test.log.info)
            irq_list = irq_check(session, device_name, devcon_folder)
            irq_nums = len(irq_list)
            if (
                not irq_nums == 1
                and min(ctypes.c_int32(int(irq)).value for irq in irq_list) > 0
            ):
                test.fail("%s's irq is not correct." % device_name)

    # prepare test data
    guest_path = tmp_dir + "src-%s" % utils_misc.generate_random_string(8)
    host_path = os.path.join(
        test.tmpdir, "tmp-%s" % utils_misc.generate_random_string(8)
    )
    test.log.info("Test setup: Creating %dMB file on host", filesize)
    process.run(dd_cmd % host_path, shell=True)

    try:
        src_md5 = crypto.hash_file(host_path, algorithm="md5")
        test.log.info("md5 value of data from src: %s", src_md5)
        # transfer data
        error_context.context("Transfer data from host to %s" % vm.name, test.log.info)
        vm.copy_files_to(host_path, guest_path)
        dst_md5 = get_file_md5sum(guest_path, session, timeout=file_md5_check_timeout)
        test.log.info("md5 value of data in %s: %s", vm.name, dst_md5)
        if dst_md5 != src_md5:
            test.fail("File changed after transfer host -> %s" % vm.name)
    finally:
        os.remove(host_path)
        session.cmd(
            delete_cmd % guest_path, timeout=login_timeout, ignore_all_errors=True
        )
        session.close()
