import arguably

from ..config import WTMPL_CONFIG_TEMPLATES_PATH


def iter_template_paths():
	yield from (path for path in WTMPL_CONFIG_TEMPLATES_PATH.iterdir() if path.is_dir())


def iter_template_names():
	yield from (path.name for path in iter_template_paths())


def arguably_choices():
	return arguably.arg.choices(*iter_template_names())
