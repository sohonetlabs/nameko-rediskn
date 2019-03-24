import os
from codecs import open
from setuptools import setup, find_packages


here = os.path.abspath(os.path.dirname(__file__))

with open(os.path.join(here, 'README.rst'), 'r', 'utf-8') as handle:
    readme = handle.read()

setup(
    name='nameko-rediskn',
    version='0.1.0',
    description='Nameko Redis Keyspace Notifications extension.',
    long_description=readme,
    long_description_content_type='text/x-rst',
    author='Julio Trigo',
    author_email='julio.trigo@sohonet.com',
    url='https://github.com/sohonetlabs/nameko-rediskn',
    packages=find_packages(exclude=['test', 'test.*']),
    install_requires=[
        'nameko>=2.6',
        'redis>=2.10.5',
    ],
    extras_require={
        'dev': [
            'pytest==4.3.1',
            'flake8',
            'coverage',
            'restructuredtext-lint',
            'Pygments',
        ],
    },
    zip_safe=True,
    license='MIT License',
    classifiers=[
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
        "Programming Language :: Python",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.4",
        "Programming Language :: Python :: 3.5",
        "Programming Language :: Python :: 3.6",
        "Programming Language :: Python :: 3.7",
        "Topic :: Database",
        "Topic :: Database :: Front-Ends",
        "Topic :: Internet",
        "Topic :: Software Development :: Libraries :: Python Modules",
    ]
)
