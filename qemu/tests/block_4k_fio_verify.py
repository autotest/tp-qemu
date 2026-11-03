"""
Verify data integrity on a 4k sector host loop device exposed as a disk with
512 byte sectors in the guest. Use multiple iothreads to make it more likely to
trigger potential race conditions.
"""

import re

from avocado.utils import process
from virttest import env_process, error_context, utils_misc

from provider.storage_benchmark import generate_instance


@error_context.context_aware
def run(test, params, env):
    """
    Test steps:
        1) Create a raw image and attach it to a loop device with 4k sectors.
        2) Boot the guest with the loop device as an extra data disk,
           using six iothreads with vq-mapping.
        3) Run fio inside the guest: 12 jobs, 512-byte writes with CRC-32C
           verification on the data disk.
        4) Assert that fio reports zero verification errors.

    :param test:   QEMU test object.
    :param params: Dictionary with the test parameters.
    :param env:    Dictionary with test environment.
    """

    logger = test.log

    loop_dev_file = params["loop_dev_file"]
    loop_dev = (
        process.system_output("cat %s" % loop_dev_file, shell=True).decode().strip()
    )
    logger.info("Using loop device: %s", loop_dev)

    params["image_name_stg1"] = loop_dev

    error_context.context("Start the VM and log in", logger.info)
    if params.get("not_preprocess", "no") == "yes":
        env_process.process(
            test,
            params,
            env,
            env_process.preprocess_image,
            env_process.preprocess_vm,
        )
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()

    timeout = params.get_numeric("login_timeout", 240)
    session = vm.wait_for_login(timeout=timeout)

    error_context.context("Prepare test inside guest", logger.info)
    drive_path = utils_misc.get_linux_drive_path(session, "stg1")
    if not drive_path:
        test.error("Cannot find data disk with serial 'stg1' in the guest")
    logger.info("Guest data disk: %s", drive_path)

    fio = generate_instance(params, vm, "fio")

    try:
        error_context.context("Run fio write + verify workload", logger.info)
        fio_options = params["fio_options"]
        fio_timeout = params.get_numeric("fio_cmd_timeout", 600)
        cmd = "--filename=%s %s" % (drive_path, fio_options)
        logger.info("fio command options: %s", cmd)
        output = fio.run(cmd, timeout=fio_timeout)
        logger.debug("fio output:\n%s", output)

        error_context.context("Check fio output for verify errors", logger.info)
        verify_lines = []
        err_count = 0
        for line in output.splitlines():
            stripped = line.strip()
            if stripped.startswith("verify:"):
                verify_lines.append(stripped)
            match = re.search(r"\berr=\s*(\d+)", stripped)
            if match:
                err_count = max(err_count, int(match.group(1)))

        if verify_lines or err_count:
            logger.error(
                "fio verify lines (%d), summary err=%d:",
                len(verify_lines),
                err_count,
            )
            for err_line in verify_lines[:50]:
                logger.error("  %s", err_line)
            test.fail(
                "fio reported %d verification error line(s) (err=%d)"
                % (len(verify_lines), err_count)
            )

        logger.info("fio completed with no verification errors")
    finally:
        fio.clean()
        session.close()
        vm.destroy()
