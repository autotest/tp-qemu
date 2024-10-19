import re

from virttest import env_process, error_context, utils_misc, utils_qemu


@error_context.context_aware
def run(test, params, env):
    """
    Check L3 cache present to guest

    1. boot guest with latest machine_type,
     checking L3 cache presents inside guest.
    2. Boot guest with old machine type(rhel7.3.0),
     L3 cache shouldn't present inside guest.

    :param test: QEMU test object.
    :param params: Dictionary with test parameters.
    :param env: Dictionary with the test environment.
    """

    def boot_and_check_guest(machine_type, check_L3=False):
        """
        Boot guest and check L3 cache inside guest

        :param machine_type: Boot guest with which machine type
        :param check_L3: if L3 cache should exist on guest
        """
        params["machine_type"] = machine_type
        params["start_vm"] = "yes"
        vm_name = params["main_vm"]
        if max(params.get_numeric("smp"), params.get_numeric("vcpu_maxcpus")) > 128:
            params["smp"] = params["vcpu_maxcpus"] = "128"
        L3_existence = "present" if check_L3 else "not present"
        test.log.info(
            "Boot guest with machine type %s and expect L3 cache %s" " inside guest",
            machine_type,
            L3_existence,
        )
        env_process.preprocess_vm(test, params, env, vm_name)
        vm = env.get_vm(vm_name)
        session = vm.wait_for_login()
        output = session.cmd_output("lscpu")
        session.close()
        vm.destroy()
        L3_present = "L3" in output
        if check_L3 ^ L3_present:
            test.fail(
                "L3 cache should %s inside guest for machine type %s"
                % (L3_existence, machine_type)
            )

    def check_version(latest_machine):
        """
        Check if the latest supported machine type is newer than the defined
        old machine type, cancel the test if not.

        :param latest_machine: The latest machine type
        """
        latest_ver = re.findall(r"\d+\.\d+", latest_machine)[0]
        old_ver = re.findall(r"\d+\.\d+", old_machine)[0]
        if latest_ver <= old_ver:
            test.cancel(
                "The latest supported machine type does not" " support this test case."
            )

    old_machine = params["old_machine"]
    machine_type = params["machine_type"]
    qemu_bin = utils_misc.get_qemu_binary(params)
    machine_types = utils_qemu.get_supported_machines_list(qemu_bin)
    m_keyword = "q35" if "q35" in machine_type else "i440fx"
    for m_type in machine_types:
        if m_keyword in m_type and m_type != m_keyword:
            check_version(m_type)
            boot_and_check_guest(m_type, True)
            break

    for m_type in machine_types:
        if old_machine in m_type and m_keyword in m_type:
            boot_and_check_guest(m_type)
            break
    else:
        test.log.warning("Old machine type is not supported, skip checking.")
