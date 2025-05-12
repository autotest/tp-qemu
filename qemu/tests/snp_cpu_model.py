import json
import os
import re

from avocado.utils import cpu, process
from virttest import data_dir as virttest_data_dir
from virttest import error_context, utils_misc
from virttest.utils_misc import verify_dmesg


@error_context.context_aware
def run(test, params, env):
    """
    CPU model test on SNP geust:
    1. Check host snp capability
    2. Get cpu model lists supported by host
    3. Check if current cpu model is in the supported lists, if no, cancel test
    4. Otherwise, boot snp guest with the cpu model
    5. Verify snp enabled in guest
    6. Verify attestation

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """
    error_context.context("Start sev-snp test", test.log.info)

    snp_module_path = params["snp_module_path"]
    if os.path.exists(snp_module_path):
        with open(snp_module_path) as f:
            output = f.read().strip()
        if output not in params.objects("module_status"):
            test.cancel("Host sev-snp support check fail.")
    else:
        test.cancel("Host sev-snp support check fail.")

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

    model_ib = "%s-IBPB" % model
    name_ib = " \\(with IBPB\\)"

    models = [x["name"] for x in out if not x["unavailable-features"]]
    if model == "host":
        cpu_model = "host"
        guest_model = ""
    elif model_ib in models:
        cpu_model = model_ib
        guest_model = model_pattern % name_ib
    elif model in models:
        cpu_model = model
        guest_model = model_pattern % ""
    else:
        test.cancel("This host doesn't support cpu model %s" % model)

    family_id = cpu.get_family()
    model_id = cpu.get_model()
    dict_cpu = {"251": "milan", "2517": "genoa", "2617": "turin"}
    key = str(family_id) + str(model_id)
    host_cpu_model = dict_cpu.get(key, "unknown")

    vm = env.get_vm(params["main_vm"])
    vm.params["cpu_model"] = cpu_model  # pylint: disable=E0606
    vm.create()

    error_context.context("Try to log into guest", test.log.info)
    session = vm.wait_for_login()

    verify_dmesg()
    guest_check_cmd = params["snp_guest_check"]
    try:
        session.cmd_output(guest_check_cmd, timeout=240)
    except Exception as e:
        test.fail("Guest snp verify fail: %s" % str(e))

    error_context.context("Check cpu model inside guest", test.log.info)
    cmd = params["get_model_cmd"]
    out = session.cmd_output(cmd)
    if not re.search(guest_model, out):  # pylint: disable=E0606
        test.fail("Guest cpu model is not right")

    # Verify attestation
    error_context.context("Start to do attestation", test.log.info)
    guest_dir = params["guest_dir"]
    host_script = params["host_script"]
    guest_cmd = params["guest_cmd"]
    deps_dir = virttest_data_dir.get_deps_dir()
    host_file = os.path.join(deps_dir, host_script)
    try:
        vm.copy_files_to(host_file, guest_dir)
        session.cmd_output(params["guest_tool_install"], timeout=240)
        session.cmd_output("chmod 755 %s" % guest_cmd)
    except Exception as e:
        test.fail("Guest test preperation fail: %s" % str(e))
    guest_cmd = guest_cmd + " " + host_cpu_model
    s = session.cmd_status(guest_cmd, timeout=360)
    if s:
        test.fail("Guest script error")
