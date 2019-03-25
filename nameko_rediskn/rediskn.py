import logging
from itertools import chain

from redis import StrictRedis

from nameko.extensions import Entrypoint


REDIS_OPTIONS = {'encoding': 'utf-8', 'decode_responses': True}

NOTIFICATIONS_SETTING_KEY = 'notify-keyspace-events'
"""
The settings key should be a string consisting of options. Available options
are:

K     Keyspace events, published with __keyspace@<db>__ prefix.
E     Keyevent events, published with __keyevent@<db>__ prefix.
g     Generic commands (non-type specific) like DEL, EXPIRE, RENAME, ...
$     String commands
l     List commands
s     Set commands
h     Hash commands
z     Sorted set commands
x     Expired events (events generated every time a key expires)
e     Evicted events (events generated when a key is evicted for maxmemory)
A     Alias for g$lshzxe, so that the "AKE" string means all the events.

NOTE: this is set on the server, so it's best to set it once when starting the
server instance, as setting it in one client affects all other clients.
However, if this entrypoint finds this setting in the container config it
applies it.
"""

KEYEVENT_TEMPLATE = '__keyevent@{db}__:{event}'
"""
Keyevent event notifications are received on events. The event is part of the
subscription channel, and the key the event refers to is part of the message
data.
"""

KEYSPACE_TEMPLATE = '__keyspace@{db}__:{key}'
"""
Keyspace event notifications are received on keys. The key is part of the
subscription channel, and the event on the key is part of the message data.
"""


log = logging.getLogger()


class RedisKNEntrypoint(Entrypoint):

    """Redis keyspace notifications entrypoint.

    https://redis.io/topics/notifications

    Event examples:

        - `expire` events fire when we call the `EXPIRE` commands
        - `expired` events fire when a key gets deleted due to expiration

    Usage example:

        from nameko_rediskn import rediskn


        class MyService:

            name = 'my-service'

            @rediskn.subscribe(keys='foo/bar-*')
            def subscriber(self, message):
                event_type = message['data']
                if event_type != 'expired':
                    return

                key = message['channel'].split(':')[1]

                # ...
    """

    def __init__(self, events=None, keys=None, dbs=None, **kwargs):
        """Initialize the notification events settings.

        Args:
            events (str or list(str)): One or more events to subscribe to
            keys (str or list(str)): One or more keys to subscribe to
            dbs (str or list(str)): One or more redis dbs to subscribe to
        """
        if events is None:
            self.events = []
        else:
            self.events = _to_list(events)

        if keys is None:
            self.keys = []
        else:
            self.keys = _to_list(keys)

        if not self.events and not self.keys:
            raise RuntimeError(
                'Provide either `events` or `keys` to get notifications'
            )

        if dbs is None:
            self.dbs = None
        else:
            self.dbs = _to_list(dbs)

        self.client = None
        self._thread = None
        super().__init__(**kwargs)

    def setup(self):
        # TODO: find a better way to expose the redis URL without
        # harcoding 'session'
        self._redis_uri = self.container.config['REDIS_URIS']['session']
        # This should ideally be set in redis.conf
        self._notification_events = self.container.config.get(
            'REDIS_NOTIFICATION_EVENTS'
        )

        super().setup()

    def start(self):
        self._thread = self.container.spawn_managed_thread(self._run)
        super().start()

    def stop(self):
        if self._thread is not None:
            self._thread.kill()
            self._thread = None
        self.client = None
        super().stop()

    def kill(self):
        if self._thread is not None:
            self._thread.kill()
            self._thread = None
        self.client = None
        super().kill()

    def _run(self):
        """Run the main loop which listens for subscription events.

        When an event is received, the decorated method is called with a
        single argument, the received message, which is a dictionary with the
        following data:

        `data`: the key for `keyevent` notifications or the event for
                `keyspace` notifications

        `type`: "pmessage" for simple events, "psubscribe" for subscription
                events (subscription events are received when the entrypoint
                initializes)
        `pattern`: The subscription pattern

        `channel`: The subscription channel

        The subscription channel has the following format:

            __<subscription type>@<db>__:<event suffix>

        `db` is the redis database the event comes from. If the subscription
        type is `keyevent`, then the event suffix is the event type (set, hset,
        expire etc.). If the subscription type is `keyspace`, then the event
        suffix is the key for which the event happened.
        """
        self._create_client()
        pubsub = self._subscribe()

        log.info('Started listening to redis keyspace notifications')

        try:
            for message in pubsub.listen():
                self.container.spawn_worker(self, [message], {})
        finally:
            pubsub.close()
            log.info('Stopped listening to redis keyspace notifications')

    def _create_client(self):
        client = StrictRedis.from_url(self._redis_uri, **REDIS_OPTIONS)

        if self.dbs is None:
            # Use the actual connected DB if no DBs have been provided
            connected_db = client.connection_pool.connection_kwargs['db']
            self.dbs = [connected_db]

        if self._notification_events is not None:
            client.config_set(
                NOTIFICATIONS_SETTING_KEY, self._notification_events
            )

        self.client = client

    def _subscribe(self):
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


def _to_list(arg):
    if isinstance(arg, tuple):
        return list(arg)
    if not isinstance(arg, list):
        return [arg]
    return arg


subscribe = RedisKNEntrypoint.decorator
