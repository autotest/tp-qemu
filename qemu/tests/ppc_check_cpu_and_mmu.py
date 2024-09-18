import re

from avocado.utils import process
from virttest import error_context


@error_context.context_aware
def run(test, params, env):
    """
    Check the CPU model and MMU mode of host and guest are matched.

    1) Launch a guest.
    2) Get CPU information both of host and guest.
    3) Assert that CPU model and MMU node are matched.

    :param test: the test object.
    :param params: the test params.
    :param env: test environment.
    """

    def get_cpu_mmu(session=None):
        cmd_func = session.cmd if session else process.getoutput
        cpu_info = cmd_func("tail -n 11 /proc/cpuinfo")
        cpu_info = re.findall(
            r"(?:cpu\s+:\s+(\w+\d+)).*(?:MMU\s+:\s+(\w+))", cpu_info, re.S
        )
        if cpu_info:
            return cpu_info[0]
        test.error("Unable to get the CPU information of this system.")

    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    guest_session = vm.wait_for_login()

    error_context.base_context("Get CPU information of host and guest.", test.log.info)
    host_cpu_model, host_mmu_mode = get_cpu_mmu()
    guest_cpu_model, guest_mmu_mode = get_cpu_mmu(guest_session)

    error_context.context(
        "Assert CPU model and MMU mode of host and guest.", test.log.info
    )
    assert guest_cpu_model == host_cpu_model, (
        "The CPU model of the host " "and guest do not match"
    )
    assert guest_mmu_mode == host_mmu_mode, (
        "The MMU mode of the host and " "guest do not match"
    )
    test.log.info("CPU model and MMU mode of host and guest are matched.")
