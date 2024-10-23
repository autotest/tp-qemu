import os
import re
import time

from avocado.utils import process
from virttest import data_dir, error_context, utils_misc


@error_context.context_aware
def run(test, params, env):
    """
    Test rdtsc sync
    1) Boot qemu with test binary bz1975840.flat
    2) get a array of rdtsc value A[m]
    3) execute "system_reset"
    4) get a new array of rdtsc value B[n]
    5) expected results: A[m-1] > B[0]

    :param test: QEMU test object.
    :param params: Dictionary with test parameters.
    :param env: Dictionary with the test environment.
    """
    source_file = params["source_file"]
    log_file = params["log_file"]
    src_test_binary = os.path.join(data_dir.get_deps_dir(), source_file)
    test_cmd = params["test_cmd"] % src_test_binary

    qemu_bin = utils_misc.get_qemu_binary(params)
    qemu_cmd = "%s %s" % (qemu_bin, test_cmd)
    test.log.info("Send host command: %s", qemu_cmd)
    process.run(cmd=qemu_cmd, verbose=True, ignore_status=True, shell=True)
    qemu_pid = process.getoutput("pgrep -f %s" % src_test_binary, shell=True)
    if not qemu_pid:
        test.fail("QEMU start failed!")

    time.sleep(5)
    process.run(
        'echo -e \'{"execute":"qmp_capabilities"}'
        '{"execute":"system_reset"}\'|nc -U /tmp/mm',
        shell=True,
        verbose=True,
    )
    time.sleep(5)
    process.run(
        'echo -e \'{"execute":"qmp_capabilities"}' '{"execute":"quit"}\'|nc -U /tmp/mm',
        shell=True,
        verbose=True,
    )

    qemu_pid = process.getoutput("pgrep -f %s" % src_test_binary, shell=True)
    if qemu_pid:
        test.fail("QEMU quit failed!")
    is_file = os.path.exists(log_file)
    if not is_file:
        test.fail("Can't find the log file %s" % log_file)

    value_a = []
    value_b = []
    reset = False
    try:
        f = open(log_file)
        lines = f.readlines()
        for line in lines[2:]:
            if not reset and line.startswith("rdtsc"):
                rdtsc = int(re.findall(r"\d+", line)[0])
                value_a.append(rdtsc)
            elif line.startswith("PM"):
                reset = True
            elif reset and line.startswith("rdtsc"):
                rdtsc = int(re.findall(r"\d+", line)[0])
                value_b.append(rdtsc)

        if not value_a or not value_b:
            test.fail("Miss some rdtsc values.")
        if not sorted(value_a) == value_a and len(set(value_a)) == len(value_a):
            test.fail("rdtsc isn't increasing order before system_reset.")
        if not sorted(value_b) == value_b and len(set(value_b)) == len(value_b):
            test.fail("rdtsc isn't increasing order after system_reset.")
        if value_a[-1] <= value_b[0]:
            test.fail("rdtsc doesn't decrease at first after system_reset.")
        test.log.info("Test passed as rdtsc behaviour is same!")
    finally:
        f.close()
        process.run("rm -rf %s" % log_file)
