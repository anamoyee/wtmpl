import pathlib as __p
from dataclasses import dataclass as _dataclass


class __NoInitMeta(type):
	def __call__(cls, *args, **kwargs):
		raise RuntimeError("This class doesnt support initialization, it is a scope for other values only.")


class BaseWtmplError(Exception):
	"""Base class for all wtmpl errors."""


class Action(metaclass=__NoInitMeta):
	class BaseError(BaseWtmplError):
		"""Base class for all wtmpl errors which are utility to cause a certain action, for example skip including a file (e.g. DontIncludeError)."""

		def __init__(self):
			pass

	class DontIncludeError(BaseError):
		"""[wtmpl action error]: Dont include this file if this error is raised from a filename or file contents."""


class Issue(metaclass=__NoInitMeta):
	class BaseWtmplIssueError(BaseWtmplError):
		"""Base class for all wtmpl errors which are NOT a utility to cause a certain action, for example skip including a file (e.g. DontIncludeError does NOT inherit from this base class)."""

	@_dataclass
	class DestinationIsAFileError(BaseWtmplIssueError):
		"""The desination directory is a file, it can't be."""

		dst_path: __p.Path

	class ActionUnsupportedInFileContentError(BaseWtmplIssueError):
		"""That action error is not supported when raised from a file's content expression."""

		def __init__(self, action_error: Action.BaseError):
			self.action_error = action_error

			super().__init__(f"This action error is not supported in file contents: {str(action_error.__class__)!r}")

	class ActionUnsupportedInFileNameError(BaseWtmplIssueError):
		"""That action error is not supported when raised from a file or directory name expression."""

		def __init__(self, action_error: Action.BaseError):
			self.action_error = action_error

			super().__init__(f"This action error is not supported in file or directory name: {str(action_error.__class__)!r}")

	class FileInaccessibleError(BaseWtmplIssueError):
		"""The file within a template was inaccessible for reading for whatever reason (check `.__cause__`) during file ."""

		def __init__(self, path: __p.Path):
			self.path = path

			super().__init__(
				f"File located at the path listed below, which is within the wtmpl template that is currently evaluated was inaccessible for reading for whatever reason (check `this.__cause__` for the reason, or if you're reading a traceback, scroll up)\n\n{path}"
			)

	@_dataclass
	class RequestedNewFilenameInvalidError(BaseWtmplIssueError):
		"""The evaluated name of a file or directory contained slashes or null bytes (or other characters unsupported in filenames on the operating system in use)."""

		requested_name: str


class TemplateArbitrary(metaclass=__NoInitMeta):
	class BaseError(BaseWtmplError):
		"""An exception was raised out of an arbitrary-code part of a template."""

		e: BaseException
		"""The exception that was raised. May also be accessed via `self.__cause__` i guess."""

		def __init__(self, e: BaseException):
			self.e = e
			super().__init__("note: The cause error originates from the template, and is likely not a problem with wtmpl")
