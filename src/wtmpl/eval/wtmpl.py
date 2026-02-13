import abc
import os
import pathlib as p
import re
import tempfile
from collections.abc import Callable, Iterable, Iterator, Mapping
from dataclasses import dataclass, field
from enum import StrEnum, auto
from mimetypes import suffix_map
from types import CodeType
from typing import TYPE_CHECKING, Any, Literal, Self

import rich
from gitignore_parser import parse_gitignore, parse_gitignore_str  # type: ignore
from rich.markup import escape as esc

from . import error
from .util import iter_subpath_chain, ls_char, pathlib_os_walk


class _TriggerSequenceABC(abc.ABC):
	@abc.abstractmethod
	def build_enter_exit_patterns(self, escaped_default_brace_pair: tuple[str, str]) -> Iterable[tuple[re.Pattern, re.Pattern]]: ...

	@staticmethod
	def merged_braces_to_enter_exit_pair(brace_l: str, brace_r: str) -> tuple[re.Pattern, re.Pattern]:
		return (
			re.compile(f"{brace_l}(?P<is_exec>!?)"),
			re.compile(f"{brace_r}"),
		)

	def __iter__(self) -> Iterator[Self]:
		return iter((self,))  # implement shorthand for `overrides={".py": self}` instead of having to do `{".py": [self]}`


@dataclass
class LineCommentTriggerSequence(_TriggerSequenceABC):
	opening: str

	optional_language_specific_part: bool = field(kw_only=True, default=False)
	optional_whitespace_between_parts: bool = field(kw_only=True, default=True)

	def _line_comment(self, *, escaped_default_brace_pair: tuple[str, str]) -> tuple[re.Pattern, re.Pattern]:
		"""Given the non-`re.escaped` param: `start` of a programming language's line comment start sequence, return a `re.Pattern` which matches the wtmpl expression in this language."""
		default_brace_escaped_l, default_brace_escaped_r = escaped_default_brace_pair

		escaped_opening = re.escape(self.opening)

		optional_language_specific_part_REGEX = "?" if self.optional_whitespace_between_parts else ""
		optional_whitespace_between_parts_REGEX = "\\s*" if self.optional_whitespace_between_parts else ""

		brace_l, brace_r = (
			f"(?:{escaped_opening}{optional_whitespace_between_parts_REGEX if escaped_opening else ''}){optional_language_specific_part_REGEX}{default_brace_escaped_l}",
			# '# {{'
			f"(?:{escaped_opening}{optional_whitespace_between_parts_REGEX if escaped_opening else ''})?{default_brace_escaped_r}",
			# '# }}' OR '}}'
			# the former if expr spans multiple lines
			# the latter if the expr doesnt, and/or it's possible to end the expr without starting another language comment
		)

		return self.merged_braces_to_enter_exit_pair(brace_l, brace_r)

	def build_enter_exit_patterns(self, escaped_default_brace_pair: tuple[str, str]) -> list[tuple[re.Pattern, re.Pattern]]:
		return [self._line_comment(escaped_default_brace_pair=escaped_default_brace_pair)]


@dataclass
class BlockCommentTriggerSequence(_TriggerSequenceABC):
	opening: str
	closing: str

	optional_language_specific_part: bool = field(kw_only=True, default=False)
	optional_whitespace_between_parts: bool = field(kw_only=True, default=True)

	def _block_comment(self, *, escaped_default_brace_pair: tuple[str, str]) -> tuple[re.Pattern, re.Pattern]:
		"""Given the non-`re.escaped` params: `start` and `end` of a programming language's block comment start and end sequences, return a `re.Pattern` which matches the wtmpl expression in this language."""
		default_brace_escaped_l, default_brace_escaped_r = escaped_default_brace_pair

		optional_language_specific_part_REGEX = "?" if self.optional_whitespace_between_parts else ""
		optional_whitespace_between_parts_REGEX = "\\s*" if self.optional_whitespace_between_parts else ""

		escaped_opening = re.escape(self.opening)
		escaped_closing = re.escape(self.closing)

		brace_l, brace_r = (
			f"(?:{escaped_opening}{optional_whitespace_between_parts_REGEX if escaped_opening else ''}){optional_language_specific_part_REGEX}{default_brace_escaped_l}",
			# '<!--{{'
			f"{default_brace_escaped_r}(?:{optional_whitespace_between_parts_REGEX if escaped_closing else ''}{escaped_closing}){optional_language_specific_part_REGEX}",
			# '}}-->'
		)

		return self.merged_braces_to_enter_exit_pair(brace_l, brace_r)

	def build_enter_exit_patterns(self, escaped_default_brace_pair: tuple[str, str]) -> Iterable[tuple[re.Pattern, re.Pattern]]:
		return [self._block_comment(escaped_default_brace_pair=escaped_default_brace_pair)]


def wtmpl_eval(
	s: str,
	*,
	suffix: str | None,
	src_path: p.Path,
	override_language_trigger_sequences: Mapping[str, Iterable[_TriggerSequenceABC]] = {},
	default_brace_pair: tuple[str, str] = ("{{", "}}"),
) -> str:
	"""Evaluate the given str as a wtmpl expression. The expr braces differ based on the filename, for example in HTML it's `<!--{{ expr }}-->`, in js it's `/*{{ expr }}*/`.

	Args:
		s: The expression to evaluate
		suffix: The file extension including the `'.'`, for example `'.py'`, `'.md'`. If evaluating filename, None.
		override_unescaped_brace_pairs: For each key, a `.`-included filename extension like: `'.html'`, all provided comments (in the value: list) will be usable with `wtmpl` expressions. If a comment provided is just a string, it's considered an inline comment (has no "closing" variant), otherwise the two tuple elements are considered to be (opening, closing). Example: `{".html": [("<!--", "-->")], ".py": ["#"]}`. Those strings will be `re.escape`d later by the function - they are provided unescaped.
	"""
	unescaped_default_brace_l, unescaped_default_brace_r = default_brace_pair
	escaped_default_brace_pair = (
		re.escape(unescaped_default_brace_l),
		re.escape(unescaped_default_brace_r),
	)

	suffix_to_trigger_sequence_builders_lookup: dict[str, Iterable[_TriggerSequenceABC]] = {
		".txt": LineCommentTriggerSequence(""),
		".html": BlockCommentTriggerSequence("<!--{{", "}}-->"),
		".py": LineCommentTriggerSequence("#", optional_language_specific_part=True),
		# this is actually the time i wish for the TS types in python
		# ```ts
		# unescaped_brace_pairs_lookup extends dict["" | f".{str}", ...]
		# ```
		# But i do know it's impossible to properly express with all the python metaclassery,,,
		**override_language_trigger_sequences,
	}

	if not all((key == "" or key.startswith(".")) for key in suffix_to_trigger_sequence_builders_lookup):
		raise ValueError('Invalid structure of `override_language_trigger_sequences`, each key must be either `""` or `startswith(".")`.')

	lang_to_pattern_lookup = {
		k: [
			pattern  #
			for ts in v
			for pattern in ts.build_enter_exit_patterns(escaped_default_brace_pair)
		]
		for k, v in suffix_to_trigger_sequence_builders_lookup.items()
	}

	if suffix is None:
		patterns = LineCommentTriggerSequence("").build_enter_exit_patterns(escaped_default_brace_pair)
	elif suffix in lang_to_pattern_lookup:
		patterns = lang_to_pattern_lookup[suffix]
	else:
		patterns = LineCommentTriggerSequence("#").build_enter_exit_patterns(escaped_default_brace_pair)

	def _setup_exec_dict() -> dict[str, Any]:

		class ShorthandImporter:
			def __init__(self, current_path: tuple[str, ...] = ()):
				self.current_path = current_path

			def __call__(self, *last_minute_path_components: str):
				return __import__(".".join((*self.current_path, *last_minute_path_components)), fromlist=["*"])

			def __getattr__(self, name: str):
				return object.__getattribute__(self, "__class__")((*self.current_path, name))

			def __getitem__(self, name: str):
				return object.__getattribute__(self, "__class__")((*self.current_path, name))

		return {
			"imp": ShorthandImporter(),
		}

	if True:

		class Node: ...

		@dataclass
		class TextNode(Node):
			text: str
			span: tuple[int, int]

		@dataclass(kw_only=True)
		class ExprNode(Node):
			span: tuple[int, int]
			groupdict: dict[str, str]
			children: list[Node]

			def get_expr_text(self, s: str) -> str:
				return s[slice(*self.span)]

		@dataclass
		class StackEntry:
			entering_match_span_end: int
			groupdict: dict[str, str]

		def _parse(s: str, patterns):
			# stack of node-lists (this creates the tree)
			node_stack: list[list[Node]] = [[]]

			# stack of open expression metadata
			expr_stack: list[StackEntry] = []

			i = 0
			n = len(s)

			while i < n:
				matched = False

				for enter_pat, exit_pat in patterns:
					# ---- ENTER ----
					if m := re.match(enter_pat, s[i:]):
						i += m.end()

						expr_stack.append(
							StackEntry(
								entering_match_span_end=i,
								groupdict=m.groupdict(),
							)
						)

						# new child node list
						node_stack.append([])

						matched = True
						break

					# ---- EXIT ----
					if m := re.match(exit_pat, s[i:]):
						if not expr_stack:
							raise ValueError("Unbalanced braces: closed more than opened")

						entry = expr_stack.pop()
						children = node_stack.pop()

						expr_span = (entry.entering_match_span_end, i)

						node_stack[-1].append(
							ExprNode(
								span=expr_span,
								groupdict=entry.groupdict,
								children=children,
							)
						)

						i += m.end()
						matched = True
						break

				if matched:
					continue

				# ---- TEXT ----
				# collect continuous text for efficiency
				text_start = i
				while i < n:
					for enter_pat, exit_pat in patterns:
						if re.match(enter_pat, s[i:]) or re.match(exit_pat, s[i:]):
							break
					else:
						i += 1
						continue
					break

				node_stack[-1].append(
					TextNode(
						text=s[text_start:i],
						span=(text_start, i),
					)
				)

			if expr_stack:
				raise ValueError("Unbalanced braces: left opened at end of string")

			return node_stack[0]

	if True:  # eval & highlight errors

		def compile_synthetic(expr: str, src_path: p.Path, mode: str) -> tuple[p.Path, Callable[[], CodeType]]:

			with tempfile.TemporaryDirectory(prefix="wtmpl-inflight-", delete=False) as dir_strpath:
				src_path = src_path.resolve()

				tmp_file_path = p.Path(dir_strpath) / src_path.relative_to("/").with_name(f"{src_path.name}.py")

				tmp_file_path.parent.mkdir(parents=True)

				tmp_file_path.write_text(
					f"# {
						str(src_path).replace('\b', '\\b')  # could be more of the edge cases but i cant think of any
					}\n{expr}"
				)

			return tmp_file_path, lambda: compile(f"\n{expr}", filename=str(tmp_file_path), mode=mode)

		def evaluate_node(node: Node, s: str, exec_dict: dict, src_path: p.Path):
			if isinstance(node, TextNode):
				return node.text
			if isinstance(node, ExprNode):
				pass  # continue on
			else:
				raise TypeError(f"Expected Node subclass, got: {node.__class__!r}")

			rendered_children = [evaluate_node(child, s, exec_dict, src_path) for child in node.children]

			expr_source = "".join(rendered_children).strip()

			d = node.groupdict

			if "is_exec" not in d:
				raise RuntimeError("BUG: missing 'is_exec'")

			is_exec = bool(d["is_exec"])
			mode = "exec" if is_exec else "eval"

			tmp_file = None

			try:
				tmp_file, make_compiled = compile_synthetic(expr_source, src_path, mode)

				if is_exec:
					exec(make_compiled(), exec_dict, exec_dict)
					retval = exec_dict.get("_", "")
				else:
					retval = eval(make_compiled(), exec_dict, exec_dict)

			except BaseException as e:
				raise error.TemplateArbitrary.BaseError(e) from e
			else:
				if tmp_file is not None:
					tmp_file.unlink(missing_ok=True)

			return str(retval)

	root_nodes = _parse(s, patterns)

	return "".join(evaluate_node(node, s, _setup_exec_dict(), src_path) for node in root_nodes)


if False:  # scrap the merge strategy idea, treat everything as `KEEP_ORIGINAL_AND_WARN` by default (and merge directories). Maybe revive this idea in the future...?

	class MergeStrategy(StrEnum):
		"""Represents types of merge strategies a pair of files (src, dst) can undergo in order to resolve the conflict of the template file wanting to replace the destination file when the latter exists."""

		OVERRIDE_ORIGINAL = auto()
		"""### That strategy's behaviour depends on the file type, see the rules below.

		---

		# Matching rules
		(apply top to bottom, first to match wins)

		---

		## for `src` is a directory, `dst` is a directory
		Merge the directory contents - think of it like "mkdir(exist_ok=True) and proceed".

		---

		## for `src` is a directory, `dst` is NOT a directory
		Act as the `KEEP_ORIGINAL` variant, if you need behaviour where the directory is `rm -rf`'ed, see `OVERRIDE_ORIGINAL_FORCE`

		---

		## for `src` is NOT a directory, `dst` is a directory
		Act as the `KEEP_ORIGINAL` variant, if you need behaviour where the directory is `rm -rf`'ed, see `OVERRIDE_ORIGINAL_FORCE`

		---

		## for `filetype(src) == filetype(dst)`
		Remove the destination file and replace it with the new one.

		---

		## otherwise
		Act as the `KEEP_ORIGINAL_AND_WARN` variant, if you need behaviour where the destination is `rm -rf`'ed, see `OVERRIDE_ORIGINAL_FORCE`

		"""

		OVERRIDE_ORIGINAL_AND_WARN = auto()
		"""Same as `OVERRIDE_ORIGINAL`, but also prints a yellow warning message to the stderr that this has happend and which paths were in conflict.

		##### The default strategy only for directories if not specified (for non-directories it's `KEEP_ORIGINAL_AND_WARN`)
		"""
		OVERRIDE_ORIGINAL_FORCE = auto()
		"""⚠️⚠️⚠️ BE CAREFUL WITH THIS ONE ⚠️⚠️⚠️. For **ALL filetypes**: if the destination exists, and is of any type including directories, solve the conflict by doing the equivalent of `rm -rf destination`. This will delete entire trees of directories if prompted to."""

		KEEP_ORRIGINAL = auto()
		"""Forget about this file from the template, as if it was `.wtmplignore`d. For directories this will effectively `.wtmplignore` all its descendants as well. use `OVERRIDE_ORIGINAL` if you dont like this behaviour."""
		KEEP_ORIGINAL_AND_WARN = auto()
		"""Same as `KEEP_ORIGINAL`, but also prints a yellow warning message to the stderr that this has happend and which paths were in conflict.

		##### The default strategy for non-directories if not specified (for directories it's `OVERRIDE_ORIGINAL`).
		"""
		KEEP_ORIGINAL_AND_ERROR = auto()
		"""Same as `KEEP_ORIGINAL`, but also prints a red error message to the stderr that this has happend and which paths were in conflict, after which it immediatelly exits the template instantiation potentially leaving the directory in an unsound state."""

		PASTE_ORIGINAL_ABOVE_NEW = auto()
		"""
		Merge the two regular files by reading them both, and writing to the destination file a concatenation of both strings, where the original file's contents are above the new one's

		⚠️ Only applicable when both `src` and `dst` are regular files, this will not attempt to read the contents of a symlink or a device file. If selected on a non-file, will result in a state simillar to `KEEP_ORIGINAL_AND_ERROR` but also this fundamental flaw is pointed out in stderr.
		"""
		PASTE_ORIGINAL_BELOW_NEW = auto()
		"""
		Merge the two regular files by reading them both, and writing to the destination file a concatenation of both strings, where the original file's contents are below the new one's

		⚠️ Only applicable when both `src` and `dst` are regular files, this will not attempt to read the contents of a symlink or a device file. If selected on a non-file, will result in a state simillar to `KEEP_ORIGINAL_AND_ERROR` but also this fundamental flaw is pointed out in stderr.
		"""
		PASTE_ORIGINAL_HERE = auto()
		"""
		Merge the two regular files by reading them both, and in the read source content find the marker that defined this merge strategy, remove it, then paste the original content in place of it, at the end write to the destination file the merged content.

		⚠️ Only applicable when both `src` and `dst` are regular files AND this marker was defined from within the file, not the filename, this will not attempt to read the contents of a symlink or a device file. If selected on a non-file or within the filename, will result in a state simillar to `KEEP_ORIGINAL_AND_ERROR` but also this fundamental flaw is pointed out in stderr.
		"""

		_match: re.Match | None

		@classmethod
		def from_str(cls, s: str) -> Self | None:
			"""In the string `s` find the first occurence of the `wtmpl_merge_strategy=` marker and resolve it into one of the enum variants. This will raise a `ValueError` if `wtmpl_merge_strategy=` was found, but the value after `=` is not a valid enum variant. You can view the `re.Match` in `s` by accessing the `MergeStrategy.from_str(...)._match` attribute on the instance. `._match` will always be non-`None` if this classmethod was used to create an instance and an instance was actually created (aka, This method did not raise an error or return None itself)."""

			match = re.search(r"wtmpl_merge_strategy=([a-zA-Z_]*)", s)

			if match is None:
				return None

			self = cls(match.group(1).lower())

			self._match = match

			return self

		@classmethod
		def from_path(cls, path: p.Path) -> Self | None:
			"""Same as `.from_str()`, but extracts the `path.name` as the str."""
			return cls.from_str(path.name)

		@classmethod
		def default_for_dir(cls) -> Literal[MergeStrategy.OVERRIDE_ORIGINAL_AND_WARN]:
			return cls.OVERRIDE_ORIGINAL_AND_WARN

		@classmethod
		def default_for_nondir(cls) -> Literal[MergeStrategy.KEEP_ORIGINAL_AND_WARN]:
			return cls.KEEP_ORIGINAL_AND_WARN


def instantiate_wtmpl_template(
	src_root_path: str | p.Path,
	dst_root_path: str | p.Path,
	*,
	dry_run: bool,
	log_verbosity: int = 0,
):
	"""Simillar to `shutil.copytree` but allows wtmpl advanced templating.

	## Args
		src_root_path: A path pointing to a directory that is the source. This path must exist and `.is_dir()`.
		dst_root_path: A path pointing to a directory that is the destination. Its parent must exist.
		dry_run: If set, do not use the copy/copytree functions (do not alter the filesystem), useful with the `log_verbosity` option.
		log_verbosity: If >=1, print any messages at all, for more info about verbosity levels read the function docstring.

	#### Verbosity levels (for the `log_verbosity` argument):
		- Verbosity `1`: Print the basic one-line messsages
		- Verbosity `2`: Print all messages for lower verbosity level(s) and file contents of evaluated files.

	---

	If the following folder structure resides at **example path** `/templates/new-py-project` (which is the src_root_path in the code sample later):
	```
	pyproject.toml
	src/
		__init__.py
	tests/
		test_example.py
	ruff.toml -> /ruff-configs/py314/ruff.toml
	```
	(the arrow notation being a symlink)

	then

	```python
	copytree_wtmpl_eval(
		"/templates/new-py-project",
		"/home/user/projects/my-game", # doesnt exist!
	)
	```

	will perform a tree copy evaluating all filenames, files inbetween.
	"""
	# MS = MergeStrategy

	src_root_path = p.Path(src_root_path).resolve()
	dst_root_path = p.Path(dst_root_path).resolve()

	if not dst_root_path.parent.exists():
		raise ValueError(f"dst_root_path.parent (f'{{dst_root_path}}/..') must exist for this funciton to work correctly (read the docstring for more info).")
	if not src_root_path.is_dir():
		raise ValueError("src_root_path must exist for this funciton to work correctly.")

	def convert_src_to_dst_path(src_path: p.Path) -> p.Path:
		dst_path = dst_root_path / src_path.relative_to(src_root_path)
		# guaranteed no ValueError from relative_to() because a item_root or path from dirs, files will be passed here, which always is a child path of src_root_path

		new_name = wtmpl_eval(
			dst_path.name,
			suffix=None,
			src_path=src_path,
		)

		try:
			return dst_path.with_name(new_name)
		except ValueError as e:
			raise error.Issue.RequestedNewFilenameInvalidError(new_name) from e

	if log_verbosity or TYPE_CHECKING:

		def _verbosity_print(
			*items: p.Path,
			sep: str = ", ",
			color: str = "default",
			ls_char: str = "-",
			relative_path_if_possible: bool = True,
			found_existing: bool | str = False,
		):
			relative_items = (
				(
					path.relative_to(dst_root_path)
					if relative_path_if_possible and path.is_relative_to(dst_root_path)  #
					else path
				)
				for path in items
			)

			display_items = (str(x) for x in relative_items)

			if isinstance(found_existing, str):
				found_existing_msg = f"[i]({esc(found_existing)})[/i]"
			else:
				found_existing_msg = "" if not found_existing else "[i](found existing)[/i]"

			rich.print(f"\\[ [green b]OK[/] ] [{esc(color)}][b]{esc(ls_char)}[/b] {sep.join(display_items)}{f' {found_existing_msg}'.rstrip()}")

	def _warn_for_merge_traditional(msg: str, *, color: str = "yellow", noun: str = "warn"):
		rich.print(f"\\[[{esc(color)}][b]{esc(noun.upper())}[/b][/]] [{esc(color)}]{msg}")

	def _warn_for_merge_simplified(
		heading: str,
		*,
		tmpl_rel_path: p.Path,
		dst_rel_path: p.Path,
		hint: str | None = "You can resolve this conflict by deleting or moving the destination file.",
		color: str = "yellow",
		noun: str = "warn",
	):
		hint_s = f"[blue](i) Hint: {esc(hint)}[/blue]" if hint is not None else None

		s = f"""
{heading}
  ->    [u]/template/{esc(str(tmpl_rel_path))}[/u]
  -> [u]/destination/{esc(str(dst_rel_path))}[/u]
  {f"{hint_s} " if hint_s is not None else ""}[i]Skipping this path as if it was .wtmplignored...
"""[1:-1]

		s += ""

		return _warn_for_merge_traditional(s, color=color, noun=noun)

	found_existing: bool | str = dst_root_path.exists(follow_symlinks=False)

	if found_existing:
		found_existing = f"found existing: {ls_char(dst_root_path)}"

	if found_existing:
		if dst_root_path.is_dir(follow_symlinks=False):
			pass  # proceed
		else:
			_warn_for_merge_traditional(
				f"Unable to merge with existing and non-directory destination: {dst_root_path}",
				color="red",
				noun="error",
			)
			raise error.Issue.DestinationIsAFileError(dst_root_path)
	else:
		if not dry_run:
			dst_root_path.mkdir()

	if log_verbosity:
		_verbosity_print(
			dst_root_path,
			ls_char="d",
			color="blue",
			relative_path_if_possible=False,
			found_existing=found_existing,
		)

	for item_root_path, src_item_dirs, src_item_files in pathlib_os_walk(src_root_path):

		def wtmplignore_match_path_as_ok(
			path: p.Path,
			*,
			__wtmplignore_matchers: Iterable[Callable[[str], bool]] = (
				parse_gitignore_str(".wtmpl/", str(src_root_path)),
				*(
					parse_gitignore(str(path))
					for path in (
						path / ".wtmplignore"  #
						for path in iter_subpath_chain(src_root_path, item_root_path)  # type: ignore # <-- mypy dumb, see first lines of the function
					)
					if path.is_file()
				),
			),
		) -> bool:
			"""Return True, if all matchers of wtmplignore_matchers return that the file of given path is NOT ignored, return False if ignored."""
			return not any(matcher(str(path)) for matcher in __wtmplignore_matchers)

		for src_item_dir in src_item_dirs.copy():  # copy: a safeguard if any 'list changed during iteration' or wahtever bullshit might come up... idk if this is needed.
			if not wtmplignore_match_path_as_ok(src_item_dir):
				src_item_dirs.remove(src_item_dir)  # let pathlib_os_walk() know not to get into this directory by mutating the list
				continue

			try:
				dst_item_dir = convert_src_to_dst_path(src_item_dir)
			except error.Action.DontIncludeError:
				src_item_dirs.remove(src_item_dir)
				continue
			except error.Action.BaseError as e:
				raise error.Issue.ActionUnsupportedInFileNameError(e) from e
			except error.TemplateArbitrary.BaseError as e:
				raise e.e from None

			found_existing = dst_item_dir.exists(follow_symlinks=False)

			if found_existing:
				found_existing = f"found existing: {ls_char(dst_item_dir)}"

			if found_existing and not dst_item_dir.is_dir(follow_symlinks=False):
				_warn_for_merge_simplified(
					heading="Unable to merge paths because first one is a directory and the second one is a file (will not override data automatically)",
					tmpl_rel_path=src_item_dir.relative_to(src_root_path),
					dst_rel_path=dst_item_dir.relative_to(dst_root_path),
					hint="You can resolve this conflict by deleting or moving the destination file.",
				)
				src_item_dirs.remove(src_item_dir)

			if not dry_run:
				if found_existing:
					pass  # nothing to do, dir already exists, but proceed to verbosity print
				else:  # doesnt exist - no merge conflict
					dst_item_dir.mkdir(exist_ok=True)

			if log_verbosity:
				_verbosity_print(
					dst_item_dir,
					color="blue",
					ls_char="d",
					found_existing=found_existing,
				)

		for src_item_file in src_item_files:
			if not wtmplignore_match_path_as_ok(src_item_file):
				continue

			try:
				dst_item_file = convert_src_to_dst_path(src_item_file)
			except error.Action.DontIncludeError:
				continue
			except error.Action.BaseError as e:
				raise error.Issue.ActionUnsupportedInFileNameError(e) from e
			except error.TemplateArbitrary.BaseError as e:
				raise e.e from None

			if src_item_file.is_symlink():
				found_existing = dst_item_file.exists(follow_symlinks=False)

				if found_existing:
					found_existing = f"found existing: {ls_char(dst_item_file)}"

				if found_existing and not dst_item_file.is_symlink():
					_warn_for_merge_simplified(
						heading="Unable to merge paths because first one is a symlink and the second one is a non-symlink (will not override data automatically)",
						tmpl_rel_path=src_item_file.relative_to(src_root_path),
						dst_rel_path=dst_item_file.relative_to(dst_root_path),
						hint="You can resolve this conflict by deleting or moving the destination.",
					)
					continue

				if not dry_run:
					if found_existing:
						dst_item_file.unlink()

					src_item_file.copy(dst_item_file, follow_symlinks=False)

				if log_verbosity:
					_verbosity_print(
						*(
							dst_item_file,
							src_item_file,
						),
						sep=" -> ",
						color="aqua",
						ls_char="l",
						found_existing=found_existing,
					)
			elif (
				src_item_file.is_fifo()  #
				or src_item_file.is_char_device()
				or src_item_file.is_char_device()
				or src_item_file.is_socket()
			):
				found_existing = dst_item_file.exists(follow_symlinks=False)

				if found_existing:
					found_existing = f"found existing: {ls_char(dst_item_file)}"

				if found_existing and not dst_item_file.is_symlink():
					_warn_for_merge_simplified(
						heading="Unable to merge paths because a symlink to (block device, char device, socket or fifo) is requested, but the destination path exists and it's not a symlink to update.",
						tmpl_rel_path=dst_item_file.relative_to(src_root_path),
						dst_rel_path=dst_item_file.relative_to(dst_root_path),
						hint="You can resolve this conflict by deleting or moving the destination.",
					)
					continue

				if not dry_run:
					if found_existing:
						dst_item_file.unlink()

					dst_item_file.symlink_to(src_item_file)

				if log_verbosity:
					src_item_file_ls_char = ls_char(src_item_file)

					_verbosity_print(
						dst_item_file,
						ls_char=src_item_file_ls_char,
						color={
							"c": "yellow",
							"b": "yellow",
							"p": "yellow",
							"s": "#83005c",
						}.get(src_item_file_ls_char, "default"),
						found_existing=found_existing,
					)

			elif src_item_file.is_file():
				try:
					content = src_item_file.read_text(encoding="utf-8")
				except (UnicodeDecodeError, PermissionError) as e:
					raise error.Issue.FileInaccessibleError(src_item_file) from e

				try:
					evaluated_content = wtmpl_eval(
						content,
						suffix=src_item_file.suffix,
						src_path=src_item_file,
					)  # for consistency, even in dry_run evaluate the content, even though it will not be written
				except error.Action.DontIncludeError:
					continue
				except error.Action.BaseError as e:
					raise error.Issue.ActionUnsupportedInFileContentError(e) from e
				except error.TemplateArbitrary.BaseError as e:
					raise e.e from None

				found_existing = dst_item_file.exists(follow_symlinks=False)

				if found_existing:
					found_existing = f"found existing: {ls_char(dst_item_file)}"

				if found_existing:
					_warn_for_merge_simplified(
						heading="Refusing to merge files which would lead to potential data loss.",
						tmpl_rel_path=src_item_file.relative_to(src_root_path),
						dst_rel_path=dst_item_file.relative_to(dst_root_path),
					)
					continue

				if not dry_run:
					dst_item_file.write_text(
						evaluated_content,
						encoding="utf-8",
					)
					dst_item_file.chmod(src_item_file.stat().st_mode)

				if log_verbosity:
					_verbosity_print(
						dst_item_file,
						color="gray",
						found_existing=found_existing,
					)

					if log_verbosity >= 2:

						def _print_file_contents(s: str, *, header: str, indent: str = "  "):
							print(header)
							print("\n".join(f"{indent}{line}" for line in s.split("\n")))

						_print_file_contents(content, header="--- BEFORE ---")
						_print_file_contents(evaluated_content, header="--- AFTER ---")
			else:
				raise FileExistsError(f"Unsupported filetype within template: {src_item_file}")
