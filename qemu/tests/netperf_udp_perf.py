import logging
import os
import threading
import time

from avocado.utils import process
from virttest import error_context, remote, virt_vm

from provider import netperf_base

LOG_JOB = logging.getLogger("avocado.test")


@error_context.context_aware
def run(test, params, env):
    """
    Netperf UDP_STREAM test with netperf.

    1) Boot up VM
    2) Prepare the test environment in server/client/host
    3) Run netserver on guest, run netperf client on remote host
    4) Collect results

    :param test: QEMU test object.
    :param params: Dictionary with the test parameters.
    :param env: Dictionary with test environment.
    """

    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    login_timeout = int(params.get("login_timeout", 360))

    try:
        vm.wait_for_serial_login(timeout=login_timeout, restart_network=True).close()
    except virt_vm.VMIPAddressMissingError:
        pass

    vm.get_mac_address(0)
    server_ip = vm.wait_for_get_address(0, timeout=90)

    if len(params.get("nics", "").split()) > 1:
        server_ctl = vm.wait_for_login(nic_index=1, timeout=login_timeout)
        server_ctl_ip = vm.wait_for_get_address(1, timeout=90)
    else:
        server_ctl = vm.wait_for_login(timeout=login_timeout)
        server_ctl_ip = server_ip

    test.log.debug(
        process.system_output(
            "numactl --hardware", verbose=False, ignore_status=True, shell=True
        ).decode()
    )
    test.log.debug(
        process.system_output(
            "numactl --show", verbose=False, ignore_status=True, shell=True
        ).decode()
    )
    # pin guest vcpus/memory/vhost threads to last numa node of host by default
    netperf_base.pin_vm_threads(vm, params.get("numa_node"))
    host = params.get("host", "localhost")
    host_ip = host
    client = params.get("client", "localhost")
    client_ip = client
    client_pub_ip = params.get("client_public_ip")
    client = remote.wait_for_login(
        params["shell_client_client"],
        client_pub_ip,
        params["shell_port_client"],
        params["username_client"],
        params["password_client"],
        params["shell_prompt_client"],
    )
    cmd = "ifconfig %s %s up" % (params.get("client_physical_nic"), client_ip)
    netperf_base.ssh_cmd(client, cmd)

    error_context.context("Prepare env of server/client/host", test.log.info)
    prepare_list = set([server_ctl, client, host])
    tag_dict = {server_ctl: "server", client: "client", host: "host"}
    ip_dict = {server_ctl: server_ctl_ip, client: client_pub_ip, host: host_ip}
    for i in prepare_list:
        params_tmp = params.object_params(tag_dict[i])
        netperf_base.env_setup(
            test,
            params,
            i,
            ip_dict[i],
            username=params_tmp["username"],
            shell_port=int(params_tmp["shell_port"]),
            password=params_tmp["password"],
        )

    netperf_base.tweak_tuned_profile(params, server_ctl, client, host)

    env.stop_ip_sniffing()

    try:
        error_context.context("Start netperf udp stream testing", test.log.info)
        start_test(
            server_ip,
            server_ctl,
            host,
            client,
            test.resultsdir,
            test_duration=int(params.get("test_duration")),
            burst_time=params.get("burst_time"),
            numbers_per_burst=params.get("numbers_per_burst"),
            params=params,
            test=test,
        )

        if params.get("log_hostinfo_script"):
            src = os.path.join(test.virtdir, params.get("log_hostinfo_script"))
            path = os.path.join(test.resultsdir, "systeminfo")
            process.system_output(
                "bash %s %s &> %s" % (src, test.resultsdir, path), shell=True
            )

        if params.get("log_guestinfo_script") and params.get("log_guestinfo_exec"):
            src = os.path.join(test.virtdir, params.get("log_guestinfo_script"))
            path = os.path.join(test.resultsdir, "systeminfo")
            destpath = params.get("log_guestinfo_path", "/tmp/log_guestinfo.sh")
            vm.copy_files_to(src, destpath)
            logexec = params.get("log_guestinfo_exec", "bash")
            output = server_ctl.cmd_output("%s %s" % (logexec, destpath))
            logfile = open(path, "a+")
            logfile.write(output)
            logfile.close()
    except process.CmdError:
        test.cancel("test faild")


@error_context.context_aware
def start_test(
    server,
    server_ctl,
    host,
    client,
    resultsdir,
    test_duration="20",
    burst_time="1",
    numbers_per_burst="1000 1500 2000 2500 3000",
    params=None,
    test=None,
):
    """
    Start to test with different combination of burst_time and numbers_per_burst

    """
    if params is None:
        params = {}

    fd = open("%s/netperf-udp-perf.result.%s.RHS" % (resultsdir, time.time()), "w")
    netperf_base.record_env_version(test, params, host, server_ctl, fd, test_duration)

    error_context.context("Start Netserver on guest", LOG_JOB.info)
    netperf_version = params.get("netperf_version", "2.6.0")
    client_path = "/tmp/netperf-%s/src/netperf" % netperf_version
    server_path = "/tmp/netperf-%s/src/netserver" % netperf_version
    LOG_JOB.info("Netserver start cmd is '%s'", server_path)
    netperf_base.ssh_cmd(server_ctl, "pidof netserver || %s" % server_path)

    base = params.get("format_base", "18")
    fbase = params.get("format_fbase", "2")
    pid = str(os.getpid())
    fname = "/tmp/netperf.%s.nf" % pid
    numa_enable = params.get("netperf_with_numa", "yes") == "yes"

    def thread_cmd(
        params,
        numa_enable,
        burst_time,
        numbers_per_burst,
        client,
        server,
        test_duration,
        fname,
    ):
        option = "%s -t UDP_STREAM -w %s -b %s -H %s -l %s" % (
            client_path,
            burst_time,
            numbers_per_burst,
            server,
            test_duration,
        )
        netperf_base.netperf_thread(params, numa_enable, client, option, fname)

    def thu_result(fname):
        with open(fname, "rt") as filehandle:
            file = filehandle.readlines()[5:]
        results = []
        for thu in file:
            thu_tmp = thu.rstrip("\n").split(" ")
            thu_result = thu_tmp[-1]
            results.append(thu_result)
        return results

    record_header = True
    record_list = [
        "burst_time",
        "numbers_per_burst",
        "send_throughput",
        "receive_throughput",
        "drop_ratio",
    ]

    for i in burst_time.split():
        for j in numbers_per_burst.split():
            client_thread = threading.Thread(
                target=thread_cmd,
                args=(params, numa_enable, i, j, client, server, test_duration, fname),
            )
            client_thread.start()
            time.sleep(test_duration + 1)
            client_thread.join()

            ret = {}
            ret["burst_time"] = int(i)
            ret["numbers_per_burst"] = int(j)

            finished_result = netperf_base.ssh_cmd(client, "cat %s" % fname)
            f = open(fname, "w")
            f.write(finished_result)
            f.close()
            thu_all = thu_result(fname)
            ret["send_throughput"] = float(thu_all[0])
            ret["receive_throughput"] = float(thu_all[1])
            ret["drop_ratio"] = float(
                ret["receive_throughput"] / ret["send_throughput"]
            )

            row, key_list = netperf_base.netperf_record(
                ret, record_list, header=record_header, base=base, fbase=fbase
            )
            if record_header:
                record_header = False
            prefix = "%s--%s" % (i, j)
            for key in key_list:
                test.write_test_keyval({"%s--%s" % (prefix, key): ret[key]})

            LOG_JOB.info(row)
            fd.write(row + "\n")
            fd.flush()
            LOG_JOB.debug("Remove temporary files")
            process.system_output(
                "rm -f %s" % fname, verbose=False, ignore_status=True, shell=True
            )
            netperf_base.ssh_cmd(client, "rm -f %s" % fname)

    fd.close()
