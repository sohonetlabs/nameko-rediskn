from collections import namedtuple
from unittest.mock import Mock

import pytest
from eventlet import sleep
from redis import StrictRedis

from nameko_rediskn import rediskn
from test import REDIS_OPTIONS, TIME_SLEEP, URI_CONFIG_KEY


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


@pytest.fixture
def redis_db_1(redis_config):
    # url argument takes precedence over db in the url
    redis_uri = '{}?db=1'.format(
        redis_config['REDIS_URIS'][URI_CONFIG_KEY]
    )
    client = StrictRedis.from_url(redis_uri, db=1, **REDIS_OPTIONS)
    client.flushall()
    yield client
    client.flushall()


@pytest.fixture
def tracker():
    yield Mock()


@pytest.fixture
def create_service(container_factory, config, tracker):
    def create(config=config, **kwargs):
        class DummyService:

            name = 'dummy_service'

            @rediskn.subscribe(**kwargs)
            def handler(self, message):
                tracker(message)

        ServiceMeta = namedtuple('ServiceMeta', ['container'])
        container = container_factory(DummyService, config)

        container.start()
        sleep(TIME_SLEEP)
        return ServiceMeta(container)

    return create
