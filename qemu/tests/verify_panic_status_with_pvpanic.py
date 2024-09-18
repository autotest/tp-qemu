import os

import aexpect
from virttest import data_dir, utils_package
from virttest.remote import scp_to_remote


def run(test, params, env):
    """
    Verify the QMP even with -device pvpanic when trigger crash,this case will:

    1) Start VM with pvpanic device.
    2) Check if pvpanic device exists in guest.
    3) Trigger crash in guest.
    4) Check vm status with QMP.

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environmen.
    """

    stop_kdump_command = params["stop_kdump_command"]
    trigger_crash = params["trigger_crash"]
    qmp_check_info = params["qmp_check_info"]
    check_info = params.get("check_info")
    is_aarch64 = params.get("vm_arch_name") == "aarch64"
    check_pci_cmd = params.get("check_pci_cmd")
    check_capability_cmd = params.get("check_capability_cmd")

    # trigger kernel panic config
    trigger_kernel_panic = params.get("trigger_kernel_panic")
    username = params.get("username")
    password = params.get("password")
    port = params.get("file_transfer_port")
    guest_path = params.get("guest_path")
    depends_pkgs = params.get("depends_pkgs")
    cmd_make = params.get("cmd_make")
    io_timeout = params.get_numeric("io_timeout")

    vm = env.get_vm(params["main_vm"])
    session = vm.wait_for_login()
    guest_addr = vm.get_address()

    if check_info:
        qtree_info = vm.monitor.info("qtree")
        if check_info not in qtree_info:
            test.fail("Not find pvpanic device in guest")

    if trigger_kernel_panic:
        host_path = os.path.join(data_dir.get_deps_dir(), "trigger_panic_drive")
        scp_to_remote(guest_addr, port, username, password, host_path, guest_path)
        if not utils_package.package_install(depends_pkgs, session):
            test.cancel("Please install %s inside guest to proceed", depends_pkgs)
        session.cmd(cmd_make % guest_path, io_timeout)

    try:
        session.cmd(stop_kdump_command)
        if is_aarch64:
            pci = session.cmd_output(check_pci_cmd).strip()
            capability_info = session.cmd_output(check_capability_cmd % pci)
            test.log.info("The pvpanic capability info of guest: %s", capability_info)
        session.cmd(trigger_crash, timeout=5)
    except aexpect.ShellTimeoutError:
        pass
    else:
        test.fail("Guest should crash.")
    finally:
        output = vm.monitor.get_status()
        if qmp_check_info not in str(output):
            test.fail("Guest status is not guest-panicked")
        if session:
            session.close()
