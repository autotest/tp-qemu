import os
import pathlib
import re

from avocado.utils import process
from virttest import env_process, error_context


@error_context.context_aware
def run(test, params, env):
    """
    Run nvdimm cases:
    1) Mount nvdimm device on host
    2) Create a file in the mount point
    3) Boot guest with nvdimm backed by the file
    4) Check flag 'sf' is present in qemu smaps

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """
    dev_path = params["dev_path"]
    p = pathlib.Path(dev_path)
    if not p.is_block_device():
        test.error(
            "There is no nvdimm device in host, please add kernel param"
            "'memmap' to emulate one"
        )

    format_cmd = params["format_command"]
    mount_cmd = params["mount_command"]
    truncate_cmd = params["truncate_command"]
    clean_cmd = params["clean_command"]
    try:
        process.run(format_cmd)
        process.run(mount_cmd, shell=True)
        process.run(truncate_cmd)
    except Exception as e:
        test.error(e)
    else:
        try:
            params["start_vm"] = "yes"
            env_process.preprocess_vm(test, params, env, params["main_vm"])
            vm = env.get_vm(params["main_vm"])
            vm.verify_alive()
            vm.wait_for_login()
            vm_pid = vm.get_pid()

            error_context.context("Check vmflags in smaps file", test.log.info)
            with open("/proc/%s/smaps" % vm_pid, "r") as fd:
                content = fd.read()
            check_pattern = params["check_pattern"]
            vmflags_match = re.search(check_pattern, content, re.M)
            if vmflags_match:
                vmflags = vmflags_match.group(1).strip()
                test.log.info("Get vmflags: %s", vmflags)
            else:
                test.error("Didn't find VmFlags in smaps file")
            if "sf" not in vmflags.split():
                test.fail("Flag 'sf' is not present in smaps file")
        finally:
            vm.destroy()
    finally:
        if os.path.ismount(params["mount_dir"]):
            process.run(clean_cmd, shell=True)
