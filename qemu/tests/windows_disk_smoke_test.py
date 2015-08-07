import time
import sys
import re
import logging
import os

from autotest.client.shared import error, utils
from virttest import utils_test
from virttest import utils_misc
from virttest import data_dir
from virttest import env_process


@error.context_aware
def run(test, params, env):
    """
    Guest reboot/shutdown/system_reset/stop while iozone running
    1) Boot up guest with specified CLI
    2) Enable verifier for specified driver except for ide driver
    3) Online the 2nd testing image
    4) Running iozone command in the guest
    5) During iozone running ,do reboot/shutdown/system_reset/stop

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """
    def iozone_run(session, iozone_cli, timeout):
        try:
            env["iozone_status"] = 1
            s, o = session.cmd_status_output(iozone_cli, timeout)
        finally:
            env["iozone_status"] = 2

    def get_disk_id(session):
        cmd = "wmic diskdrive where Partitions=0 Get deviceid"
        output = session.cmd(cmd, timeout=120)
        disk_id = re.search(r'[0-9]+', output, re.M)
        if not disk_id:
            return ""
        else:
            return disk_id.group(0)[-1]

    def verifier_cleanup(vm, session, clear_verifier):
        error.context("clear driver verifier: %s"
                      % clear_verifier, logging.info)
        try:
            s, o = session.cmd_status_output(clear_verifier, timeout=120)
        finally:
            session = vm.reboot()
            if session:
                session.close()

    error.context("Generating qemu-kvm commandline", logging.info)
    vm_name = params['main_vm']
    env_process.preprocess_vm(test, params, env, vm_name)
    vm = env.get_vm(vm_name)
    vm.verify_alive()
    session = vm.wait_for_login(timeout=1200)
    env["iozone_status"] = 0
    verifier_cli = params.get("verifier_cli")
    verifier_query = params.get("verifier_query")
    iozone_cli = params.get("iozone_cli")
    disk_format = params.get("disk_format")
    iozone_timeout = int(params.get("iozone_timeout", 1800))
    virt_subtest = params.get("virt_subtest")
    testtag = params.get("testtag")
    image_size_stg = params.get("image_size_stg")
    iozone_start_timeout = int(params.get("iozone_start_timeout", 600))
    clear_verifier = params.get("clear_verifier", "verifier /reset")

    if params["os_type"] == "windows":
        winutil_drive = utils_misc.get_winutils_vol(session)
    if verifier_cli:
        error.context("Enable driver verifier and reboot guest", logging.info)
        session.cmd(verifier_cli)
        session = vm.reboot()
        error.context("Check driver verifier whether enabled", logging.info)
        status, output = session.cmd_status_output(verifier_query)
        if status:
            raise error.TestFail("Execute %s Failed "
                                 "Failed to enable driver verifier"
                                 % verifier_query)
            verifier_cleanup(vm, session, clear_verifier)

    error.context("Get disk_ID for testing", logging.info)
    pre_volumes = utils_misc.get_windows_drive_letters(session)
    disk_id = get_disk_id(session)
    if not disk_id:
        raise error.TestFail("Failed to find the testing disks ,aborting")
        verifier_cleanup(vm, session, clear_verifier)

    error.context("Formatting data disks for testing", logging.info)
    status, output = session.cmd_status_output(disk_format
                                               % (winutil_drive, disk_id))
    if status:
        raise error.TestFail("Failed to exec diskpart"
                             "logs %s" % output)
        verifier_cleanup(vm, session, clear_verifier)
    post_volumes = utils_misc.get_windows_drive_letters(session)
    for item in pre_volumes:
        post_volumes.remove(item)
    if not len(post_volumes):
        raise error.TestFail("Failed to assign letters")
        verifier_cleanup(vm, session, clear_verifier)
    else:
        testing_letter = post_volumes[-1]

    target = iozone_run
    iozone_cli = iozone_cli % (winutil_drive, testing_letter, testing_letter)
    args = (session, iozone_cli, iozone_timeout)
    kwargs = {}
    iozone_thread = utils.InterruptedThread(target, args, kwargs)
    error.context("Iozone commands starting", logging.info)
    iozone_thread.start()
    start = time.time()
    while time.time() < start + iozone_start_timeout:
        if env["iozone_status"] == 1:
            break
        time.sleep(0.5)

    if (not env["iozone_status"]) or env["iozone_status"] == 0:
        raise error.TestError("Waiting for iozone start timeout in %s"
                              % iozone_start_timeout)
        verifier_cleanup(vm, session, clear_verifier)
    elif env["iozone_status"] == 2:
        raise error.TestError("Iozone finished before subtest start")
    if virt_subtest:
        suppress_exception = params.get("suppress_exception")
        error.context("Running subtests : %s " % virt_subtest, logging.info)
        utils_test.run_virt_sub_test(test, params, env, virt_subtest, testtag)
    iozone_thread.join(timeout=iozone_timeout,
                       suppress_exception=suppress_exception)

    if iozone_thread.is_alive():
        raise error.TestFail("Waiting for iozone finished in %s"
                             % iozone_timeout)
    error.context("clear driver verifier at last", logging.info)
    if vm.is_dead():
        vm.create(params=params)
    session = vm.wait_for_login(timeout=1200)
    verifier_cleanup(vm, session, clear_verifier)
