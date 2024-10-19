import re

from avocado.utils import process
from virttest import cpu, env_process, error_context, utils_misc
from virttest.utils_version import VersionInterval


@error_context.context_aware
def run(test, params, env):
    """
    cpuinfo query test:
    1). run query cmd. e.g -cpu ?cpuid
    2). check the expected info is included in the cmd output.
    3). Boot guest and check the output of qmp command "qom-list-types"
    4). Check the output of qmp command "query-cpu-definitions"
    5). Check the output of qmp command "query-cpu-model-expansion"
    """

    def remove_models(model_list):
        """
        Remove models from cpu_types
        :param model_list: The list of models to be removed
        """
        for model in model_list:
            try:
                cpu_types.remove(model)
            except ValueError:
                test.log.warning(
                    "The model to be removed is not" " in the list: %s", model
                )
                continue

    def get_patterns(p_list):
        """
        Return all possible patterns for given flags
        :param p_list: The list of flags
        """
        r_list = []
        replace_char = [("_", ""), ("_", "-"), (".", "-"), (".", ""), (".", "_")]
        for p in p_list:
            r_list.extend(list(map(lambda x: p.replace(*x), replace_char)))
        return set(r_list)

    cpu_types = []
    list(map(cpu_types.extend, list(cpu.CPU_TYPES.values())))

    qemu_path = utils_misc.get_qemu_binary(params)
    qemu_version = env_process._get_qemu_version(qemu_path)
    match = re.search(r"[0-9]+\.[0-9]+\.[0-9]+(\-[0-9]+)?", qemu_version)
    host_qemu = match.group(0)
    remove_list_deprecated = params.get("remove_list_deprecated", "")
    if host_qemu in VersionInterval("[7.0.0-8, )") and remove_list_deprecated:
        params["remove_list"] = remove_list_deprecated
    remove_models(params.objects("remove_list"))
    if host_qemu in VersionInterval("[,4.2.0)"):
        remove_models(params.objects("cpu_model_8"))
    if host_qemu in VersionInterval("[,3.1.0)"):
        remove_models(params.objects("cpu_model_3_1_0"))
    if host_qemu in VersionInterval("[,2.12.0)"):
        remove_models(params.objects("cpu_model_2_12_0"))
    qemu_binary = utils_misc.get_qemu_binary(params)
    test.log.info("Query cpu models by qemu command")
    query_cmd = "%s -cpu ? | awk '{print $2}'" % qemu_binary
    qemu_binary_output = (
        process.system_output(query_cmd, shell=True).decode().splitlines()
    )
    cpuid_index = qemu_binary_output.index("CPUID")
    cpu_models_binary = qemu_binary_output[1 : cpuid_index - 1]
    cpu_flags_binary = qemu_binary_output[cpuid_index + 1 :]
    params["start_vm"] = "yes"
    vm_name = params["main_vm"]
    env_process.preprocess_vm(test, params, env, vm_name)
    vm = env.get_vm(vm_name)
    # query cpu model supported by qemu
    test.log.info("Query cpu model supported by qemu by qemu monitor")
    qmp_model_output = str(vm.monitor.cmd("qom-list-types"))
    qmp_def_output = str(vm.monitor.cmd("query-cpu-definitions"))

    # Check if all the output contain expected cpu models
    output_list = {
        "qemu-kvm": cpu_models_binary,
        "qom-list-types": qmp_model_output,
        "query-cpu-definitions": qmp_def_output,
    }
    missing = dict.fromkeys(output_list.keys(), [])
    for cpu_model in cpu_types:
        test.log.info(
            "Check cpu model %s from qemu command output and" " qemu monitor output",
            cpu_model,
        )
        for key, value in output_list.items():
            if cpu_model not in value:
                missing[key].append(cpu_model)
    for key, value in missing.items():
        if value:
            test.fail(
                "%s is missing in the %s output: %s\n"
                % (", ".join(value), key, output_list[key])
            )

    # Check if qemu command output matches qmp output
    missing = []
    test.log.info("Check if qemu command output matches qemu monitor output")
    for cpu_model in cpu_models_binary:
        if cpu_model not in qmp_model_output:
            missing.append(cpu_model)
    if missing:
        test.fail(
            "The qemu monitor output does not included all the cpu"
            " model in qemu command output, missing: \n %s" % ", ".join(missing)
        )

    # Check if the flags in qmp output matches expectation
    args = {"type": "full", "model": {"name": vm.cpuinfo.model}}
    output = vm.monitor.cmd("query-cpu-model-expansion", args)
    model = output.get("model")
    model_name = model.get("name")
    if model_name != vm.cpuinfo.model:
        test.fail(
            "Command query-cpu-model-expansion return" " wrong model: %s" % model_name
        )
    model_prop = model.get("props")
    for flag in cpu.CPU_TYPES_RE.get(model_name).split(","):
        test.log.info("Check flag %s from qemu monitor output", flag)
        flags = get_patterns(flag.split("|"))
        for f in flags:
            if model_prop.get(f) is True:
                break
        else:
            test.fail("Check cpu model props failed, %s is not True" % flag)

    # Check if the flags in qmp output matches qemu command output
    missing = []
    test.log.info(
        "Check if the flags in qemu monitor output matches" " qemu command output"
    )
    for flag in cpu_flags_binary:
        if flag not in str(output):
            missing.append(flag)
    if missing:
        test.fail(
            "The monitor output does not included all the cpu flags"
            " in qemu  command output, missing: \n %s" % ", ".join(missing)
        )
