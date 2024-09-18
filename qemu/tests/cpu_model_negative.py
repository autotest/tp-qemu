import re

from avocado.utils import process
from virttest import cpu, error_context, utils_misc, utils_qemu
from virttest.utils_version import VersionInterval


@error_context.context_aware
def run(test, params, env):
    """
    Runs CPU negative test:

    1. Launch qemu with improper cpu configuration
    2. Verify qemu failed to start

    :param test: QEMU test object.
    :param params: Dictionary with test parameters.
    :param env: Dictionary with the test environment.
    """

    enforce_flag = params.get("enforce_flag")
    if enforce_flag and "CPU_MODEL" in params["wrong_cmd"]:
        if enforce_flag in cpu.get_host_cpu_models():
            test.cancel(
                "This case only test on the host without the flag" " %s." % enforce_flag
            )
        cpu_model = cpu.get_qemu_best_cpu_model(params)
        params["wrong_cmd"] = params["wrong_cmd"].replace("CPU_MODEL", cpu_model)

    qemu_bin = utils_misc.get_qemu_binary(params)
    if "OUT_OF_RANGE" in params["wrong_cmd"]:
        machine_type = params["machine_type"].split(":")[-1]
        m_types = utils_qemu.get_machines_info(qemu_bin)[machine_type]
        m_type = re.search(r"\(alias of (\S+)\)", m_types)[1]
        max_value = utils_qemu.get_maxcpus_hard_limit(qemu_bin, m_type)
        smp = str(max_value + 1)
        params["wrong_cmd"] = (
            params["wrong_cmd"]
            .replace("MACHINE_TYPE", machine_type)
            .replace("OUT_OF_RANGE", smp)
        )
        msg = (
            params["warning_msg"]
            .replace("SMP_VALUE", smp)
            .replace("MAX_VALUE", str(max_value))
            .replace("MACHINE_TYPE", m_type)
        )
        params["warning_msg"] = msg

    if "maxcpus" in params["wrong_cmd"]:
        qemu_version = utils_qemu.get_qemu_version(qemu_bin)[0]
        if qemu_version in VersionInterval("[, 6.2.0)"):
            params["warning_msg"] = params["old_warning_msg"]
        else:
            params["warning_msg"] = params["new_warning_msg"]
    warning_msg = params["warning_msg"]
    wrong_cmd = "%s %s" % (qemu_bin, params["wrong_cmd"])
    test.log.info("Start qemu with command: %s", wrong_cmd)
    ret_cmd = process.run(cmd=wrong_cmd, verbose=False, ignore_status=True, shell=True)
    output = ret_cmd.stderr_text
    status = ret_cmd.exit_status
    test.log.info("Qemu prompt output:\n%s", output)
    if status == 0:
        test.fail("Qemu guest boots up while it should not.")
    if warning_msg not in output:
        test.fail("Does not get expected warning message.")
    else:
        test.log.info(
            "Test passed as qemu does not boot up and" " prompts expected message."
        )
