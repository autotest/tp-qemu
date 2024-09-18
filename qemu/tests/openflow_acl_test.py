import functools
import os
import re

import aexpect
from avocado.utils import process
from virttest import data_dir, error_context, remote, utils_net

_system_statusoutput = functools.partial(
    process.getstatusoutput, shell=True, ignore_status=False
)


@error_context.context_aware
def run(test, params, env):
    """
    Test Step:
        1. Boot up guest using the openvswitch bridge
        2. Setup related service in test enviroment(http, ftp etc.)(optional)
        3. Access the service in guest
        4. Setup access control rules in ovs to disable the access
        5. Access the service in guest
        6. Setup access control rules in ovs to enable the access
        7. Access the service in guest
        8. Delete the access control rules in ovs
        9. Access the service in guest

    Params:
        :param test: QEMU test object
        :param params: Dictionary with the test parameters
        :param env: Dictionary with test environment.
    """

    def access_service(access_sys, access_targets, disabled, host_ip, ref=False):
        err_msg = ""
        err_type = ""
        for asys in access_sys:
            for atgt in access_targets:
                test.log.debug("Try to access target %s from %s", atgt, asys)

                access_params = access_sys[asys]
                atgt_disabled = access_params["disabled_%s" % atgt]
                if asys in vms_tags:
                    vm = env.get_vm(asys)
                    session = vm.wait_for_login(timeout=timeout)
                    run_func = session.cmd_status_output
                    remote_src = vm
                    ssh_src_ip = vm.get_address()
                else:
                    run_func = _system_statusoutput
                    remote_src = "localhost"
                    ssh_src_ip = host_ip
                if atgt in vms_tags:
                    vm = env.get_vm(atgt)
                    access_re_sub_string = vm.wait_for_get_address(0)
                else:
                    access_re_sub_string = host_ip

                access_cmd = re.sub(
                    "ACCESS_TARGET", access_re_sub_string, access_params["access_cmd"]
                )
                ref_cmd = re.sub(
                    "ACCESS_TARGET", access_re_sub_string, access_params["ref_cmd"]
                )

                if access_cmd in ["ssh", "telnet"]:
                    if atgt in vms_tags:
                        target_vm = env.get_vm(atgt)
                        target_ip = target_vm.get_address()
                    else:
                        target_vm = "localhost"
                        target_ip = host_ip
                    out = ""
                    out_err = ""
                    try:
                        out = remote_login(
                            access_cmd, target_ip, remote_src, params, host_ip
                        )
                        stat = 0
                    except remote.LoginError as err:
                        stat = 1
                        out_err = "Failed to login %s " % atgt
                        out_err += "from %s, err: %s" % (asys, err.output)
                    if "TelnetServer" in params.get("setup_cmd_windows", ""):
                        try:
                            out += remote_login(
                                access_cmd, ssh_src_ip, target_vm, params, host_ip
                            )
                        except remote.LoginError as err:
                            stat += 1
                            out_err += "Failed to login %s " % asys
                            out_err += "from %s, err: %s" % (atgt, err.output)
                    if out_err:
                        out = out_err
                else:
                    try:
                        stat, out = run_func(access_cmd, timeout=op_timeout)
                        check_string = access_params.get("check_from_output")
                        if check_string and check_string in out:
                            stat = 1
                    except aexpect.ShellTimeoutError as err:
                        out = err.output
                        stat = 1
                    except process.CmdError as err:
                        out = err.result.stderr
                        stat = err.result.exit_status

                    if access_params.get("clean_cmd"):
                        try:
                            run_func(access_params["clean_cmd"])
                        except Exception:
                            pass

                if disabled and atgt_disabled and stat == 0:
                    err_msg += "Still can access %s after" % atgt
                    err_msg += " disable it from ovs. "
                    err_msg += "Command: %s " % access_cmd
                    err_msg += "Output: %s" % out
                if disabled and atgt_disabled and stat != 0:
                    test.log.debug("Can not access target as expect.")
                if not disabled and stat != 0:
                    if ref:
                        err_msg += "Can not access %s at the" % atgt
                        err_msg += " beginning. Please check your setup."
                        err_type = "ref"
                    else:
                        err_msg += "Still can not access %s" % atgt
                        err_msg += " after enable the access. "
                    err_msg += "Command: %s " % access_cmd
                    err_msg += "Output: %s" % out
                if err_msg:
                    if err_type == "ref":
                        test.cancel(err_msg)
                    test.fail(err_msg)

                if not ref_cmd:
                    return

                try:
                    stat, out = run_func(ref_cmd, timeout=op_timeout)
                except aexpect.ShellTimeoutError as err:
                    out = err.output
                    stat = 1
                except process.CmdError as err:
                    out = err.result.stderr
                    stat = err.result.exit_status

                if stat != 0:
                    if ref:
                        err_msg += "Reference command failed at beginning."
                        err_type = "ref"
                    else:
                        err_msg += "Reference command failed after setup"
                        err_msg += " the rules. "
                    err_msg += "Command: %s " % ref_cmd
                    err_msg += "Output: %s" % out
                if err_msg:
                    if err_type == "ref":
                        test.cancel(err_msg)
                    test.fail(err_msg)

    def get_acl_cmd(protocol, in_port, action, extra_options):
        acl_cmd = protocol.strip()
        acl_cmd += ",in_port=%s" % in_port.strip()
        if extra_options.strip():
            acl_cmd += ",%s" % ",".join(extra_options.strip().split())
        if action.strip():
            acl_cmd += ",action=%s" % action.strip()
        return acl_cmd

    def acl_rules_check(acl_rules, acl_setup_cmd):
        acl_setup_cmd = re.sub("action=", "actions=", acl_setup_cmd)
        acl_option = re.split(",", acl_setup_cmd)
        for line in acl_rules.splitlines():
            rule = [_.lower() for _ in re.split("[ ,]", line) if _]
            item_in_rule = 0

            for acl_item in acl_option:
                if acl_item.lower() in rule:
                    item_in_rule += 1

            if item_in_rule == len(acl_option):
                return True
        return False

    def remote_login(client, host, src, params_login, host_ip):
        src_name = src
        if src != "localhost":
            src_name = src.name
        test.log.info("Login %s from %s", host, src_name)
        port = params_login["target_port"]
        username = params_login["username"]
        password = params_login["password"]
        prompt = params_login["shell_prompt"]
        linesep = eval("'%s'" % params_login.get("shell_linesep", r"\n"))
        quit_cmd = params.get("quit_cmd", "exit")
        if host == host_ip:
            # Try to login from guest to host.
            prompt = r"^\[.*\][\#\$]\s*$"
            linesep = "\n"
            username = params_login["host_username"]
            password = params_login["host_password"]
            quit_cmd = "exit"

        if client == "ssh":
            # We only support ssh for Linux in this test
            cmd = (
                "ssh -o UserKnownHostsFile=/dev/null "
                "-o StrictHostKeyChecking=no "
                "-o PreferredAuthentications=password -p %s %s@%s"
                % (port, username, host)
            )
        elif client == "telnet":
            cmd = "telnet -l %s %s %s" % (username, host, port)
        else:
            raise remote.LoginBadClientError(client)

        if src == "localhost":
            test.log.debug("Login with command %s", cmd)
            session = aexpect.ShellSession(cmd, linesep=linesep, prompt=prompt)
        else:
            if params_login.get("os_type") == "windows":
                if client == "telnet":
                    cmd = "C:\\telnet.py %s %s " % (host, username)
                    cmd += '%s "%s" && ' % (password, prompt)
                    cmd += "C:\\wait_for_quit.py"
                cmd = "%s || ping 127.0.0.1 -n 5 -w 1000 > nul" % cmd
            else:
                cmd += " || sleep 5"
            session = src.wait_for_login()
            test.log.debug("Sending login command: %s", cmd)
            session.sendline(cmd)
        try:
            out = remote.handle_prompts(
                session, username, password, prompt, timeout, debug=True
            )
        except Exception as err:
            session.close()
            raise err
        try:
            session.cmd(quit_cmd)
            session.close()
        except Exception:
            pass
        return out

    def setup_service(setup_target):
        setup_timeout = int(params.get("setup_timeout", 360))
        if setup_target == "localhost":
            setup_func = _system_statusoutput
            os_type = "linux"
        else:
            setup_vm = env.get_vm(setup_target)
            setup_session = setup_vm.wait_for_login(timeout=timeout)
            setup_func = setup_session.cmd
            os_type = params["os_type"]

        setup_params = params.object_params(os_type)
        setup_cmd = setup_params.get("setup_cmd", "service SERVICE restart")
        prepare_cmd = setup_params.get("prepare_cmd")
        setup_cmd = re.sub("SERVICE", setup_params.get("service", ""), setup_cmd)

        error_context.context(
            "Set up %s service in %s" % (setup_params.get("service"), setup_target),
            test.log.info,
        )
        if params.get("copy_ftp_site") and setup_target != "localhost":
            ftp_site = os.path.join(
                data_dir.get_deps_dir(), params.get("copy_ftp_site")
            )
            ftp_dir = params.get("ftp_dir")
            setup_vm.copy_files_to(ftp_site, ftp_dir)
        access_param = setup_params.object_params(setup_target)
        if "ftp" in access_param.get("access_cmd") and os_type == "linux":
            setup_func(
                "sed -i 's/anonymous_enable=NO/anonymous_enable=YES/g' %s"
                % params["vsftpd_conf"]
            )
        if prepare_cmd:
            setup_func(prepare_cmd, timeout=setup_timeout)
        setup_func(setup_cmd, timeout=setup_timeout)
        if setup_target != "localhost":
            setup_session.close()

    def stop_service(setup_target):
        setup_timeout = int(params.get("setup_timeout", 360))
        if setup_target == "localhost":
            setup_func = _system_statusoutput
            os_type = "linux"
        else:
            setup_vm = env.get_vm(setup_target)
            setup_session = setup_vm.wait_for_login(timeout=timeout)
            setup_func = setup_session.cmd
            os_type = params["os_type"]

        setup_params = params.object_params(os_type)
        stop_cmd = setup_params.get("stop_cmd", "service SERVICE stop")
        cleanup_cmd = setup_params.get("cleanup_cmd")
        stop_cmd = re.sub("SERVICE", setup_params.get("service", ""), stop_cmd)

        error_context.context(
            "Stop %s service in %s" % (setup_params.get("service"), setup_target),
            test.log.info,
        )
        if stop_cmd:
            setup_func(stop_cmd, timeout=setup_timeout)

        if cleanup_cmd:
            setup_func(cleanup_cmd, timeout=setup_timeout)

        if setup_target != "localhost":
            setup_session.close()

    timeout = int(params.get("login_timeout", "360"))
    op_timeout = int(params.get("op_timeout", "360"))
    acl_protocol = params["acl_protocol"]
    acl_extra_options = params.get("acl_extra_options", "")

    for vm in env.get_all_vms():
        session = vm.wait_for_login(timeout=timeout)
        if params.get("disable_iptables") == "yes":
            session.cmd_output("systemctl stop firewalld||service firewalld stop")
        if params.get("copy_scripts"):
            root_dir = data_dir.get_root_dir()
            script_dir = os.path.join(root_dir, "shared", "scripts")
            tmp_dir = params.get("tmp_dir", "C:\\")
            for script in params.get("copy_scripts").split():
                script_path = os.path.join(script_dir, script)
                vm.copy_files_to(script_path, tmp_dir)
        if params.get("copy_curl") and params.get("os_type") == "windows":
            curl_win_path = params.get("curl_win_path", "C:\\curl\\")
            session.cmd("dir {0} || mkdir {0}".format(curl_win_path))
            for script in params.get("copy_curl").split():
                curl_win_link = os.path.join(data_dir.get_deps_dir("curl"), script)
                vm.copy_files_to(curl_win_link, curl_win_path, timeout=60)
        session.close()

    vms_tags = params.objects("vms")
    br_name = params.get("netdst")
    if br_name == "private":
        br_name = params.get("priv_brname", "atbr0")

    for setup_target in params.get("setup_targets", "").split():
        setup_service(setup_target)

    access_targets = params.get("access_targets", "localhost").split()
    deny_target = params.get("deny_target", "localhost")
    all_target = params.get("extra_target", "").split() + vms_tags
    target_port = params["target_port"]
    vm = env.get_vm(vms_tags[0])
    nic = vm.virtnet[0]
    if_name = nic.ifname
    params_nic = params.object_params("nic1")
    if params["netdst"] == "private":
        params_nic["netdst"] = params_nic.get("priv_brname", "atbr0")
    host_ip = utils_net.get_host_ip_address(params_nic)
    if deny_target in vms_tags:
        deny_vm = env.get_vm(deny_target)
        deny_vm_ip = deny_vm.wait_for_get_address(0)
    elif deny_target == "localhost":
        deny_vm_ip = host_ip
    if "NW_DST" in acl_extra_options:
        acl_extra_options = re.sub("NW_DST", deny_vm_ip, acl_extra_options)  # pylint: disable=E0606
    acl_extra_options = re.sub("TARGET_PORT", target_port, acl_extra_options)

    access_sys = {}
    for target in all_target:
        if target not in access_targets:
            if target in vms_tags:
                os_type = params["os_type"]
            else:
                os_type = "linux"
            os_params = params.object_params(os_type)
            access_param = os_params.object_params(target)
            check_from_output = access_param.get("check_from_output")

            access_sys[target] = {}
            access_sys[target]["access_cmd"] = access_param["access_cmd"]
            access_sys[target]["ref_cmd"] = access_param.get("ref_cmd", "")
            access_sys[target]["clean_cmd"] = access_param.get("clean_guest", "")
            if check_from_output:
                access_sys[target]["check_from_output"] = check_from_output
            for tgt in access_targets:
                tgt_param = access_param.object_params(tgt)
                acl_disabled = tgt_param.get("acl_disabled") == "yes"
                access_sys[target]["disabled_%s" % tgt] = acl_disabled

    error_context.context("Try to access target before setup the rules", test.log.info)
    access_service(access_sys, access_targets, False, host_ip, ref=True)
    error_context.context("Disable the access in ovs", test.log.info)
    br_infos = utils_net.openflow_manager(br_name, "show").stdout.decode()
    if_port = re.findall(r"(\d+)\(%s\)" % if_name, br_infos)
    if not if_port:
        test.cancel("Can not find %s in bridge %s" % (if_name, br_name))
    if_port = if_port[0]

    acl_cmd = get_acl_cmd(acl_protocol, if_port, "drop", acl_extra_options)
    utils_net.openflow_manager(br_name, "add-flow", acl_cmd)
    acl_rules = utils_net.openflow_manager(br_name, "dump-flows").stdout.decode()
    if not acl_rules_check(acl_rules, acl_cmd):
        test.fail("Can not find the rules from ovs-ofctl: %s" % acl_rules)

    error_context.context(
        "Try to acess target to exam the disable rules", test.log.info
    )
    access_service(access_sys, access_targets, True, host_ip)
    error_context.context("Enable the access in ovs", test.log.info)
    acl_cmd = get_acl_cmd(acl_protocol, if_port, "normal", acl_extra_options)
    utils_net.openflow_manager(br_name, "mod-flows", acl_cmd)
    acl_rules = utils_net.openflow_manager(br_name, "dump-flows").stdout.decode()
    if not acl_rules_check(acl_rules, acl_cmd):
        test.fail("Can not find the rules from ovs-ofctl: %s" % acl_rules)

    error_context.context("Try to acess target to exam the enable rules", test.log.info)
    access_service(access_sys, access_targets, False, host_ip)
    error_context.context("Delete the access rules in ovs", test.log.info)
    acl_cmd = get_acl_cmd(acl_protocol, if_port, "", acl_extra_options)
    utils_net.openflow_manager(br_name, "del-flows", acl_cmd)
    acl_rules = utils_net.openflow_manager(br_name, "dump-flows").stdout.decode()
    if acl_rules_check(acl_rules, acl_cmd):
        test.fail("Still can find the rules from ovs-ofctl: %s" % acl_rules)
    error_context.context(
        "Try to acess target to exam after delete the rules", test.log.info
    )
    access_service(access_sys, access_targets, False, host_ip)

    for setup_target in params.get("setup_targets", "").split():
        stop_service(setup_target)
