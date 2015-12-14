import logging
from autotest.client.shared import error
from autotest.client.shared import utils
from virttest import utils_misc
from virttest import utils_test


@error.context_aware
def run(test, params, env):
    """
    Test virtio serial guest file transfer.

    Steps:
    1) Boot up a VM with virtio serial device.
    2) Create a large file in guest or host.
    3) Copy this file between guest and host through virtio serial.
    4) Check if file transfers ended good by md5 (optional).

    :param test: QEMU test object.
    :param params: Dictionary with the test parameters.
    :param env: Dictionary with test environment.
    """
    testtag = params.get("virt_subtest_tag", None)
    subtest = params.get("virt_subtest_type", None)
    login_timeout = float(params.get("login_timeout", 360))
    start_timeout = float(params.get("start_transfer_timeout", 240))
    file_sender = params.get("file_sender", "guest")
    md5_check = params.get("md5_check", "yes") == "yes"
    ports_name = params.get("file_transfer_serial_port").split()
    suppress_exception = params.get("suppress_exception", "yes") == "yes"
    transfer_timeout = int(params.get("transfer_timeout", 720))

    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    session = vm.wait_for_login(timeout=login_timeout)
    if params.get("enable_verifier", "no") == "yes":
        driver = params.get("driver_name", "vioser")
        session = utils_test.qemu.setup_win_driver_verifier(session,
                                                            driver,
                                                            vm, 240)
    try:
        target = utils_test.run_virtio_serial_file_transfer
        args = (test, params, env,)
        kwargs = {"port_names": ports_name,
                  "sender": file_sender,
                  "md5_check": md5_check}
        transfer_thread = utils.InterruptedThread(target, args, kwargs)
        error.context("Start file transfer thread", logging.info)
        transfer_thread.start()
        is_running = utils_misc.wait_for(transfer_thread.is_alive, timeout=120)
        start_transfer = utils_misc.wait_for(
                             lambda: env.get("serial_file_transfer_start"),
                             timeout=start_timeout)
        if start_transfer is None:
            raise error.TestError("Wait transfer file thread start timeout "
                                  "in %ss" % start_timeout)
        if subtest:
            utils_test.run_virt_sub_test(test, params, env, subtest, testtag)
        if is_running:
            transfer_thread.join(timeout=transfer_timeout,
                                 suppress_exception=suppress_exception)
    finally:
        vm = env.get_vm(params["main_vm"])
        try:
            vm.verify_alive()
        except Exception:
            vm.create()
            vm.verify_alive()
        session = vm.wait_for_login(timeout=login_timeout)
        if params.get("enable_verifier", "no") == "yes":
            driver = params.get("driver_name", "vioser")
            session = utils_test.qemu.clear_win_driver_verifier(session, vm)
        if session:
            session.close()
        vm.destroy(gracefully=False)
