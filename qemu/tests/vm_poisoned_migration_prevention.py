import re
import sys
from shutil import rmtree

from avocado.utils import process
from virttest import error_context, qemu_monitor


@error_context.context_aware
def run(test, params, env):
    """
    Handle migration prevention after VM memory poisoning
    1) Boot VMs in source and destination hosts
    2) Download the (internal) hwpoison tool
    3) Executes the tool to poison some memory
    4) Checks in the host dmesg the failure traces
    5) Do migration and check the error message is correct

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment
    """
    hwpoison_file = params.get("hwpoison_file", "")
    target_path = params.get("target_path")
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    vm.wait_for_login()

    process.system(f"mkdir -p {target_path}", shell=True)
    qemu_pid = vm.get_pid()

    # This tool is only for internal use, replace the values if needed
    error_context.base_context("Download the hwpoison tool", test.log.info)
    process.system(f"wget {hwpoison_file} -P {target_path} ", shell=True)

    error_context.context("Execute the hwpoison tool", test.log.info)
    process.system(
        f"{sys.executable} {target_path}/hwpoison.py -p {qemu_pid}", shell=True
    )

    error_context.context("Check the memory failure in dmesg log", test.log.debug)
    trace_found = re.search("Memory failure", str(process.system_output("dmesg")))

    if not trace_found:
        test.fail("No memory failure traces found in dmesg")

    mig_timeout = params.get_numeric("mig_timeout", 1200, float)
    mig_protocol = params.get("migration_protocol", "tcp")
    try:
        vm.migrate(mig_timeout, mig_protocol, env=env, not_wait_for_migration=True)
    except qemu_monitor.MonitorError as e:
        error_context.context(f"The monitor error: {e}", test.log.info)

    test.log.debug("Cleaning the tool file")
    rmtree(target_path, ignore_errors=True)
