import re

from virttest import error_context, utils_package


@error_context.context_aware
def run(test, params, env):
    """
    Verify the TPM device info inside guest and host.
    Steps:
        1. Launch a guest with vTPM device
        2. Clone the tpm2-tss repository and compile it
        3. Execute the tpm2-tss unit test and analyze the test result

    :param test: QEMU test object.
    :type  test: avocado.core.test.Test
    :param params: Dictionary with the test parameters.
    :type  params: virttest.utils_params.Params
    :param env: Dictionary with test environment.
    :type  env: virttest.utils_env.Env
    """

    configure_cmd = params["configure_cmd"]
    check_log_cmd = params["check_log_cmd"]
    make_check_cmd = params["make_check_cmd"]
    required_packages = params.objects("required_pkgs")
    tpm_device = params["tpm_device"]
    tpm2_tss_path = params["tpm2_tss_path"]
    tpm2_tss_repo = params["tpm2_tss_repo"]

    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    session = vm.wait_for_login()

    error_context.context("Check if TPM2 device exists", test.log.info)
    if session.cmd_status("test -c %s" % tpm_device) != 0:
        test.error("Cannot find the TPM2 device inside guest")

    test.log.info("Install required packages in VM")
    if not utils_package.package_install(required_packages, session):
        test.cancel("Cannot install required packages in VM")

    try:
        error_context.context("Compile the tpm2-tss test suite", test.log.info)
        test.log.info("Clone the tpm2-tss repo...")
        session.cmd("git clone --depth=1 %s %s" % (tpm2_tss_repo, tpm2_tss_path))
        test.log.info("Configure tpm2-tss...")
        session.cmd(configure_cmd, timeout=180)

        error_context.context("Check test result of tpm2-tss", test.log.info)
        status, output = session.cmd_status_output(make_check_cmd, timeout=600)
        if status != 0:
            test.fail("tpm2-tss test suite execution failed, output is:\n%s" % output)
        result = session.cmd_output(check_log_cmd)
        t_total, t_pass = re.findall(r"^# (?:TOTAL|PASS): +(\d+)$", result, re.M)
        if t_total != t_pass:
            test.fail("The count of TOTAL and PASS do not match")
    finally:
        session.cmd("rm -rf %s" % tpm2_tss_path, ignore_all_errors=True)
        session.close()
