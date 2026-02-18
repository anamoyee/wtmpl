import abc
import functools
import os
from collections.abc import Callable, Generator
from contextlib import contextmanager
from dataclasses import dataclass
from re import L
from types import NoneType
from typing import Any, Literal, Self, Unpack

import rich
import rich.markup
import rich.prompt
import rich.text
from nya_scope import Scope
from rich.console import RenderableType
from rich.markup import escape as esc

MISSING_IN_DICT = object()


type Textish = rich.text.TextType


class BaseTransformation[T]:
	type TransformFn[R] = Callable[[Interview, QuestionABC], R]
	type ValidateFn[A] = Callable[[Interview, QuestionABC[A], A], bool]

	def transform(self, iv: Interview, q: QuestionABC[T], /) -> QuestionABC[T]:
		return q

	def validate(self, iv: Interview, q: QuestionABC[T], a: T) -> bool:
		return True

	def invalid_message(self, iv: Interview, q: QuestionABC[T], a: T) -> rich.text.Text | str | None:
		return "[red]Invalid value, try again[/]"


class Transformation__(Scope):
	class KeepIf[T](BaseTransformation[T]):
		def __init__(self, predicate: BaseTransformation.TransformFn[bool]) -> None:
			self.predicate = predicate

		def transform(self, iv: Interview, q: QuestionABC) -> QuestionABC:
			if not self.predicate(iv, q):
				q.set_skip()

			return super().transform(iv, q)

	class ValidIf[T](BaseTransformation[T]):
		def __init__(
			self,
			predicate: BaseTransformation.ValidateFn[T],
			*,
			msg: rich.text.Text | str | None = "[red]Invalid value, try again[/]",
		) -> None:
			self.predicate = predicate
			self.msg = msg

		def validate(self, iv: Interview, q: QuestionABC[T], a: T) -> bool:
			return self.predicate(iv, q, a)

		def invalid_message(self, iv: Interview, q: QuestionABC[T], a: T) -> rich.prompt.Text | str | None:
			return self.msg


class QuestionABC[T](abc.ABC):
	@abc.abstractmethod
	def ask(self, iv: Interview, /) -> T: ...

	def ask_handling_validation(self, iv: Interview, /) -> T:
		try:
			answer = self.ask(iv)
		except (KeyboardInterrupt, EOFError) as e:
			raise iv.UserExitException(e) from e

		# code duplication, but i dont really want to make it more complex by adding a function
		# PLEASE, why  is there no do-while loop in python :sob:

		def key(trans: BaseTransformation[T]):
			result = trans.validate(iv, self, answer)

			if not result:
				msg = trans.invalid_message(iv, self, answer)

				if msg is not None:
					iv.rich_console.print(msg)

			return result  # short-circuit the all()

		while not all(key(trans) for trans in self._transformations):  # 🏳️‍⚧️
			try:
				answer = self.ask(iv)
			except (KeyboardInterrupt, EOFError) as e:
				raise iv.UserExitException(e) from e

		return answer

	def invoke_subquestion[SubT](self, subq: QuestionABC[SubT], iv: Interview) -> SubT:
		ans = subq.ask_handling_validation(iv)

		if subq._skip:
			self.set_skip()

		return ans

	_skip: bool

	def __init__(self) -> None:
		self._transformations: list[BaseTransformation[T]] = []
		self._skip = False

	def set_skip(self, skip: bool = True):
		self._skip = skip

	def with_transformation(self, transformation: BaseTransformation) -> Self:
		self._transformations.append(transformation)

		return self

	def with_keep_if(self, predicate: BaseTransformation.TransformFn[bool]) -> Self:
		return self.with_transformation(Transformation__.KeepIf[T](predicate))

	def with_valid_if(
		self,
		predicate: BaseTransformation.ValidateFn[T],
		*,
		msg: rich.text.Text | str | None = "[red]Invalid value, try again[/]",
	) -> Self:
		return self.with_transformation(Transformation__.ValidIf[T](predicate, msg=msg))


class Interview(QuestionABC[dict[str, Any]]):
	class UserExitException(SystemExit):
		"""Raised when the user wishes to exit the interview, at any point of it, either by pressing Ctrl+C (`KeyboardInterrupt`) or Ctrl+D (`EOFError`). The specific error can be viewed through `.__cause__` but it's not recommended to build any functionality around the difference between the two."""

		def __init__(
			self,
			/,
			e: KeyboardInterrupt | EOFError,
			print_newline: bool = True,
			print_ctrl_d: bool = True,
			print_ctrl_c: bool = os.name == "nt",
		):
			s = ""

			if print_ctrl_d and isinstance(e, EOFError):
				s += "^D"
			if print_ctrl_c and isinstance(e, KeyboardInterrupt):
				s += "^C"

			if print_newline:
				s += "\n"

			print(s, end="")

			super().__init__(2)

	class KeyOccupiedError(ValueError):
		"""Raised when adding a question at a key that is already occupied."""

		def __init__(self, /, *, keys: set[str], interview: Interview) -> None:
			self.keys = keys
			self.interview = interview

			super().__init__(f"Cannot add questions with the following keys to {interview!r}, because they are already occupied by previously added questions: {keys!r}")

	def __repr__(self) -> str:
		return f"""
{self.__class__.__name__}(
	questions.keys()={list(self.questions)!r},
	answers={self.answers!r},
)"""[1:-1]

	def __init__(self, /, **questions: QuestionABC[Any]):
		super().__init__()

		self.questions: dict[str, QuestionABC[Any]] = {}
		self._answers: dict[str, Any] | None = None
		self.parent_interview: Self | None = None
		self._rich_console: rich.console.Console | None = None

		self(**questions)

	@property
	def parent_interviews(self) -> tuple[Interview, ...]:
		ivs = []

		current: Interview | None = self

		while current is not None:
			ivs.append(current)
			current = current.parent_interview

		return tuple(ivs)

	@property
	def answers(self):
		if self._answers is None:
			raise RuntimeError("You cannot access this helper when this Interview isn't in progress!")

		return self._answers

	def with_rich_console(self, rich_console: rich.console.Console | None) -> Self:
		"""Provide a custom console used in this `Interview` and any child `Interview`s."""
		self._rich_console = rich_console

		return self

	@property
	def root_iv(self) -> Self:
		"""Iteratively find the root-most `.parent_interview`."""

		deepest_iv = self

		while deepest_iv.parent_interview is not None:
			deepest_iv = deepest_iv.parent_interview

		return deepest_iv

	@property
	def rich_console(self) -> rich.Console:
		"""Get the `rich.console.Console` object from the closest `Interview` in the tree, if not found on any, return a new Console()."""

		deepest_iv = self

		while deepest_iv.parent_interview is not None:
			if deepest_iv._rich_console is not None:
				return deepest_iv._rich_console

			deepest_iv = deepest_iv.parent_interview

		if deepest_iv._rich_console is not None:
			return deepest_iv._rich_console

		return rich.get_console()

	def __call__(self, /, **questions: QuestionABC[Any]) -> Self:
		"""Add a question (or multiple at a time) to this Interview, if any keys would be overwritten, raise a Interview.KeyOccupiedError. This operation is atomic."""
		occupied_keys = {k for k in questions if k in self.questions}

		if occupied_keys:
			raise Interview.KeyOccupiedError(keys=occupied_keys, interview=self)

		self.questions.update(questions)

		return self

	def ask(self, parent_interview: Self | None = None) -> dict[str, Any]:
		self.parent_interview = parent_interview
		self._answers = {}

		for name, question in self.questions.items():
			for transformation in question._transformations.copy():
				question = transformation.transform(self, question)

			if question._skip:
				continue

			answer = question.ask_handling_validation(self)

			if question._skip:
				# this check is already present higher in this loop, however this one checks if during the process of asking this flag was set, in which case simply dont include the given result.
				continue

			self._answers[name] = answer

		try:
			return self._answers
		finally:
			self._answers = None
			self.parent_interview = None


class Question__(Scope):
	class Label(QuestionABC[None]):
		def __init__(self, label: RenderableType) -> None:
			super().__init__()
			self.label_renderable: RenderableType = label

		def ask(self, iv: Interview) -> None:
			iv.rich_console.print(self.label_renderable)
			self.set_skip()  # do not include in the results dict

	class _QuestionABCWithText[T](QuestionABC[T]):
		def __init__(self, text: Textish) -> None:
			super().__init__()

			self.text = text

	class Str(_QuestionABCWithText[str]):
		def ask(self, iv: Interview) -> str:
			return rich.prompt.Prompt.ask(self.text, console=iv.rich_console)

		def with_valid_if_any_answer(self, *, msg: rich.text.Text | str | None = "[red]Provide an answer[/]") -> Self:
			self.with_valid_if(lambda iv, q, a: bool(a), msg=msg)
			return self

	class Int(_QuestionABCWithText[int]):
		def __init__(self, text: Textish, *, invalid_msg: str = "[red]Provide a valid integer") -> None:
			super().__init__(text)

			self.str_question = Question__.Str(self.text).with_valid_if(
				lambda iv, q, a: self._str_is_int_parsable(a),
				msg=invalid_msg,
			)

		@staticmethod
		def _str_is_int_parsable(s: str) -> bool:
			try:
				int(s)
			except ValueError:
				return False

			return True

		def ask(self, iv: Interview) -> int:
			ans = self.invoke_subquestion(self.str_question, iv)

			return int(ans)

	class YesNo(_QuestionABCWithText[bool]):
		def __init__(
			self,
			text: Textish,
			default: bool | None = True,
			show_choices: bool = True,
		) -> None:
			super().__init__(text)
			self.default_str = {True: "yes", False: "no", None: None}[default]

			if isinstance(self.text, str):
				self.text = rich.text.Text(self.text)

			if show_choices:
				parens = ("(", ")") if default is None else ("[", "]")

				self.text.append(
					rich.markup.render(
						f" {esc(parens[0])}[green b]{'Y' if default and default is not None else 'y'}[/]/[red b]{'N' if not default and default is not None else 'n'}[/]{esc(parens[1])}"
					)
				)

			self.str_question = Question__.Str(self.text)

			if default is None:
				self.str_question.with_valid_if_any_answer()

		def ask(self, iv: Interview) -> bool:
			ans = self.invoke_subquestion(self.str_question, iv) or self.default_str

			if ans is None:
				raise RuntimeError("Should be unreachable: self.default is only None, if self.str_question enforces truthy string.")  # unreachable

			return ans.lower() in ("y", "yes")

	class Dynamic[T](QuestionABC[T]):
		def __init__(self, make_question: Callable[[Interview], QuestionABC[T]]) -> None:
			super().__init__()
			self.make_question = make_question

		def ask(self, iv: Interview) -> T:
			return self.invoke_subquestion(self.make_question(iv), iv)
