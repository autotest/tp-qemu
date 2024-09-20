import os
import socket
import time

from avocado.utils import cpu, process
from virttest import data_dir


def run(test, params, env):
    """
    soft lockup/drift test with stress.

    1) Boot up a VM.
    2) Build stress on host and guest.
    3) run heartbeat with the given options on server and host.
    3) Run for a relatively long time length. ex: 12, 18 or 24 hours.
    4) Output the test result and observe drift.

    :param test: QEMU test object.
    :param params: Dictionary with the test parameters.
    :param env: Dictionary with test environment.
    """
    stress_setup_cmd = params.get("stress_setup_cmd", None)
    stress_cmd = params.get("stress_cmd")
    server_setup_cmd = params.get("server_setup_cmd")
    drift_cmd = params.get("drift_cmd")
    kill_stress_cmd = params.get("kill_stress_cmd")
    kill_monitor_cmd = params.get("kill_monitor_cmd")

    threshold = int(params.get("stress_threshold"))
    monitor_log_file_server = params.get("monitor_log_file_server")
    monitor_log_file_client = params.get("monitor_log_file_client")
    test_length = int(3600 * float(params.get("test_length")))
    monitor_port = int(params.get("monitor_port"))

    vm = env.get_vm(params["main_vm"])
    login_timeout = int(params.get("login_timeout", 360))
    stress_dir = data_dir.get_deps_dir("stress")
    monitor_dir = params.get("monitor_dir", data_dir.get_deps_dir("softlockup"))

    def _kill_guest_programs(session, kill_stress_cmd, kill_monitor_cmd):
        test.log.info("Kill stress and monitor on guest")
        try:
            session.cmd(kill_stress_cmd)
        except Exception:
            pass
        try:
            session.cmd(kill_monitor_cmd)
        except Exception:
            pass

    def _kill_host_programs(kill_stress_cmd, kill_monitor_cmd):
        test.log.info("Kill stress and monitor on host")
        process.run(kill_stress_cmd, ignore_status=True, shell=True)
        process.run(kill_monitor_cmd, ignore_status=True, shell=True)

    def host():
        test.log.info("Setup monitor server on host")
        # Kill previous instances of the host load programs, if any
        _kill_host_programs(kill_stress_cmd, kill_monitor_cmd)
        # Cleanup previous log instances
        if os.path.isfile(monitor_log_file_server):
            os.remove(monitor_log_file_server)
        # Opening firewall ports on host
        process.run("iptables -F", ignore_status=True)

        # Run heartbeat on host
        process.run(
            server_setup_cmd
            % (monitor_dir, threshold, monitor_log_file_server, monitor_port),
            shell=True,
        )

        if stress_setup_cmd is not None:
            test.log.info("Build stress on host")
            # Uncompress and build stress on host
            process.run(stress_setup_cmd % stress_dir, shell=True)

        test.log.info("Run stress on host")
        # stress_threads = 2 * n_cpus
        threads_host = 2 * cpu.online_count()
        # Run stress test on host
        process.run(
            stress_cmd % (stress_dir, threads_host),
            ignore_bg_processes=True,
            shell=True,
        )

    def guest():
        try:
            host_ip = socket.gethostbyname(socket.gethostname())
        except socket.error:
            try:
                # Hackish, but works well on stand alone (laptop) setups
                # with access to the internet. If this fails, well, then
                # not much else can be done...
                s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                s.connect(("redhat.com", 80))
                host_ip = s.getsockname()[0]
            except socket.error as e:
                test.error("Could not determine host IP: %s" % e)

        # Now, starting the guest
        vm.verify_alive()
        session = vm.wait_for_login(timeout=login_timeout)

        # Kill previous instances of the load programs, if any
        _kill_guest_programs(session, kill_stress_cmd, kill_monitor_cmd)
        # Clean up previous log instances
        session.cmd("rm -f %s" % monitor_log_file_client)

        # Opening firewall ports on guest
        try:
            session.cmd("iptables -F")
        except Exception:
            pass

        # Get monitor files and copy them from host to guest
        monitor_path = os.path.join(
            data_dir.get_deps_dir(), "softlockup", "heartbeat_slu.py"
        )
        vm.copy_files_to(monitor_path, "/tmp")

        test.log.info("Setup monitor client on guest")
        # Start heartbeat on guest
        session.cmd(
            params.get("client_setup_cmd")
            % ("/tmp", host_ip, monitor_log_file_client, monitor_port)
        )

        if stress_setup_cmd is not None:
            # Copy, uncompress and build stress on guest
            stress_source = params.get("stress_source")
            stress_path = os.path.join(stress_dir, stress_source)
            vm.copy_files_to(stress_path, "/tmp")
            test.log.info("Build stress on guest")
            session.cmd(stress_setup_cmd % "/tmp", timeout=200)

        test.log.info("Run stress on guest")
        # stress_threads = 2 * n_vcpus
        threads_guest = 2 * int(params.get("smp", 1))
        # Run stress test on guest
        session.cmd(stress_cmd % ("/tmp", threads_guest))

        # Wait and report
        test.log.debug("Wait for %d s", test_length)
        time.sleep(test_length)

        # Kill instances of the load programs on both guest and host
        _kill_guest_programs(session, kill_stress_cmd, kill_monitor_cmd)
        _kill_host_programs(kill_stress_cmd, kill_monitor_cmd)

        # Collect drift
        drift = process.system_output(drift_cmd % monitor_log_file_server, shell=True)
        test.log.info("Drift noticed: %s", drift)

    host()
    guest()
