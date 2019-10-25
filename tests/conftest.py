from collections import namedtuple
from unittest.mock import Mock, patch

import eventlet
import pytest
from eventlet import sleep
from redis import StrictRedis

from nameko_rediskn import rediskn
from tests import REDIS_OPTIONS, TIME_SLEEP, URI_CONFIG_KEY


@pytest.fixture
def redis_config():
    return {
        'REDIS': {'notification_events': 'KEA'},
        'REDIS_URIS': {URI_CONFIG_KEY: "redis://localhost:6379/0"},
    }


@pytest.fixture
def config(rabbit_config, redis_config):
    conf = {}
    conf.update(rabbit_config or {})
    conf.update(redis_config or {})
    return conf


@pytest.fixture
def redis(config):
    redis_uri = config['REDIS_URIS'][URI_CONFIG_KEY]
    client = StrictRedis.from_url(redis_uri, **REDIS_OPTIONS)
    client.flushall()
    yield client
    client.flushall()


@pytest.fixture
def redis_db_1(config):
    # url argument takes precedence over db in the url
    redis_uri = '{}?db=1'.format(config['REDIS_URIS'][URI_CONFIG_KEY])
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


@pytest.fixture
def log_mock():
    with patch('nameko_rediskn.rediskn.log') as log_mock:
        yield log_mock


@pytest.fixture
def mock_strict_redis():
    with patch('nameko_rediskn.rediskn.StrictRedis') as m:
        yield m


@pytest.fixture
def mock_redis_client(mock_strict_redis):
    return mock_strict_redis.from_url.return_value


@pytest.fixture
def mock_pubsub(mock_redis_client):
    return mock_redis_client.pubsub.return_value


@pytest.fixture
def mock_container(mock_container, config):
    mock_container.spawn_managed_thread = eventlet.spawn
    mock_container.config = config
    mock_container.service_name = 'MockService'
    return mock_container


@pytest.fixture
def entrypoint(mock_container):
    return rediskn.RedisKNEntrypoint(
        uri_config_key=URI_CONFIG_KEY, events='*', keys='*', dbs=[0]
    ).bind(mock_container, 'test_method')
