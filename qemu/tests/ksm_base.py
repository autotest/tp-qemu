import os
import random
import re
import time

import aexpect
from avocado.utils import process
from virttest import data_dir, error_context, utils_misc

TMPFS_OVERHEAD = 0.0022


@error_context.context_aware
def run(test, params, env):
    """
    Test how KSM (Kernel Shared Memory) act when more than physical memory is
    used. In second part we also test how KVM handles a situation when the host
    runs out of memory (it is expected to pause the guest system, wait until
    some process returns memory and bring the guest back to life)

    :param test: QEMU test object.
    :param params: Dictionary with test parameters.
    :param env: Dictionary with the test environment.
    """

    def _start_allocator(vm, session, timeout):
        """
        Execute guest script and wait until it is initialized.

        :param vm: VM object.
        :param session: Remote session to a VM object.
        :param timeout: Timeout that will be used to verify if guest script
                started properly.
        """
        test.log.debug("Starting guest script on guest %s", vm.name)
        session.sendline(
            "$(command -v python python3 | head -1) /tmp/ksm_overcommit_guest.py"
        )
        try:
            _ = session.read_until_last_line_matches(["PASS:", "FAIL:"], timeout)
        except aexpect.ExpectProcessTerminatedError as exc:
            test.fail(
                "Command guest script on vm '%s' failed: %s" % (vm.name, str(exc))
            )

    def _execute_allocator(command, vm, session, timeout):
        """
        Execute a given command on guest script main loop, indicating the vm
        the command was executed on.

        :param command: Command that will be executed.
        :param vm: VM object.
        :param session: Remote session to VM object.
        :param timeout: Timeout used to verify expected output.

        :return: Tuple (match index, data)
        """
        test.log.debug(
            "Executing '%s' on guest script loop, vm: %s, timeout: %s",
            command,
            vm.name,
            timeout,
        )
        session.sendline(command)
        try:
            (match, data) = session.read_until_last_line_matches(
                ["PASS:", "FAIL:"], timeout
            )
        except aexpect.ExpectProcessTerminatedError as exc:
            e_str = "Failed to execute command '%s' on guest script, vm '%s': %s" % (
                command,
                vm.name,
                str(exc),
            )
            test.fail(e_str)
        return (match, data)

    timeout = float(params.get("login_timeout", 240))
    guest_script_overhead = int(params.get("guest_script_overhead", 5))
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    session = vm.wait_for_login(timeout=timeout)

    # Prepare work in guest
    error_context.context("Turn off swap in guest", test.log.info)
    session.cmd_status_output("swapoff -a")
    script_file_path = os.path.join(
        data_dir.get_root_dir(), "shared/scripts/ksm_overcommit_guest.py"
    )
    vm.copy_files_to(script_file_path, "/tmp")
    test_type = params.get("test_type")
    shared_mem = int(params["shared_mem"])
    get_free_mem_cmd = params.get("get_free_mem_cmd", "grep MemFree /proc/meminfo")
    free_mem = vm.get_memory_size(get_free_mem_cmd)
    max_mem = int(free_mem / (1 + TMPFS_OVERHEAD) - guest_script_overhead)

    # Keep test from OOM killer
    if max_mem < shared_mem:
        shared_mem = max_mem
    fill_timeout = int(shared_mem) / 10
    query_cmd = params.get("query_cmd")
    query_regex = params.get("query_regex")
    random_bits = params.get("random_bits")
    seed = random.randint(0, 255)

    query_cmd = re.sub("QEMU_PID", str(vm.process.get_pid()), query_cmd)

    sharing_page_0 = process.run(
        query_cmd, verbose=False, ignore_status=True, shell=True
    ).stdout_text
    if query_regex:
        sharing_page_0 = re.findall(query_regex, sharing_page_0)[0]

    error_context.context("Start to allocate pages inside guest", test.log.info)
    _start_allocator(vm, session, 60)
    error_context.context("Start to fill memory in guest", test.log.info)
    mem_fill = "mem = MemFill(%s, 0, %s)" % (shared_mem, seed)
    _execute_allocator(mem_fill, vm, session, fill_timeout)
    cmd = "mem.value_fill()"
    _execute_allocator(cmd, vm, session, fill_timeout)
    time.sleep(120)

    sharing_page_1 = process.run(
        query_cmd, verbose=False, ignore_status=True, shell=True
    ).stdout_text
    if query_regex:
        sharing_page_1 = re.findall(query_regex, sharing_page_1)[0]

    error_context.context(
        "Start to fill memory with random value in guest", test.log.info
    )
    split = params.get("split")
    if split == "yes":
        if test_type == "negative":
            cmd = "mem.static_random_fill(%s)" % random_bits
        else:
            cmd = "mem.static_random_fill()"
    _execute_allocator(cmd, vm, session, fill_timeout)
    time.sleep(120)

    sharing_page_2 = process.run(
        query_cmd, verbose=False, ignore_status=True, shell=True
    ).stdout_text
    if query_regex:
        sharing_page_2 = re.findall(query_regex, sharing_page_2)[0]

    # clean up work in guest
    error_context.context("Clean up env in guest", test.log.info)
    session.cmd_output("die()", 20)
    session.cmd_status_output("swapon -a")
    session.cmd_output("echo 3 > /proc/sys/vm/drop_caches")

    sharing_page = [sharing_page_0, sharing_page_1, sharing_page_2]
    for i in sharing_page:
        if re.findall("[A-Za-z]", i):
            data = i[0:-1]
            unit = i[-1]
            index = sharing_page.index(i)
            if unit == "g":
                sharing_page[index] = utils_misc.aton(data) * 1024
            else:
                sharing_page[index] = utils_misc.aton(data)

    fail_type = 0
    if test_type == "disable":
        if int(sharing_page[0]) != 0 and int(sharing_page[1]) != 0:
            fail_type += 1
    else:
        if int(sharing_page[0]) >= int(sharing_page[1]):
            fail_type += 2
        if int(sharing_page[1]) <= int(sharing_page[2]):
            fail_type += 4

    fail = [
        "Sharing page increased abnormally",
        "Sharing page didn't increase",
        "Sharing page didn't split",
    ]

    if fail_type != 0:
        turns = 0
        while fail_type > 0:
            if fail_type % 2 == 1:
                test.log.error(fail[turns])
            fail_type = fail_type / 2
            turns += 1
        test.fail(
            "KSM test failed: %s %s %s"
            % (sharing_page_0, sharing_page_1, sharing_page_2)
        )
    session.close()
