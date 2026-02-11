@(lambda f: f())
def __():
	import os

	from rich.traceback import install

	install(width=os.get_terminal_size().columns)


import pathlib as p
import shutil
import sys
from typing import Annotated as Ann

import arguably
import rich
import rich.box
import rich.table
from rich.markup import escape as esc

from ._version import __version__
from .api import arguably_choices
from .config import WTMPL_CONFIG_TEMPLATES_PATH
from .eval import instantiate_wtmpl_template
from .not_target_return import not_target_return
from .parse_template import ModuleExecError, TemplateInfo

# @arguably.command
# @not_target_return
# def __root__():
# 	print("/")


@arguably.command
@not_target_return
def list_():
	"""Show a list of all installed templates."""

	table = rich.table.Table(
		*(
			"name",
			*TemplateInfo.into_brief_table_headers(),
		),
		# title=str(WTMPL_CONFIG_TEMPLATES_PATH),
		box=rich.box.HEAVY_HEAD,
	)

	for template_path in WTMPL_CONFIG_TEMPLATES_PATH.iterdir():
		try:
			tinfo = TemplateInfo.from_path(template_path)
		except RuntimeError as e:
			table.add_row(
				template_path.name,
				f"[red][b]Internal error in wtmpl machinery: [/b]{esc(str(e))}",
			)
		except ModuleExecError as e:
			table.add_row(
				template_path.name,
				f"[red][b]{esc(e.__cause__.__class__.__name__)}: [/b]{esc(str(e.__cause__))}[/red]\n[blue]  (i) Hint: view the template to view the error traceback",
			)
		else:
			table.add_row(
				template_path.name,
				*tinfo.into_brief_table_row(),
			)

	rich.print(table)


@arguably.command
@not_target_return
def view(name: Ann[str, arguably_choices()]):
	path = WTMPL_CONFIG_TEMPLATES_PATH / name

	tinfo = TemplateInfo.from_path(path)

	table = rich.table.Table("name", name)

	for pair_or_none in tinfo.into_detailed_table_pairs():
		if pair_or_none is None:
			table.add_section()
			continue

		k, v = pair_or_none

		table.add_row(k, v)

	rich.print(table)


@arguably.command
@not_target_return
def new(
	name: Ann[str, arguably_choices()],
	dst_path: p.Path,
	*,
	dry_run: bool = False,
	verbose: Ann[int, arguably.arg.count()] = 0,
):
	"""Instantiate a wtmpl template folder into the specified path (current directory by default if missing) by evaulating all wtmpl expressions in filenames & file contents. Do not read pipes/sockets/(char/block devices) or symlinks to them - make a symlink to the original in the template folder instead.

	Args:
		name: The name of the template (must match one of the present ones in the <SYSTEM_APP_CONFIG_DIR>/wtmpl/templates directory.)
		dst_path: The path where this template should be instantiated, use an existing directory to merge any files within with the template. Use `.` for merger with cwd.
		dry_run: [-d] If provided, dont make any filesystem operations, however any scripts may be evaluted and all dirname/filename/filecontents will be evaluated, but their values not written to the filesystem (thrown out). If provided, verbosity is set to at least 1, even if not provided the --verbose argument, it can still be made more verbose by providing --verbose multiple times.
		verbose: [-v] Can be provided multiple times: `-v -v` or `-vv`, for each one provided increase the verbosity of the logs printed. If `--dry-run/-d` is provided, the verbosity is always >=1 even if this argument is not provided.
	"""

	src_path = WTMPL_CONFIG_TEMPLATES_PATH / name

	instantiate_wtmpl_template(src_path, dst_path, dry_run=dry_run, log_verbosity=max(verbose, int(dry_run)))


def main():
	__main__ = sys.modules["__main__"]

	__main__.__version__ = __version__  # fixes arguably whining of missing version when running as a pyproject.toml script
	__main__.__doc__ = """
WIP
"""[1:-1]

	arguably.run(
		always_subcommand=True,
		version_flag=("-V", "--version"),
		show_types=False,
		show_defaults=False,
	)


if __name__ == "__main__":
	main()
