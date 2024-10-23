import os

from virttest import error_context, utils_misc, utils_test

from provider import virtio_fs_utils
from provider.storage_benchmark import generate_instance


@error_context.context_aware
def run(test, params, env):
    """
    Check if there is memory leak in the vm during io test on virtiofs.

    1) Boot guest with virtiofs device.
    2) Enable driver verifier first.
    3) Remove the poolmon result file.
    4) Record the non-paged pool Mmdi info.
    5) Run iozone test on virtiofs.
    6) Record the non-paged pool Mmdi info after iotest.
    5) Check if there is Mmdi Diff increation.

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """

    def _record_poolmon():
        """Record Mmdi tag memory info in pool monitor to C: volume"""
        status = session.cmd_status(poolmon_mmdi_cmd)
        if status:
            test.fail("Fail to get Mmdi pool tag memory " "info in pool monitor.")

    driver = params["driver_name"]
    driver_verifier = params.get("driver_verifier", driver)
    driver_running = params.get("driver_running", driver_verifier)
    timeout = params.get_numeric("login_timeout", 360)
    fs_target = params.get("fs_target")
    test_file = params.get("virtio_fs_test_file")
    iozone_options = params.get("iozone_options")
    io_timeout = params.get_numeric("io_timeout", 1800)
    poolmon_mmdi_cmd = params["poolmon_mmdi_cmd"]
    get_mem_poolmon_cmd = params["get_mem_poolmon_cmd"]
    record_file = params["record_file"]

    vm_name = params["main_vm"]
    vm = env.get_vm(vm_name)
    vm.verify_alive()
    error_context.context("Boot guest with %s device" % driver, test.log.info)
    session = vm.wait_for_login(timeout=timeout)

    error_context.context("Run the viofs service", test.log.info)
    utils_test.qemu.windrv_verify_running(session, test, driver_running)
    session = utils_test.qemu.setup_win_driver_verifier(session, driver_verifier, vm)
    virtio_fs_utils.run_viofs_service(test, params, session)

    driver_letter = virtio_fs_utils.get_virtiofs_driver_letter(test, fs_target, session)
    fs_dest = "%s:" % driver_letter
    guest_file = os.path.join(fs_dest, test_file).replace("/", "\\")

    test.log.info("Record memory info before iotest.")
    poolmon_mmdi_cmd = utils_misc.set_winutils_letter(session, poolmon_mmdi_cmd)
    if session.cmd_status("dir %s" % record_file) == 0:
        test.log.info("Removing file %s.", record_file)
        session.cmd_status("del /f /q %s" % record_file)
    _record_poolmon()

    error_context.context("Start iozone test.", test.log.info)
    io_test = generate_instance(params, vm, "iozone")
    try:
        io_test.run(iozone_options % guest_file, io_timeout)
    finally:
        io_test.clean()

    test.log.info("Record memory info after iotest")
    _record_poolmon()

    error_context.context(
        "Check the diff of allocation memory and"
        " free memory for Mmdi pool tag"
        " in memory pool monitor before"
        " start io test.",
        test.log.info,
    )
    result = session.cmd_output(get_mem_poolmon_cmd).strip()
    test.log.info("The pool monitor result is\n%s", result)
    diff_befor = result.split("\n")[0].split()[4]
    diff_aft = result.split("\n")[1].split()[4]
    if int(diff_aft) - int(diff_befor) > 100:
        test.fail("There are memory leak on virtiofs," " the result is %s" % result)
