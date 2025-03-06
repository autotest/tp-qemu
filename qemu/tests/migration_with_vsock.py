import ast
import random

from avocado.utils import path, process
from virttest import error_context, utils_misc

from qemu.tests.vsock_test import (
    check_received_data,
    compile_nc_vsock,
    send_data_from_guest_to_host,
    vsock_connect,
    vsock_listen,
)


@error_context.context_aware
def run(test, params, env):
    """
    Vsock migration test

    1. Boot guest with vhost-vsock-pci device
    2. Download and compile nc-vsock on both guest and host if needed
    3. Start listening inside guest
    4. Connect guest CID from host
    5. Input character, e.g. 'Hello world'
    6. Check if guest receive the content correctly
    7. Reboot guest with differnt guest CID
    8. Migration
    9. Check guest session exited and close host session
    10. repeat step 3 to 6
    11. Send data from guest
    12. Receive data from host
    13. Do ping-pong migration 3 times

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment
    """

    def ping_pong_migration(repeat_times):
        """Do ping pong migration."""
        mig_timeout = float(params.get("mig_timeout", "3600"))
        mig_protocol = params.get("migration_protocol", "tcp")
        mig_cancel_delay = int(params.get("mig_cancel") == "yes") * 2
        inner_funcs = ast.literal_eval(params.get("migrate_inner_funcs", "[]"))
        capabilities = ast.literal_eval(params.get("migrate_capabilities", "{}"))
        for i in range(repeat_times):
            if i % 2 == 0:
                test.log.info("Round %s ping...", str(i / 2))
            else:
                test.log.info("Round %s pong...", str(i / 2))
            vm.migrate(
                mig_timeout,
                mig_protocol,
                mig_cancel_delay,
                migrate_capabilities=capabilities,
                mig_inner_funcs=inner_funcs,
                env=env,
            )

    def input_character_vsock():
        host_vsock_session = None
        if vsock_test_tool == "ncat":
            vsock_listen(tool_bin, port, session)
            host_vsock_session = vsock_connect(tool_bin, guest_cid, port)
        send_data = "Hello world"
        if vsock_test_tool == "nc_vsock":
            vsock_listen(tool_bin, port, session)
            host_vsock_session = vsock_connect(tool_bin, guest_cid, port)
            connected_str = r"Connection from cid*"
            check_received_data(test, session, connected_str)
        if host_vsock_session is None:
            raise ValueError(f"unexpected test tool: {vsock_test_tool}")
        error_context.context('Input "Hello world" to vsock.', test.log.info)
        host_vsock_session.sendline(send_data)
        check_received_data(test, session, send_data)
        return host_vsock_session

    vsock_test_tool = params["vsock_test_tool"]
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    session = vm.wait_for_login()
    if vsock_test_tool == "nc_vsock":
        tool_bin = compile_nc_vsock(test, vm, session)
    if vsock_test_tool == "ncat":
        tool_bin = path.find_command("ncat")
    vsock_dev = params["vsocks"].split()[0]
    guest_cid = vm.devices.get(vsock_dev).get_param("guest-cid")
    port = random.randrange(1, 6000)
    host_vsock_session = input_character_vsock()
    guest_cid = int(vm.devices.get(vsock_dev).get_param("guest-cid")) + 1
    vm.devices.get(vsock_dev).set_param("guest-cid", guest_cid)
    session.close()
    # reboot with different guest-cid
    vm.reboot()
    # do migration
    ping_pong_migration(1)
    session = vm.wait_for_login(timeout=360)
    if session.cmd_output("ss --vsock | grep %s" % port):
        test.fail("vsock listening process inside guest does not exit after migrate")
    host_vsock_session.close()
    # send data from guest to host
    tmp_file = "/tmp/vsock_file_%s" % utils_misc.generate_random_string(6)
    rec_session = send_data_from_guest_to_host(session, tool_bin, guest_cid, tmp_file)
    utils_misc.wait_for(lambda: not rec_session.is_alive(), timeout=20)
    cmd_chksum = "md5sum %s" % tmp_file
    md5_origin = session.cmd_output(cmd_chksum, timeout=180, safe=True).split()[0]
    md5_received = process.system_output(cmd_chksum, timeout=180).split()[0].decode()
    host_vsock_session = input_character_vsock()
    ping_pong_migration(3)
    cmd_rm = "rm -rf %s" % tmp_file
    if vsock_test_tool == "nc_vsock":
        cmd_rm += "; rm -rf %s*" % tool_bin
    session.cmd_output_safe(cmd_rm, timeout=120)
    process.system(cmd_rm, shell=True, ignore_status=True)
    if md5_received != md5_origin:
        test.fail(
            "Data transfer not integrated, the original md5 value"
            " is %s, while the md5 value received on host is %s"
            % (md5_origin, md5_received)
        )
