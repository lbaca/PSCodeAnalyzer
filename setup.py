import os.path

from setuptools import find_packages, setup


here = os.path.abspath(os.path.dirname(__file__))

with open(os.path.join(here, 'README.md'), encoding='utf-8') as f:
    long_description = f.read()

setup(
    name='pscodeanalyzer',
    version='1.2.3',
    description='A static code analyzer with configurable plug-in rules',
    long_description=long_description,
    long_description_content_type='text/markdown',
    python_requires='~=3.6',
    author='Leandro Baca',
    author_email='leandrobaca77@gmail.com',
    url='https://github.com/lbaca/PSCodeAnalyzer',
    packages=find_packages(),
    install_requires=['peoplecodeparser'],
    classifiers=[
        'Development Status :: 5 - Production/Stable',
        'Environment :: Console',
        'Intended Audience :: Developers',
        'Intended Audience :: Information Technology',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.6',
        'Programming Language :: Python :: 3.7',
        'Programming Language :: Python :: 3.8',
        'Programming Language :: Python :: 3.9',
        'License :: OSI Approved :: MIT License',
        'Operating System :: OS Independent',
        'Topic :: Software Development',
    ],
    keywords=('peoplesoft peoplecode source application-class '
              'application-package code-analysis code-review'),
)
