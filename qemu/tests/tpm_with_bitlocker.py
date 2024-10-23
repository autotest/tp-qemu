import re

from virttest import error_context, utils_misc


@error_context.context_aware
def run(test, params, env):
    """
    Test virtual TPM device by BitLocker inside windows guest.
    Steps:
        1. Boot guest with a emulator TPM device.
        2. Install BitLocker inside guest.
        3. Prepares hard drive for BitLocker Drive Encryption.
        4. Encrypts the volume and turns BitLocker protection on.
        5. Wait until Percentage Encrypted to 100%.

    :param test: QEMU test object.
    :param params: Dictionary with the test parameters.
    :param env: Dictionary with test environment.
    """
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    session = vm.wait_for_login()

    cmd_install_bitlocker = params.get("cmd_install_bitlocker")
    if cmd_install_bitlocker:
        error_context.context("Install BitLocker inside guest", test.log.info)
        session.cmd(cmd_install_bitlocker, 360)
        session = vm.reboot(session, timeout=480)

    error_context.context(
        "Prepares hard drive for BitLocker Drive " "Encryption inside guest",
        test.log.info,
    )
    cmd_bdehdcfg = session.cmd_output(params.get("cmd_bdehdcfg"))
    if re.search(r"error", cmd_bdehdcfg, re.M | re.A):
        test.fail("Found error message.")

    error_context.context(
        "Encrypts the volume and turns BitLocker " "protection on inside guest",
        test.log.info,
    )
    session.cmd(params.get("cmd_manage_bde_on"))
    session = vm.reboot(session, timeout=480)

    error_context.context("Wait until Percentage Encrypted finished", test.log.info)
    finished_keywords = params.get("finished_keywords")
    cmd_manage_bde_status = params.get("cmd_manage_bde_status")
    if not utils_misc.wait_for(
        lambda: finished_keywords in session.cmd(cmd_manage_bde_status, 300),
        step=5,
        timeout=600,
    ):
        test.fail("Failed to encrypt the volume.")
