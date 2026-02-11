import pathlib as p
import stat
from collections.abc import Generator as __Generator
from collections.abc import Iterator as __Iterator
from typing import Literal, Never


def pathlib_os_walk(root: p.Path, *, follow_symlinks: bool = True) -> __Generator[tuple[p.Path, list[p.Path], list[p.Path]]]:
	"""Simillar to `os.walk()`, but yields `pathlib.Path` objects instead.

	```python
	for (
		root, # root of the current set
		dirs, # all dirs in this root
		files, # all non-dirs in this root
	) in pathlib_os_walk(path):
		...
	"""

	root = p.Path(root)

	dirs = []
	files = []

	for path in root.iterdir():
		if path.is_dir(follow_symlinks=follow_symlinks):
			dirs.append(path)
		else:
			files.append(path)

	yield root, dirs, files

	for d in dirs:
		yield from pathlib_os_walk(d)


def iter_subpath_chain(root: p.Path, leaf: p.Path) -> __Iterator[p.Path]:
	"""Given an absolute path `root` and an absolute path `leaf` (if either is not absolute, they will be `.resolved()`) where the former is one of the parents in the latter (if not, a `ValueError` will be raised out of `Path.relative_to()`), yield from an iterator of absolute paths starting from the `root` path interpolating towards `leaf` path by adding one path part at a time.

	Example:
	```python
	import pathlib as p

	root = p.Path("/repo/whatever/subdir")
	leaf = root / "item_dir/item1/properties"

	assert list(iter_subpath_chain(root, leaf)) == [
		p.Path("/repo/whatever/subdir"),
		p.Path("/repo/whatever/subdir/item_dir"),
		p.Path("/repo/whatever/subdir/item_dir/item1"),
		p.Path("/repo/whatever/subdir/item_dir/item1/properties"),
	]
	```
	"""

	root = root.resolve()
	leaf = leaf.resolve()

	relative = leaf.relative_to(root)

	current = root
	yield current

	for part in relative.parts:
		current = current / part
		yield current


def ls_char(path: p.Path) -> Literal["-", "d", "l", "s", "c", "b", "p", "?", ""]:
	"""Return the `/bin/ls` char of the given path, unless the below exceptions apply.

	- Path doesnt exist; then return `""` (Not `None` to keep the type `str` and not `str | None`)
	- Path is of an unknown type (all linux types supported); then return `"?"`
	"""

	try:
		mode = path.lstat().st_mode
	except FileNotFoundError:
		return ""

	if stat.S_ISREG(mode):
		return "-"  # regular file
	if stat.S_ISDIR(mode):
		return "d"  # directory
	if stat.S_ISLNK(mode):
		return "l"  # symlink
	if stat.S_ISSOCK(mode):
		return "s"  # socket
	if stat.S_ISCHR(mode):
		return "c"  # char device
	if stat.S_ISBLK(mode):
		return "b"  # block device
	if stat.S_ISFIFO(mode):
		return "p"  # fifo / pipe

	return "?"
