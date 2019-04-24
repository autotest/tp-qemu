"""
:author: Golita Yue <gyue@redhat.com>
:author: Amos Kong <akong@redhat.com>
"""
import logging
import time
import re
import os

from virttest import data_dir
from virttest import error_context
from virttest import utils_misc
from virttest import utils_test


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
        error_context.context("Install Iometer", logging.info)
        session.cmd(re.sub("WIN_UTILS", vol_utils, ins_cmd), cmd_timeout)
        time.sleep(0.5)

    def register_iometer():
        error_context.context("Register Iometer", logging.info)
        session.cmd_output(
            re.sub("WIN_UTILS", vol_utils, params["register_cmd"]), cmd_timeout)

    def prepare_ifc_file():
        error_context.context("Prepare icf for Iometer", logging.info)
        icf_file = os.path.join(data_dir.get_deps_dir(), "iometer", icf_name)
        vm.copy_files_to(icf_file, "%s\\%s" % (ins_path, icf_name))

    def _run_backgroud(args):
        thread_session = vm.wait_for_login(timeout=360)
        thread = utils_misc.InterruptedThread(thread_session.cmd, args)
        thread.start()
        cmd = 'TASKLIST /FI "IMAGENAME eq Iometer.exe'
        if not utils_misc.wait_for(
                lambda: 'Iometer.exe' in session.cmd_output(cmd), 180, step=3.0):
            test.fail("Iometer is not alive!")

    def run_iometer():
        error_context.context("Start Iometer", logging.info)
        args = (
            ' && '.join((("cd %s" % ins_path), run_cmd % (icf_name, res_file))),
            run_timeout)
        if params.get('bg_mode', 'no') == 'yes':
            _run_backgroud(args)
            time.sleep(int(params.get('sleep_time', '900')))
        else:
            session.cmd(*args)
            error_context.context(
                "Copy result '%s' to host" % res_file, logging.info)
            vm.copy_files_from(res_file, test.resultsdir)

    def change_vm_status():
        method, command = params.get('command_opts').split(',')
        logging.info('Sending command(%s): %s' % (method, command))
        if method == 'shell':
            session = vm.wait_for_login(timeout=360)
            session.sendline(command)
            session.close()
        else:
            getattr(vm.monitor, command)()

    def check_vm_status(timeout=600):
        action = 'shutdown' if shutdown_vm else 'login'
        if not getattr(vm, 'wait_for_%s' % action)(timeout=timeout):
            test.fail('Failed to %s vm.' % action)

    cmd_timeout = int(params.get("cmd_timeout", 360))
    ins_cmd = params["install_cmd"]
    icf_name = params["icf_name"]
    ins_path = params["install_path"]
    res_file = params["result_file"]
    run_cmd = params["run_cmd"]
    run_timeout = int(params.get("run_timeout", 1000))
    shutdown_vm = params.get('shutdown_vm', 'no') == 'yes'
    reboot_vm = params.get('reboot_vm', 'no') == 'yes'
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
    utils_test.run_virt_sub_test(test, params, env, "format_disk")
    install_iometer()
    register_iometer()
    prepare_ifc_file()
    run_iometer()
    if shutdown_vm or reboot_vm:
        change_vm_status()
        check_vm_status()
