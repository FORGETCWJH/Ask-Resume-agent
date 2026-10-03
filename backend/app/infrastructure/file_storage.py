import shutil
from pathlib import Path

from ..config import settings


class LocalFileStorage:
    def material_dir(self, set_id: str, revision_id: str) -> Path:
        return settings.app_data_dir / "material-sets" / set_id / revision_id

    def delete_material_set(self, set_id: str) -> None:
        shutil.rmtree(settings.app_data_dir / "material-sets" / set_id, ignore_errors=True)

