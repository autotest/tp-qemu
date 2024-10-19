import time

from avocado.utils import process
from virttest import error_context, utils_misc, utils_qemu, utils_test
from virttest.qemu_devices.qdevices import Memory
from virttest.utils_test.qemu import MemoryHotplugTest
from virttest.utils_version import VersionInterval


@error_context.context_aware
def run(test, params, env):
    """
    prealloc-threads test:
    1) Boot guest in paused status
    2) Get and check qemu initial threads number
    3) Hotplug memory backend with a large size and option prealloc-threads
    4) Get qemu threads number during step 3
    5) Check if qemu threads number in step 4 is expected, if not, fail test
    6) Otherwise, hotplug pc-dimm device
    7) Resume vm
    8) Check guest memory

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """

    def get_qemu_threads(cmd, timeout=60):
        """
        Get qemu threads when it's stable
        """
        threads = 0
        time.time()
        end_time = time.time() + float(timeout)
        while time.time() < end_time:
            cur_threads = int(process.system_output(cmd, shell=True))
            if cur_threads != threads:
                threads = cur_threads
                time.sleep(1)
            else:
                return threads
        test.error("Can't get stable qemu threads number in %ss." % timeout)

    vm = env.get_vm(params["main_vm"])
    get_threads_cmd = params["get_threads_cmd"] % vm.get_pid()
    qemu_binary = utils_misc.get_qemu_binary(params)
    qemu_version = utils_qemu.get_qemu_version(qemu_binary)[0]
    target_mems = params.get("target_mems").split()
    if qemu_version in VersionInterval("[7.1.0,)"):
        threads_default = params.get_numeric("smp")
    else:
        target_mems.remove("plug1")
    for target_mem in target_mems:
        test.log.info("Get qemu threads number at beginning")
        pre_threads = get_qemu_threads(get_threads_cmd)
        test.log.info("QEMU boot threads number is %s", pre_threads)
        new_params = params.object_params(target_mem).object_params("mem")
        attrs = Memory.__attributes__[new_params["backend"]][:]
        new_params = new_params.copy_from_keys(attrs)
        dev = Memory(new_params["backend"], new_params)
        dev.set_param("id", "%s-%s" % ("mem", target_mem))
        args = [vm.monitor, vm.devices.qemu_version]
        bg = utils_test.BackgroundTest(dev.hotplug, args)
        test.log.info("Hotplug memory backend '%s' to guest", dev["id"])
        bg.start()
        mem_params = params.object_params(target_mem)
        if mem_params.get("prealloc-threads_mem"):
            threads_num = mem_params.get_numeric("prealloc-threads_mem")
        else:
            threads_num = threads_default  # pylint: disable=E0606
        test.log.info("Get qemu threads number again")
        post_threads = get_qemu_threads(get_threads_cmd)
        if post_threads - pre_threads != threads_num:
            test.fail(
                "QEMU threads number is not right, pre is %s, post is %s"
                % (pre_threads, post_threads)
            )
        bg.join()
        memhp_test = MemoryHotplugTest(test, params, env)
        memhp_test.update_vm_after_hotplug(vm, dev)
        dimm = vm.devices.dimm_device_define_by_params(
            params.object_params(target_mem), target_mem
        )
        dimm.set_param("memdev", dev["id"])
        test.log.info("Hotplug pc-dimm '%s' to guest", dimm["id"])
        vm.devices.simple_hotplug(dimm, vm.monitor)
        memhp_test.update_vm_after_hotplug(vm, dimm)
    test.log.info("Resume vm and check memory inside guest")
    vm.resume()
    memhp_test.check_memory(vm)
