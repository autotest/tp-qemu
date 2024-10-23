import os
import time

from virttest import data_dir, error_context, utils_disk, utils_misc, utils_test

from provider import virtio_fs_utils, win_driver_utils


@error_context.context_aware
def run(test, params, env):
    """
    Stop/continue the vm during the virtiofs test.

    1) Boot guest with virtiofs device.
    2) For windows guest, enable driver verifier first.
       For the linux guest, skip this step.
    3) Run virtiofs function test.
    4) During steps 3, stop vm and then resume vm.
    5) Memory leak check.

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """

    def sleep_before_basic_io_test(test, params, session):
        # The reason that sleeping 3 seconds at here is to let the main thread
        # running into file detection logic.
        time.sleep(3)
        virtio_fs_utils.basic_io_test(test, params, session)

    driver = params["driver_name"]
    driver_verifier = params.get("driver_verifier", driver)
    driver_running = params.get("driver_running", driver_verifier)
    timeout = int(params.get("login_timeout", 360))
    fs_dest = params.get("fs_dest")
    fs_target = params.get("fs_target")
    test_file = params.get("virtio_fs_test_file")
    fs_source = params.get("fs_source_dir")
    base_dir = params.get("fs_source_base_dir", data_dir.get_data_dir())
    if not os.path.isabs(fs_source):
        fs_source = os.path.join(base_dir, fs_source)
    host_data = os.path.join(fs_source, test_file)

    vm_name = params["main_vm"]
    vm = env.get_vm(vm_name)
    vm.verify_alive()
    error_context.context("Boot guest with %s device" % driver, test.log.info)
    session = vm.wait_for_login(timeout=timeout)

    if params["os_type"] == "windows":
        error_context.context("Run the viofs service", test.log.info)
        utils_test.qemu.windrv_verify_running(session, test, driver_running)
        session = utils_test.qemu.setup_win_driver_verifier(
            session, driver_verifier, vm
        )
        virtio_fs_utils.run_viofs_service(test, params, session)
    else:
        error_context.context(
            "Create a destination directory %s " "inside guest." % fs_dest,
            test.log.info,
        )
        if not utils_misc.make_dirs(fs_dest, session=session):
            test.fail("Creating directory was failed!")
        error_context.context(
            "Mount virtiofs target %s to %s inside" " guest." % (fs_target, fs_dest),
            test.log.info,
        )
        if not utils_disk.mount(fs_target, fs_dest, "virtiofs", session=session):
            test.fail("Mount virtiofs target failed.")

    basic_io_test = utils_misc.InterruptedThread(
        target=sleep_before_basic_io_test,
        kwargs={"test": test, "params": params, "session": session},
    )
    basic_io_test.daemon = True

    error_context.context("Start the io test thread's activity....", test.log.info)
    basic_io_test.start()
    test.log.info("The io test thread is running...")

    start_time = time.time()  # record the start time.
    # run time expected, the unit is second.
    max_run_time = params.get_numeric("max_run_time", 30)
    while time.time() - start_time < max_run_time:
        if os.path.exists(host_data) and os.path.getsize(host_data) > 0:
            test.log.info("The file has been detected: %s", host_data)
            error_context.context("Going to stop the vm...", test.log.info)
            vm.pause()
            time.sleep(2)
            error_context.context("Going to resume the vm...", test.log.info)
            vm.resume()
            if not basic_io_test.is_alive():
                test.fail("The io test thread is NOT alive!")
            break

    basic_io_test.join()
    test.log.info("The io test thread is terminated...")

    if params.get("os_type") == "windows":
        win_driver_utils.memory_leak_check(vm, test, params)
