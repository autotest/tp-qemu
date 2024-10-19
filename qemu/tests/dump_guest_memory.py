import operator
import os

from avocado.utils import process
from virttest import utils_misc, utils_package


def run(test, params, env):
    """
    Test dump-guest-memory, this case will:

    1) Start VM with qmp enable.
    2) Check if host kernel are same with guest
    3) Connect to qmp port then run qmp_capabilities command.
    4) Initiate the qmp command defined in config (qmp_cmd)
    5) Verify that qmp command works as designed.
    6) Verify dump file with crash

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environmen.
    """

    def check_env():
        """
        Check if host kernel version is same with guest
        """
        guest_kernel_version = session.cmd("uname -r").strip()
        if host_kernel_version != guest_kernel_version:
            test.cancel("Please update your host and guest kernel " "to same version")

    def check_list(qmp_o, key, val=None, check_item_in_pair=True):
        """
        Check if the expect key, val are contained in QMP output qmp_o.

        :param qmp_o: output of QMP command
        :type qmp_o: list
        :param key: expect result
        :type key: str
        :param val: expect result
        :type val: str or None(if check_item_in_pair=False)
        :param check_item_in_pair: expect result is dict (True) or str (False)
        :type check_item_in_pair: bool.

        :return check result
        :rtype: bool
        """
        for element in qmp_o:
            if isinstance(element, dict):
                if _check_dict(element, key, val, check_item_in_pair):
                    return True
            elif isinstance(element, list):
                if check_list(element, key, val, check_item_in_pair):
                    return True
            elif element != "" and not check_item_in_pair:
                if key in str(element):
                    return True
        return False

    def _check_dict(dic, key, val, check_item_in_pair=True):
        """
        Check if the expect key, val are contained in QMP output dic.

        :param dic: content of QMP command return value
        :type dic: dict
        :param key: expect result
        :type key: str
        :param val: expect result
        :type val: str or None(if check_item_in_pair=False)
        :param check_item_in_pair: If expect result is dict or str
        :type check_item_in_pair: bool. Means expect result is dict or str.

        :return check result
        :rtype: bool
        """
        if key in dic and not check_item_in_pair:
            return True
        elif key in dic and val == dic[key]:
            return True
        else:
            for value in dic.values():
                if isinstance(value, dict):
                    if _check_dict(value, key, val, check_item_in_pair):
                        return True
                elif isinstance(value, list):
                    if check_list(value, key, val, check_item_in_pair):
                        return True
                elif value != "" and not check_item_in_pair:
                    if key in str(value):
                        return True
            return False

    def check_result(qmp_o, expect_o=None):
        """
        Check test result with difference way according to result_check.
        result_check = equal, expect_o should equal to qmp_o.
        result_check = contain, expect_o should be contained in qmp_o

        :param qmp_o: output from qmp_cmd.
        :type qmp_o: list
        :param expect_o: the expect result.
        :type expect_o: dict

        :return check result
        :rtype: bool
        """
        test.log.info("Expect result is %s", expect_o)
        test.log.info("Actual result that get from qmp_cmd is %s", qmp_o)
        result = None
        if result_check == "equal":
            if not operator.eq(qmp_o, expect_o):
                test.fail(
                    "QMP output does not equal to the expect result.\n "
                    "Expect result: '%s'\n"
                    "Actual result: '%s'" % (expect_o, qmp_o)
                )
        elif result_check == "contain":
            if len(expect_o) == 0:
                result = True
            elif isinstance(expect_o, dict):
                for key, val in expect_o.items():
                    result = check_list(qmp_o, key, val)
        return result

    def execute_qmp_cmd(qmp_cmd, expect_result):
        """
        Execute qmp command and check if result as expect

        :param qmp_cmd: qmp command
        :type qmp_cmd: str
        :param expect_result: expect result of qmp command
        :type expect_result: str

        :return check result
        :rtype: bool
        """
        # qmp command
        try:
            # Testing command
            test.log.info("Run qmp command '%s'.", qmp_cmd)
            qmp_o = qmp_port.send_args_cmd(qmp_cmd)
            test.log.debug("QMP command:'%s' \n Output: '%s'", qmp_cmd, [qmp_o])
        except Exception as err:
            qmp_o = err.data
            test.log.info(err)

        if result_check:
            test.log.info("Verify qmp command '%s'.", qmp_cmd)
            return check_result([qmp_o], eval(expect_result))

    def check_dump_file():
        """
        Use crash to check dump file
        """
        process.getstatusoutput("echo bt > %s" % crash_script)
        process.getstatusoutput("echo quit >> %s" % crash_script)
        crash_cmd = "crash -i %s /usr/lib/debug/lib/modules/%s/vmlinux "
        crash_cmd %= (crash_script, host_kernel_version)
        crash_cmd += dump_file
        status, output = process.getstatusoutput(crash_cmd)
        os.remove(crash_script)
        test.log.debug(output)
        if status != 0 or "error" in output:
            test.fail("vmcore corrupt")

    # install crash/gdb/kernel-debuginfo in host
    utils_package.package_install(["crash", "gdb", "kernel-debuginfo*"])

    vm = env.get_vm(params["main_vm"])
    session = vm.wait_for_login()
    host_kernel_version = process.getoutput("uname -r").strip()
    check_env()
    qmp_port = vm.monitor

    qmp_cmd = params.get("qmp_cmd")
    query_qmp_cmd = params.get("query_qmp_cmd")
    dump_file = params.get("dump_file")
    crash_script = params.get("crash_script")
    check_dump = params.get("check_dump")
    result_check = params.get("cmd_result_check")
    query_cmd_return_value = params.get("query_cmd_return_value")
    expect_result = params.get("cmd_return_value", "[]")
    dump_file_timeout = params.get("dump_file_timeout")

    # execute qmp command
    execute_qmp_cmd(qmp_cmd, expect_result)

    if check_dump == "True":
        # query dump status and wait for dump completed
        utils_misc.wait_for(
            lambda: execute_qmp_cmd(query_qmp_cmd, query_cmd_return_value),
            dump_file_timeout,
        )
        check_dump_file()
        os.remove(dump_file)

    session.close()
