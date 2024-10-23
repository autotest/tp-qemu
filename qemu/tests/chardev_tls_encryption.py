import aexpect
from avocado.utils import process
from virttest import env_process, error_context, utils_misc, utils_package

from provider.chardev_utils import setup_certs


@error_context.context_aware
def run(test, params, env):
    """
    Test native TLS encryption on chardev TCP transports
    Scenario 1:
        a. Run gnutls server
        b. Launch QEMU with a serial port as TLS client
        c. Check the server endpoint output
    Scenario 2:
        a. Launch QEMU with a serial port as TLS server
        b. Run gnutls client to connect TLS server
        c. Check the client endpoint output
    Scenario 3:
        a. Launch QEMU with a serial port as TLS server
        b. Execute 'cat /dev/ttyS0' in guest which boot from step 1
        c. Launch QEMU with a serial port as TLS client
        d. Check the output of step b
    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """
    clean_cmd = params["clean_cmd"]
    try:
        pkgs = params.objects("depends_pkgs")
        if not utils_package.package_install(pkgs):
            test.error("Install dependency packages failed")
        setup_certs(params)
        expected_msg = params["expected_msg"]
        hostname = process.run(
            "hostname", ignore_status=False, shell=True, verbose=True
        ).stdout_text.strip()
        port = str(utils_misc.find_free_ports(5000, 9999, 1, hostname)[0])

        # Scenario 1
        gnutls_cmd_server = params.get("gnutls_cmd_server")
        if gnutls_cmd_server:
            gnutls_cmd_server = gnutls_cmd_server % port
            params["extra_params"] = params["extra_params"] % (hostname, port)
            error_context.context("Run gnutls server ...", test.log.info)
            tls_server = aexpect.run_bg(gnutls_cmd_server)
            params["start_vm"] = "yes"
            vm_name = params["main_vm"]
            error_context.context(
                "Launch QEMU with a serial port as TLS client", test.log.info
            )
            env_process.preprocess_vm(test, params, env, vm_name)
            if not utils_misc.wait_for(
                lambda: expected_msg in tls_server.get_output(), first=5, timeout=15
            ):
                test.fail("TLS server can't connect client succssfully.")

        # Scenario 2
        gnutls_cmd_client = params.get("gnutls_cmd_client")
        if gnutls_cmd_client:
            gnutls_cmd_client = gnutls_cmd_client % (port, hostname)
            params["extra_params"] = params["extra_params"] % (hostname, port)
            params["start_vm"] = "yes"
            vm_name = params["main_vm"]
            error_context.context(
                "Launch QEMU with a serial port as TLS server", test.log.info
            )
            env_process.preprocess_vm(test, params, env, vm_name)
            error_context.context(
                "Run gnutls client to connect TLS server", test.log.info
            )
            tls_client = aexpect.run_bg(gnutls_cmd_client)
            if not utils_misc.wait_for(
                lambda: expected_msg in tls_client.get_output(), first=5, timeout=15
            ):
                test.fail("TLS client can't connect server succssfully.")

        # Scenario 3:
        guest_cmd = params.get("guest_cmd")
        if guest_cmd:
            params["start_vm"] = "yes"
            vms = params.get("vms").split()
            params["extra_params"] = params["extra_params_%s" % vms[0]] % (
                hostname,
                port,
            )
            error_context.context(
                "Launch QEMU with a serial port as TLS server", test.log.info
            )
            env_process.preprocess_vm(test, params, env, vms[0])
            vm1 = env.get_vm(vms[0])
            session_vm1 = vm1.wait_for_login()
            session_vm1.cmd(guest_cmd)
            params["extra_params"] = params["extra_params_%s" % vms[1]] % (
                hostname,
                port,
            )
            error_context.context(
                "Launch QEMU with a serial port as TLS client", test.log.info
            )
            env_process.preprocess_vm(test, params, env, vms[1])
            try:
                session_vm1.read_until_output_matches([expected_msg], timeout=15)
            except aexpect.ExpectError:
                test.fail("Can't connect TLS client inside TLS server guest.")
            vm2 = env.get_vm(vms[1])
            session_vm1.close()
            vm1.destroy()
            vm2.destroy()
    finally:
        gnutls_serv_pid = process.getoutput("pgrep -f gnutls-serv", shell=True)
        if gnutls_serv_pid:
            process.run("pkill -9 gnutls-serv")
        gnutls_cli_pid = process.getoutput("pgrep -f gnutls-cli", shell=True)
        if gnutls_cli_pid:
            process.run("pkill -9 gnutls-cli")
        process.run(clean_cmd)
