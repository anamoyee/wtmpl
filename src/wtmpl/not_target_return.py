import functools
from collections.abc import Callable

import arguably


def not_target_return(f: Callable):
	@functools.wraps(f)
	def wrapper(*args, **kwargs):
		if not arguably.is_target():
			return None

		return f(*args, **kwargs)

	return wrapper
