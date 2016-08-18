# -*- coding: utf-8 -*-
"""
base
~~~~
"""
from __future__ import division, print_function, unicode_literals

import abc
from decimal import Decimal
from fractions import Fraction
import uuid

try:
    import cPickle as pickle
except ImportError:
    import pickle as pickle  # NOQA

import redis
import six

NUMERIC_TYPES = six.integer_types + (float, Decimal, Fraction, complex)


@six.add_metaclass(abc.ABCMeta)
class RedisCollection(object):
    """Abstract class providing backend functionality for all the other
    Redis collections.
    """

    not_impl_msg = ('Cannot be implemented efficiently or atomically '
                    'due to limitations in Redis command set.')

    @abc.abstractmethod
    def __init__(self, redis=None, key=None):
        """
        :param data: Initial data.
        :param redis: Redis client instance. If not provided, default Redis
                      connection is used.
        :type redis: :class:`redis.StrictRedis`
        :param key: Redis key of the collection. Collections with the same key
                    point to the same data. If not provided, default random
                    string is generated.
        :type key: str

        .. note::
            :func:`uuid.uuid4` is used for default key generation.
            If you are not satisfied with its `collision
            probability <http://stackoverflow.com/a/786541/325365>`_,
            make your own implementation by subclassing and overriding
            internal method :func:`_create_key`.
        """
        #: Redis client instance. :class:`StrictRedis` object with default
        #: connection settings is used if not set by :func:`__init__`.
        self.redis = redis or self._create_redis()

        #: Redis key of the collection.
        self.key = key or self._create_key()

    def _create_redis(self):
        """Creates default Redis connection.

        :rtype: :class:`redis.StrictRedis`
        """
        return redis.StrictRedis()

    def _create_key(self):
        """Creates new Redis key.

        :rtype: string

        .. note::
            :func:`uuid.uuid4` is used. If you are not satisfied with its
            `collision
            probability <http://stackoverflow.com/a/786541/325365>`_,
            make your own implementation by subclassing and overriding this
            method.
        """
        return uuid.uuid4().hex

    @abc.abstractmethod
    def _data(self, pipe=None):
        """Helper for getting collection's data within a transaction.

        :param pipe: Redis pipe in case creation is performed as a part
                     of transaction.
        :type pipe: :class:`redis.client.StrictPipeline` or
                    :class:`redis.client.StrictRedis`
        """

    def _pickle(self, data):
        """Converts given data to string.

        :param data: Data to be serialized.
        :type data: anything serializable
        :rtype: string
        """
        return pickle.dumps(data)

    def _pickle_2(self, data):
        # On Python 2 some values of the str and unicode types have the same
        # hash, are equal to each other, but nonetheless pickle to different
        # byte strings. This method encodes unicode types to str to help match
        # Python's behavior.
        # The length of {b'a', u'a'} is 1 on Python 2.x and 2 on Python 3.x
        if isinstance(data, six.text_type):
            data = data.encode('utf-8')

        return self._pickle_3(data)

    def _pickle_3(self, data):
        # Several numeric types are equal, have the same hash, but nonetheless
        # pickle to different byte strings. This method reduces them down to
        # integers to help match with Python's behavior.
        # len({1.0, 1, complex(1, 0)}) == 1
        if isinstance(data, complex):
            int_data = int(data.real)
            if data == int_data:
                data = int_data
        elif isinstance(data, NUMERIC_TYPES):
            int_data = int(data)
            if data == int_data:
                data = int_data

        return pickle.dumps(data)

    def _unpickle(self, string):
        """Converts given string serialization back to corresponding data.
        If :obj:`None` or empty string given, :obj:`None` is returned.

        :param string: String to be unserialized.
        :type string: string
        :rtype: anything serializable
        """
        return pickle.loads(string) if string else None

    def _unpickle_2(self, string):
        # Because we encoded text data in the pickle method, we should decode
        # it on the way back out
        data = pickle.loads(string) if string else None
        if isinstance(data, six.binary_type):
            try:
                data = data.decode('utf-8')
            except UnicodeDecodeError:
                pass

        return data

    def _clear(self, pipe=None):
        """Helper for clear operations.

        :param pipe: Redis pipe in case update is performed as a part
                     of transaction.
        :type pipe: :class:`redis.client.StrictPipeline` or
                    :class:`redis.client.StrictRedis`
        """
        redis = pipe or self.redis
        redis.delete(self.key)

    def _same_redis(self, other, cls=None):
        cls = cls or self.__class__
        if not isinstance(other, cls):
            return False

        self_kwargs = self.redis.connection_pool.connection_kwargs
        other_kwargs = other.redis.connection_pool.connection_kwargs

        return (
            self_kwargs['host'] == other_kwargs['host'] and
            self_kwargs['port'] == other_kwargs['port'] and
            self_kwargs.get('db', 0) == other_kwargs.get('db', 0)
        )

    def _transaction(self, fn, *extra_keys):
        """Helper simplifying code within watched transaction.

        Takes *fn*, function treated as a transaction. Returns whatever
        *fn* returns. ``self.key`` is watched. *fn* takes *pipe* as the
        only argument.

        :param fn: Closure treated as a transaction.
        :type fn: function *fn(pipe)*
        :param extra_keys: Optional list of additional keys to watch.
        :type extra_keys: list
        :rtype: whatever *fn* returns
        """
        results = []

        def trans(pipe):
            results.append(fn(pipe))

        self.redis.transaction(trans, self.key, *extra_keys)
        return results[0]

    def __enter__(self):
        self.writeback = True
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.sync()

    def sync(self):
        pass

    def _repr_data(self, data):
        return repr(data)

    def __repr__(self):
        cls_name = self.__class__.__name__
        data = self._repr_data(self._data())
        return '<redis_collections.%s at %s %s>' % (cls_name, self.key, data)
