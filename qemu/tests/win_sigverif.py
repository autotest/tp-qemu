import re
import time

from virttest import error_context, utils_misc, utils_test
from virttest.utils_windows import system


@error_context.context_aware
def run(test, params, env):
    """
    sigverif test:
    1) Boot guest with related virtio devices
    2) Run sigverif command(an autoit script) in guest
    3) Open sigverif log and check whether driver is signed

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment
    """

    vm = env.get_vm(params["main_vm"])
    session = vm.wait_for_login()

    driver_name = params["driver_name"]
    driver_verifier = params.get("driver_verifier", driver_name)
    session = utils_test.qemu.windrv_check_running_verifier(
        session, vm, test, driver_verifier
    )

    run_sigverif_cmd = utils_misc.set_winutils_letter(
        session, params["run_sigverif_cmd"]
    )
    sigverif_log = params["sigverif_log"]
    check_sigverif_cmd = params["check_sigverif_cmd"] % driver_name
    clean_sigverif_cmd = params["clean_sigverif_cmd"]

    error_context.context("Run sigverif in windows guest", test.log.info)
    session.cmd(clean_sigverif_cmd, ignore_all_errors=True)
    vm.send_key("meta_l-d")
    time.sleep(60)
    status, output = session.cmd_status_output(run_sigverif_cmd)
    if status != 0:
        test.error(output)

    if not utils_misc.wait_for(
        lambda: system.file_exists(session, sigverif_log), 180, 0, 5
    ):
        test.error("sigverif logs are not created")

    try:
        error_context.context(
            "Open sigverif logs and check driver signature" " status", test.log.info
        )
        output = session.cmd_output(check_sigverif_cmd)
        pattern = r"%s.sys.*\s{2,}Signed" % driver_name
        if not re.findall(pattern, output, re.M):
            test.fail(
                "%s driver is not digitally signed, details info is:\n %s"
                % (driver_name, output)
            )
    finally:
        error_context.context("Clean sigverif logs", test.log.info)
        session.cmd(clean_sigverif_cmd, ignore_all_errors=True)
