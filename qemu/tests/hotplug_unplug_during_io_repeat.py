import time

from avocado.utils import process
from virttest import error_context, utils_disk, utils_misc

from provider.block_devices_plug import BlockDevicesPlug
from provider.storage_benchmark import generate_instance


@error_context.context_aware
def run(test, params, env):
    """
    Test hotplug of block devices.

    1) Boot up guest with virtio-blk or virtio-scsi system disk.
    2) Hoplug a virtio-blk or virtio-scsi data disk by qmp.
    3) Do read/write data on hotplug block.
    4) Unplug block device during serving block io, then verify devices.
    5) repeat step2~step4 100 times.

    :param test:   QEMU test object.
    :param params: Dictionary with the test parameters.
    :param env:    Dictionary with test environment.
    """

    def _check_iozone_status():
        ck_session = vm.wait_for_login(timeout=360)
        if not utils_misc.wait_for(
            lambda: check_cmd[os_type].split()[-1].lower()
            in ck_session.cmd_output(check_cmd[os_type]).lower(),
            180,
            step=3.0,
        ):
            test.fail("Iozone is not alive!")
        ck_session.close()

    def _run_iozone_background():
        test.log.info("Start iozone under background.")
        thread = utils_misc.InterruptedThread(
            iozone.run,
            (
                params["iozone_options"].format(mount_point),  # pylint: disable=E0606
                float(params["iozone_timeout"]),
            ),
        )
        thread.start()
        _check_iozone_status()
        return thread

    check_cmd = {
        "linux": "pgrep -lx iozone",
        "windows": 'TASKLIST /FI "IMAGENAME eq IOZONE.EXE',
    }
    os_type = params["os_type"]
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    session = vm.wait_for_login(timeout=360)

    iozone = generate_instance(params, vm, "iozone")
    plug = BlockDevicesPlug(vm)
    need_format = True
    try:
        for i in range(int(params["repeat_time"])):
            test.log.info("Start to run testing.(iteration: %d).", (i + 1))
            plug.hotplug_devs_serial()
            dev = plug[0]
            if need_format:
                if os_type == "windows":
                    utils_disk.update_windows_disk_attributes(session, dev)
                else:
                    full_dev = "/dev/" + dev
                    cmd = (
                        "dd if=/dev/zero of={0} bs=1M count=64 oflag=direct "
                        "&& sleep 1; partprobe {0}".format(full_dev)
                    )
                    session.cmd(cmd)

                mount_point = utils_disk.configure_empty_disk(
                    session, dev, params["image_size_stg0"], os_type
                )[0]
                if os_type == "windows":
                    need_format = False
            iozone_thread = _run_iozone_background()
            time.sleep(float(params["sleep_time"]))
            _check_iozone_status()
            plug.unplug_devs_serial()
            iozone_thread.join(suppress_exception=True)
            if need_format and os_type != "windows":
                test.log.info("umount dev:%s", dev)
                session.cmd("mount|grep {0} ; umount /mnt/{0}1 && sleep 3".format(dev))

    except Exception as e:
        pid = vm.get_pid()
        test.log.debug("Find %s Exception:'%s'.", pid, str(e))
        if pid:
            logdir = test.logdir
            process.getoutput("gstack %s > %s/gstack.log" % (pid, logdir))
            process.getoutput(
                "timeout 20 strace -tt -T -v -f -s 32 -p %s -o %s/strace.log"
                % (pid, logdir)
            )
        else:
            test.log.debug("VM dead...")
        raise e
    finally:
        iozone.clean(force=True)
        session.close()
