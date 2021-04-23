import time
import logging

from avocado.utils import process
from virttest import error_context
from virttest import utils_test
from virttest.qemu_devices.qdevices import Memory
from virttest.utils_test.qemu import MemoryHotplugTest


@error_context.context_aware
def run(test, params, env):
    """
    prealloc-threads test:
    1) Boot guest in paused status
    2) Get qemu threads number
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
        start_time = time.time()
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
    logging.info("Get qemu threads number at beginning")
    get_threads_cmd = params["get_threads_cmd"] % vm.get_pid()
    pre_threads = get_qemu_threads(get_threads_cmd)
    mem = params.get("target_mems")
    new_params = params.object_params(mem).object_params("mem")
    attrs = Memory.__attributes__[new_params["backend"]][:]
    new_params = new_params.copy_from_keys(attrs)
    dev = Memory(new_params["backend"], new_params)
    dev.set_param("id", "%s-%s" % ("mem", mem))
    args = [vm.monitor, vm.devices.qemu_version]
    bg = utils_test.BackgroundTest(dev.hotplug, args)
    logging.info("Hotplug memory backend '%s' to guest", dev["id"])
    bg.start()
    threads_num = int(new_params["prealloc-threads"])
    logging.info("Get qemu threads number again")
    post_threads = get_qemu_threads(get_threads_cmd)
    if post_threads - pre_threads != threads_num:
        test.fail("QEMU threads number is not right, pre is %s, post is %s"
                  % (pre_threads, post_threads))
    bg.join()
    memhp_test = MemoryHotplugTest(test, params, env)
    memhp_test.update_vm_after_hotplug(vm, dev)
    dimm = vm.devices.dimm_device_define_by_params(params.object_params(mem),
                                                   mem)
    dimm.set_param("memdev", dev["id"])
    logging.info("Hotplug pc-dimm '%s' to guest", dimm["id"])
    vm.devices.simple_hotplug(dimm, vm.monitor)
    memhp_test.update_vm_after_hotplug(vm, dimm)
    logging.info("Resume vm and check memory inside guest")
    vm.resume()
    memhp_test.check_memory(vm)
