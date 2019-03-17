import pytest


@pytest.fixture
def config(rabbit_config):
    config = {
        'REDIS_NOTIFICATION_EVENTS': 'KEA',
        'REDIS_URIS': {'session': "redis://localhost:6379/0"},
    }
    config.update()
    return config
