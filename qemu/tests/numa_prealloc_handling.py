from avocado.utils import process
from virttest import utils_misc, utils_package


def run(test, params, env):
    """
    numa_prealloc_handling test
    1) Measures the time takes QEMU to preallocate the memory
    2) Checks the timing is shorter when thread-context is used
    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment
    """
    if not utils_package.package_install("time"):
        test.cancel("time package is not installed!")

    qemu_path = utils_misc.get_qemu_binary(params)

    cmd_without_tc = params.get("cmd_without_tc") % qemu_path
    cmd_with_tc = params.get("cmd_with_tc") % qemu_path

    execution_time = float(
        process.getoutput(cmd_without_tc, ignore_status=True, shell=True)
    )
    test.log.debug("Execution time without thread_context: %f", execution_time)

    execution_time_tc = float(
        process.getoutput(cmd_with_tc, ignore_status=True, shell=True)
    )
    test.log.debug("Execution time with thread_context: %f", execution_time_tc)

    if execution_time <= execution_time_tc:
        test.fail("There is no boot time speedup when using thread-context!")
