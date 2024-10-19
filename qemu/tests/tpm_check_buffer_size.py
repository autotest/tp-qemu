import os
from shutil import rmtree

from avocado.utils import git, process
from virttest import error_context


@error_context.context_aware
def run(test, params, env):
    """
    Run Check size of buffer before accessing it in libtpms
    upstream test tree

    1. Download and install libtpms-devel rpm
    2. Clone libtpms test tree
    3. Comple and execute test cases

    :param test: QEMU test object.
    :param params: Dictionary with the test parameters.
    :param env: Dictionary with test environment.
    """

    libtpms_rpm = process.getoutput("rpm -q libtpms", shell=True).strip()
    libtpms_devel_rpm = libtpms_rpm.replace("libtpms", "libtpms-devel")

    if process.system("rpm -q libtpms-devel", shell=True, ignore_status=True) != 0:
        try:
            process.system(
                "cd /home/ && brew download-build --rpm %s" % libtpms_devel_rpm,
                shell=True,
            )
            libtpms_devel_rpm = libtpms_devel_rpm + ".rpm"
            process.system("rpm -i /home/%s" % libtpms_devel_rpm, shell=True)
        except Exception:
            test.cancel("libtpms-devel package installation failed.")

    repo_url = params["repo_url"]
    repo_dir = git.get_repo(
        repo_url, destination_dir=os.path.join(test.tmpdir, "libtpms")
    )

    try:
        error_context.base_context("Build and execute test cases", test.log.info)
        for test_case in params.get("test_case").split(";"):
            test_case_o = test_case.split(".")[0]
            build_execute_cmd = params["build_execute_cmd"] % (
                test_case,
                test_case_o,
                test_case_o,
            )
            process.system("cd %s && %s" % (repo_dir, build_execute_cmd), shell=True)
    finally:
        process.system(
            "rm -f /home/%s*" % libtpms_devel_rpm, shell=True, ignore_status=True
        )
        rmtree(repo_dir, ignore_errors=True)
