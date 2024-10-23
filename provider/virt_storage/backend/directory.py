import os

from provider.virt_storage import storage_volume
from provider.virt_storage.backend import base
from provider.virt_storage.helper import fscli
from provider.virt_storage.utils import storage_util


class DirectoryPool(base.BaseStoragePool):
    TYPE = "directory"

    @property
    def helper(self):
        if self._helper is None:
            self._helper = fscli.FsCli(self.target.path)
        return self._helper

    def find_sources(self):
        return self.helper.list_files()

    def start(self):
        self.helper.create()
        self.refresh()

    def stop(self):
        pass

    def delete(self):
        self.helper.remove()

    def refresh(self):
        files = filter(lambda x: not self.find_volume_by_path, self.find_sources())
        return map(self.create_volume_from_local, files)

    def create_volume_from_local(self, path):
        """
        Create logical volume from local file
        file size maybe mismatch, but need to resize in here
        it will be recreate by qemu-img in next step.

        """
        volume = storage_volume.StorageVolume(self)
        volume.path = path
        volume.url = self.helper.path_to_url(path)
        volume.capacity = self.helper.get_size(path)
        volume.is_allocated = True
        return volume

    def create_volume(self, volume):
        storage_util.create_volume(volume)
        volume.is_allocated = True
        return volume

    def remove_volume(self, volume):
        self.helper.remove_file(volume.path)
        self._volumes.discard(volume)

    def get_volume_path_by_param(self, params):
        image_name = params.get("image_name", self.name)
        image_format = params.get("image_format", "qcow2")
        filename = "%s.%s" % (image_name, image_format)
        return os.path.join(self.target.path, filename)

    def get_volume_by_params(self, params, name):
        volume_params = params.object_params(name)
        path = self.get_volume_path_by_param(volume_params)
        volume = self.get_volume_by_path(path)
        if not volume:
            volume = storage_volume.StorageVolume(self)
            volume.name = name
            volume.path = path
            volume.refresh_with_params(volume_params)
        return volume
