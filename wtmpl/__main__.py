import pathlib as p
from functools import wraps

import arguably
import rich
import rich.traceback
import tcrutils as tcr
from rich import print
from tcrutils import c

from . import config
from .version import __version__

rich.traceback.install(show_locals=True)


# def only_target(f):
# 	@wraps(f)
# 	def wrapper(*args, **kwargs):
# 		if not arguably.is_target():
# 			return None
# 		return f(*args, **kwargs)

# 	return wrapper


@arguably.command
def config_(key: str = None, value: str = None, *, reset: bool = False):
	"""Show, change or reset the wtmpl configuration.

	Args:
		key: The settings key, if not provided print all settings.
		value: The new value for the given setting key, if not provided print setting at key.
		reset: Reset the settings to the default values (key or key+value actions stilly apply if specified, though not recommended). This *should* fix any corupted configs.
	"""

	if reset:
		config.reset()
		print("[green][b]Successfully reset the config!")

	conf = config.get()

	if key is None:
		tcr.print_iterable(conf, syntax_highlighting=True)
		return

	if key not in conf.model_fields:
		print(f"[red][b]Unknown key: {key!r}")
		return

	if value is None:
		tcr.print_iterable(getattr(conf, key), syntax_highlighting=True)
		return

	setattr(conf, key, value)
	config.save(conf)
	tcr.print_iterable(conf, syntax_highlighting=True)


def main():
	arguably.run(
		name=p.Path(__file__).parent.name,
		always_subcommand=True,
		version_flag=("-V", "--version"),
	)


if __name__ == "__main__":
	main()
