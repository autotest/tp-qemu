import json
import re

from avocado.utils import cpu, process
from virttest import env_process, error_context, utils_misc

from provider.cpu_utils import check_cpu_flags


@error_context.context_aware
def run(test, params, env):
    """
    Qemu reboot test:
    1) Get cpu model lists supported by host
    2) Check if current cpu model is in the supported lists, if no, cancel test
    3) Otherwise, boot guest with the cpu model
    4) Check cpu model name in guest
    5) Check cpu flags in guest(only for linux guest)
    6) Reboot guest

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """
    qemu_binary = utils_misc.get_qemu_binary(params)
    qmp_cmds = [
        '{"execute": "qmp_capabilities"}',
        '{"execute": "query-cpu-definitions", "id": "RAND91"}',
        '{"execute": "quit"}',
    ]
    cmd = (
        "echo -e '{0}' | {1} -qmp stdio -vnc none -M none | grep return |"
        "grep RAND91".format(r"\n".join(qmp_cmds), qemu_binary)
    )
    output = process.run(
        cmd, timeout=10, ignore_status=True, shell=True, verbose=False
    ).stdout_text
    out = json.loads(output)["return"]

    model = params["model"]
    model_pattern = params["model_pattern"]
    flags = params["flags"]
    if cpu.get_vendor() == "intel":
        model_ib = "%s-IBRS" % model
        flag_ib = " ibpb ibrs"
        name_ib = ", IBRS( update)?"
    else:
        model_ib = "%s-IBPB" % model
        flag_ib = " ibpb"
        name_ib = " \\(with IBPB\\)"

    models = [x["name"] for x in out if not x["unavailable-features"]]
    if model_ib in models:
        cpu_model = model_ib
        guest_model = model_pattern % name_ib
        flags += flag_ib
    elif model in models:
        cpu_model = model
        guest_model = model_pattern % ""
    else:
        test.cancel("This host doesn't support cpu model %s" % model)

    params["cpu_model"] = cpu_model  # pylint: disable=E0606
    params["start_vm"] = "yes"
    vm_name = params["main_vm"]
    env_process.preprocess_vm(test, params, env, vm_name)

    vm = env.get_vm(vm_name)
    error_context.context("Try to log into guest", test.log.info)
    session = vm.wait_for_login()

    error_context.context("Check cpu model inside guest", test.log.info)
    cmd = params["get_model_cmd"]
    out = session.cmd_output(cmd)
    if not re.search(guest_model, out):  # pylint: disable=E0606
        test.fail("Guest cpu model is not right")

    if params["os_type"] == "linux":
        check_cmd = params.get("check_cmd")
        if check_cmd:
            vul_host = process.getoutput(params.get("vulnerabilities")).split()
            vul_guest = session.cmd_output(params.get("vulnerabilities")).split()
            vulnerabilities = list(set(vul_host).intersection(set(vul_guest)))
            check_items = params.get("check_items").split()
            expect_result = params.get("expect_result")
            for item in vulnerabilities:
                h_out = re.search(
                    "Vulnerable|Mitigation|Not affected",
                    process.getoutput(check_cmd % item),
                )[0]
                g_out = re.search(
                    "Vulnerable|Mitigation|Not affected",
                    session.cmd_output(check_cmd % item),
                )[0]
                if h_out != g_out:
                    test.fail("Guest is not equal to Host with '%s'" % item)
                if item in check_items and g_out != expect_result:
                    test.fail("'%s' can't get '%s'" % (item, expect_result))
        check_cpu_flags(params, flags, test, session)

    if params.get("reboot_method"):
        error_context.context("Reboot guest '%s'." % vm.name, test.log.info)
        session = vm.reboot(session=session)

    vm.verify_kernel_crash()
    session.close()
