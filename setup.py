import os
from codecs import open

from setuptools import find_packages, setup

here = os.path.abspath(os.path.dirname(__file__))

with open(os.path.join(here, 'README.rst'), 'r', 'utf-8') as handle:
    readme = handle.read()

setup(
    name='nameko-rediskn',
    version='0.1.1',
    description='Nameko Redis Keyspace Notifications extension.',
    long_description=readme,
    long_description_content_type='text/x-rst',
    author='Julio Trigo',
    author_email='julio.trigo@sohonet.com',
    url='https://github.com/sohonetlabs/nameko-rediskn',
    keywords='nameko redis keyspace notifications extension',
    package_dir={'': 'src'},
    packages=find_packages('src', exclude=['*.tests', '*.tests.*', 'tests.*', 'tests']),
    install_requires=['nameko>=2.6', 'redis>=2.10.5'],
    extras_require={
        'dev': [
            'pytest<5.0.0',
            'coverage~=4.5.3',
            'flake8',
            'flake8-bugbear',
            'black;python_version>"3.5"',
            'isort',
            'check-manifest',
            'restructuredtext-lint',
            'Pygments',
        ]
    },
    zip_safe=True,
    license='MIT License',
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
        "Programming Language :: Python",
        "Programming Language :: Python :: 3 :: Only",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.5",
        "Programming Language :: Python :: 3.6",
        "Programming Language :: Python :: 3.7",
        "Topic :: Database",
        "Topic :: Database :: Front-Ends",
        "Topic :: Internet",
        "Topic :: Software Development :: Libraries :: Python Modules",
    ],
)
