import rich
from tcrutils.console import c  # type: ignore

from . import Interview as I
from . import Question__ as Q__
from . import Transformation__ as T__

if __name__ == "__main__":  # interactive tests
	results = (
		I(
			name1=(
				Q__.Label("1").  #
				with_keep_if(lambda iv, q: 1 == 2)
			),
			name2=Q__.Label("2"),
			name3=Q__.Label("3"),
			string=(
				Q__
				.Str("What is your name")
				.with_valid_if_any_answer()
				.with_valid_if(
					lambda iv, q, a: a.lower() not in ["gay", "meow"],
					msg="[red]You must NOT say `gay` or `meow` ",
				)
				.with_valid_if(
					lambda iv, q, a: a.__len__() % 2 == 0,
					msg="[red]answer len must be divisible by 2",
				)
			),
			lvl=Q__.Int("What is your lvl"),
			default_for_next_question=Q__.YesNo("Choose next question's default", default=True),
			start_subinterview=Q__.Dynamic(lambda iv: Q__.YesNo("Start a subinterview?", default=iv.answers["default_for_next_question"])),
			subinterview=I(
				name=Q__.Str("| Your name"),
				lvl=Q__.Int("| Your lvl"),
			).with_keep_if(lambda iv, q: iv.answers["start_subinterview"]),
		)
		.with_rich_console(rich.console.Console(highlight=False))
		.ask()
	)

	rich.get_console().print(results)
