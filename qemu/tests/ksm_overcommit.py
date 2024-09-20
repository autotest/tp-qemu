import math
import os
import random
import time

import aexpect
from avocado.utils import process
from virttest import data_dir, env_process, utils_misc, utils_test
from virttest.staging import utils_memory


def run(test, params, env):
    """
    Tests KSM (Kernel Shared Memory) capability by allocating and filling
    KVM guests memory using various values. KVM sets the memory as
    MADV_MERGEABLE so all VM's memory can be merged. The workers in
    guest writes to tmpfs filesystem thus allocations are not limited
    by process max memory, only by VM's memory. Two test modes are supported -
    serial and parallel.

    Serial mode - uses multiple VMs, allocates memory per guest and always
                  verifies the correct number of shared memory.
                  0) Prints out the setup and initialize guest(s)
                  1) Fills guest with the same number (S1)
                  2) Random fill on the first guest
                  3) Random fill of the remaining VMs one by one until the
                     memory is completely filled (KVM stops machines which
                     asks for additional memory until there is available
                     memory) (S2, shouldn't finish)
                  4) Destroy all VMs but the last one
                  5) Checks the last VMs memory for corruption
    Parallel mode - uses one VM with multiple allocator workers. Executes
                   scenarios in parallel to put more stress on the KVM.
                   0) Prints out the setup and initialize guest(s)
                   1) Fills memory with the same number (S1)
                   2) Fills memory with random numbers (S2)
                   3) Verifies all pages
                   4) Fills memory with the same number (S2)
                   5) Changes the last 96B (S3)

    Scenarios:
    S1) Fill all vms with the same value (all pages should be merged into 1)
    S2) Random fill (all pages should be splitted)
    S3) Fill last 96B (change only last 96B of each page; some pages will be
                      merged; there was a bug with data corruption)
    Every worker has unique random key so we are able to verify the filled
    values.

    :param test: kvm test object.
    :param params: Dictionary with test parameters.
    :param env: Dictionary with the test environment.

    :param cfg: ksm_swap - use swap?
    :param cfg: ksm_overcommit_ratio - memory overcommit (serial mode only)
    :param cfg: ksm_parallel_ratio - number of workers (parallel mode only)
    :param cfg: ksm_host_reserve - override memory reserve on host in MB
    :param cfg: ksm_guest_reserve - override memory reserve on guests in MB
    :param cfg: ksm_mode - test mode {serial, parallel}
    :param cfg: ksm_perf_ratio - performance ratio, increase it when your
                                 machine is too slow
    """

    def _start_allocator(vm, session, timeout):
        """
        Execute ksm_overcommit_guest.py on guest, wait until it's initialized.

        :param vm: VM object.
        :param session: Remote session to a VM object.
        :param timeout: Timeout that will be used to verify if
                ksm_overcommit_guest.py started properly.
        """
        test.log.debug("Starting ksm_overcommit_guest.py on guest %s", vm.name)
        session.sendline(
            "$(command -v python python3 | head -1) " "/tmp/ksm_overcommit_guest.py"
        )
        try:
            session.read_until_last_line_matches(["PASS:", "FAIL:"], timeout)
        except aexpect.ExpectProcessTerminatedError as details:
            e_msg = "Command ksm_overcommit_guest.py on vm '%s' failed: %s" % (
                vm.name,
                str(details),
            )
            test.fail(e_msg)

    def _execute_allocator(command, vm, session, timeout):
        """
        Execute a given command on ksm_overcommit_guest.py main loop,
        indicating the vm the command was executed on.

        :param command: Command that will be executed.
        :param vm: VM object.
        :param session: Remote session to VM object.
        :param timeout: Timeout used to verify expected output.

        :return: Tuple (match index, data)
        """
        test.log.debug(
            "Executing '%s' on ksm_overcommit_guest.py loop, " "vm: %s, timeout: %s",
            command,
            vm.name,
            timeout,
        )
        session.sendline(command)
        try:
            (match, data) = session.read_until_last_line_matches(
                ["PASS:", "FAIL:"], timeout
            )
        except aexpect.ExpectProcessTerminatedError as details:
            e_msg = (
                "Failed to execute command '%s' on "
                "ksm_overcommit_guest.py, vm '%s': %s"
                % (command, vm.name, str(details))
            )
            test.fail(e_msg)
        return (match, data)

    def get_ksmstat():
        """
        Return sharing memory by ksm in MB

        :return: memory in MB
        """
        fpages = open("/sys/kernel/mm/ksm/pages_sharing")
        ksm_pages = int(fpages.read())
        fpages.close()
        sharing_mem = ksm_pages * pagesize
        return int(float(utils_misc.normalize_data_size("%sK" % sharing_mem)))

    def initialize_guests():
        """
        Initialize guests (fill their memories with specified patterns).
        """
        test.log.info("Phase 1: filling guest memory pages")
        for session in lsessions:
            vm = lvms[lsessions.index(session)]

            test.log.debug("Turning off swap on vm %s", vm.name)
            session.cmd("swapoff -a", timeout=300)

            # Start the allocator
            _start_allocator(vm, session, 60 * perf_ratio)

        # Execute allocator on guests
        for i in range(0, vmsc):
            vm = lvms[i]

            cmd = "mem = MemFill(%d, %s, %s)" % (ksm_size, skeys[i], dkeys[i])
            _execute_allocator(cmd, vm, lsessions[i], 60 * perf_ratio)

            cmd = "mem.value_fill(%d)" % skeys[0]
            _execute_allocator(
                cmd, vm, lsessions[i], fill_base_timeout * 2 * perf_ratio
            )

            # Let ksm_overcommit_guest.py do its job
            # (until shared mem reaches expected value)
            shm = 0
            j = 0
            test.log.debug("Target shared meminfo for guest %s: %s", vm.name, ksm_size)
            while (new_ksm and (shm < (ksm_size * (i + 1)))) or (
                not new_ksm and (shm < (ksm_size))
            ):
                if j > 256:
                    test.log.debug(utils_test.get_memory_info(lvms))
                    test.error(
                        "SHM didn't merge the memory until "
                        "the DL on guest: %s" % vm.name
                    )
                pause = ksm_size / 200 * perf_ratio
                test.log.debug("Waiting %ds before proceeding...", pause)
                time.sleep(pause)
                if new_ksm:
                    shm = get_ksmstat()
                else:
                    shm = vm.get_shared_meminfo()
                test.log.debug(
                    "Shared meminfo for guest %s after " "iteration %s: %s",
                    vm.name,
                    j,
                    shm,
                )
                j += 1

        # Keep some reserve
        pause = ksm_size / 200 * perf_ratio
        test.log.debug("Waiting %ds before proceeding...", pause)
        time.sleep(pause)

        test.log.debug(utils_test.get_memory_info(lvms))
        test.log.info("Phase 1: PASS")

    def separate_first_guest():
        """
        Separate memory of the first guest by generating special random series
        """
        test.log.info("Phase 2: Split the pages on the first guest")

        cmd = "mem.static_random_fill()"
        data = _execute_allocator(
            cmd, lvms[0], lsessions[0], fill_base_timeout * 2 * perf_ratio
        )[1]

        r_msg = data.splitlines()[-1]
        test.log.debug("Return message of static_random_fill: %s", r_msg)
        out = int(r_msg.split()[4])
        test.log.debug(
            "Performance: %dMB * 1000 / %dms = %dMB/s",
            ksm_size,
            out,
            (ksm_size * 1000 / out),
        )
        test.log.debug(utils_test.get_memory_info(lvms))
        test.log.debug("Phase 2: PASS")

    def split_guest():
        """
        Sequential split of pages on guests up to memory limit
        """
        test.log.info(
            "Phase 3a: Sequential split of pages on guests up to " "memory limit"
        )
        last_vm = 0
        session = None
        vm = None
        for i in range(1, vmsc):
            # Check VMs
            for j in range(0, vmsc):
                if not lvms[j].is_alive:
                    e_msg = (
                        "VM %d died while executing static_random_fill on"
                        " VM %d in allocator loop" % (j, i)
                    )
                    test.fail(e_msg)
            vm = lvms[i]
            session = lsessions[i]
            cmd = "mem.static_random_fill()"
            test.log.debug(
                "Executing %s on ksm_overcommit_guest.py loop, " "vm: %s", cmd, vm.name
            )
            session.sendline(cmd)

            out = ""
            try:
                test.log.debug("Watching host mem while filling vm %s memory", vm.name)
                while not out.startswith("PASS") and not out.startswith("FAIL"):
                    if not vm.is_alive():
                        e_msg = (
                            "VM %d died while executing "
                            "static_random_fill on allocator loop" % i
                        )
                        test.fail(e_msg)
                    free_mem = int(utils_memory.read_from_meminfo("MemFree"))
                    if ksm_swap:
                        free_mem = free_mem + int(
                            utils_memory.read_from_meminfo("SwapFree")
                        )
                    test.log.debug("Free memory on host: %d", free_mem)

                    # We need to keep some memory for python to run.
                    if (free_mem < 64000) or (
                        ksm_swap and free_mem < (450000 * perf_ratio)
                    ):
                        vm.pause()
                        for j in range(0, i):
                            lvms[j].destroy(gracefully=False)
                        time.sleep(20)
                        vm.resume()
                        test.log.debug(
                            "Only %s free memory, killing %d guests", free_mem, (i - 1)
                        )
                        last_vm = i
                    out = session.read_nonblocking(0.1, 1)
                    time.sleep(2)
            except OSError:
                test.log.debug(
                    "Only %s host free memory, killing %d guests", free_mem, (i - 1)
                )
                test.log.debug("Stopping %s", vm.name)
                vm.pause()
                for j in range(0, i):
                    test.log.debug("Destroying %s", lvms[j].name)
                    lvms[j].destroy(gracefully=False)
                time.sleep(20)
                vm.resume()
                last_vm = i

            if last_vm != 0:
                break
            test.log.debug("Memory filled for guest %s", vm.name)

        test.log.info("Phase 3a: PASS")

        test.log.info("Phase 3b: Verify memory of the max stressed VM")
        for i in range(last_vm + 1, vmsc):
            lsessions[i].close()
            if i == (vmsc - 1):
                test.log.debug(utils_test.get_memory_info([lvms[i]]))
            test.log.debug("Destroying guest %s", lvms[i].name)
            lvms[i].destroy(gracefully=False)

        # Verify last machine with randomly generated memory
        cmd = "mem.static_random_verify()"
        _execute_allocator(
            cmd, lvms[last_vm], lsessions[last_vm], (mem / 200 * 50 * perf_ratio)
        )
        test.log.debug(utils_test.get_memory_info([lvms[last_vm]]))

        lsessions[last_vm].cmd_output("die()", 20)
        lvms[last_vm].destroy(gracefully=False)
        test.log.info("Phase 3b: PASS")

    def split_parallel():
        """
        Parallel page spliting
        """
        test.log.info("Phase 1: parallel page spliting")
        # We have to wait until allocator is finished (it waits 5 seconds to
        # clean the socket

        session = lsessions[0]
        vm = lvms[0]
        for i in range(1, max_alloc):
            lsessions.append(vm.wait_for_login(timeout=360))

        session.cmd("swapoff -a", timeout=300)

        for i in range(0, max_alloc):
            # Start the allocator
            _start_allocator(vm, lsessions[i], 60 * perf_ratio)

        test.log.info("Phase 1: PASS")

        test.log.info("Phase 2a: Simultaneous merging")
        test.log.debug(
            "Memory used by allocator on guests = %dMB", (ksm_size / max_alloc)
        )

        for i in range(0, max_alloc):
            cmd = "mem = MemFill(%d, %s, %s)" % (
                (ksm_size / max_alloc),
                skeys[i],
                dkeys[i],
            )
            _execute_allocator(cmd, vm, lsessions[i], 60 * perf_ratio)

            cmd = "mem.value_fill(%d)" % (skeys[0])
            _execute_allocator(cmd, vm, lsessions[i], fill_base_timeout * perf_ratio)

        # Wait until ksm_overcommit_guest.py merges pages (3 * ksm_size / 3)
        shm = 0
        i = 0
        test.log.debug("Target shared memory size: %s", ksm_size)
        while shm < ksm_size:
            if i > 64:
                test.log.debug(utils_test.get_memory_info(lvms))
                test.error("SHM didn't merge the memory until DL")
            pause = ksm_size / 200 * perf_ratio
            test.log.debug("Waiting %ds before proceed...", pause)
            time.sleep(pause)
            if new_ksm:
                shm = get_ksmstat()
            else:
                shm = vm.get_shared_meminfo()
            test.log.debug("Shared meminfo after attempt %s: %s", i, shm)
            i += 1

        test.log.debug(utils_test.get_memory_info([vm]))
        test.log.info("Phase 2a: PASS")

        test.log.info("Phase 2b: Simultaneous spliting")
        # Actual splitting
        for i in range(0, max_alloc):
            cmd = "mem.static_random_fill()"
            data = _execute_allocator(
                cmd, vm, lsessions[i], fill_base_timeout * perf_ratio
            )[1]

            data = data.splitlines()[-1]
            test.log.debug(data)
            out = int(data.split()[4])
            test.log.debug(
                "Performance: %dMB * 1000 / %dms = %dMB/s",
                (ksm_size / max_alloc),
                out,
                (ksm_size * 1000 / out / max_alloc),
            )
        test.log.debug(utils_test.get_memory_info([vm]))
        test.log.info("Phase 2b: PASS")

        test.log.info("Phase 2c: Simultaneous verification")
        for i in range(0, max_alloc):
            cmd = "mem.static_random_verify()"
            data = _execute_allocator(
                cmd, vm, lsessions[i], (mem / 200 * 50 * perf_ratio)
            )[1]
        test.log.info("Phase 2c: PASS")

        test.log.info("Phase 2d: Simultaneous merging")
        # Actual splitting
        for i in range(0, max_alloc):
            cmd = "mem.value_fill(%d)" % skeys[0]
            data = _execute_allocator(
                cmd, vm, lsessions[i], fill_base_timeout * 2 * perf_ratio
            )[1]
        test.log.debug(utils_test.get_memory_info([vm]))
        test.log.info("Phase 2d: PASS")

        test.log.info("Phase 2e: Simultaneous verification")
        for i in range(0, max_alloc):
            cmd = "mem.value_check(%d)" % skeys[0]
            data = _execute_allocator(
                cmd, vm, lsessions[i], (mem / 200 * 50 * perf_ratio)
            )[1]
        test.log.info("Phase 2e: PASS")

        test.log.info("Phase 2f: Simultaneous spliting last 96B")
        for i in range(0, max_alloc):
            cmd = "mem.static_random_fill(96)"
            data = _execute_allocator(
                cmd, vm, lsessions[i], fill_base_timeout * perf_ratio
            )[1]

            data = data.splitlines()[-1]
            out = int(data.split()[4])
            test.log.debug(
                "Performance: %dMB * 1000 / %dms = %dMB/s",
                ksm_size / max_alloc,
                out,
                (ksm_size * 1000 / out / max_alloc),
            )

        test.log.debug(utils_test.get_memory_info([vm]))
        test.log.info("Phase 2f: PASS")

        test.log.info("Phase 2g: Simultaneous verification last 96B")
        for i in range(0, max_alloc):
            cmd = "mem.static_random_verify(96)"
            _, data = _execute_allocator(
                cmd, vm, lsessions[i], (mem / 200 * 50 * perf_ratio)
            )
        test.log.debug(utils_test.get_memory_info([vm]))
        test.log.info("Phase 2g: PASS")

        test.log.debug("Cleaning up...")
        for i in range(0, max_alloc):
            lsessions[i].cmd_output("die()", 20)
        session.close()
        vm.destroy(gracefully=False)

    # Main test code
    test.log.info("Starting phase 0: Initialization")
    if process.run("ps -C ksmtuned", ignore_status=True).exit_status == 0:
        test.log.info("Killing ksmtuned...")
        process.run("killall ksmtuned")
    new_ksm = False
    if os.path.exists("/sys/kernel/mm/ksm/run"):
        process.run("echo 50 > /sys/kernel/mm/ksm/sleep_millisecs", shell=True)
        process.run("echo 5000 > /sys/kernel/mm/ksm/pages_to_scan", shell=True)
        process.run("echo 1 > /sys/kernel/mm/ksm/run", shell=True)

        e_up = "/sys/kernel/mm/transparent_hugepage/enabled"
        e_rh = "/sys/kernel/mm/redhat_transparent_hugepage/enabled"
        if os.path.exists(e_up):
            process.run("echo 'never' > %s" % e_up, shell=True)
        if os.path.exists(e_rh):
            process.run("echo 'never' > %s" % e_rh, shell=True)
        new_ksm = True
    else:
        try:
            process.run("modprobe ksm")
            process.run("ksmctl start 5000 100")
        except process.CmdError as details:
            test.fail("Failed to load KSM: %s" % details)

    # host_reserve: mem reserve kept for the host system to run
    host_reserve = int(params.get("ksm_host_reserve", -1))
    if host_reserve == -1:
        try:
            available = utils_memory.read_from_meminfo("MemAvailable")
        except process.CmdError:  # ancient kernels
            utils_memory.drop_caches()
            available = utils_memory.read_from_meminfo("MemFree")
        # default host_reserve = UsedMem + one_minimal_guest(128MB)
        # later we add 64MB per additional guest
        host_reserve = (utils_memory.memtotal() - available) / 1024 + 128
        # using default reserve
        _host_reserve = True
    else:
        _host_reserve = False

    # guest_reserve: mem reserve kept to avoid guest OS to kill processes
    guest_reserve = int(params.get("ksm_guest_reserve", -1))
    if guest_reserve == -1:
        # In case of OOM, set guest_reserve to 1536M
        guest_reserve = 1536
        # using default reserve
        _guest_reserve = True
    else:
        _guest_reserve = False

    max_vms = int(params.get("max_vms", 2))
    overcommit = float(params.get("ksm_overcommit_ratio", 2.0))
    max_alloc = int(params.get("ksm_parallel_ratio", 1))

    # vmsc: count of all used VMs
    vmsc = int(overcommit) + 1
    vmsc = max(vmsc, max_vms)

    if params["ksm_mode"] == "serial":
        max_alloc = vmsc
        if _host_reserve:
            # First round of additional guest reserves
            host_reserve += vmsc * 64
            _host_reserve = vmsc

    host_mem = int(utils_memory.memtotal()) / 1024 - host_reserve
    pagesize = utils_memory.getpagesize()

    ksm_swap = False
    if params.get("ksm_swap") == "yes":
        ksm_swap = True

    # Performance ratio
    perf_ratio = params.get("ksm_perf_ratio")
    if perf_ratio:
        perf_ratio = float(perf_ratio)
    else:
        perf_ratio = 1

    if params["ksm_mode"] == "parallel":
        vmsc = 1
        overcommit = 1
        mem = host_mem
        # 32bit system adjustment
        if "64" not in params.get("vm_arch_name"):
            test.log.debug(
                "Probably i386 guest architecture, " "max allocator mem = 2G"
            )
            # Guest can have more than 2G but
            # kvm mem + 1MB (allocator itself) can't
            if host_mem > 3100:
                mem = 3100

        if os.popen("uname -i").readline().startswith("i386"):
            test.log.debug("Host is i386 architecture, max guest mem is 2G")
            # Guest system with qemu overhead (64M) can't have more than 2G
            if mem > 3100 - 64:
                mem = 3100 - 64

    else:
        # mem: Memory of the guest systems. Maximum must be less than
        # host's physical ram
        mem = int(overcommit * host_mem / vmsc)
        # If guest memory is too much, it will take very very long time for ksm
        # to scan and merge same pages, sometimes will hit timeout
        if mem > 8192:
            mem = 8192

        # 32bit system adjustment
        if params["vm_arch_name"] == "i686":
            test.log.debug(
                "Probably i386 guest architecture, " "max allocator mem = 2G"
            )
            # Guest can have more than 2G but
            # kvm mem + 1MB (allocator itself) can't
            if mem - guest_reserve - 1 > 3100:
                vmsc = int(math.ceil((host_mem * overcommit) / (3100 + guest_reserve)))
                if _host_reserve:
                    host_reserve += (vmsc - _host_reserve) * 64
                    host_mem -= (vmsc - _host_reserve) * 64
                    _host_reserve = vmsc
                mem = int(math.floor(host_mem * overcommit / vmsc))

        if os.popen("uname -i").readline().startswith("i386"):
            test.log.debug("Host is i386 architecture, max guest mem is 2G")
            # Guest system with qemu overhead (64M) can't have more than 2G
            if mem > 3100 - 64:
                vmsc = int(math.ceil((host_mem * overcommit) / (3100 - 64.0)))
                if _host_reserve:
                    host_reserve += (vmsc - _host_reserve) * 64
                    host_mem -= (vmsc - _host_reserve) * 64
                    _host_reserve = vmsc
                mem = int(math.floor(host_mem * overcommit / vmsc))

    # 0.055 represents OS + TMPFS additional reserve per guest ram MB
    if _guest_reserve:
        guest_reserve += math.ceil(mem * 0.055)

    swap = int(utils_memory.read_from_meminfo("SwapTotal")) / 1024

    test.log.debug("Overcommit = %f", overcommit)
    test.log.debug("True overcommit = %f ", (float(vmsc * mem) / float(host_mem)))
    test.log.debug("Host memory = %dM", host_mem)
    test.log.debug("Guest memory = %dM", mem)
    test.log.debug("Using swap = %s", ksm_swap)
    test.log.debug("Swap = %dM", swap)
    test.log.debug("max_vms = %d", max_vms)
    test.log.debug("Count of all used VMs = %d", vmsc)
    test.log.debug("Performance_ratio = %f", perf_ratio)

    # Generate unique keys for random series
    skeys = []
    dkeys = []
    for i in range(0, max(vmsc, max_alloc)):
        key = random.randrange(0, 255)
        while key in skeys:
            key = random.randrange(0, 255)
        skeys.append(key)

        key = random.randrange(0, 999)
        while key in dkeys:
            key = random.randrange(0, 999)
        dkeys.append(key)

    test.log.debug("skeys: %s", skeys)
    test.log.debug("dkeys: %s", dkeys)

    lvms = []
    lsessions = []

    # As we don't know the number and memory amount of VMs in advance,
    # we need to specify and create them here
    vm_name = params["main_vm"]
    vm_arch_name = params["vm_arch_name"]
    if vm_arch_name in ("ppc64", "ppc64le"):
        if divmod(mem, 256)[1] > 0:
            mem = 256 * (divmod(mem, 256)[0] + 1)
    params["mem"] = mem
    params["vms"] = vm_name

    # ksm_size: amount of memory used by allocator
    ksm_size = mem - guest_reserve
    test.log.debug("Memory used by allocator on guests = %dM", ksm_size)
    fill_base_timeout = ksm_size / 10

    # Creating the first guest
    env_process.preprocess_vm(test, params, env, vm_name)
    lvms.append(env.get_vm(vm_name))
    if not lvms[0]:
        test.error("VM object not found in environment")
    if not lvms[0].is_alive():
        test.error("VM seems to be dead; Test requires a living VM")

    test.log.debug("Booting first guest %s", lvms[0].name)

    lsessions.append(lvms[0].wait_for_login(timeout=360))

    # Creating other guest systems
    for i in range(1, vmsc):
        vm_name = "vm" + str(i + 1)

        # Last VM is later used to run more allocators simultaneously
        lvms.append(lvms[0].clone(vm_name, params))
        env.register_vm(vm_name, lvms[i])
        params["vms"] += " " + vm_name

        test.log.debug("Booting guest %s", lvms[i].name)
        lvms[i].create()
        if not lvms[i].is_alive():
            test.error(
                "VM %s seems to be dead; Test requires a" "living VM" % lvms[i].name
            )

        lsessions.append(lvms[i].wait_for_login(timeout=360))

    # Let guests rest a little bit :-)
    pause = vmsc * 2 * perf_ratio
    test.log.debug("Waiting %ds before proceed", pause)
    time.sleep(vmsc * 2 * perf_ratio)
    test.log.debug(utils_test.get_memory_info(lvms))

    # Copy ksm_overcommit_guest.py into guests
    vksmd_src = os.path.join(
        data_dir.get_shared_dir(), "scripts", "ksm_overcommit_guest.py"
    )
    dst_dir = "/tmp"
    for vm in lvms:
        vm.copy_files_to(vksmd_src, dst_dir)
    test.log.info("Phase 0: PASS")

    if params["ksm_mode"] == "parallel":
        test.log.info("Starting KSM test parallel mode")
        split_parallel()
        test.log.info("KSM test parallel mode: PASS")
    elif params["ksm_mode"] == "serial":
        test.log.info("Starting KSM test serial mode")
        initialize_guests()
        separate_first_guest()
        split_guest()
        test.log.info("KSM test serial mode: PASS")
