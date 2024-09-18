from virttest import data_dir, error_context, utils_misc


@error_context.context_aware
def run(test, params, env):
    """
    Runs CPU rdrand test:

    :param test: QEMU test object.
    :param params: Dictionary with test parameters.
    :param env: Dictionary with the test environment.
    """

    vm = env.get_vm(params["main_vm"])
    session = vm.wait_for_login()
    test_bin = params["test_bin"]
    source_file = params["source_file"]
    guest_path = params["guest_path"]
    host_path = utils_misc.get_path(data_dir.get_deps_dir("rdrand"), source_file)
    vm.copy_files_to(host_path, "%s%s" % (guest_path, source_file))
    if params["os_type"] == "linux":
        build_cmd = params.get("build_cmd", "cd %s; gcc -lrt %s -o %s")
        error_context.context("build binary file 'rdrand'", test.log.info)
        session.cmd(build_cmd % (guest_path, source_file, test_bin))
    s, o = session.cmd_status_output("%s%s" % (guest_path, test_bin))
    session.cmd(params["delete_cmd"])
    if s != 0:
        test.fail("rdrand failed with status %s" % s)
    if params["os_type"] == "linux":
        try:
            if int(float(o)) not in range(-101, 101):
                test.fail("rdrand output is %s, which is not expected" % o)
        except ValueError as e:
            test.fail("rdrand should output a float: %s" % str(e))
