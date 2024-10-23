import os

from avocado.utils import process
from virttest import utils_misc, utils_package


def run(test, params, env):
    """
    Test dump-guest-core, this case will:

    1) Start VM with dump-guest-core option.
    2) Check host env.
    3) Trigger a core dump in host.
    4) Use gdb to check core dump file.
    5) If dump-guest-core=on, use crash to check vmcore file

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environmen.
    """

    def check_env():
        """
        Check if host kernel version is same with guest
        """
        guest_kernel_version = session.cmd("uname -r").strip()
        if host_kernel_version != guest_kernel_version:
            test.cancel(
                "Please update your host and guest kernel "
                "to same version.The host kernel version is %s"
                "The guest kernel version is %s"
                % (host_kernel_version, guest_kernel_version)
            )

    def check_core_file(arch):
        """
        Use gdb to check core dump file
        """
        arch_map = {"x86_64": "X86_64", "ppc64le": "ppc64-le"}
        arch_name = arch_map.get(arch)
        arch = arch_name if arch_name else arch
        command = (
            'echo -e "source %s\nset height 0\ndump-guest-memory'
            ' %s %s\nbt\nquit" > %s'
            % (dump_guest_memory_file, vmcore_file, arch, gdb_command_file)
        )
        process.run(command, shell=True)
        status, output = process.getstatusoutput(gdb_command, timeout=360)
        os.remove(gdb_command_file)
        os.remove(core_file)
        test.log.debug(output)
        if status != 0:
            test.fail("gdb command execute failed")
        elif "<class 'gdb.MemoryError'>" in output:
            if dump_guest_core == "on":
                test.fail("Cannot access memory")

    def check_vmcore_file():
        """
        Use crash to check vmcore file
        """
        process.run(
            'echo -e "bt\ntask 0\ntask 1\nquit" > %s' % crash_script, shell=True
        )
        output = process.getoutput(crash_cmd, timeout=60)
        os.remove(crash_script)
        os.remove(vmcore_file)
        test.log.debug(output)
        if "systemd" in output and "swapper" in output:
            test.log.info("Crash command works as expected")
        else:
            test.fail("Vmcore corrupt")

    # install crash/gdb/kernel-debuginfo in host
    packages = [
        "crash",
        "gdb",
        "kernel-debuginfo*",
        "qemu-kvm-debuginfo",
        "qemu-kvm-debugsource",
        "qemu-kvm-core-debuginfo",
    ]
    utils_package.package_install(packages)

    trigger_core_dump_command = params["trigger_core_dump_command"]
    core_file = params["core_file"]
    dump_guest_memory_file = params["dump_guest_memory_file"]
    gdb_command = params["gdb_command"]
    gdb_command_file = params["gdb_command_file"]
    dump_guest_core = params["dump_guest_core"]
    crash_script = params["crash_script"]
    crash_cmd = params["crash_cmd"]
    vmcore_file = params["vmcore_file"]
    check_vmcore = params["check_vmcore"]
    arch = params["vm_arch_name"]
    host_kernel_version = process.getoutput("uname -r").strip()
    vm = env.get_vm(params["main_vm"])
    session = vm.wait_for_login()
    if params.get("check_env", "yes") == "yes":
        check_env()

    qemu_id = vm.get_pid()
    core_file += str(qemu_id)
    gdb_command %= str(qemu_id)
    trigger_core_dump_command %= str(qemu_id)
    test.log.info("trigger core dump command: %s", trigger_core_dump_command)
    process.run(trigger_core_dump_command)
    utils_misc.wait_for(lambda: os.path.exists(core_file), timeout=120)
    if params.get("check_core_file", "yes") == "yes":
        check_core_file(arch)
        if dump_guest_core == "on" and check_vmcore == "yes":
            crash_cmd %= host_kernel_version
            utils_misc.wait_for(lambda: os.path.exists(vmcore_file), timeout=60)
            check_vmcore_file()
