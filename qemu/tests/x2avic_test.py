from avocado.utils import process

from provider.cpu_utils import check_cpu_flags


def run(test, params, env):
    """
    avic test:
    1) Turn on avic on Genoa host
    2) Verify kernel x2AVIC is enabled on host
    3) Boot a guest
    4) Check 'x2apic' enabled inside guest
    5) Then run the follow linux perf utility to verify VMEXIT counter on host

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """

    flags = params["flags"]
    check_cpu_flags(params, flags, test)

    vm = env.get_vm(params["main_vm"])
    vm.create()

    try:
        session = vm.wait_for_login()
        if params.get("os_type") == "linux":
            output = session.cmd_output("dmesg | grep x2apic")
            if "x2apic enabled" not in output:
                if "x2apic: enabled" not in output:
                    test.fail("x2apic is not enabled inside guest.")
    finally:
        session.close()
    kvm_stat_output = process.getoutput("kvm_stat -1")
    if "kvm_avic" not in kvm_stat_output:
        test.fail("No avic events on host.")
    elif "unaccelerated_access" not in kvm_stat_output:
        test.fail("No kvm_avic_unaccelerated_access event on host.")
    elif "incomplete_ipi" not in kvm_stat_output:
        test.fail("No vm_avic_incomplete_ipi event on host.")

    vm.verify_kernel_crash()
