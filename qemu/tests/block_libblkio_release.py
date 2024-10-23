"""Verify libblkio release"""

import os

from virttest import data_dir as virttest_data_dir


def run(test, params, env):
    """
    Verify libblkio release

    1) Boot the main vm.
    2) Copy test script to guest.
    3) Run test script in guest to verify the libblkio
        main function is available.
    """

    logger = test.log
    guest_dir = params["guest_dir"]
    host_script = params["host_script"]
    guest_cmd = params["guest_cmd"]

    logger.info("Get the main VM")
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()

    session = vm.wait_for_login(timeout=360)
    logger.info("Copy script to guest")
    deps_dir = virttest_data_dir.get_deps_dir()
    host_file = os.path.join(deps_dir, host_script)
    vm.copy_files_to(host_file, guest_dir)

    logger.info("Execute script in guest")
    status, output = session.cmd_status_output(guest_cmd, timeout=360)
    logger.info("Guest cmd output: '%s'", output)
    if status:
        test.fail("Guest script error")
