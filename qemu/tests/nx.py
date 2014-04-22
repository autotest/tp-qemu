import os
import logging
from autotest.client.shared import error
from virttest import data_dir, remote_build


@error.context_aware
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

    address = vm.get_address(0)
    source_dir = data_dir.get_deps_dir("nx")
    build_dir = params.get("build_dir", None)
    builder = remote_build.Builder(params, address, source_dir,
                                   build_dir=build_dir)

    exploit_cmd = os.path.join(builder.build(), "nx_exploit")

    error.context("Run exploit program in guest.", logging.info)
    # if nx is enabled (by default), the program failed.
    # segmentation error. return value of shell is not zero.
    exec_res = session.cmd_status(exploit_cmd)
    nx_on = params.get('nx_on', 'yes')
    if nx_on == 'yes':
        if exec_res:
            logging.info('NX works good.')
            error.context("Using execstack to remove the protection.",
                          logging.info)
            enable_exec = 'execstack -s %s' % exploit_cmd
            if session.cmd_status(enable_exec):
                if session.cmd_status("execstack --help"):
                    msg = "Please make sure guest have execstack command."
                    raise error.TestError(msg)
                raise error.TestError('Failed to enable the execstack')

            if session.cmd_status(exploit_cmd):
                raise error.TestFail('NX is still protecting. Error.')
            else:
                logging.info('NX is disabled as desired. good')
        else:
            raise error.TestFail('Fatal Error: NX does not protect anything!')
    else:
        if exec_res:
            msg = "qemu fail to disable 'nx' flag or the exploit is corrupted."
            raise error.TestError(msg)
        else:
            logging.info('NX is disabled, and this Test Case passed.')
    if session:
        session.close()
