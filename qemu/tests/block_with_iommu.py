import logging

from virttest import cpu
from virttest import error_context


@error_context.context_aware
def run(test, params, env):
    """
    Test the vIOMMU platform.

    Steps:
        1. Add "intel_iommu=on" to kernel line of q35 guest.
        2. Boot a guest with virtio-scsi with iommu_platform=on.
        3. Verify IOMMU enabled in the guest.

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """

    def verify_iommu_enabled():
        """ Verify whether the iommu is enabled. """
        error_context.context(
            'Verify whether IOMMU is enabled in the guest.', logging.info)
        for key_words in params['check_key_words'].split(';'):
            output = session.cmd_output("journalctl -k | grep -i \"%s\"" % key_words)
            if not output:
                test.fail("No found the info \"%s\" "
                          "from the systemd journal log." % key_words)
            logging.debug(output)

    if cpu.get_cpu_vendor(verbose=False) != 'GenuineIntel':
        test.cancel("This case only support Intel platform.")

    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    session = vm.wait_for_login(timeout=360)
    verify_iommu_enabled()
