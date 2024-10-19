import os
import re
import shutil

from avocado.utils import process
from virttest import data_dir, error_context


@error_context.context_aware
def run(test, params, env):
    """
    Negative test.virtiofsd shouldn't boot up with an unknown socket group name.
    Steps:
        1. Create shared directories on the host.
        2. Run virtiofsd daemons with an unknown socket group name.

    :param test: QEMU test object.
    :param params: Dictionary with the test parameters.
    :param env: Dictionary with test environment.
    """
    result_pattern = params.get("result_pattern", "unable to find group")

    # set fs daemon path
    fs_source = params.get("fs_source_dir")
    base_dir = params.get("fs_source_base_dir", data_dir.get_data_dir())

    if not os.path.isabs(fs_source):
        fs_source = os.path.join(base_dir, fs_source)
    if os.path.exists(fs_source):
        shutil.rmtree(fs_source, ignore_errors=True)
    test.log.info("Create filesystem source %s.", fs_source)
    os.makedirs(fs_source)
    try:
        sock_path = os.path.join(
            data_dir.get_tmp_dir(),
            "-".join(("avocado-vt-vm1", "viofs", "virtiofsd.sock")),
        )
        # run daemon
        process.system(params.get("cmd_create_fs_source"), shell=True)
        cmd_run_virtiofsd = params.get("cmd_run_virtiofsd") % sock_path
        cmd_run_virtiofsd += " -o source=%s" % fs_source
        cmd_run_virtiofsd += params.get("fs_binary_extra_options")

        error_context.context(
            "Running daemon command %s." % cmd_run_virtiofsd, test.log.info
        )
        output = (
            process.system_output(cmd_run_virtiofsd, ignore_status=True, shell=True)
            .strip()
            .decode()
        )

        match = re.search(result_pattern, output, re.I | re.M)
        if match:
            test.fail(
                "Virtiofsd started with an unknown socket group name which isn't "
                "expected, output is %s" % output
            )
    finally:
        os.removedirs(fs_source)
