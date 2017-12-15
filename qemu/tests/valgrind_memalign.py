import logging
import time

from autotest.client.shared import error
from autotest.client.shared import utils

from virttest import env_process


@error.context_aware
def run(test, params, env):
    """
    This case is from [general operation] Work around valgrind choking on our
    use of memalign():
    1.download valgrind form valgrind download page: www.valgrind.org.
    2.install the valgrind in host.
    3.run # valgrind /usr/libexec/qemu-kvm  -vnc :0 -S -m 384 -monitor stdio
    4.check the status and do continue the VM.
    5.quit the VM.

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment
    """
    interval = float(params.get("interval_time", "10"))

    def valgrind_intall():
        valgrind_install_cmd = params.get("valgrind_install_cmd")
        s = utils.system(valgrind_install_cmd, timeout=3600)
        if s != 0:
            raise error.TestError("Fail to install valgrind")
        else:
            logging.info("Install valgrind successfully.")

    valgring_support_check_cmd = params.get("valgring_support_check_cmd")
    error.context("Check valgrind installed in host", logging.info)
    try:
        utils.system(valgring_support_check_cmd, timeout=interval)
    except Exception:
        valgrind_intall()

    params['mem'] = 384
    params["start_vm"] = "yes"
    error.context("Start guest with specific parameters", logging.info)
    env_process.preprocess_vm(test, params, env, params.get("main_vm"))
    vm = env.get_vm(params["main_vm"])

    time.sleep(interval)
    error.context("Verify guest status is running after cont", logging.info)
    vm.verify_status(params.get("expected_status", "running"))

    error.context("Quit guest and check the process quit normally",
                  logging.info)
    vm.monitor.quit()
    vm.wait_until_dead(5, 0.5, 0.5)
    vm.verify_userspace_crash()
