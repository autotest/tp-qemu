import re

from virttest import env_process, error_context, qemu_qtree, utils_misc


@error_context.context_aware
def run(test, params, env):
    """
    Qemu device options value check test:

    1) Boot up guest with setted option value
    2) Check the value is correct inside guest

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """
    error_context.context("Boot up guest.", test.log.info)
    timeout = float(params.get("login_timeout", 240))
    vm = env.get_vm(params["main_vm"])
    parameter_value = params.get("parameter_value", "random")
    params_name = params["params_name"]
    parameter_prefix = params.get("parameter_prefix", "")
    check_cmds = params["check_cmds"]
    convert_str = params.get("convert_str")
    sg_vpd_cmd = params.get("sg_vpd_cmd")

    if params.get("start_vm") == "no":
        if parameter_value == "random":
            parameter_len = int(params.get("parameter_len", 4))
            random_ignore_str = params.get("ignore_str")
            func_generate_random_string = utils_misc.generate_random_string
            args = (parameter_len,)
            if random_ignore_str:
                args += ("ignore_str=%s" % random_ignore_str,)
            if convert_str:
                args += ("convert_str=%s" % convert_str,)
            parameter_value = func_generate_random_string(*args)

        params[params_name] = parameter_prefix + parameter_value
        test.log.debug("Setup '%s' to '%s'", params_name, params[params_name])

        params["start_vm"] = "yes"
        env_process.preprocess_vm(test, params, env, vm.name)

    if convert_str:
        tmp_str = re.sub(r"\\\\", "Abackslash", parameter_value)
        tmp_str = re.sub(r"\\", "", tmp_str)
        tmp_str = re.sub("Abackslash", r"\\", tmp_str)
        parameter_value_raw = tmp_str
    else:
        parameter_value_raw = parameter_value

    if params.get("check_in_qtree") == "yes":
        error_context.context("Check option in qtree", test.log.info)
        qtree = qemu_qtree.QtreeContainer()
        try:
            qtree.parse_info_qtree(vm.monitor.info("qtree"))
            keyword = params["qtree_check_keyword"]
            qtree_check_value = params["qtree_check_value"]
            qtree_check_option = params["qtree_check_option"]

            for qdev in qtree.get_nodes():
                if keyword not in qdev.qtree:
                    continue
                if qdev.qtree[keyword] != qtree_check_value:
                    continue

                qtree_value = None
                for node in qemu_qtree.traverse(qdev):
                    if qtree_check_option in node.qtree:
                        qtree_value = str(node.qtree.get(qtree_check_option))
                        break

                if qtree_value is not None:
                    break
            else:
                test.fail(
                    "Can not find property '%s' from info qtree where '%s' is "
                    "'%s'" % (qtree_check_option, keyword, qtree_check_value)
                )

            qtree_value = re.findall('"?(.*)"?$', qtree_value)[0]
            if (
                qtree_value != parameter_value_raw
                and parameter_value_raw not in qtree_value
            ):
                test.fail(
                    "Value from info qtree is not match with the value from"
                    "command line: '%s' vs '%s'" % (qtree_value, parameter_value_raw)
                )
        except AttributeError:
            test.log.debug("Monitor deson't support info qtree skip this test")

    session = vm.wait_for_login(timeout=timeout)

    failed_log = ""
    for check_cmd in check_cmds.split():
        check_cmd_params = params.object_params(check_cmd)
        cmd = check_cmd_params["cmd"]
        cmd = utils_misc.set_winutils_letter(session, cmd)
        pattern = check_cmd_params["pattern"] % parameter_value_raw

        error_context.context("Check option with command %s" % cmd, test.log.info)
        _, output = session.cmd_status_output(cmd)
        if not re.findall(r"%s" % pattern, output):
            failed_log += (
                "Can not find option %s from guest."
                " Guest output is '%s'" % (params_name, output)
            )

        if sg_vpd_cmd:
            error_context.context(
                "Check serial number length with command %s" % sg_vpd_cmd, test.log.info
            )
            sg_vpd_cmd = utils_misc.set_winutils_letter(session, sg_vpd_cmd)
            output = session.cmd_output(sg_vpd_cmd)
            actual_len = sum(len(_.split()[-1]) for _ in output.splitlines()[1:3])
            expected_len = len(params.get("drive_serial_image1")) + 4
            if actual_len != expected_len:
                test.fail(
                    "Incorrect serial number length return."
                    " Guest output serial number is %s" % actual_len
                )

    session.close()

    if failed_log:
        test.fail(failed_log)
