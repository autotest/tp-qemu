import random
import threading
import time

from virttest.tests import unattended_install

error_flag = False


def run(test, params, env):
    """
    Unattended install test:
    1) Starts a VM with an appropriated setup to start an unattended OS install.
    2) Wait until the install reports to the install watcher its end.

    :param test: QEMU test object.
    :param params: Dictionary with the test parameters.
    :param env: Dictionary with test environment.
    """
    # use vm name to differentiate among single/multivm
    vms = params.objects("vms")

    if len(vms) < 2:
        unattended_install.run(test, params, env)
        return

    def thread_func(vm):
        """
        Thread Method to trigger the unattended installation

        :param vm: VM name
        """
        global error_flag
        try:
            vm_params = params.object_params(vm)
            vm_params["main_vm"] = vm
            unattended_install.run(test, vm_params, env)
        except Exception as info:
            test.log.error(info)
            error_flag = True

    if not params.get("master_images_clone"):
        test.cancel("provide the param `master_images_clone` to clone" "images for vms")

    trigger_time = int(params.get("install_trigger_time", 0))
    random_trigger = params.get("random_trigger", "no") == "yes"
    install_threads = []

    for vm in vms:
        thread = threading.Thread(target=thread_func, args=(vm,))
        install_threads.append(thread)

    for thread in install_threads:
        if trigger_time:
            sleep_time = trigger_time
            if random_trigger:
                sleep_time = random.randint(0, trigger_time)
            time.sleep(sleep_time)
        thread.start()

    for thread in install_threads:
        thread.join()

    if error_flag:
        test.fail("Failed to perform unattended install")
