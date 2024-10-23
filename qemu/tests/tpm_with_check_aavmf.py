from aexpect.exceptions import ExpectProcessTerminatedError, ExpectTimeoutError
from virttest import error_context, utils_package


@error_context.context_aware
def run(test, params, env):
    """
    Verify the TPM device in the guest and check it in UEFI
    Steps:
        1. Boot guest with an emulator TPM device.
        2. Check and verify TPM/vTPM device info in the UEFI log
        3. Use tpm2_selftest for a basic check.

    :param test: QEMU test object.
    :type  test: avocado.core.test.Test
    :param params: Dictionary with the test parameters.
    :type  params: virttest.utils_params.Params
    :param env: Dictionary with test environment.
    :type  env: virttest.utils_env.Env
    """
    tpm_pattern = [r".*efi: SMBIOS .* TPMFinalLog=.* TPMEventLog=.*"]

    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()

    error_context.context("Check TPM pattern in the serial output", test.log.info)
    try:
        vm.serial_console.read_until_output_matches(tpm_pattern)
    except (ExpectProcessTerminatedError, ExpectTimeoutError) as err:
        test.log.error(err)
        test.fail("Failed to get the expected tpm pattern.")

    error_context.context(
        "Execute tpm2_selftest command for a basic check", test.log.info
    )
    session = vm.wait_for_login()
    if not utils_package.package_install("tpm2-tools", session):
        test.error("Cannot install tpm2-tools to execute tpm2_selftest")
    s, o = session.cmd_status_output("tpm2_selftest")
    if s != 0:
        test.log.error("tpm2_selftest output:\n%s", o)
        test.fail("tpm2_selftest failed")
