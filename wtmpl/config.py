import pathlib as p
import shelve

import platformdirs
from pydantic import BaseModel, Field
from pydantic import ConfigDict as PydanticModelConfigDict


class Config(BaseModel):
	template_directory: p.Path = Field(default_factory=lambda: (_get_data_dir() / "templates"))

	model_config = PydanticModelConfigDict(
		validate_assignment=True,
		validate_default=True,
		validate_return=True,
	)


def _get_data_dir() -> p.Path:
	return platformdirs.user_config_path(appname="itmpl", appauthor="anamoyee", ensure_exists=True)


def _get_config_file(*, _ensure_valid_contents: bool = True) -> p.Path:
	file = _get_data_dir() / "config"

	if _ensure_valid_contents:
		save(Config())

	return file


def reset() -> None:
	"""Reset the user's config to a default one."""
	save(Config())


def get() -> Config:
	"""Get the user's config."""
	with shelve.open(_get_config_file(_ensure_valid_contents=False)) as shelf:
		return shelf.get("config") or Config()


def save(config: Config) -> None:
	"""Set the user's config to the passed in one."""
	with shelve.open(_get_config_file(_ensure_valid_contents=False)) as shelf:
		shelf["config"] = config


__all__ = ["get", "save", "reset"]
