import os


def parse_bool(value, default=False):
    if value is None:
        return default
    return value.strip().lower() in ('1', 'true', 'yes', 'on')


def parse_dotenv(filepath):
    """Parse a .env file into a dict. Skips comments and blank lines."""
    values = {}
    if not os.path.isfile(filepath):
        return values
    with open(filepath, 'r') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            if line.startswith('export '):
                line = line[len('export '):]
            key, sep, value = line.partition('=')
            if not sep:
                continue
            key = key.strip()
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
                value = value[1:-1]
            values[key] = value
    return values


DEFAULTS = {
    'APP_NAME': 'MyApp',
    'DEBUG': False,
    'DATABASE_URL': 'sqlite:///db.sqlite3',
}


def load_config(env_path=None):
    if env_path is None:
        env_path = os.path.join(os.getcwd(), '.env')

    dotenv_values = parse_dotenv(env_path)

    config = {}
    for key, default in DEFAULTS.items():
        env_val = os.environ.get(key)
        if env_val is not None:
            raw = env_val
        elif key in dotenv_values:
            raw = dotenv_values[key]
        else:
            config[key] = default
            continue

        if isinstance(default, bool):
            config[key] = parse_bool(raw)
        else:
            config[key] = raw

    return config
