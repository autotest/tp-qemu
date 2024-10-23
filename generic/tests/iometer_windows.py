"""
:author: Golita Yue <gyue@redhat.com>
:author: Amos Kong <akong@redhat.com>
"""

import os
import re
import time

from virttest import data_dir, error_context, utils_misc, utils_test

from provider import win_driver_utils


@error_context.context_aware
def run(test, params, env):
    """
    Run Iometer for Windows on a Windows guest:

    1) Boot guest with additional disk
    2) Format the additional disk
    3) Install and register Iometer
    4) Perpare icf to Iometer.exe
    5) Run Iometer.exe with icf
    6) Copy result to host

    :param test: kvm test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """

    def install_iometer():
        error_context.context("Install Iometer", test.log.info)
        session.cmd(re.sub("WIN_UTILS", vol_utils, ins_cmd), cmd_timeout)
        time.sleep(0.5)

    def register_iometer():
        error_context.context("Register Iometer", test.log.info)
        session.cmd_output(
            re.sub("WIN_UTILS", vol_utils, params["register_cmd"]), cmd_timeout
        )

    def prepare_ifc_file():
        error_context.context("Prepare icf for Iometer", test.log.info)
        icf_file = os.path.join(data_dir.get_deps_dir(), "iometer", icf_name)
        vm.copy_files_to(icf_file, "%s\\%s" % (ins_path, icf_name))

    def _is_iometer_alive():
        cmd = 'TASKLIST /FI "IMAGENAME eq Iometer.exe'
        _session = vm.wait_for_login(timeout=360)
        if not utils_misc.wait_for(
            lambda: "Iometer.exe" in _session.cmd_output(cmd, timeout=180),
            600,
            step=3.0,
        ):
            test.fail("Iometer is not alive!")
        _session.close()

    def _run_backgroud(args):
        thread_session = vm.wait_for_login(timeout=360)
        thread = utils_misc.InterruptedThread(thread_session.cmd, args)
        thread.start()

    def run_iometer():
        error_context.context("Start Iometer", test.log.info)
        args = (
            " && ".join((("cd %s" % ins_path), run_cmd % (icf_name, res_file))),
            run_timeout,
        )
        if params.get("bg_mode", "no") == "yes":
            _run_backgroud(args)
            _is_iometer_alive()
            time.sleep(int(params.get("sleep_time", "180")))
            _is_iometer_alive()
        else:
            session.cmd(*args)
            error_context.context("Copy result '%s' to host" % res_file, test.log.info)
            vm.copy_files_from(res_file, test.resultsdir)

    def change_vm_status():
        method, command = params.get("command_opts").split(",")
        test.log.info("Sending command(%s): %s", method, command)
        if method == "shell":
            vm.wait_for_login(timeout=360).sendline(command)
        else:
            getattr(vm.monitor, command)()
        if shutdown_vm:
            if not utils_misc.wait_for(lambda: vm.monitor.get_event("SHUTDOWN"), 600):
                raise test.fail("Not received SHUTDOWN QMP event.")

    def check_vm_status(timeout=600):
        action = "shutdown" if shutdown_vm else "login"
        if not getattr(vm, "wait_for_%s" % action)(timeout=timeout):
            test.fail("Failed to %s vm." % action)

    def format_multi_disks():
        disk_letters = params["disk_letters"].split()
        disk_indexes = params["disk_indexes"].split()
        disk_fstypes = params["disk_fstypes"].split()
        error_context.context("Format the multiple disks.", test.log.info)
        for index, letter, fstype in zip(disk_indexes, disk_letters, disk_fstypes):
            utils_misc.format_windows_disk(session, index, letter, fstype=fstype)

    cmd_timeout = int(params.get("cmd_timeout", 360))
    ins_cmd = params["install_cmd"]
    icf_name = params["icf_name"]
    ins_path = params["install_path"]
    res_file = params["result_file"]
    run_cmd = params["run_cmd"]
    run_timeout = int(params.get("run_timeout", 1000))
    shutdown_vm = params.get("shutdown_vm", "no") == "yes"
    reboot_vm = params.get("reboot_vm", "no") == "yes"
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    session = vm.wait_for_login(timeout=360)
    vol_utils = utils_misc.get_winutils_vol(session)
    if not vol_utils:
        test.error("WIN_UTILS CDROM not found.")

    # diskpart requires windows volume INF file and volume setup
    # events ready, add 10s to wait events done.
    time.sleep(10)
    # format the target disk
    if params.get("format_multi_disks", "no") == "yes":
        format_multi_disks()
    else:
        utils_test.run_virt_sub_test(test, params, env, "format_disk")
    install_iometer()
    register_iometer()
    prepare_ifc_file()
    run_iometer()
    if shutdown_vm or reboot_vm:
        change_vm_status()
        check_vm_status()
    # for windows guest, disable/uninstall driver to get memory leak based on
    # driver verifier is enabled
    if params.get("memory_leak_check", "no") == "yes":
        win_driver_utils.memory_leak_check(vm, test, params)
