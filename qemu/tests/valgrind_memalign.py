import logging
import time

from avocado.utils import process
from virttest import env_process
from virttest import error_context


@error_context.context_aware
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
        s = process.system(valgrind_install_cmd, timeout=3600, shell=True)
        if s != 0:
            test.error("Fail to install valgrind")
        else:
            logging.info("Install valgrind successfully.")

    valgring_support_check_cmd = params.get("valgring_support_check_cmd")
    error_context.context("Check valgrind installed in host", logging.info)
    try:
        process.system(valgring_support_check_cmd, timeout=interval,
                       shell=True)
    except Exception:
        valgrind_intall()

    params['mem'] = 384
    params["start_vm"] = "yes"
    error_context.context("Start guest with specific parameters", logging.info)
    env_process.preprocess_vm(test, params, env, params.get("main_vm"))
    vm = env.get_vm(params["main_vm"])

    time.sleep(interval)
    error_context.context("Verify guest status is running after cont",
                          logging.info)
    vm.verify_status(params.get("expected_status", "running"))

    error_context.context("Quit guest and check the process quit normally",
                          logging.info)
    vm.monitor.quit()
    vm.wait_until_dead(5, 0.5, 0.5)
    vm.verify_userspace_crash()
