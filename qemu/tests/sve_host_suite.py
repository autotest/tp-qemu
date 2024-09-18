import os
import re
import shutil

from avocado.utils import process
from virttest import error_context, utils_package

from provider import cpu_utils


@error_context.context_aware
def run(test, params, env):
    def compile_kernel_selftests():
        error_context.context(
            "Download the kernel src.rpm package and uncompress it", test.log.info
        )
        process.run(get_suite_cmd, shell=True)
        if os.path.exists(dst_dir):
            shutil.rmtree(dst_dir)
        os.mkdir(dst_dir)
        process.run(uncompress_cmd.format(tmp_dir, linux_name), shell=True)

        error_context.context("Compile kernel selftests", test.log.info)
        s, o = process.getstatusoutput(compile_cmd, timeout=180)
        if s:
            test.log.error("Compile output: %s", o)
            test.error("Failed to compile the test suite.")

    compile_cmd = params["compile_cmd"]
    dst_dir = params["dst_dir"]
    execute_suite_cmd = params["execute_suite_cmd"]
    get_suite_cmd = params["get_suite_cmd"]
    required_pkgs = params.objects("required_pkgs")
    suite_timeout = params.get_numeric("suite_timeout")
    uncompress_cmd = params["uncompress_cmd"]
    tmp_dir = test.tmpdir

    if not utils_package.package_install(required_pkgs):
        test.error("Failed to install required packages in host")
    error_context.base_context("Check if the CPU of host supports SVE", test.log.info)
    cpu_utils.check_cpu_flags(params, "sve", test)

    kernel_version = os.uname()[2].rsplit(".", 1)[0]
    srpm = f"kernel-{kernel_version}.src.rpm"
    linux_name = f"linux-{kernel_version}"
    get_suite_cmd = get_suite_cmd.format(tmp_dir, srpm)

    try:
        compile_kernel_selftests()
        s, o = process.getstatusoutput(execute_suite_cmd, timeout=suite_timeout)
        if s:
            test.fail('The exit code of "get-reg-list" test suite is not 0.')
        elif not all(
            [result == "PASS" for result in re.findall(r"^sve\S*: (\w+)$", o, re.M)]
        ):
            test.log.error("Test result: %s", o)
            test.fail('The sve part of the "get-reg-list" test failed')
        test.log.info("get-reg-list test passed")
    finally:
        shutil.rmtree(dst_dir, ignore_errors=True)
