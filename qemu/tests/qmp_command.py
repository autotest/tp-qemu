import operator
import platform
import time

from avocado.utils import process
from virttest import qemu_monitor, utils_misc
from virttest.qemu_capabilities import Flags


def run(test, params, env):
    """
    Test qmp event notification, this case will:
    1) Start VM with qmp enable.
    2) Connect to qmp port then run qmp_capabilities command.
    3) Initiate the qmp command defined in config (qmp_cmd)
    4) Verify that qmp command works as designed.

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environmen.
    """

    def check_list(qmp_o, key, val=None, check_item_in_pair=True):
        """
        Check if the expect key, val are contained in QMP output qmp_o.

        :param qmp_o: output of QMP command
        :type qmp_o: list
        :param key: expect result
        :type key: str
        :param val: expect result
        :type val: str or None(if check_item_in_pair=False)
        :param check_item_in_pair: If expect result is dict (True) or str (False)
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
                if strict_match:
                    if operator.eq(key, element):
                        return True
                else:
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
                    if strict_match:
                        if operator.eq(key, value):
                            return True
                    else:
                        if key in str(value):
                            return True
            return False

    def check_result(qmp_o, expect_o=None):
        """
        Check test result with difference way according to result_check.
        result_check = equal, expect_o should equal to qmp_o.
        result_check = contain, expect_o should be contained in qmp_o
        result_check = not_contain, expect_o should not be contained in qmp_o.

        :param qmp_o: output from pre_cmd, qmp_cmd or post_cmd.
        :type qmp_o: list
        :param expect_o: the expect result.
        :type expect_o: list
        """
        test.log.info("Expect result is %s", expect_o)
        test.log.info("Actual result that get from qmp_cmd/post_cmd is %s", qmp_o)
        if result_check == "equal":
            if not operator.eq(qmp_o, expect_o):
                test.fail(
                    "QMP output does not equal to the expect result.\n "
                    "Expect result: '%s'\n"
                    "Actual result: '%s'" % (expect_o, qmp_o)
                )
        elif result_check == "contain":
            for o in expect_o:
                if isinstance(o, dict):
                    for key, val in o.items():
                        result = check_list(qmp_o, key, val)
                        if not result:
                            break
                elif isinstance(o, str):
                    result = check_list(qmp_o, o, check_item_in_pair=False)

                if result:
                    test.log.info("QMP output contain the expect value %s", o)
                else:
                    test.fail(
                        "QMP output does not contain the expect value.\n"
                        "Missed expect value: '%s'\n"
                        "Actual result: '%s'\n" % (o, qmp_o)
                    )
        elif result_check == "not_contain":
            for o in expect_o:
                if isinstance(o, dict):
                    for key, val in o.items():
                        result = check_list(qmp_o, key, val)
                        if result:
                            break
                elif isinstance(o, str):
                    result = check_list(qmp_o, o, check_item_in_pair=False)

                if result:
                    test.fail(
                        "QMP output contain the unexpect result.\n"
                        "Unexpect result: '%s'\n"
                        "Actual result: '%s'" % (o, qmp_o)
                    )

    qemu_binary = utils_misc.get_qemu_binary(params)
    if not utils_misc.qemu_has_option("qmp", qemu_binary):
        test.cancel("Host qemu does not support qmp.")

    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()

    session = vm.wait_for_login(timeout=int(params.get("login_timeout", 360)))

    module = params.get("modprobe_module")
    if module:
        test.log.info("modprobe the module %s", module)
        session.cmd("modprobe %s" % module)

    qmp_ports = vm.get_monitors_by_type("qmp")
    if qmp_ports:
        qmp_port = qmp_ports[0]
    else:
        test.error("Incorrect configuration, no QMP monitor found.")
    callback = {
        "host_cmd": lambda cmd: process.system_output(cmd, shell=True).decode(),
        "guest_cmd": session.cmd_output,
        "qmp_cmd": qmp_port.send_args_cmd,  # pylint: disable=E0606
    }

    def send_cmd(cmd):
        """Helper to execute command on host/ssh guest/qmp monitor"""
        if cmd_type in callback.keys():
            return callback[cmd_type](cmd)
        else:
            test.error("cmd_type is not supported")

    pre_cmd = params.get("pre_cmd")
    qmp_cmd = params.get("qmp_cmd")
    post_cmd = params.get("post_cmd")
    cmd_type = params.get("event_cmd_type")
    result_check = params.get("cmd_result_check")
    strict_match = params.get("strict_match", "yes") == "yes"
    expect_o = eval(params.get("cmd_return_value", "[]"))

    # Pre command
    if pre_cmd is not None:
        test.log.info("Run prepare command '%s'.", pre_cmd)
        pre_o = send_cmd(pre_cmd)
        test.log.debug("Pre-command: '%s'\n Output: '%s'", pre_cmd, pre_o)

    # qmp command
    try:
        # Testing command
        test.log.info("Run qmp command '%s'.", qmp_cmd)
        qmp_o = qmp_port.send_args_cmd(qmp_cmd)
        if not isinstance(qmp_o, list):
            qmp_o = [qmp_o]
        test.log.debug("QMP command: '%s' \n Output: '%s'", qmp_cmd, qmp_o)
    except qemu_monitor.QMPCmdError as err:
        if params.get("negative_test") == "yes":
            test.log.debug("Negative QMP command: '%s'\n output:'%s'", qmp_cmd, err)
            if params.get("negative_check_pattern"):
                check_pattern = params.get("negative_check_pattern")
                if check_pattern not in str(err):
                    test.fail("'%s' not in exception '%s'" % (check_pattern, err))
        else:
            test.fail(err)
    except qemu_monitor.MonitorProtocolError as err:
        test.fail(err)
    except Exception as err:
        test.fail(err)

    # sleep 10s to make netdev_del take effect
    if "netdev_del" in qmp_cmd:
        time.sleep(10)

    # Post command
    if post_cmd is not None:
        test.log.info("Run post command '%s'.", post_cmd)
        post_o = send_cmd(post_cmd)
        if not isinstance(post_o, list):
            post_o = [post_o]
        test.log.debug("Post-command: '%s'\n Output: '%s'", post_cmd, post_o)

    if result_check == "equal" or result_check == "contain":
        test.log.info("Verify qmp command '%s' works as designed.", qmp_cmd)
        if qmp_cmd == "query-name":
            vm_name = params["main_vm"]
            expect_o = [{"name": vm_name}]
        elif qmp_cmd == "query-uuid":
            uuid_input = params["uuid"]
            expect_o = [{"UUID": uuid_input}]
        elif qmp_cmd == "query-version":
            qemu_version_cmd = (
                "rpm -qa | grep -E 'qemu-kvm(-(rhev|ma))?-[0-9]' | head -n 1"
            )
            host_arch = platform.machine()
            qemu_version = callback["host_cmd"](qemu_version_cmd).replace(
                ".%s" % host_arch, ""
            )
            expect_o = [str(qemu_version)]
        elif qmp_cmd == "query-block":
            images = params["images"].split()
            image_info = {}
            for image in images:
                image_params = params.object_params(image)
                image_format = image_params["image_format"]
                image_drive = "drive_%s" % image
                if vm.check_capability(Flags.BLOCKDEV):
                    image_info["node-name"] = image_drive
                else:
                    image_info["device"] = image_drive
                image_info["qdev"] = image
                image_info["format"] = image_format
                expect_o.append(image_info)
        elif qmp_cmd == "query-target":
            host_arch = platform.machine()
            if host_arch == "ppc64le":
                host_arch = host_arch[:5]
            expect_o = [{"arch": host_arch}]
        elif qmp_cmd == "query-machines":
            # Remove avocado machine type
            vm_machines = params["machine_type"].split(":", 1)[-1]
            expect_o = [{"alias": vm_machines}]
        elif qmp_cmd == "query-vnc":
            vnc_port = vm.get_vnc_port()
            expect_o = [
                {"service": str(vnc_port)},
                {"enabled": True},
                {"host": "0.0.0.0"},
            ]
        check_result(qmp_o, expect_o)
    elif result_check.startswith("post_"):
        test.log.info("Verify post qmp command '%s' works as designed.", post_cmd)
        result_check = result_check.split("_", 1)[1]
        check_result(post_o, expect_o)
    session.close()
