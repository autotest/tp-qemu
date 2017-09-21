import logging
import re

from autotest.client.shared import error

from avocado.core import exceptions
from avocado.utils import process

from virttest import utils_misc
from virttest import qemu_monitor


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
    def check_result(qmp_o, output=None, exception_list=""):
        """
        Check test result with difference way accoriding to
        result_check.
        result_check = equal, will compare cmd_return_value with qmp
                       command output.
        result_check = contain, will try to find cmd_return_value in qmp
                       command output.
        result_check = m_equal_q, will compare key value in monitor command
                       output and qmp command output.
        result_check = m_in_q, will try to find monitor command output's key
                       value in qmp command output.
        result_check = m_format_q, will try to match the output's format with
                       check pattern.

        :param qmp_o: output from pre_cmd, qmp_cmd or post_cmd.
        :param o: output from pre_cmd, qmp_cmd or post_cmd or an execpt
        :param exception_list: element no need check.
        result set in config file.
        """
        if result_check == "equal":
            value = output
            if value != str(qmp_o):
                raise exceptions.TestFail("QMP command return value does not match "
                                          "the expect result. Expect result: '%s'\n"
                                          "Actual result: '%s'" % (value, qmp_o))
        elif result_check == "contain":
            values = output.split(';')
            for value in values:
                if value in exception_list:
                    continue
                if value.strip() not in str(qmp_o):
                    raise exceptions.TestFail("QMP command output does not contain "
                                              "expect result. Expect result: '%s'\n"
                                              "Actual result: '%s'"
                                              % (value, qmp_o))
        elif result_check == "not_contain":
            values = output.split(';')
            for value in values:
                if value in exception_list:
                    continue
                if value in str(qmp_o):
                    raise exceptions.TestFail("QMP command output contains unexpect"
                                              " result. Unexpect result: '%s'\n"
                                              "Actual result: '%s'"
                                              % (value, qmp_o))
        elif result_check == "m_equal_q":
            msg = "QMP command ouput is not equal to in human monitor command."
            msg += "\nQMP command output: '%s'" % qmp_o
            msg += "\nHuman command output: '%s'" % output
            res = output.splitlines(True)
            if type(qmp_o) != type(res):
                len_o = 1
            else:
                len_o = len(qmp_o)
            if len(res) != len_o:
                if res[0].startswith(' '):
                    raise exceptions.TestFail("Human command starts with ' ', "
                                              "there is probably some garbage in "
                                              "the output.\n" + msg)
                res_tmp = []
                #(qemu)info block in RHEL7 divided into 3 lines
                for line in res:
                    if not line.startswith(' '):
                        res_tmp.append(line)
                    else:
                        res_tmp[-1] += line
                res = res_tmp
                if len(res) != len_o:
                    raise exceptions.TestFail(msg)
            re_str = r'([^ \t\n\r\f\v=]*)=([^ \t\n\r\f\v=]*)'
            for i in range(len(res)):
                if qmp_cmd == "query-version":
                    version = qmp_o['qemu']
                    version = "%s.%s.%s" % (version['major'], version['minor'],
                                            version['micro'])
                    package = qmp_o['package']
                    re_str = r"([0-9]+\.[0-9]+\.[0-9]+)\s*(\(\S*\))?"
                    hmp_version, hmp_package = re.findall(re_str, res[i])[0]
                    if not hmp_package:
                        hmp_package = package
                    hmp_package = hmp_package.strip()
                    package = package.strip()
                    hmp_version = hmp_version.strip()
                    if version != hmp_version or package != hmp_package:
                        raise exceptions.TestFail(msg)
                else:
                    matches = re.findall(re_str, res[i])
                    for key, val in matches:
                        if key in exception_list:
                            continue
                        if '0x' in val:
                            val = long(val, 16)
                            val_str = str(bin(val))
                            com_str = ""
                            for p in range(3, len(val_str)):
                                if val_str[p] == '1':
                                    com_str += '0'
                                else:
                                    com_str += '1'
                            com_str = "0b" + com_str
                            value = eval(com_str) + 1
                            if val_str[2] == '1':
                                value = -value
                            if value != qmp_o[i][key]:
                                msg += "\nValue in human monitor: '%s'" % value
                                msg += "\nValue in qmp: '%s'" % qmp_o[i][key]
                                raise exceptions.TestFail(msg)
                        elif qmp_cmd == "query-block":
                            cmp_str = "u'%s': u'%s'" % (key, val)
                            cmp_s = "u'%s': %s" % (key, val)
                            if '0' == val:
                                cmp_str_b = "u'%s': False" % key
                            elif '1' == val:
                                cmp_str_b = "u'%s': True" % key
                            else:
                                cmp_str_b = cmp_str
                            if (cmp_str not in str(qmp_o[i]) and
                                    cmp_str_b not in str(qmp_o[i]) and
                                    cmp_s not in str(qmp_o[i])):
                                msg += ("\nCan not find '%s', '%s' or '%s' in "
                                        " QMP command output."
                                        % (cmp_s, cmp_str_b, cmp_str))
                                raise exceptions.TestFail(msg)
                        elif qmp_cmd == "query-balloon":
                            if (int(val) * 1024 * 1024 != qmp_o[key] and
                                    val not in str(qmp_o[key])):
                                msg += ("\n'%s' is not in QMP command output"
                                        % val)
                                raise exceptions.TestFail(msg)
                        else:
                            if (val not in str(qmp_o[i][key]) and
                                    str(bool(int(val))) not in str(qmp_o[i][key])):
                                msg += ("\n'%s' is not in QMP command output"
                                        % val)
                                raise exceptions.TestFail(msg)
        elif result_check == "m_in_q":
            res = output.splitlines(True)
            msg = "Key value from human monitor command is not in"
            msg += "QMP command output.\nQMP command output: '%s'" % qmp_o
            msg += "\nHuman monitor command output '%s'" % output
            for i in range(len(res)):
                params = res[i].rstrip().split()
                for param in params:
                    if param.rstrip() in exception_list:
                        continue
                    try:
                        str_o = str(qmp_o.values())
                    except AttributeError:
                        str_o = qmp_o
                    if param.rstrip() not in str(str_o):
                        msg += "\nKey value is '%s'" % param.rstrip()
                        raise error.TestFail(msg)
        elif result_check == "m_format_q":
            match_flag = True
            for i in qmp_o:
                if output is None:
                    raise exceptions.TestError("QMP output pattern is missing")
                if re.match(output.strip(), str(i)) is None:
                    match_flag = False
            if not match_flag:
                msg = "Output does not match the pattern: '%s'" % output
                raise exceptions.TestFail(msg)

    qemu_binary = utils_misc.get_qemu_binary(params)
    if not utils_misc.qemu_has_option("qmp", qemu_binary):
        raise exceptions.TestSkipError("Host qemu does not support qmp.")

    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()

    session = vm.wait_for_login(timeout=int(params.get("login_timeout", 360)))

    module = params.get("modprobe_module")
    if module:
        logging.info("modprobe the module %s", module)
        session.cmd("modprobe %s" % module)

    qmp_ports = vm.get_monitors_by_type('qmp')
    if qmp_ports:
        qmp_port = qmp_ports[0]
    else:
        raise exceptions.TestError("Incorrect configuration, no QMP monitor found.")
    hmp_ports = vm.get_monitors_by_type('human')
    if hmp_ports:
        hmp_port = hmp_ports[0]
    else:
        raise exceptions.TestError("Incorrect configuration, no QMP monitor found.")
    callback = {"host_cmd": process.system_output,
                "guest_cmd": session.get_command_output,
                "monitor_cmd": hmp_port.send_args_cmd,
                "qmp_cmd": qmp_port.send_args_cmd}

    def send_cmd(cmd):
        """ Helper to execute command on ssh/host/monitor """
        if cmd_type in callback.keys():
            return callback[cmd_type](cmd)
        else:
            raise exceptions.TestError("cmd_type is not supported")

    pre_cmd = params.get("pre_cmd")
    qmp_cmd = params.get("qmp_cmd")
    cmd_type = params.get("event_cmd_type")
    post_cmd = params.get("post_cmd")
    result_check = params.get("cmd_result_check")
    cmd_return_value = params.get("cmd_return_value")
    exception_list = params.get("exception_list", "")

    # Pre command
    if pre_cmd is not None:
        logging.info("Run prepare command '%s'.", pre_cmd)
        pre_o = send_cmd(pre_cmd)
        logging.debug("Pre-command: '%s'\n Output: '%s'", pre_cmd, pre_o)
    try:
        # Testing command
        logging.info("Run qmp command '%s'.", qmp_cmd)
        output = qmp_port.send_args_cmd(qmp_cmd)
        logging.debug("QMP command: '%s' \n Output: '%s'", qmp_cmd, output)
    except qemu_monitor.QMPCmdError, err:
        if params.get("negative_test") == 'yes':
            logging.debug("Negative QMP command: '%s'\n output:'%s'", qmp_cmd,
                          err)
            if params.get("negative_check_pattern"):
                check_pattern = params.get("negative_check_pattern")
                if check_pattern not in str(err):
                    raise exceptions.TestFail("'%s' not in exception '%s'"
                                              % (check_pattern, err))
        else:
            raise exceptions.TestFail(err)
    except qemu_monitor.MonitorProtocolError, err:
        raise exceptions.TestFail(err)
    except Exception, err:
        raise exceptions.TestFail(err)

    # Post command
    if post_cmd is not None:
        logging.info("Run post command '%s'.", post_cmd)
        post_o = send_cmd(post_cmd)
        logging.debug("Post-command: '%s'\n Output: '%s'", post_cmd, post_o)

    if result_check is not None:
        txt = "Verify that qmp command '%s' works as designed." % qmp_cmd
        logging.info(txt)
        if result_check == "equal" or result_check == "contain":
            if qmp_cmd == "query-name":
                vm_name = params["main_vm"]
                check_result(output, vm_name, exception_list)
            elif qmp_cmd == "query-uuid":
                uuid_input = params["uuid"]
                check_result(output, uuid_input, exception_list)
            else:
                check_result(output, cmd_return_value, exception_list)
        elif result_check == "m_format_q":
            check_result(output, cmd_return_value, exception_list)
        elif 'post' in result_check:
            result_check = result_check.split('_', 1)[1]
            check_result(post_o, cmd_return_value, exception_list)
        else:
            check_result(output, post_o, exception_list)
    session.close()
