import re

from virttest import env_process, error_context, utils_misc, utils_qemu


@error_context.context_aware
def run(test, params, env):
    """
    Enable interrupt based asynchronous page fault mechanism by default

    1. boot a guest with "-machine pc-q35-rhel8.5.0" or newer.
    2. check 'Hypervisor callback interrupts' inside guest,
       should have at least 1 for each CPU.

    :param test: QEMU test object.
    :param params: Dictionary with test parameters.
    :param env: Dictionary with the test environment.
    """

    def boot_and_check_guest(machine_type):
        """
        Boot guest and check async PF inside guest

        :param machine_type: Boot guest with which machine type
        """
        params["machine_type"] = machine_type
        check_interrupts = params["check_interrupts"]
        params["start_vm"] = "yes"
        vm_name = params["main_vm"]
        env_process.preprocess_vm(test, params, env, vm_name)
        vm = env.get_vm(vm_name)

        session = vm.wait_for_login()
        g_vcpus = session.cmd_output("grep processor /proc/cpuinfo -c").strip()
        output = session.cmd_output(check_interrupts).split("\n")[0]
        g_interrupts = re.findall(r"\d+", output)
        session.close()
        vm.destroy()

        if g_interrupts.count("0") >= 1:
            test.fail("cpu interrupt value is not right")
        elif len(g_interrupts) != int(g_vcpus):
            test.fail(
                "interrupts %s is not equal to cpu count %s"
                % (len(g_interrupts), g_vcpus)
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
    qemu_bin = utils_misc.get_qemu_binary(params)
    machine_types = utils_qemu.get_supported_machines_list(qemu_bin)
    m_keyword = "q35"

    m_type = [m for m in machine_types if m_keyword in m and m_keyword != m]
    if m_type:
        check_version(m_type[0])
        boot_and_check_guest(m_type[0])
