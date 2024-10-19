from virttest import utils_misc

from qemu.tests import block_copy


class BlockCommit(block_copy.BlockCopy):
    def start(self):
        """
        start block device committing job;
        """
        base_image = self.params["base_image"]
        base_image = utils_misc.get_path(self.data_dir, base_image)
        top_image = self.params["top_image"]
        top_image = utils_misc.get_path(self.data_dir, top_image)
        default_speed = self.params.get("default_speed")
        backing_file = self.params.get("backing_file", None)
        if backing_file is not None:
            backing_file = utils_misc.get_path(self.data_dir, backing_file)

        if self.vm.monitor.protocol == "qmp":
            self.vm.monitor.clear_event("BLOCK_JOB_READY")
            self.vm.monitor.clear_event("BLOCK_JOB_COMPLETED")
        else:
            self.test.cancel("hmp command is not supportable.")
        self.test.log.info("start to commit block device")
        self.vm.block_commit(
            self.device, default_speed, base_image, top_image, backing_file
        )
        status = self.get_status()
        if not status:
            self.test.fail("no active job found")
        self.test.log.info(
            "block commit job running, with limited speed %S B/s", default_speed
        )

    def create_snapshots(self):
        """
        create live snapshot_chain, snapshots chain define in $snapshot_chain
        """
        image_format = self.params["snapshot_format"]
        snapshots = self.params["snapshot_chain"].split()
        self.test.log.info("create live snapshots %s", snapshots)
        for snapshot in snapshots:
            snapshot = utils_misc.get_path(self.data_dir, snapshot)
            image_file = self.get_image_file()
            self.test.log.info("snapshot %s, base %s", snapshot, image_file)
            device = self.vm.live_snapshot(image_file, snapshot, image_format)
            if device != self.device:
                image_file = self.get_image_file()
                self.test.log.info(
                    "expect file: %s, opening file: %s", snapshot, image_file
                )
                self.test.fail("create snapshot '%s' failed" % snapshot)
            self.trash_files.append(snapshot)
