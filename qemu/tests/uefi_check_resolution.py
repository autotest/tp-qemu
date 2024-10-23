import random
import re

from virttest import error_context, utils_misc


@error_context.context_aware
def run(test, params, env):
    """
    Verify UEFI config setting in the GUI screen:
    1) Boot up a guest.
    2) Set default resolution
    3) Change resolution to $re1
    4) Save it by hitting 'F10' + 'Y' or 'Commit Changes and Exit'
    5) Exit setup interface
    6) Check if resolution had been change to $re1
    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """

    change_prefered = [
        "640 x 480",
        "800 x 480",
        "800 x 600",
        "832 x 624",
        "960 x 640",
        "1024 x 600",
        "1024 x 768",
        "1152 x 864",
        "1152 x 870",
        "1280 x 720",
        "1280 x 760",
        "1280 x 768",
        "1280 x 800",
        "1280 x 960",
        "1280 x 1024",
        "1360 x 768",
        "1366 x 768",
        "1400 x 1050",
        "1440 x 900",
        "1600 x 900",
        "1600 x 1200",
        "1680 x 1050",
        "1920 x 1080",
        "1920 x 1200",
        "1920 x 1440",
        "2000 x 2000",
        "2048 x 1536",
        "2048 x 2048",
        "2560 x 1440",
        "2560 x 1600",
    ]

    def boot_check(info):
        """
        boot info check
        """
        logs = vm.logsessions["seabios"].get_output()
        result = re.search(info, logs, re.S)
        return result

    def choose_resolution():
        """
        choose resolution randomly
        """
        n = random.randint(0, 29)
        change_resolution_key = ["kp_enter"] + ["down"] * n + ["kp_enter"]
        resolution = change_prefered[n]
        check_info = "GraphicsConsole video resolution " + resolution
        return change_resolution_key, check_info, resolution

    timeout = int(params.get("timeout", 360))
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()

    boot_menu_hint = params["boot_menu_hint"]
    enter_change_preferred = params["enter_change_preferred"].split(";")
    default_resolution_key = params["default_resolution_key"].split(";")
    save_change_key = params["save_change"].split(";")
    esc_boot_menu_key = params["esc_boot_menu_key"].split(";")
    default_resolution = params.get("default_resolution")
    if default_resolution:
        index = change_prefered.index(default_resolution)
        if index != 0:
            del change_prefered[index]
            change_prefered = [default_resolution] + change_prefered
    change_resolution_key, check_info, resolution = choose_resolution()
    if not utils_misc.wait_for(lambda: boot_check(boot_menu_hint), timeout, 1):
        test.fail("Could not get boot menu message")
    key = []
    key += enter_change_preferred
    key += default_resolution_key
    key += change_resolution_key
    key += save_change_key
    key += esc_boot_menu_key
    list(map(vm.send_key, key))
    vm.reboot(timeout=timeout)

    if not boot_check(check_info):
        test.fail("Change to resolution {'%s'} fail" % resolution)
