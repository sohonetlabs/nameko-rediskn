import logging
from itertools import chain

from eventlet import sleep
from nameko.exceptions import ConfigurationError
from nameko.extensions import Entrypoint
from redis import StrictRedis

REDIS_OPTIONS = {'encoding': 'utf-8', 'decode_responses': True}

NOTIFICATIONS_SETTING_KEY = 'notify-keyspace-events'
"""
Configuration parameter used to enable keyspace events notifications.

By default, those notifications are disabled. Setting this parameter to the
empty string also disables them.

To enable them, a non-empty string must be used. The set of allowed characters
can be found in the Redis keyspace notifications documentation.

NOTE: it is recomended to set this parameter on the server side (`redis.conf`),
as setting it in one of the clients (via CONFIG SET) also affects the rest
of them.
"""

KEYEVENT_TEMPLATE = '__keyevent@{db}__:{event}'
"""Key-event pattern template."""

KEYSPACE_TEMPLATE = '__keyspace@{db}__:{key}'
"""Key-space pattern template."""

REDIS_PMESSAGE_TYPE = 'pmessage'
"""Pattern-matching subscription message type."""

DEFAULT_BACKOFF_FACTOR = 2
"""
Default backoff factor for exponential backoff on errors while listening for
redis events. On an error, we will sleep for `backoff_factor * 2 ** (n - 1)`
where `n` is the number of consecutive errors that have occurred.
"""

log = logging.getLogger(__name__)


class RedisKNEntrypoint(Entrypoint):

    """Redis keyspace notifications entrypoint.

    Key-space notifications and key-event notification as documented here
    https://redis.io/topics/notifications and based on Pub/Sub
    https://redis.io/topics/pubsub

    When a Redis event is received then the decorated method is called with a
    single argument, the received `message`, which is a dictionary with the
    following data:

        `type`: message type.

            - `pmessage` for messages received as a result of pattern matching.
            - `psubscribe` for subscription events (subscription events are
              received when the entrypoint initializes).

        `pattern`: the original pattern matched.

        `channel`: the name of the originating channel.

        `data`: message payload.

            - The Key-space channel receives the name of the event.
            - The Key-event channel receives the name of the key.

    The originating channel has the following format:

        __<subscription type>@<db>__:<event suffix>

    where:

        - `subscription type` is either `keyspace` or `keyevent`.
        - `db` is the Redis database the event comes from.
        - If the `subscription type` is `keyevent`, then the `event suffix` is
          the event type (`set`, `hset`, `expire`, etc.). If the
          `subscription type` is `keyspace`, then the `event suffix` is the key
          for which the event happened.

    The subscription pattern has the same format, but it displays the original
    pattern that matched.

    Message example:

        {
            'type': 'pmessage',
            'pattern': '__keyevent@*__:*',
            'channel': '__keyevent@0__:expired',
            'data': 'foo',
        }

    Code example:

        from nameko_rediskn import rediskn, REDIS_PMESSAGE_TYPE


        class MyService:

            name = 'my-service'

            @rediskn.subscribe(uri_config_key='MY_REDIS', keys='foo/bar-*')
            def subscriber(self, message):
                '''Notifications subscriber entrypoint.

                Args:
                    message (dict): notification message formed of `type`,
                    `pattern`, `channel` and `data`.
                '''
                if message['type'] != REDIS_PMESSAGE_TYPE:
                    return

                event_type = message['data']
                if event_type != 'expired':
                    return

                key = message['channel'].split(':')[1]

                # ...
    """

    def __init__(self, uri_config_key, events=None, keys=None, dbs=None, **kwargs):
        """Initialize the entrypoint.

        Args:
            uri_config_key (str): Redis URI config key.
            events (str or list(str)): one or more events to subscribe to.
            keys (str or list(str)): one or more keys to subscribe to.
            dbs (str or list(str)): one or more DBs to subscribe to.
        """
        self.uri_config_key = uri_config_key

        self.events = [] if events is None else _to_list(events)
        self.keys = [] if keys is None else _to_list(keys)
        self.dbs = None if dbs is None else _to_list(dbs)

        self.client = None
        self._thread = None
        super().__init__(**kwargs)

    def setup(self):
        if not self.events and not self.keys:
            error_message = 'Provide either `events` or `keys` to get notifications'
            log.error(error_message)
            raise ConfigurationError(error_message)

        self._redis_uri = self.container.config['REDIS_URIS'][self.uri_config_key]
        redis_config = self.container.config.get('REDIS', {})
        self._notification_events = redis_config.get('notification_events')
        self._backoff_factor = redis_config.get(
            'pubsub_backoff_factor', DEFAULT_BACKOFF_FACTOR
        )
        super().setup()

    def start(self):
        self._thread = self.container.spawn_managed_thread(self._run)
        super().start()
        log.debug("%s started", self)

    def stop(self):
        self._kill_thread()
        super().stop()
        log.debug("%s stopped", self)

    def kill(self):
        self._kill_thread()
        super().kill()
        log.debug("%s killed", self)

    def _run(self):
        """Run the main loop which listens for subscription events."""
        self._create_client()
        pubsub = None

        log.info('Started listening to Redis keyspace notifications')
        error_count = 0

        try:
            while True:
                try:
                    pubsub = self._subscribe()

                    for message in pubsub.listen():  # pragma: no branch
                        error_count = 0
                        self.container.spawn_worker(self, [message], {})
                except Exception:
                    log.exception(
                        'Error while listening for redis keyspace notifications'
                    )
                    sleep(self._backoff_factor * 2 ** error_count)
                    error_count += 1
                finally:
                    if pubsub is not None:
                        pubsub.close()
        finally:
            log.info('Stopped listening to Redis keyspace notifications')

    def _create_client(self):
        client = StrictRedis.from_url(self._redis_uri, **REDIS_OPTIONS)

        if self.dbs is None:
            # Use the actual connected DB if no DBs have been provided
            connected_db = client.connection_pool.connection_kwargs['db']
            self.dbs = [connected_db]

        if self._notification_events is not None:
            # This should ideally be set in redis.conf
            client.config_set(NOTIFICATIONS_SETTING_KEY, self._notification_events)

        self.client = client

    def _subscribe(self):
        log.debug('%s setting up redis subscriptions', self)
        pubsub = self.client.pubsub()

        keyevent_patterns = (
            KEYEVENT_TEMPLATE.format(db=db, event=event)
            for db in self.dbs
            for event in self.events
        )

        keyspace_patterns = (
            KEYSPACE_TEMPLATE.format(db=db, key=key)
            for db in self.dbs
            for key in self.keys
        )

        for pattern in chain(keyevent_patterns, keyspace_patterns):
            pubsub.psubscribe(pattern)

        return pubsub

    def _kill_thread(self):
        if self._thread is not None:
            self._thread.kill()


def _to_list(arg):
    if isinstance(arg, tuple):
        return list(arg)
    if not isinstance(arg, list):
        return [arg]
    return arg


subscribe = RedisKNEntrypoint.decorator
