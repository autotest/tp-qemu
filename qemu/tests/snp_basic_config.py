import os

from avocado.utils import cpu
from virttest import data_dir as virttest_data_dir
from virttest import error_context
from virttest.utils_misc import verify_dmesg


@error_context.context_aware
def run(test, params, env):
    """
    Qemu snp basic test on Milan and above host:
    1. Check host snp capability
    2. Boot snp VM
    3. Verify snp enabled in guest
    4. Check snp qmp cmd and policy

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """

    error_context.context("Start sev-snp test", test.log.info)
    timeout = params.get_numeric("login_timeout", 240)

    snp_module_path = params["snp_module_path"]
    if os.path.exists(snp_module_path):
        with open(snp_module_path) as f:
            output = f.read().strip()
        if output not in params.objects("module_status"):
            test.cancel("Host sev-snp support check fail.")
    else:
        test.cancel("Host sev-snp support check fail.")
    single_socket = params.get_boolean("single_socket", False)
    if single_socket:
        res = cpu.lscpu()
        if int(res["sockets"]) != 1:
            test.cancel("Host cpu has more than 1 socket, skip the case.")

    family_id = int(cpu.get_family())
    model_id = int(cpu.get_model())
    dict_cpu = {
        "milan": [25, 0, 15],
        "genoa": [25, 16, 31],
        "bergamo": [25, 160, 175],
        "turin": [26, 0, 31],
    }
    host_cpu_model = None
    for platform, values in dict_cpu.items():
        if values[0] == family_id:
            if model_id >= values[1] and model_id <= values[2]:
                host_cpu_model = platform
    if not host_cpu_model:
        test.cancel("Unsupported platform. Requires milan or above.")
    test.log.info("Detected platform: %s", host_cpu_model)
    vm_name = params["main_vm"]
    vm = env.get_vm(vm_name)
    vm.create()
    vm.verify_alive()
    session = vm.wait_for_login(timeout=timeout)
    verify_dmesg()
    # Check for /dev/sev-guest inside the guest
    test.log.info("Checking for SNP attestation support in guest")
    rc_code = session.cmd_status("test -c /dev/sev-guest")
    if rc_code:
        test.cancel(
            "Error: Unable to find /dev/sev-guest. Guest kernel support for "
            "SNP attestation is missing."
        )
    vm_policy = vm.params.get("snp_policy")
    vm_policy_int = int(vm_policy, 0)
    guest_check_cmd = params["snp_guest_check"]
    sev_guest_info = vm.monitor.query_sev()
    if sev_guest_info["snp-policy"] != vm_policy_int:
        test.fail("QMP snp policy doesn't match %s." % vm_policy)
    try:
        session.cmd_output(guest_check_cmd, timeout=240)
    except Exception as e:
        test.fail("Guest snp verify fail: %s" % str(e))
    else:
        # Verify attestation
        error_context.context("Start to do attestation", test.log.info)
        guest_dir = params["guest_dir"]
        host_script = params["host_script"]
        guest_cmd = params["guest_cmd"]
        deps_dir = virttest_data_dir.get_deps_dir()
        host_file = os.path.join(deps_dir, host_script)
        try:
            vm.copy_files_to(host_file, guest_dir)
            if params.get("snpguest_sourcebuild", "0") == "1":
                snpguest_build_location = params["snpguest_build_location"]
                snpguest_buildcmd = params["snpguest_buildcmd"]
                snpguest_buildcmd_args = (
                    snpguest_buildcmd + " " + params.get("snpguest_buildcmd_args", "")
                )
                install_snpguest = os.path.join(deps_dir, snpguest_build_location)
                vm.copy_files_to(install_snpguest, guest_dir)
                session.cmd("chmod 755 %s" % snpguest_buildcmd)
                session.cmd(snpguest_buildcmd_args, timeout=360)
            else:
                session.cmd_output(params["guest_tool_install"], timeout=240)
            session.cmd_output("chmod 755 %s" % guest_cmd)
        except Exception as e:
            test.fail("Guest test preparation fail: %s" % str(e))
        guest_cmd = guest_cmd + " " + host_cpu_model
        s = session.cmd_status(guest_cmd, timeout=360)
        if s:
            test.fail("Guest script error, check the session logs for further details")
    finally:
        session.close()
        vm.destroy()
