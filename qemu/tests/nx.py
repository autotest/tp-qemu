import os

from virttest import data_dir, error_context


@error_context.context_aware
def run(test, params, env):
    """
    try to exploit the guest to test whether nx(cpu) bit takes effect.

    1) boot the guest
    2) cp the exploit prog into the guest
    3) run the exploit

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """

    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    session = vm.wait_for_login(timeout=int(params.get("login_timeout", 360)))

    exploit_cmd = params.get("exploit_cmd", "")
    if not exploit_cmd or session.cmd_status("test -x %s" % exploit_cmd):
        exploit_file = os.path.join(data_dir.get_deps_dir(), "nx", "x64_sc_rdo.c")
        dst_dir = "/tmp"

        error_context.context("Copy the Exploit file to guest.", test.log.info)
        vm.copy_files_to(exploit_file, dst_dir)

        error_context.context("Build exploit program in guest.", test.log.info)
        build_exploit = "gcc -o /tmp/nx_exploit /tmp/x64_sc_rdo.c"
        if session.cmd_status(build_exploit):
            test.error("Failed to build the exploit program")

        exploit_cmd = "/tmp/nx_exploit"

    error_context.context("Run exploit program in guest.", test.log.info)
    # if nx is enabled (by default), the program failed.
    # segmentation error. return value of shell is not zero.
    exec_res = session.cmd_status(exploit_cmd)
    nx_on = params.get("nx_on", "yes")
    if nx_on == "yes":
        if exec_res:
            test.log.info("NX works good.")
            error_context.context(
                "Using execstack to remove the protection.", test.log.info
            )
            enable_exec = "execstack -s %s" % exploit_cmd
            if session.cmd_status(enable_exec):
                if session.cmd_status("execstack --help"):
                    msg = "Please make sure guest have execstack command."
                    test.error(msg)
                test.error("Failed to enable the execstack")

            if session.cmd_status(exploit_cmd):
                test.fail("NX is still protecting. Error.")
            else:
                test.log.info("NX is disabled as desired. good")
        else:
            test.fail("Fatal Error: NX does not protect anything!")
    else:
        if exec_res:
            msg = "qemu fail to disable 'nx' flag or the exploit is corrupted."
            test.error(msg)
        else:
            test.log.info("NX is disabled, and this Test Case passed.")
    if session:
        session.close()
