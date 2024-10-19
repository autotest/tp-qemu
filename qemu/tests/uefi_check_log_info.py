import os
import re

from avocado.utils import process
from virttest import env_process, error_context, utils_misc


@error_context.context_aware
def run(test, params, env):
    """
    Verify UEFI config setting in the GUI screen:
    1) Boot up a guest.
    2) If boot_splash_time not None, check splash-time in log output
    3) If check_info_pattern not None, check info in log output
    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """

    def info_check(info):
        """
        Check log info
        """
        logs = vm.logsessions["seabios"].get_output()
        result = re.search(info, logs, re.S)
        return result

    def create_cdroms(cdrom_test):
        """
        Create 'test' cdrom with one file on it
        """
        test.log.info("creating test cdrom")
        process.run("dd if=/dev/urandom of=test bs=10M count=1")
        process.run("mkisofs -o %s test" % cdrom_test)
        process.run("rm -f test")

    boot_splash_time = params.get("boot_splash_time")
    check_info_pattern = params.get("check_info_pattern")
    timeout = int(params.get("check_timeout", 360))
    cdrom_test = params.get("cdrom_test")
    if cdrom_test:
        create_cdroms(cdrom_test)
    params["start_vm"] = "yes"
    env_process.process(
        test, params, env, env_process.preprocess_image, env_process.preprocess_vm
    )
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()

    try:
        if check_info_pattern:
            expect_result = check_info_pattern
        elif boot_splash_time:
            splash_time_pattern = params.get("splash_time_pattern")
            expect_result = splash_time_pattern % (int(boot_splash_time) // 1000)
        if not utils_misc.wait_for(lambda: info_check(expect_result), timeout):  # pylint: disable=E0606
            test.fail("Does not get expected result from bios log: %s" % expect_result)
    finally:
        if params.get("cdroms") == "test":
            test.log.info("cleaning up temp cdrom images")
            os.remove(cdrom_test)
