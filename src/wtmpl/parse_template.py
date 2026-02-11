import importlib.util
import os
import pathlib as p
import sys
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import final

from rich.console import RenderableType


class ModuleExecError(Exception): ...


def bool_to_rich_yes_no(__o: bool, /, *, str_format_fn: Callable[[str], str] = str.title) -> str:
	return f"[b]{f'[green]{str_format_fn("Yes")}' if __o else f'[red]{str_format_fn("No")}'}"


@contextmanager
def pushd(path: p.Path):
	prev = p.Path.cwd()
	os.chdir(path)
	try:
		yield
	finally:
		os.chdir(prev)


@final  # due to how .wtmpl.py file is handled - it will not be aware of any subclasses
@dataclass(kw_only=True, frozen=True)
class TemplateInfo:
	"""### Struct containing information about a wtmpl template."""

	path: p.Path = field(default_factory=p.Path.cwd)
	"""### The path at which the template in question is stored (or has been at the time of creating this object). This defaults to p.Path.cwd() to facilitate easier `info()` method implementation."""

	rich_description: str = "[i]No description provided"
	"""### The description of this template stored as a `rich` string."""

	smart: bool = True
	"""#### Whether the template contains a smart `.wtmpl/` loader script which provides at least a `info()` method to make this `TemplateInfo`.

	##### (This value may not be mistakenly set to `False`  by any buggy template script, because there's a check for that)
	"""

	@staticmethod
	def _dumb_instance_from_path(path: p.Path) -> TemplateInfo:
		return TemplateInfo(path=path, smart=False)

	@staticmethod  # not classmethod because {read comment on @final}
	def from_path(path: p.Path) -> TemplateInfo:
		"""Evaluate the template script at `path` (if any) and produce a `TemplateInfo` from this process. If no script is found, return the dumb template info.

		If `.wtmpl/` is malformed, raise `RuntimeError`.
		"""
		if not (wtmpl_path := path / ".wtmpl").is_dir():
			return TemplateInfo._dumb_instance_from_path(path)

		if not (wtmpl_path / "__init__.py").is_file():
			raise RuntimeError("`.wtmpl/` dir present, but `__init__.py` in it missing.")

		with pushd(path):
			spec = importlib.util.spec_from_file_location(
				(module_name := f"wtmpl/{wtmpl_path.parent.name}"),
				str(wtmpl_path / "__init__.py"),
				submodule_search_locations=[str(wtmpl_path)],
			)
			if spec is None:
				raise RuntimeError("unable to produce an `importlib.util.spec_from_file_location()` ...?")

			module = importlib.util.module_from_spec(spec)
			if module is None:
				raise RuntimeError("unable to produce a `importlib.util.module_from_spec()` ...?")

			if spec.loader is None:
				raise RuntimeError("unable to ackquire a `spec.loader` ...?")

			sys.modules[module_name] = module

			try:
				spec.loader.exec_module(module)
			except BaseException as e:
				raise ModuleExecError(e) from e

			if hasattr(module, "info"):
				tinfo: TemplateInfo = module.info()

				if not isinstance(tinfo, TemplateInfo):
					raise RuntimeError("`(wtmpl/module).info()` did not return a TemplateInfo ...?")

				if tinfo.path.resolve() != path.resolve():
					raise RuntimeError("TemplateInfo().path must be the actual path when returning from `template_module.info()` (Leave blank without changing directory anywhere for the default impl of `p.Path.cwd()` to kick in).")

				if not tinfo.smart:
					raise RuntimeError("TemplateInfo().smart must be True when returning from `template_module.info()`.")

				return tinfo

		return TemplateInfo._dumb_instance_from_path(path)

	@staticmethod
	def into_brief_table_headers() -> tuple[RenderableType, ...]:
		"""Return a tuple of `RenderableType`s (rich headers).

		##### "brief" -> for use in `list` command.
		"""
		return ("description",)

	def into_brief_table_row(self) -> tuple[RenderableType, ...]:
		"""Return a tuple of `RenderableType`s (rich values of corresponding header).

		##### "brief" -> for use in `list` command.
		"""
		row = (self.rich_description,)

		assert len(row) == len(self.into_brief_table_headers())

		return row

	def into_detailed_table_pairs(self) -> tuple[tuple[str, str] | None, ...]:
		"""Return an iterable of header-value pairs which are both rich strings or None (request to insert a .add_section() here).

		##### "detailed" -> for use in `view` command.
		"""

		return (
			("description", self.rich_description),
			None,
			("is smart?", bool_to_rich_yes_no(self.smart)),
		)
