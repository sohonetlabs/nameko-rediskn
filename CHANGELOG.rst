Version History
===============

Here you can see the full list of changes between
nameko-rediskn versions, where semantic versioning is used:
**major.minor.patch**.

Backwards-compatible changes increment the minor version number only.

0.1.1
-----

Released 2019-10-28

* Reconnect to redis on errors (`#6 <https://github.com/sohonetlabs/nameko-rediskn/pull/6>`_)
* New config key ``pubsub_backoff_factor`` (`#6 <https://github.com/sohonetlabs/nameko-rediskn/pull/6>`_)

0.1.0
-----

Released 2019-08-09

Thanks to `@alexpeits <https://github.com/alexpeits>`_ for his contribution to the
initial implementation.


* Initial release of the library (`#1 <https://github.com/sohonetlabs/nameko-rediskn/pull/1>`_)

  - Add the ability to subscribe to events
  - Add the ability to subscribe to keys
  - Add the ability to subscribe to databases

* Add support for Python ``3.5``, ``3.6``, ``3.7`` (`#1 <https://github.com/sohonetlabs/nameko-rediskn/pull/1>`_)
* Add support for Nameko ``2.11``, ``2.12`` (`#1 <https://github.com/sohonetlabs/nameko-rediskn/pull/1>`_)
* Add support for (Python) Redis ``2.10``, ``3.0``, ``3.1``, ``3.2`` (`#1 <https://github.com/sohonetlabs/nameko-rediskn/pull/1>`_)
* Add support for Redis ``4.0`` (`#1 <https://github.com/sohonetlabs/nameko-rediskn/pull/1>`_)
