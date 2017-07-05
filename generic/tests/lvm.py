import os
import logging
from virttest import error_context
from virttest import utils_misc
from virttest import utils_test


@error_context.context_aware
def mount_lv(lv_path, session):
    error_context.context("mounting ext3 filesystem made on logical volume %s"
                          % os.path.basename(lv_path), logging.info)
    session.cmd("mkdir -p /mnt/kvm_test_lvm")
    session.cmd("mount %s /mnt/kvm_test_lvm" % lv_path)


@error_context.context_aware
def umount_lv(lv_path, session):
    error_context.context("umounting ext3 filesystem made on logical volume "
                          "%s" % os.path.basename(lv_path), logging.info)
    session.cmd("umount %s" % lv_path)
    session.cmd("rm -rf /mnt/kvm_test_lvm")


@error_context.context_aware
def check_mount_lv(check_mount, session):
    error_context.context("Check the lvm is mounted or not", logging.info)
    s, o = session.cmd_status_output(check_mount)
    if "is not a mountpoint" in o or s != 0:
        logging.info("lvm is not mounted")
        return False
    else:
        return True


@error_context.context_aware
def run(test, params, env):
    """
    KVM reboot test:
    1) Log into a guest
    2) Create a volume group and add both disks as pv to the Group
    3) Create a logical volume on the VG
    5) `fsck' to check the partition that LV locates

    :param test: kvm test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    timeout = int(params.get("login_timeout", 360))
    session = vm.wait_for_login(timeout=timeout)

    vg_name = "vg_kvm_test"
    lv_name = "lv_kvm_test"
    lv_path = "/dev/%s/%s" % (vg_name, lv_name)
    clean = params.get("clean", "yes")
    timeout = params.get("lvm_timeout", "600")
    check_mount = params.get("check_mount", "mountpoint /mnt/kvm_test_lvm")
    sub_type = params.get("sub_type", "lvm_create")
    try:
        if sub_type == "lvm_create":
            disk_list = []
            for disk in params.objects("images")[-2:]:
                d_id = params["blk_extra_params_%s" % disk].split("=")[1]
                d_path = utils_misc.get_linux_drive_path(session, d_id)
                if not d_path:
                    test.error("Failed to get '%s' drive path" % d_id)
                disk_list.append(d_path)
            disks = " ".join(disk_list)
            error_context.context("adding physical volumes %s" % disks,
                                  logging.info)
            session.cmd("pvcreate %s" % disks)
            error_context.context("creating a volume group out of %s" % disks,
                                  logging.info)
            session.cmd("vgcreate %s %s" % (vg_name, disks))
            error_context.context("activating volume group %s" % vg_name,
                                  logging.info)
            session.cmd("vgchange -ay %s" % vg_name)
            error_context.context("creating logical volume on volume group %s"
                                  % vg_name, logging.info)
            session.cmd("lvcreate -L2000 -n %s %s" % (lv_name, vg_name))
            error_context.context("creating ext3 filesystem on logical volume"
                                  " %s" % lv_name, logging.info)
            session.cmd("yes | mkfs.ext3 %s" % lv_path, timeout=int(timeout))
            mount_lv(lv_path, session)
            umount_lv(lv_path, session)
            error_context.context("checking ext3 filesystem made on logical "
                                  "volume %s" % lv_name, logging.info)
            session.cmd("fsck %s" % lv_path, timeout=int(timeout))
            if clean == "no":
                mount_lv(lv_path, session)
        elif sub_type == "fillup_disk" or sub_type == "ioquit":
            if not check_mount_lv(check_mount, session):
                mount_lv(lv_path, session)
            utils_test.run_virt_sub_test(test, params, env, sub_type)
        elif sub_type == "lvm_clean":
            pass
        else:
            test.error("Failed to get sub_type")
    finally:
        if clean == "yes":
            if check_mount_lv(check_mount, session):
                umount_lv(lv_path, session)
            error_context.context("removing logical volume %s" % lv_path,
                                  logging.info)
            session.cmd("yes | lvremove %s" % lv_path)
            error_context.context("disabling volume group %s" % vg_name,
                                  logging.info)
            session.cmd("vgchange -a n %s" % vg_name)
            error_context.context("removing volume group %s" % vg_name,
                                  logging.info)
            session.cmd("vgremove -f %s" % vg_name)
        session.close()
