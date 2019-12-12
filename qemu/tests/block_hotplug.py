import logging
import re

from virttest import error_context
from virttest import utils_disk
from virttest import env_process
from virttest import utils_misc
from virttest import utils_numeric
from virttest import utils_test

from provider.block_devices_plug import BlockDevicesPlug


@error_context.context_aware
def run(test, params, env):
    """
    Test hotplug of block devices.

    1) Boot up guest with/without block device(s).
    2) Hotplug block device and verify.
    3) Do read/write data on hotplug block.
    4) Unplug block device and verify.

    :param test:   QEMU test object.
    :param params: Dictionary with the test parameters.
    :param env:    Dictionary with test environment.
    """
    def configure_images_params():
        """ Configure the images params. """
        for i, name in enumerate(data_imgs):
            boot_drive = params['boot_drive_%s' % name] if params.get(
                    'boot_drive_%s' % name) else params['boot_drive']
            drive_format = params['drive_format_%s' % name] if params.get(
                    'drive_format_%s' % name) else params['drive_format']
            image_name = params['image_name_%s' % name] if params.get(
                    'image_name_%s' % name) else 'images/storage%d' % i
            image_size = params['image_size_%s' % name] if params.get(
                    'image_size_%s' % name) else '1G'
            params['boot_drive_%s' % name] = boot_drive
            params['drive_format_%s' % name] = drive_format
            params['image_name_%s' % name] = image_name
            params['image_size_%s' % name] = image_size
            params['remove_image_%s' % name] = 'yes'
            params['force_create_image_%s' % name] = 'yes'
            if set_drive_bus:
                params['drive_bus_%s' % name] = str(i + 1)
            image_params = params.object_params(name)
            env_process.preprocess_image(test, image_params, name)

    def run_sub_test(test_name):
        """ Run subtest before/after hotplug/unplug device. """
        error_context.context(
                "Running sub test '%s'." % test_name, logging.info)
        utils_test.run_virt_sub_test(test, params, env, test_name)

    def format_disk_win():
        """ Format disk in windows. """
        error_context.context(
                "Format disk %s in windows." % plug[0], logging.info)
        session = vm.wait_for_login()
        utils_disk.update_windows_disk_attributes(session, plug)
        if not disk_index and not disk_letter:
            drive_letters.append(
                utils_disk.configure_empty_windows_disk(
                    session, plug[0], params['image_size_%s' % img])[0])
        elif disk_index and disk_letter:
            utils_misc.format_windows_disk(
                session, disk_index[index], disk_letter[index])
            drive_letters.append(disk_letter[index])
        session.close()

    def run_io_test():
        """ Run io test on the hot plugged disks. """
        error_context.context(
            "Run io test on the hot plugged disks.", logging.info)
        session = vm.wait_for_login()
        if is_windows:
            drive_letter = drive_letters[index]
            test_cmd = disk_op_cmd % (drive_letter, drive_letter)
            test_cmd = utils_misc.set_winutils_letter(session, test_cmd)
        else:
            test_cmd = disk_op_cmd % ('/dev/%s' % plug[0],
                                      '/dev/%s' % plug[0])
        session.cmd(test_cmd, timeout=disk_op_timeout)
        session.close()

    def _get_disk_size(did):
        """
        Get the disk size from guest.

        :param did: the disk of id, e.g. sdb,sda for linux, 1, 2 for windows
        :return: the disk size
        """
        session = vm.wait_for_login()
        if is_windows:
            script = '{}_{}'.format(
                    "disk",  utils_misc.generate_random_string(6))
            p = r'Disk\s+%s\s+[A-Z]+\s+(?P<size>\d+\s+[A-Z]+)\s+'
            disk_info = session.cmd(
                    "echo %s > {0} && diskpart /s {0} && "
                    "del /f {0}".format(script) % 'list disk')
            size = re.search(p % did, disk_info,
                             re.I | re.M).groupdict()['size'].strip()
        else:
            size = utils_disk.get_linux_disks(session)[did][1].strip()
        logging.info('The size of disk %s is %s' % (did, size))
        session.close()
        return size

    def check_disk_size(did, excepted_size):
        """
        Checkt whether the disk size is equal to excepted size.

        :param did: the disk of id, e.g. sdb,sda for linux, 1, 2 for windows
        :param excepted_size: the excepted size
        """
        error_context.context(
            'Check whether the size of the disk[%s] hot plugged is equal to '
            'excepted size(%s).' % (did, excepted_size), logging.info)
        value, unit = re.search(r"(\d+\.?\d*)\s*(\w?)", excepted_size).groups()
        if utils_numeric.normalize_data_size(_get_disk_size(did), unit) != value:
            test.fail('The size of disk %s is not equal to excepted size(%s).'
                      % (did, excepted_size))

    data_imgs = params.get("images").split()[1:]
    set_drive_bus = params.get("set_drive_bus", "no") == "yes"
    disk_index = params.objects("disk_index")
    disk_letter = params.objects("disk_letter")
    disk_op_cmd = params.get("disk_op_cmd")
    disk_op_timeout = int(params.get("disk_op_timeout", 360))
    is_windows = params["os_type"] == 'windows'

    sub_test_after_plug = params.get("sub_type_after_plug")
    sub_test_after_unplug = params.get("sub_type_after_unplug")
    sub_test_before_unplug = params.get("sub_type_before_unplug")
    shutdown_after_plug = sub_test_after_plug == 'shutdown'
    need_plug = params.get("need_plug", 'no') == "yes"
    need_check_disk_size = params.get('check_disk_size', 'no') == 'yes'
    drive_letters = []

    configure_images_params()
    params["start_vm"] = "yes"
    env_process.preprocess_vm(test, params, env, params["main_vm"])
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    vm.wait_for_login()

    plug = BlockDevicesPlug(vm)
    for iteration in range(int(params.get("repeat_times", 3))):
        for index, img in enumerate(data_imgs):
            if need_plug:
                plug.hotplug_devs_serial(img)
                if is_windows and not iteration:
                    format_disk_win()
                if need_check_disk_size:
                    check_disk_size(plug[0] if is_windows else plug[0],
                                    params['image_size_%s' % img])
                if disk_op_cmd:
                    run_io_test()
        if sub_test_after_plug:
            run_sub_test(sub_test_after_plug)
        if shutdown_after_plug:
            return

        if sub_test_before_unplug:
            run_sub_test(sub_test_before_unplug)
        plug.unplug_devs_serial(' '.join(data_imgs))
        if sub_test_after_unplug:
            run_sub_test(sub_test_after_unplug)
