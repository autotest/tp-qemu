import os
from glob import glob
from shutil import rmtree

from avocado.utils import git, process
from virttest import error_context


@error_context.context_aware
def run(test, params, env):
    """
    Run kvm-unit-tests subtest cases and check results

    1) Clone kvm-unit-tests repository in the host
    2) Compile the test suite
    3) Run subtest group tests and check results

    :param test: QEMU test object.
    :type  test: avocado_vt.test.VirtTest
    :param params: Dictionary with the test parameters.
    :type  params: virttest.utils_params.Params
    :param env: Dictionary with test environment.
    :type  env: virttest.utils_env.Env
    """

    repo_url = params["repo_url"]
    sub_type = params["sub_type"]
    repo_dir = git.get_repo(
        repo_url, destination_dir=os.path.join(test.tmpdir, "kvm-unit-tests")
    )
    tests_dir = os.path.join(repo_dir, "tests")
    failed_tests = []

    try:
        error_context.base_context(f"Run {sub_type} sub tests", test.log.info)
        process.system(
            f"cd {repo_dir} && ./configure && make standalone",
            verbose=False,
            shell=True,
        )
        for test_file in glob(os.path.join(tests_dir, sub_type + "*")):
            test_name = os.path.basename(test_file)
            s, o = process.getstatusoutput(test_file)
            test.log.debug('Output of "%s":\n%s', test_name, o)
            if s and s != 77:
                failed_tests.append(os.path.basename(test_file))

        if failed_tests:
            test.fail(f"Certain {sub_type} test cases fail: {failed_tests}")
        test.log.info("All %s tests passed", sub_type)
    finally:
        rmtree(repo_dir, ignore_errors=True)
