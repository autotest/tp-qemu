import re
import time
import random
import logging

from virttest import utils_misc

from qemu.tests import block_copy


class BlockCommit(block_copy.BlockCopy):
    def __init__(self, test, params, env, tag):
        super(BlockCommit, self).__init__(test, params, env, tag)

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
        logging.info("start to commit block device")
        self.vm.block_commit(self.device, default_speed, base_image, top_image,
                             backing_file)
        status = self.get_status()
        if not status:
            self.test.fail("no active job found")
        logging.info("block commit job running, with limited speed {0} B/s".format(default_speed))

    def create_snapshots(self, create_file=True):
        """
        create live snapshot_chain, snapshots chain define in $snapshot_chain

        :param create_file, create file inside guest or not
        """
        image_format = self.params["snapshot_format"]
        snapshots = self.params["snapshot_chain"].split()
        guest_file_name = self.params["file_names"]
        logging.info("create live snapshots %s" % snapshots)
        for snapshot in snapshots:
            snapshot_name = re.sub("images/", "", snapshot)
            snapshot = utils_misc.get_path(self.data_dir, snapshot)
            image_file = self.get_image_file()
            logging.info("snapshot {0}, base {1}".format(snapshot, image_file))
            device = self.vm.live_snapshot(image_file, snapshot, image_format)
            if device != self.device:
                image_file = self.get_image_file()
                logging.info("expect file: {0}, opening file: {1}".format(snapshot, image_file))
                self.test.fail("create snapshot '%s' failed" % snapshot)
            self.trash_files.append(snapshot)
            # By default, create file inside guest after each snapshot,
            # or sleep for a while for vm to generate data by itself.
            if create_file:
                self.create_file("%s_%s" % (guest_file_name, snapshot_name))
            else:
                time.sleep(random.uniform(10, 100))

    def verify_backingfile(self):
        """
        check no backingfile found after commit job done via qemu-img info;
        """
        logging.info("Check image backing-file")
        exp_img_file = self.params["expected_image_file"]
        exp_img_file = utils_misc.get_path(self.data_dir, exp_img_file)
        logging.debug("Expected image file read from config file is '%s'" % exp_img_file)

        backingfile_monitor = self.get_backingfile("monitor")
        backingfile_qemu_img = self.get_backingfile("qemu_img")
        if backingfile_monitor:
            logging.info("Got backing-file: #{0}# by 'info/query block' in #{1}# "
                         "monitor".format(backingfile_monitor, self.vm.monitor.protocol))
        if exp_img_file == backingfile_monitor == backingfile_qemu_img:
            logging.info("check backing file with monitor and qemu-img passed")
        else:
            self.test.fail("backing file is different with the expected one. "
                           "expecting: %s, monitor feedback: %s, qemu-img feedback %s" %
                           (exp_img_file, backingfile_monitor, backingfile_qemu_img))
