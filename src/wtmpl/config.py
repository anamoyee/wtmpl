from platformdirs import user_config_path

WTMPL_CONFIG_PATH = user_config_path() / "wtmpl"
WTMPL_CONFIG_PATH.mkdir(exist_ok=True, parents=True)

WTMPL_CONFIG_TEMPLATES_PATH = WTMPL_CONFIG_PATH / "templates"
WTMPL_CONFIG_TEMPLATES_PATH.mkdir(exist_ok=True)
