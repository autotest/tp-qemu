import os

from avocado.utils import cpu
from virttest import data_dir as virttest_data_dir
from virttest import env_process, error_context
from virttest.utils_misc import verify_dmesg


@error_context.context_aware
def run(test, params, env):
    """
    Snp direct kernel boot test:
    1. Boot sev/snp VM with direct kernel boot
    2. Verify sev/snp enabled in guest
    3. Verify attestation with snp guest

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """

    secure_guest_type = params["vm_secure_guest_type"]
    error_context.context(f"Start {secure_guest_type} kernel hash test", test.log.info)
    timeout = params.get_numeric("login_timeout", 240)

    if secure_guest_type == "snp":
        guest_check_cmd = params["snp_guest_check"]
        guest_fail_msg = "Guest snp verify fail"
    else:
        guest_check_cmd = params["sev_guest_check"]
        guest_fail_msg = "Guest sev verify fail"

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

    params["start_vm"] = "yes"
    guest_name = params["guest_name"]
    params["kernel"] = f"images/{guest_name}/vmlinuz"
    params["initrd"] = f"images/{guest_name}/initrd.img"

    vm_name = params["main_vm"]
    env_process.preprocess_vm(test, params, env, vm_name)
    vm = env.get_vm(vm_name)
    vm.verify_alive()
    session = vm.wait_for_login(timeout=timeout)
    verify_dmesg()

    try:
        session.cmd_output(guest_check_cmd, timeout=240)
    except Exception as e:
        test.fail(f"{guest_fail_msg}: {str(e)}")
    else:
        # Verify attestation (only for SNP)
        if secure_guest_type == "snp":
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
                test.fail("Guest test preparation fail: %s" % str(e))
            guest_cmd = guest_cmd + " " + host_cpu_model
            s = session.cmd_status(guest_cmd, timeout=360)
            if s:
                test.fail(f"Attestation script failed with exit status {s}")
    finally:
        session.close()
        vm.destroy()
