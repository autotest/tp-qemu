import json
import os

from avocado.utils import cpu, process
from avocado.utils.software_manager import manager
from virttest import cpu as virttest_cpu
from virttest import data_dir as virttest_data_dir
from virttest import error_context


@error_context.context_aware
def run(test, params, env):
    """
    Nested test:
    1) Boot VM
    2) Install ansible and related packages
    3) Generate inventory file with L1 guest IP
    4) Generate parameter file with parameters for tests on L2 guest
    5) Execute ansible command

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """

    setup_bridge_sh = "/root/setup_bridge.sh"

    def get_live_vms(env):
        live_vms = []
        for vm in env.get_all_vms():
            if vm.is_alive():
                live_vms.append(vm)
        if not live_vms:
            test.fail("No live VM.")
        return live_vms

    def generate_invent_file(env):
        vms = get_live_vms(env)
        tmp_dir = virttest_data_dir.get_tmp_dir()
        file_name = "inventory_file"
        ip_lst = list(map(lambda v: v.wait_for_get_address(0, 240), vms))
        invent_file = open(os.path.join(tmp_dir, file_name), "w")
        invent_file.writelines(ip_lst)
        invent_file.close()

        return invent_file.name

    def copy_network_script(env):
        login_timeout = params.get_numeric("login_timeout", 360)
        deps_dir = virttest_data_dir.get_deps_dir()

        file_name = os.path.basename(setup_bridge_sh)
        br_file = os.path.join(deps_dir, file_name)
        for vm in get_live_vms(env):
            vm.wait_for_login(timeout=login_timeout)
            vm.copy_files_to(br_file, setup_bridge_sh)

    def generate_parameter_file(params):
        tmp_dir = virttest_data_dir.get_tmp_dir()
        file_name = "parameter_file"

        guest_password = params.get("password")

        bootstrap_options = params.get("nested_bs_options")
        accept_cancel = params.get_boolean("accept_cancel")

        kar_cmd = "python3 ./ConfigTest.py "

        test_type = params.get("test_type")
        variant_name = params.get("nested_test")
        case_name = params.get("case_name", "")

        if variant_name == "check_cpu_model_l2":
            host_cpu_models = virttest_cpu.get_host_cpu_models()
            case_name = ",".join(["%s.%s" % (case_name, i) for i in host_cpu_models])

        kar_cmd += " --%s=%s " % (test_type, case_name)

        l2_guest_name = params.get("l2_guest_name")
        if l2_guest_name:
            kar_cmd += " --guestname=%s" % l2_guest_name
        clone = params.get("install_node")
        if clone == "yes":
            kar_cmd += " --clone=yes"
        else:
            kar_cmd += " --clone=no"

        l2_kar_options = params.get("l2_kar_options")
        if l2_kar_options:
            kar_cmd += " %s" % l2_kar_options

        test.log.info("Kar cmd: %s", kar_cmd)

        results_dir = test.logdir
        test.log.info("Result_dir: %s", results_dir)

        kar_repo = params.get("kar_repo")
        cert_url = params.get("cert_url")

        data = {
            "guest_password": guest_password,
            "bootstrap_options": bootstrap_options,
            "accept_cancel": accept_cancel,
            "command_line": kar_cmd,
            "setup_br_sh": setup_bridge_sh,
            "host_log_files_dir": results_dir,
            "kar_repo": kar_repo,
            "cert_url": cert_url,
        }

        json_file = open(os.path.join(tmp_dir, file_name), "w")
        json.dump(data, json_file)
        json_file.close()

        return json_file.name

    if params.get("check_vendor", "no") == "yes" and cpu.get_vendor() != "intel":
        test.cancel("We only test this case with Intel platform now")

    sm = manager.SoftwareManager()
    if not sm.check_installed("ansible"):
        sm.install("ansible")

    invent_file = generate_invent_file(env)

    copy_network_script(env)

    deps_dir = virttest_data_dir.get_deps_dir()
    playbook_file = os.path.join(deps_dir, "playbook.yml")

    params_file = generate_parameter_file(params)

    ansible_cmd = (
        'export ANSIBLE_SSH_ARGS="-C -o ControlMaster=auto '
        "-o ControlPersist=60s "
        "-o StrictHostKeyChecking=no "
        '-o UserKnownHostsFile=/dev/null"; '
        "ansible-playbook %s "
        '--extra-vars "@%s" '
        "-i %s " % (playbook_file, params_file, invent_file)
    )

    test.log.debug("ansible cmd: %s", ansible_cmd)

    timeout = float(params.get("test_timeout", 3600))

    status, output = process.getstatusoutput(ansible_cmd, timeout)
    if status != 0:
        test.fail("ansible_cmd failed, status: %s, output: %s" % (status, output))
