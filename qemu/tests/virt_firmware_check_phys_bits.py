import re

from virttest import env_process, error_context, virt_vm


def get_host_phys_bits(test):
    """
    Get the host phys-bits from CPUID leaf 0x80000008, which is the very
    same source QEMU uses for the host-phys-bits property, see
    host_cpu_phys_bits() in target/i386/host-cpu.c.

    /proc/cpuinfo must not be used here: when memory encryption is enabled
    some bits are taken from the physical address, and the kernel subtracts
    them from the width it reports there, while CPUID, and so QEMU, keeps
    reporting the full width.

    :param test: QEMU test object
    :return: the host phys-bits as an integer
    """
    try:
        with open("/dev/cpu/0/cpuid", "rb") as cpuid_dev:
            cpuid_dev.seek(0x80000008)
            # the driver only accepts reads that are a multiple of its
            # 16 bytes chunk, one {eax,ebx,ecx,edx} tuple per leaf
            regs = cpuid_dev.read(16)
            return int.from_bytes(regs[:4], "little") & 0xFF
    except OSError as details:
        test.error("Failed to read CPUID leaf 0x80000008: %s" % details)


@error_context.context_aware
def run(test, params, env):
    """
    Test parameters host-phys-bits and host-phys-bits-limit.
    host-phys-bits=on is default on rhel qemu-kvm builds,
    so cover the default value in the test.
    phys-bits to be covered in the test:
    AMD processors have 40, 43, 48 or 52 phys-bits.
    Intel processors have 36, 39, 46 or 52 phys-bits.
    In this case, the cpu will be configured with host-phys-bits=on
    and host-phys-bits-limit=<phys-bits-to-test>.
    The maximum number OVMF is using right now is 46.
    For 5-level page inside OVMF, they don't have that yet.
    The limit setting its higher on the host configuration doesn't hurt,
    but OVMF just wouldn't use it.

    1) boot a guest with invalid phys-bits, check the error messag
       e.g. host-phys-bits-limit=-1, host-phys-bits-limit=1
    2) boot a guest with valid phys-bits, check the phys-bits in guest
       make sure it equals to the set value or equals to the maximum
       number which host supporting
    3) check the phys-bits in virt firmware log, it also equals to the
       set value or equals to the maximum number which host supporting
    4) for ovmf, if phys-bits number is greater than 46, check the
       limitation message in virt firmware log
       limitation message: limit PhysBits to 46 (avoid 5-level paging)
       seabios limit to 46 phys-bits too. It doesn't print a limitation
       message about it, so for seabios, don't check it

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """
    phys_bits_grep_cmd = params["phys_bits_grep_cmd"]
    host_phys_bits = get_host_phys_bits(test)
    host_phys_bits_limit = params["host_phys_bits_limit"]
    params["cpu_model_flags"] %= host_phys_bits_limit
    err_msg = params.get("err_msg")
    ignored_err_msg = params.get("ignored_err_msg")
    try:
        error_context.context(
            "Start the vm with host-phys-bits-limit=%s." % host_phys_bits_limit,
            test.log.info,
        )
        vm_name = params["main_vm"]
        env_process.preprocess_vm(test, params, env, vm_name)
        vm = env.get_vm(vm_name)
        vm.verify_alive()
    except (virt_vm.VMCreateError, virt_vm.VMStartError) as e:
        if err_msg:
            if err_msg not in str(e):
                test.fail(
                    "Boot a vm with invalid phys-bits '%s', "
                    "the error message is not the expected value "
                    "'%s'. The actual output is '%s'."
                    % (host_phys_bits_limit, err_msg, str(e))
                )
        elif ignored_err_msg:
            if not re.search(ignored_err_msg, str(e), re.S | re.I):
                test.fail(
                    "Boot a vm with phys-bits '%s', the ignored "
                    "error message is not the expected value "
                    "'%s'. The actual output is '%s'."
                    % (host_phys_bits_limit, ignored_err_msg, str(e))
                )
        else:
            test.error("Failed to create a vm, the error is '%s'" % str(e))
    else:
        if err_msg:
            test.fail(
                "Start the vm unexpectedly with "
                "host-phys-bits-limit=%s." % host_phys_bits_limit
            )
        error_context.context("Check the phys-bits in guest.", test.log.info)
        session = vm.wait_for_login()
        guest_phys_bits = int(session.cmd_output(phys_bits_grep_cmd).strip())
        expected_phys_bits = min(host_phys_bits, int(host_phys_bits_limit))
        session.close()
        err_str = "The phys-bits in guest, it dosen't equal to expected value."
        err_str += "The expected value is %s, but the actual value is %s."
        err_str %= (expected_phys_bits, guest_phys_bits)
        test.assertEqual(guest_phys_bits, expected_phys_bits, err_str)
        phys_bits_msg = params["phys_bits_msg"] % expected_phys_bits
        logs = vm.logsessions["seabios"].get_output()
        error_context.context(
            "Check the phys-bits message in virt firmware log.", test.log.info
        )
        if not re.search(phys_bits_msg, logs, re.S | re.I):
            test.fail(
                "Not found phys-bits message '%s' in virt firmware log." % phys_bits_msg
            )
        limitation = params.get_numeric("limitation_from_ovmf")
        if limitation and expected_phys_bits > limitation:
            error_context.context(
                "Check the limitation message in virt firmware log.", test.log.info
            )
            if not re.search(params["limitation_msg"], logs, re.S | re.I):
                test.fail("Not found the limitation message in virt firmware log.")
