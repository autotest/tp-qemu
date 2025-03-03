import os

from virttest import utils_test


def run(test, params, env):
    """
    Run an autotest test inside a guest.

    :param test: kvm test object.
    :param params: Dictionary with test parameters.
    :param env: Dictionary with the test environment.
    """
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    timeout = int(params.get("login_timeout", 360))
    session = vm.wait_for_login(timeout=timeout)

    mount_dir = params.get("9p_mount_dir")

    if mount_dir is None:
        test.log.info("User Variable for mount dir is not set")
    else:
        session.cmd("mkdir -p %s" % mount_dir)

        mount_option = " trans=virtio"

        p9_proto_version = params.get("9p_proto_version", "9p2000.L")
        mount_option += ",version=" + p9_proto_version

        guest_cache = params.get("9p_guest_cache")
        if guest_cache == "yes":
            mount_option += ",cache=loose"

        posix_acl = params.get("9p_posix_acl")
        if posix_acl == "yes":
            mount_option += ",posixacl"

        test.log.info("Mounting 9p mount point with options %s", mount_option)
        cmd = "mount -t 9p -o %s autotest_tag %s" % (mount_option, mount_dir)
        mount_status = session.cmd_status(cmd)

        if mount_status != 0:
            test.log.error("mount failed")
            test.fail("mount failed.")

        # Collect test parameters
        timeout = int(params.get("test_timeout", 14400))
        control_path = os.path.join(
            test.virtdir, "autotest_control", params.get("test_control_file")
        )

        outputdir = test.outputdir

        utils_test.run_autotest(vm, session, control_path, timeout, outputdir, params)
