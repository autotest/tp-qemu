import time
import logging
from autotest.client.shared import error
from autotest.client.shared import utils
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
    5) Run ACPI sub-test during file transfer

    :param test: QEMU test object.
    :param params: Dictionary with the test parameters.
    :param env: Dictionary with test environment.
    """
    testtag = params.get("subtest_tag", None)
    subtest = params.get("subtest", "stop_continue")
    file_sender = params.get("file_sender", "guest")
    md5_check = params.get("md5_check", "yes") == "yes"
    ports_name = params.get("file_transfer_serial_port").split()
    suppress_exception = params.get("suppress_exception", "yes") == "yes"
    start_transfer_timeout = int(params.get("start_transfer_timeout", 120))
    transfer_timeout = int(params.get("transfer_timeout", 720))
    target = utils_test.run_virtio_serial_file_transfer
    args = (test, params, env,)
    kwargs = {"port_names": ports_name,
              "sender": file_sender,
              "md5_check": md5_check}
    transfer_thread = utils.InterruptedThread(target, args, kwargs)
    error.context("Start file transfer thread", logging.info)
    transfer_thread.start()
    start_transfer = None
    start = time.time()
    while time.time() < start + start_transfer_timeout:
        start_transfer = env["serial_file_transfer_start"]
        if start_transfer:
            break
        time.sleep(0.5)
    if start_transfer is None:
        raise error.TestFail("Wait transfer file thread start timeout "
                             "in %ss" % start_transfer_timeout)
    elif start_transfer is False:
        file_size = params["file_size"]
        raise error.TestError("File transfer finished before run sub test," +
                              " Please increase 'file_size' param in cfg," +
                              " current value is '%s'" % file_size)
    utils_test.run_virt_sub_test(test, params, env, subtest, testtag)
    transfer_thread.join(timeout=transfer_timeout,
                         suppress_exception=suppress_exception)
    if transfer_thread.is_alive():
        raise error.TestFail("Wait file transfer finish timeout in %s"
                             % transfer_timeout)
