import os

from provider.virt_storage import storage_volume, virt_source, virt_target
from provider.virt_storage.backend import base
from provider.virt_storage.helper import rbdcli


class RBDPool(base.BaseStoragePool):
    TYPE = "rbd"

    def __init__(self, name):
        self.image = None
        self.server = None
        super(RBDPool, self).__init__(name)

    @property
    def helper(self):
        if self._helper is None:
            self._helper = rbdcli.RBDCli(self.source.pool_name)
        return self._helper

    def find_sources(self):
        return self.helper.list_images()

    def start(self):
        pass

    def stop(self):
        pass

    def refresh(self):
        files = filter(lambda x: not self.find_volume_by_path, self.find_sources())
        return map(self.create_volume_on_rbd, files)

    def create_volume_on_rbd(self, path):
        """
        Create volume on rbd

        """
        volume = storage_volume.StorageVolume(self)
        volume.path = path
        volume.capacity = self.helper.get_size(path)
        volume.is_allocated = True
        return volume

    def remove_volume(self, volume):
        self.helper.remove_image(volume.path)
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

    @classmethod
    def pool_define_by_params(cls, name, params):
        inst = cls(name)
        inst.target = virt_target.PoolTarget.target_define_by_params(params)
        inst.target.path = params["rbd_pool_name"]
        source_params = params.object_params(name)
        inst.source = virt_source.PoolSource.source_define_by_params(
            name, source_params
        )
        inst.set_special_opts_by_params(params)
        return inst
