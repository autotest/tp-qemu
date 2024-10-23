from avocado.utils import process
from virttest import error_context, utils_misc


@error_context.context_aware
def run(test, params, env):
    """
    cpuinfo query test:
    1). run query cmd. e.g -cpu ?cpuid
    2). check the expected info is inclued in the cmd output.
    3). raise error if defined info is missing.
    """
    qemu_binary = utils_misc.get_qemu_binary(params)

    error_context.context("run query cmd")
    qcmd = params.get("query_cmd")
    if qcmd is None:
        test.error("query cmd is missing, pls check query_cmd in config file")
    cmd = qemu_binary + qcmd
    output = process.system_output(cmd, shell=True)

    error_context.context("check if expected info is included in output of %s" % cmd)
    cpuinfos = params.get("cpu_info", "Conroe").split(",")
    missing = []
    for cpuinfo in cpuinfos:
        if cpuinfo not in output:
            missing.append(cpuinfo)
    if missing:
        test.fail("%s is missing in the output\n %s" % (", ".join(missing), output))
