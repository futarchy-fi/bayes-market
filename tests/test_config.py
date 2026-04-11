import sys
import os
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from config import load_config, parse_bool, parse_dotenv


def test_defaults_when_no_env():
    env_path = os.path.join(tempfile.gettempdir(), 'nonexistent.env')
    old = {k: os.environ.pop(k, None) for k in ('APP_NAME', 'DEBUG', 'DATABASE_URL')}
    try:
        cfg = load_config(env_path=env_path)
        assert cfg['APP_NAME'] == 'MyApp'
        assert cfg['DEBUG'] is False
        assert cfg['DATABASE_URL'] == 'sqlite:///db.sqlite3'
    finally:
        for k, v in old.items():
            if v is not None:
                os.environ[k] = v


def test_env_vars_override_defaults():
    old = {k: os.environ.pop(k, None) for k in ('APP_NAME', 'DEBUG', 'DATABASE_URL')}
    os.environ['APP_NAME'] = 'TestApp'
    os.environ['DEBUG'] = 'true'
    os.environ['DATABASE_URL'] = 'postgres://localhost/test'
    try:
        cfg = load_config(env_path='/nonexistent')
        assert cfg['APP_NAME'] == 'TestApp'
        assert cfg['DEBUG'] is True
        assert cfg['DATABASE_URL'] == 'postgres://localhost/test'
    finally:
        for k in ('APP_NAME', 'DEBUG', 'DATABASE_URL'):
            os.environ.pop(k, None)
        for k, v in old.items():
            if v is not None:
                os.environ[k] = v


def test_dotenv_file_loading():
    old = {k: os.environ.pop(k, None) for k in ('APP_NAME', 'DEBUG', 'DATABASE_URL')}
    try:
        with tempfile.NamedTemporaryFile(mode='w', suffix='.env', delete=False) as f:
            f.write('APP_NAME=FromDotenv\n')
            f.write('DEBUG=yes\n')
            f.write('DATABASE_URL=mysql://localhost/mydb\n')
            env_path = f.name
        cfg = load_config(env_path=env_path)
        assert cfg['APP_NAME'] == 'FromDotenv'
        assert cfg['DEBUG'] is True
        assert cfg['DATABASE_URL'] == 'mysql://localhost/mydb'
    finally:
        os.unlink(env_path)
        for k, v in old.items():
            if v is not None:
                os.environ[k] = v


def test_env_vars_override_dotenv():
    old = {k: os.environ.pop(k, None) for k in ('APP_NAME', 'DEBUG', 'DATABASE_URL')}
    os.environ['APP_NAME'] = 'FromEnv'
    try:
        with tempfile.NamedTemporaryFile(mode='w', suffix='.env', delete=False) as f:
            f.write('APP_NAME=FromDotenv\n')
            f.write('DEBUG=1\n')
            env_path = f.name
        cfg = load_config(env_path=env_path)
        assert cfg['APP_NAME'] == 'FromEnv'
        assert cfg['DEBUG'] is True
    finally:
        os.unlink(env_path)
        os.environ.pop('APP_NAME', None)
        for k, v in old.items():
            if v is not None:
                os.environ[k] = v


def test_parse_bool():
    assert parse_bool('true') is True
    assert parse_bool('True') is True
    assert parse_bool('1') is True
    assert parse_bool('yes') is True
    assert parse_bool('on') is True
    assert parse_bool('false') is False
    assert parse_bool('0') is False
    assert parse_bool('no') is False
    assert parse_bool('off') is False
    assert parse_bool(None) is False
    assert parse_bool(None, default=True) is True


def test_parse_dotenv_comments_and_blanks():
    with tempfile.NamedTemporaryFile(mode='w', suffix='.env', delete=False) as f:
        f.write('# this is a comment\n')
        f.write('\n')
        f.write('KEY=value\n')
        f.write('  # another comment\n')
        env_path = f.name
    try:
        values = parse_dotenv(env_path)
        assert values == {'KEY': 'value'}
    finally:
        os.unlink(env_path)


def test_parse_dotenv_quoted_values():
    with tempfile.NamedTemporaryFile(mode='w', suffix='.env', delete=False) as f:
        f.write('SINGLE=\'hello world\'\n')
        f.write('DOUBLE="hello world"\n')
        env_path = f.name
    try:
        values = parse_dotenv(env_path)
        assert values['SINGLE'] == 'hello world'
        assert values['DOUBLE'] == 'hello world'
    finally:
        os.unlink(env_path)


def test_parse_dotenv_export_prefix():
    with tempfile.NamedTemporaryFile(mode='w', suffix='.env', delete=False) as f:
        f.write('export FOO=bar\n')
        env_path = f.name
    try:
        values = parse_dotenv(env_path)
        assert values == {'FOO': 'bar'}
    finally:
        os.unlink(env_path)
