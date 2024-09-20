import re

from avocado.utils import process
from virttest import error_context


@error_context.context_aware
def run(test, params, env):
    """
    Microcode test:
    1) Get microcode version on host
    2) Boot guest with '-cpu host'
    3) Check if microcode version inside guest match host

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """

    def get_microcode_ver(cmd, session=None):
        """
        Get microcde version in guest or host
        """
        if session:
            output = session.cmd_output(cmd)
        else:
            output = process.getoutput(cmd, shell=True)
        ver = re.findall(r":\s*(0x[0-9A-Fa-f]+)", output)[0]
        return ver

    cmd = params["get_microcode_cmd"]
    error_context.context("Get microcode version on host", test.log.info)
    host_ver = get_microcode_ver(cmd)
    test.log.info("The microcode version on host is %s", host_ver)

    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    session = vm.wait_for_login()
    try:
        error_context.context("Get microcode version in guest", test.log.info)
        guest_ver = get_microcode_ver(cmd)
        test.log.info("The microcode version in guest is %s", guest_ver)
        if guest_ver != host_ver:
            test.fail("The microcode version in guest does not match host")
    finally:
        if session:
            session.close()
