import logging
import os

import six
from avocado.utils import process
from virttest import data_dir, error_context, remote, utils_misc, utils_test

LOG_JOB = logging.getLogger("avocado.test")


def pin_vm_threads(vm, node):
    """
    pin vm threads to assigned node

    """
    if node:
        if not isinstance(node, utils_misc.NumaNode):
            node = utils_misc.NumaNode(int(node))
        utils_test.qemu.pin_vm_threads(vm, node)

    return node


@error_context.context_aware
def record_env_version(test, params, host, server_ctl, fd, test_duration):
    """
    Get host kernel/qemu/guest kernel version

    """
    ver_cmd = params.get("ver_cmd", "rpm -q qemu-kvm")
    guest_ver_cmd = params.get("guest_ver_cmd", "uname -r")

    test.write_test_keyval({"kvm-userspace-ver": ssh_cmd(host, ver_cmd).strip()})
    test.write_test_keyval(
        {"guest-kernel-ver": ssh_cmd(server_ctl, guest_ver_cmd).strip()}
    )
    test.write_test_keyval({"session-length": test_duration})
    fd.write("### kvm-userspace-ver : %s\n" % ssh_cmd(host, ver_cmd).strip())
    fd.write("### guest-kernel-ver : %s\n" % ssh_cmd(server_ctl, guest_ver_cmd).strip())
    fd.write("### kvm_version : %s\n" % os.uname()[2])
    fd.write("### session-length : %s\n" % test_duration)


def env_setup(test, params, session, ip, username, shell_port, password):
    """
    Prepare the test environment in server/client/host

    """
    error_context.context("Setup env for %s" % ip)
    if params.get("env_setup_cmd"):
        ssh_cmd(session, params.get("env_setup_cmd"), ignore_status=True)

    pkg = params["netperf_pkg"]
    pkg = os.path.join(data_dir.get_deps_dir(), pkg)
    remote.scp_to_remote(ip, shell_port, username, password, pkg, "/tmp")
    ssh_cmd(session, params.get("setup_cmd"))

    agent_path = os.path.join(test.virtdir, "scripts/netperf_agent.py")
    remote.scp_to_remote(ip, shell_port, username, password, agent_path, "/tmp")


def tweak_tuned_profile(params, server_ctl, client, host):
    """

    Tweak configuration with truned profile

    """

    client_tuned_profile = params.get("client_tuned_profile")
    server_tuned_profile = params.get("server_tuned_profile")
    host_tuned_profile = params.get("host_tuned_profile")
    error_context.context("Changing tune profile of guest", LOG_JOB.info)
    if server_tuned_profile:
        ssh_cmd(server_ctl, server_tuned_profile)

    error_context.context("Changing tune profile of client/host", LOG_JOB.info)
    if client_tuned_profile:
        ssh_cmd(client, client_tuned_profile)
    if host_tuned_profile:
        ssh_cmd(host, host_tuned_profile)


def ssh_cmd(session, cmd, timeout=120, ignore_status=False):
    """
    Execute remote command and return the output

    :param session: a remote shell session or tag for localhost
    :param cmd: executed command
    :param timeout: timeout for the command
    """
    if session == "localhost":
        o = process.system_output(
            cmd, timeout=timeout, ignore_status=ignore_status, shell=True
        ).decode()
    else:
        o = session.cmd(cmd, timeout=timeout, ignore_all_errors=ignore_status)
    return o


def netperf_thread(params, numa_enable, client_s, option, fname):
    """
    Start netperf thread on client

    """
    cmd = ""
    if numa_enable:
        n = abs(int(params.get("numa_node"))) - 1
        cmd += "numactl --cpunodebind=%s --membind=%s " % (n, n)
    cmd += option
    cmd += " >> %s" % fname
    LOG_JOB.info("Start netperf thread by cmd '%s'", cmd)
    ssh_cmd(client_s, cmd)


def format_result(result, base="17", fbase="2"):
    """
    Format the result to a fixed length string.

    :param result: result need to convert
    :param base: the length of converted string
    :param fbase: the decimal digit for float
    """
    if isinstance(result, six.string_types):
        value = "%" + base + "s"
    elif isinstance(result, int):
        value = "%" + base + "d"
    elif isinstance(result, float):
        value = "%" + base + "." + fbase + "f"
    else:
        raise TypeError(f"unexpected result type: {type(result).__name__}")
    return value % result


def netperf_record(results, filter_list, header=False, base="17", fbase="2"):
    """
    Record the results in a certain format.

    :param results: a dict include the results for the variables
    :param filter_list: variable list which is wanted to be shown in the
                        record file, /also fix the order of variables
    :param header: if record the variables as a column name before the results
    :param base: the length of a variable
    :param fbase: the decimal digit for float
    """
    key_list = []
    for key in filter_list:
        if key in results:
            key_list.append(key)

    record = ""
    if header:
        for key in key_list:
            record += "%s|" % format_result(key, base=base, fbase=fbase)
        record = record.rstrip("|")
        record += "\n"
    for key in key_list:
        record += "%s|" % format_result(results[key], base=base, fbase=fbase)
    record = record.rstrip("|")
    return record, key_list
