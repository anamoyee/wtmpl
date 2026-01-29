import arguably

from .not_target_return import not_target_return


@arguably.command
@not_target_return
def __root__():
	if not arguably.is_target():
		return

	print("/")


@arguably.command
@not_target_return
def list_():
	print("/list")


def main():
	import sys

	from ._version import __version__

	sys.modules["__main__"].__version__ = __version__  # fixes arguably whining of missing version when running as a pyproject.toml script

	arguably.run(
		always_subcommand=True,
		version_flag=("-V", "--version"),
	)


if __name__ == "__main__":
	main()
