import shutil
import sys
from importlib import resources

from platformdirs import user_config_path


def _put_default_templates_into_templates_folder_if_not_exists():
	if "--DEV-DANGEROUS-OPTION-REMOVE-IN-PROD-RESTORE-DEFAULT-CONFIG" in sys.argv:
		1 - 1
		if WTMPL_CONFIG_TEMPLATES_PATH.exists():
			shutil.rmtree(WTMPL_CONFIG_TEMPLATES_PATH)
		sys.argv.remove("--DEV-DANGEROUS-OPTION-REMOVE-IN-PROD-RESTORE-DEFAULT-CONFIG")

	if WTMPL_CONFIG_TEMPLATES_PATH.exists():
		return

	default_templates_path = resources.files("wtmpl") / "default_templates"

	shutil.copytree(default_templates_path, WTMPL_CONFIG_TEMPLATES_PATH)


WTMPL_CONFIG_PATH = user_config_path() / "wtmpl"
WTMPL_CONFIG_PATH.mkdir(exist_ok=True, parents=True)

WTMPL_CONFIG_TEMPLATES_PATH = WTMPL_CONFIG_PATH / "templates"
_put_default_templates_into_templates_folder_if_not_exists()  # this includes a mkdir()
