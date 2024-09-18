import re

from virttest import env_process, error_context, utils_misc


@error_context.context_aware
def run(test, params, env):
    """
    KVM Seabios test:
    [seabios] Check boot menu prompts with more than 10 available boot devices
    1) Start guest with sga bios
    2) Check the boot menu list
    3) Login into the guest

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """

    def prepare_images(img_num):
        """
        prepare extra images
        """
        for i in range(img_num):
            img = "stg%s" % i
            params["images"] = " ".join([params["images"], img])
            params["image_name_%s" % img] = "images/%s" % img
            params["image_size_%s" % img] = params["extra_img_size"]
            params["force_create_image_%s" % img] = "yes"
            params["remove_image_%s" % img] = "yes"

    def get_output(session_obj):
        """
        Use the function to short the lines in the scripts
        """
        return session_obj.get_stripped_output()

    def boot_menu():
        return re.search(boot_menu_hint, get_output(seabios_session))

    def get_boot_menu_list():
        return re.findall(r"^([1-9a-z])\. (.*)\s", get_output(seabios_session), re.M)

    timeout = float(params.get("timeout", 60))
    boot_menu_hint = params["boot_menu_hint"]
    boot_menu_key = params.get("boot_menu_key", "esc")
    boot_device = str(int(params["bootindex_image1"]) + 1)
    extra_img_num = int(params["extra_img_num"])

    error_context.context("Preprocess params", test.log.info)
    prepare_images(extra_img_num)
    params["start_vm"] = "yes"
    env_process.process_images(env_process.preprocess_image, test, params)
    env_process.preprocess_vm(test, params, env, params["main_vm"])

    error_context.context("Start guest with sga bios", test.log.info)
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    seabios_session = vm.logsessions["seabios"]

    error_context.context("Get boot menu list", test.log.info)
    if not utils_misc.wait_for(boot_menu, timeout, 1):
        test.fail("Could not get boot menu message")
    vm.send_key(boot_menu_key)

    boot_list = utils_misc.wait_for(get_boot_menu_list, timeout, 1)
    if not boot_list:
        test.fail("Could not get boot menu list")
    test.log.info("Got boot menu entries: '%s'", boot_list)

    error_context.context("Login into the guest", test.log.info)
    vm.send_key(boot_device)

    session = vm.wait_for_login()

    error_context.context("Check kernel crash message", test.log.info)
    vm.verify_kernel_crash()

    session.close()
