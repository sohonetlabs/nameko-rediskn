import pytest
from redis import StrictRedis

from test import URI_CONFIG_KEY, REDIS_OPTIONS


@pytest.fixture
def redis_config():
    return {
        'REDIS': {'NOTIFICATION_EVENTS': 'KEA'},
        'REDIS_URIS': {URI_CONFIG_KEY: "redis://localhost:6379/0"},
    }


@pytest.fixture
def config(rabbit_config, redis_config):
    config = rabbit_config.copy()
    config.update(redis_config)
    return config


@pytest.fixture
def redis(redis_config):
    redis_uri = redis_config['REDIS_URIS'][URI_CONFIG_KEY]
    client = StrictRedis.from_url(redis_uri, **REDIS_OPTIONS)
    client.flushall()
    yield client
    client.flushall()
