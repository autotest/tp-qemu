import os
import re
import time

from virttest import data_dir, error_context, qemu_storage, storage, utils_misc


@error_context.context_aware
def run(test, params, env):
    """
    live_snapshot chain test:

    Will test snapshot as following steps:
    1. Boot up guest with base image
    2. Do pre snapshot operates(option)
    3. Do live snapshot
    4. Do post snapshot operates(option)
    5. Check the base and snapshot images(option)

    :param test: Kvm test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """

    def generate_snapshot_chain(snapshot_chain, snapshot_num):
        for i in range(snapshot_num):
            snapshot_tag = "sn%s" % i
            snapshot_chain += " %s" % snapshot_tag
            params["image_name_%s" % snapshot_tag] = "images/%s" % snapshot_tag
        if snapshot_num > 0:
            params["check_base_image_%s" % snapshot_tag] = "yes"
        return snapshot_chain

    def get_base_image(snapshot_chain, snapshot_file):
        try:
            index = snapshot_chain.index(snapshot_file)
        except ValueError:
            index = -1

        if index > 0:
            base_image = snapshot_chain[index - 1]
        else:
            base_image = None
        return base_image

    def do_operate(params, key_word):
        operate_cmd = params.get(key_word)
        timeout = int(params.get("operate_timeout", "60"))
        for cmd in re.findall("{(.+?)}", operate_cmd):
            if re.match("shell:", cmd):
                cmd = cmd[6:]
                session.cmd(cmd, timeout=timeout)
            elif re.match("shell_no_reply:", cmd):
                cmd = cmd[15:]
                session.sendline(cmd)
                time.sleep(timeout)
            elif re.match("monitor:", cmd):
                cmd = cmd[8:]
                vm.monitor.send_args_cmd(cmd)

    def cleanup_images(snapshot_chain, params):
        if not params.get("remove_snapshot_images"):
            return []
        errs = []
        for index, image in enumerate(snapshot_chain):
            try:
                image_params = params.object_params(image)
                if index != 0:
                    image = qemu_storage.QemuImg(
                        image_params, data_dir.get_data_dir(), image
                    )
                    if not os.path.exists(image.image_filename):
                        errs.append(
                            "Image %s was not created during test."
                            % image.image_filename
                        )
                    image.remove()
            except Exception as details:
                errs.append(
                    "Fail to remove image %s: %s" % (image.image_filename, details)
                )
        return errs

    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    timeout = int(params.get("login_timeout", 360))
    snapshot_chain = params.get("snapshot_chain")
    snapshot_num = int(params.get("snapshot_num", 0))
    file_create_cmd = params.get("file_create_cmd")
    file_check_cmd = params.get("file_check_cmd")
    file_dir = params.get("file_dir")
    dir_create_cmd = params.get("dir_create_cmd")
    md5_cmd = params.get("md5_cmd")
    sync_cmd = params.get("sync_bin", "sync")

    snapshot_chain = generate_snapshot_chain(snapshot_chain, snapshot_num)
    snapshot_chain = re.split(r"\s+", snapshot_chain)
    session = vm.wait_for_login(timeout=timeout)
    sync_cmd = utils_misc.set_winutils_letter(session, sync_cmd)

    md5_value = {}
    files_in_guest = {}
    try:
        for index, image in enumerate(snapshot_chain):
            image_params = params.object_params(image)
            if image_params.get("file_create"):
                session.cmd(dir_create_cmd % file_dir)
            if index > 0:
                snapshot_file = storage.get_image_filename(
                    image_params, data_dir.get_data_dir()
                )
                base_image = get_base_image(snapshot_chain, image)
                base_image_params = params.object_params(base_image)
                base_file = storage.get_image_filename(
                    base_image_params, data_dir.get_data_dir()
                )
                snapshot_format = image_params.get("image_format")

                error_context.context("Do pre snapshot operates", test.log.info)
                if image_params.get("pre_snapshot_cmd"):
                    do_operate(image_params, "pre_snapshot_cmd")

                error_context.context("Do live snapshot ", test.log.info)
                vm.live_snapshot(base_file, snapshot_file, snapshot_format)

                error_context.context("Do post snapshot operates", test.log.info)
                if image_params.get("post_snapshot_cmd"):
                    do_operate(image_params, "post_snapshot_cmd")
                md5 = ""
                if image_params.get("file_create"):
                    session.cmd(file_create_cmd % image)
                    md5 = session.cmd_output(md5_cmd % image)
                md5_value[image] = md5_value[base_image].copy()
                md5_value[image].update({image: md5})
            elif index == 0:
                md5 = ""
                if params.get("file_create"):
                    session.cmd(file_create_cmd % image)
                    md5 = session.cmd_output(md5_cmd % image)
                md5_value[image] = {image: md5}
            status, output = session.cmd_status_output(sync_cmd)
            if status != 0:
                test.error("Execute '%s' with failures('%s') " % (sync_cmd, output))
            if image_params.get("check_alive_cmd"):
                session.cmd(image_params.get("check_alive_cmd"))
            if image_params.get("file_create"):
                files_check = session.cmd(file_check_cmd % file_dir)
                files_in_guest[image] = files_check
        session.close()

        error_context.context("Reboot guest", test.log.info)
        if image_params.get("need_reboot", "no") == "yes":
            vm.monitor.cmd("system_reset")
            vm.verify_alive()

        error_context.context("Do base files check", test.log.info)
        snapshot_chain_backward = snapshot_chain[:]
        snapshot_chain_backward.reverse()

        for index, image in enumerate(snapshot_chain_backward):
            image_params = params.object_params(image)
            if image_params.get("check_base_image"):
                vm.destroy()
                vm.create(params=image_params)
                vm.verify_alive()

                session = vm.wait_for_login(timeout=timeout)
                if image_params.get("file_create"):
                    for file in md5_value[image]:
                        md5 = session.cmd_output(md5_cmd % file)
                        if md5 != md5_value[image][file]:
                            error_message = "File %s in image %s changed " % (
                                file,
                                image,
                            )
                            error_message += "from '%s' to '%s'(md5)" % (
                                md5_value[image][file],
                                md5,
                            )
                            test.fail(error_message)
                    files_check = session.cmd(file_check_cmd % file_dir)
                    if files_check != files_in_guest[image]:
                        error_message = "Files in image %s is not as expect:" % image
                        error_message += "Before shut down: %s" % files_in_guest[image]
                        error_message += "Now: %s" % files_check
                        test.fail(error_message)
                if image_params.get("image_check"):
                    image = qemu_storage.QemuImg(
                        image_params, data_dir.get_data_dir(), image
                    )
                    image.check_image(image_params, data_dir.get_data_dir())
                session.close()

        error_context.context("Remove snapshot images", test.log.info)
        if vm.is_alive():
            vm.destroy()
        errs = cleanup_images(snapshot_chain, params)
        test.assertFalse(
            errs, "Errors occurred while removing images:\n%s" % "\n".join(errs)
        )
    except Exception as details:
        error_context.context(
            "Force-cleaning after exception: %s" % details, test.log.error
        )
        if vm.is_alive():
            vm.destroy()
        cleanup_images(snapshot_chain, params)
        raise
